"""Persiapan jaringan, konversi GeoJSON, dan simulasi jarak Dijkstra.

Graf memakai meter pada CRS proyeksi. Hanya vertex bersama/endpoint yang
disnap yang menjadi simpang; perpotongan visual tidak otomatis terhubung.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

import networkx as nx
from pyproj import CRS, Transformer
from pyproj.exceptions import CRSError
from shapely import transform as transform_geometry
from shapely.errors import GEOSException
from shapely.geometry import LineString, MultiLineString, Point, mapping, shape
from shapely.ops import substring
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parent
EPSILON = 1e-7


def transform(function, geometry):
    """Gunakan fungsi transformasi pyproj dengan API Shapely 2."""
    return transform_geometry(geometry, function, interleaved=False)


class DataError(ValueError):
    """Input penelitian atau konfigurasi tidak dapat digunakan."""


class RoutingError(ValueError):
    def __init__(self, message, code="unreachable", details=None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def read_json(path):
    try:
        with Path(path).open(encoding="utf-8-sig") as stream:
            return json.load(stream)
    except (OSError, ValueError) as exc:
        raise DataError(f"Tidak dapat membaca {Path(path).name}: {exc}") from exc


def collection(features):
    return {"type": "FeatureCollection", "features": features}


def node_key(coordinate):
    # Presisi mikrometer untuk identitas vertex, bukan toleransi snapping.
    return tuple(round(float(value), 6) for value in coordinate[:2])


def feature_collection(path):
    data = read_json(path)
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
        raise DataError(f"{Path(path).name} harus berupa GeoJSON FeatureCollection.")
    if not isinstance(data.get("features"), list):
        raise DataError(f"Daftar features tidak valid di {Path(path).name}.")
    return data


def optional_text(value):
    return str(value).strip() if value is not None else ""


class TourismNetwork:
    def __init__(self, config_path=ROOT / "config.json"):
        self.config_path = Path(config_path).resolve()
        self.config = read_json(self.config_path)
        if not isinstance(self.config, dict):
            raise DataError("Konfigurasi harus berupa objek JSON.")
        for key in ("road_fields", "place_fields"):
            if not isinstance(self.config.get(key, {}), dict):
                raise DataError(f"{key} harus berupa objek pemetaan atribut.")
        self.base = self.config_path.parent
        try:
            self.metric_crs = CRS.from_user_input(self.config["metric_crs"])
            self.tolerance = float(self.config.get("endpoint_snap_tolerance_m", 1))
            self.max_snap = float(self.config.get("max_location_snap_m", 150))
        except (KeyError, TypeError, ValueError, CRSError) as exc:
            raise DataError(f"Konfigurasi CRS/toleransi tidak valid: {exc}") from exc
        if (not self.metric_crs.is_projected
                or any(abs(axis.unit_conversion_factor - 1) > EPSILON
                       for axis in self.metric_crs.axis_info[:2])):
            raise DataError("metric_crs harus merupakan CRS proyeksi dengan satuan meter.")
        if not math.isfinite(self.tolerance) or self.tolerance < 0:
            raise DataError("Toleransi endpoint harus berupa angka nonnegatif.")
        if not math.isfinite(self.max_snap) or self.max_snap <= 0:
            raise DataError("Batas snapping lokasi harus lebih besar dari nol.")
        self.to_wgs = Transformer.from_crs(self.metric_crs, 4326, always_xy=True)
        self.from_wgs = Transformer.from_crs(4326, self.metric_crs, always_xy=True)
        self.report = {
            "metric_crs": self.metric_crs.to_string(),
            "directed": False,
            "endpoint_snap_tolerance_m": self.tolerance,
            "max_location_snap_m": self.max_snap,
            "issues": [],
            "endpoint_snaps": [],
            "unconnected_crossings": [],
            "assumptions": [
                "Seluruh kelas jalan digunakan; aturan satu arah tidak diterapkan.",
                "Persilangan tanpa vertex bersama tidak otomatis menjadi simpang.",
                "Bobot dihitung dari panjang geometri dalam meter.",
                "Akses dari titik asli ke ruas terdekat tidak termasuk jarak rute.",
            ],
        }
        self.places = {}
        self.parts = []
        self.graph = nx.MultiGraph()
        self._load_roads()
        self._snap_endpoints()
        self._build_graph()
        self._audit_crossings()
        self._load_places()
        self._load_scenarios()
        self.edges = list(self.graph.edges(keys=True, data=True))
        self.edge_tree = STRtree([edge[3]["geometry"] for edge in self.edges])
        self.report.update({
            "valid_road_parts": len(self.parts),
            "nodes": self.graph.number_of_nodes(),
            "edges": self.graph.number_of_edges(),
            "components": nx.number_connected_components(self.graph),
            "component_node_counts": sorted(
                (len(c) for c in nx.connected_components(self.graph)), reverse=True),
            "places": len(self.places),
        })
        self.report["place_snapping"] = []
        for place in self.places.values():
            _, _, _, _, distance = self._nearest(place["point"])
            self.report["place_snapping"].append({
                "id": place["id"], "name": place["name"],
                "distance_m": distance, "within_limit": distance <= self.max_snap,
            })

    def _input(self, key):
        try:
            path = self.base / self.config[key]
        except (KeyError, TypeError) as exc:
            raise DataError(f"Konfigurasi {key} belum ditentukan.") from exc
        data = feature_collection(path)
        # Jangan memakai SRS_ID atribut: yang berwenang adalah CRS geometri.
        declared = data.get("crs", {}).get("properties", {}).get("name")
        crs_name = declared or self.config.get("source_crs")
        if not crs_name:
            raise DataError(f"CRS {path.name} harus dinyatakan dalam konfigurasi.")
        try:
            converter = Transformer.from_crs(crs_name, self.metric_crs, always_xy=True)
        except Exception as exc:
            raise DataError(f"CRS {path.name} tidak valid: {crs_name}") from exc
        return data, converter

    def _issue(self, feature_id, reason, dataset="roads"):
        self.report["issues"].append({"dataset": dataset, "id": feature_id, "reason": reason})

    def _load_roads(self):
        data, converter = self._input("roads_file")
        fields = self.config.get("road_fields", {})
        self.report["input_road_features"] = len(data["features"])
        seen = set()
        for index, feature in enumerate(data["features"]):
            props = feature.get("properties") or {} if isinstance(feature, dict) else {}
            if not isinstance(props, dict):
                self._issue(index + 1, "Properties jalan harus berupa objek JSON.")
                continue
            source_id = props.get(fields.get("id", "OBJECTID"), index + 1)
            try:
                geom = shape(feature.get("geometry"))
                if geom.is_empty or not geom.is_valid:
                    raise ValueError("Geometri kosong atau tidak valid.")
                if not isinstance(geom, (LineString, MultiLineString)):
                    raise ValueError("Geometri jalan harus LineString/MultiLineString.")
                geom = transform(converter.transform, geom)
                geoms = list(geom.geoms) if isinstance(geom, MultiLineString) else [geom]
                for part_no, line in enumerate(geoms):
                    coords = [tuple(p[:2]) for p in line.coords]
                    if not all(math.isfinite(v) for p in coords for v in p):
                        raise ValueError("Koordinat tidak hingga.")
                    line = LineString(coords)
                    if not line.is_valid or line.length <= EPSILON:
                        raise ValueError("Ruas tidak valid atau panjangnya nol.")
                    forward = tuple(coords)
                    fingerprint = min(forward, forward[::-1])
                    if fingerprint in seen:
                        self._issue(source_id, "Geometri duplikat identik diabaikan.")
                        continue
                    seen.add(fingerprint)
                    self.parts.append({
                        "geometry": line, "source_id": source_id,
                        "part": part_no, "properties": props,
                    })
                raw_length = props.get(fields.get("length", "Shape_Length"))
                if raw_length is None:
                    self._issue(source_id, "Atribut panjang kosong; panjang geometri digunakan.")
                else:
                    try:
                        length = float(raw_length)
                        if not math.isfinite(length) or length <= 0:
                            raise ValueError()
                        if abs(length - geom.length) > max(1, geom.length * .01):
                            self._issue(source_id, "Atribut panjang berbeda dari geometri >1%; geometri digunakan.")
                    except (TypeError, ValueError):
                        self._issue(source_id, "Atribut panjang tidak valid; panjang geometri digunakan.")
            except (AttributeError, TypeError, ValueError, GEOSException) as exc:
                self._issue(source_id, str(exc))
        if not self.parts:
            raise DataError("Tidak ada ruas jalan valid yang dapat dianalisis.")

    def _snap_endpoints(self):
        if self.tolerance <= 0:
            return
        endpoints = sorted({node_key(c) for part in self.parts
                            for c in (part["geometry"].coords[0], part["geometry"].coords[-1])})
        cells = defaultdict(list)
        representatives = {}
        for coordinate in endpoints:
            cx, cy = (math.floor(v / self.tolerance) for v in coordinate)
            candidates = [p for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                          for p in cells[(cx + dx, cy + dy)]
                          if math.dist(coordinate, p) <= self.tolerance]
            representative = min(candidates, key=lambda p: (math.dist(coordinate, p), p)) if candidates else coordinate
            representatives[coordinate] = representative
            if representative == coordinate:
                cells[(cx, cy)].append(coordinate)
            else:
                self.report["endpoint_snaps"].append({
                    "from": list(coordinate), "to": list(representative),
                    "distance_m": math.dist(coordinate, representative),
                })
        for part in self.parts:
            coords = list(part["geometry"].coords)
            coords[0] = representatives[node_key(coords[0])]
            coords[-1] = representatives[node_key(coords[-1])]
            part["geometry"] = LineString(coords)

    def _build_graph(self):
        # Vertex interior menjadi simpang hanya ketika dipakai ruas lain.
        owners = defaultdict(set)
        for index, part in enumerate(self.parts):
            for coordinate in part["geometry"].coords:
                owners[node_key(coordinate)].add(index)
        for part in self.parts:
            coords = list(part["geometry"].coords)
            cuts = [0] + [i for i in range(1, len(coords) - 1)
                          if len(owners[node_key(coords[i])]) > 1] + [len(coords) - 1]
            for left, right in zip(cuts, cuts[1:]):
                line = LineString(coords[left:right + 1])
                if line.length <= EPSILON:
                    self._issue(part["source_id"], "Ruas nol setelah snapping diabaikan.")
                    continue
                u, v = node_key(line.coords[0]), node_key(line.coords[-1])
                self.graph.add_edge(u, v, geometry=line, weight=line.length,
                                    source_id=part["source_id"], properties=part["properties"],
                                    start_node=u)
        if not self.graph.number_of_edges():
            raise DataError("Graf tidak memiliki ruas dengan panjang positif.")

    def _audit_crossings(self):
        lines = [part["geometry"] for part in self.parts]
        tree = STRtree(lines)
        vertices = [{node_key(p) for p in line.coords} for line in lines]
        for i, line in enumerate(lines):
            for j_raw in tree.query(line, predicate="intersects"):
                j = int(j_raw)
                if j <= i:
                    continue
                intersection = line.intersection(lines[j])
                points = ([intersection] if isinstance(intersection, Point)
                          else list(intersection.geoms) if intersection.geom_type == "MultiPoint" else [])
                for point in points:
                    key = node_key(point.coords[0])
                    if key not in vertices[i] or key not in vertices[j]:
                        self.report["unconnected_crossings"].append({
                            "road_ids": [self.parts[i]["source_id"], self.parts[j]["source_id"]],
                            "coordinate_metric": list(point.coords[0]),
                            "reason": "Perpotongan tanpa vertex bersama; periksa simpang/beda elevasi di GIS.",
                        })

    def _load_places(self):
        data, converter = self._input("places_file")
        fields = self.config.get("place_fields", {})
        for index, feature in enumerate(data["features"]):
            props = feature.get("properties") or {} if isinstance(feature, dict) else {}
            if not isinstance(props, dict):
                self._issue(index + 1, "Properties wisata harus berupa objek JSON.", "places")
                continue
            place_id = props.get(fields.get("id", "OBJECTID"))
            try:
                if place_id is None or isinstance(place_id, (dict, list, bool)):
                    raise ValueError("ID wisata harus unik dan tidak kosong.")
                name = optional_text(props.get(fields.get("name", "Nama_Objek")))
                if not name:
                    raise ValueError("Nama wisata kosong.")
                if str(place_id) in self.places:
                    raise DataError(f"ID wisata duplikat: {place_id}")
                point = shape(feature.get("geometry"))
                if not isinstance(point, Point) or point.is_empty or not point.is_valid:
                    raise ValueError("Geometri wisata harus Point yang valid.")
                point = transform(converter.transform, point)
                if not math.isfinite(point.x) or not math.isfinite(point.y):
                    raise ValueError("Koordinat wisata tidak hingga.")
                place = {"id": place_id, "name": name, "point": point}
                for key in ("address", "category", "description", "photo"):
                    value = optional_text(props.get(fields.get(key, key)))
                    if value:
                        place[key] = value
                self.places[str(place_id)] = place
            except DataError:
                raise
            except (AttributeError, TypeError, ValueError, GEOSException) as exc:
                self._issue(place_id if place_id is not None else index + 1, str(exc), "places")
        if not self.places:
            raise DataError("Tidak ada lokasi wisata valid.")

    def _load_scenarios(self):
        self.scenarios = {}
        scenarios = self.config.get("scenarios")
        if not isinstance(scenarios, list) or not scenarios:
            raise DataError("Daftar skenario belum tersedia.")
        for scenario in scenarios:
            if (not isinstance(scenario, dict) or not isinstance(scenario.get("id"), str)
                    or not scenario["id"] or not scenario.get("name")):
                raise DataError("Skenario memerlukan id dan name.")
            ids = scenario.get("place_ids")
            if not isinstance(ids, list) or not ids:
                raise DataError(f"Urutan wisata {scenario['id']} kosong.")
            missing = [p for p in ids if str(p) not in self.places]
            if missing:
                raise DataError(f"ID wisata pada {scenario['id']} tidak ditemukan: {missing}")
            if scenario["id"] in self.scenarios:
                raise DataError(f"ID skenario duplikat: {scenario['id']}")
            self.scenarios[scenario["id"]] = scenario

    def places_geojson(self):
        return collection([{
            "type": "Feature", "id": p["id"],
            "geometry": mapping(transform(self.to_wgs.transform, p["point"])),
            "properties": {k: v for k, v in p.items() if k != "point"},
        } for p in self.places.values()])

    def roads_geojson(self):
        fields = self.config.get("road_fields", {})
        return collection([{
            "type": "Feature",
            "geometry": mapping(transform(self.to_wgs.transform, attrs["geometry"])),
            "properties": {
                "source_id": attrs["source_id"], "length_m": attrs["weight"],
                "name": optional_text(attrs["properties"].get(fields.get("name", "NAMOBJ"))),
                "category": optional_text(attrs["properties"].get(fields.get("category", "REMARK"))),
            },
        } for _, _, _, attrs in self.graph.edges(keys=True, data=True)])

    def scenarios_json(self):
        return [{"id": s["id"], "name": s["name"], "color": s.get("color", "#176b50"),
                 "is_example": True, "max_location_snap_m": self.max_snap,
                 "visits": [{"id": self.places[str(i)]["id"], "name": self.places[str(i)]["name"]}
                            for i in s["place_ids"]]} for s in self.scenarios.values()]

    def _nearest(self, point):
        index = int(self.edge_tree.nearest(point))
        u, v, key, attrs = self.edges[index]
        measure = attrs["geometry"].project(point)
        snapped = attrs["geometry"].interpolate(measure)
        return (u, v, key), measure, snapped, attrs, point.distance(snapped)

    def _insert_points(self, graph, points, labels):
        groups = defaultdict(list)
        anchors = [None] * len(points)
        snaps = []
        for index, point in enumerate(points):
            edge, measure, snapped, attrs, distance = self._nearest(point)
            if distance > self.max_snap:
                label = labels[index]
                raise RoutingError(f"{label} berjarak {distance:.0f} m dari jalan terdekat; batasnya {self.max_snap:g} m.",
                                   "too_far", {"point_index": index, "distance_m": distance,
                                               "max_distance_m": self.max_snap})
            lon, lat = self.to_wgs.transform(snapped.x, snapped.y)
            snaps.append({"distance_m": distance, "coordinates": [lon, lat]})
            groups[edge].append((measure, index))
        for (u, v, key), items in groups.items():
            attrs = graph.get_edge_data(u, v, key)
            line = attrs["geometry"]
            start_node = attrs["start_node"]
            end_node = v if start_node == u else u
            cuts = [(0.0, start_node), (line.length, end_node)]
            for measure, index in sorted(items):
                nearby = next((node for m, node in cuts if abs(m - measure) <= EPSILON), None)
                if nearby is not None:
                    anchors[index] = nearby
                    continue
                # Node per edge: posisi pada dua jalan silang tidak menyambungkannya.
                node = ("snap", u, v, key, round(measure, 7))
                cuts.append((measure, node))
                anchors[index] = node
            graph.remove_edge(u, v, key)
            cuts.sort(key=lambda item: item[0])
            for (left, a), (right, b) in zip(cuts, cuts[1:]):
                if right - left <= EPSILON:
                    continue
                segment = substring(line, left, right)
                data = {**attrs, "geometry": segment, "weight": segment.length, "start_node": a}
                graph.add_edge(a, b, **data)
        return anchors, snaps

    def calculate_route(self, scenario_id, lat, lon):
        if scenario_id not in self.scenarios:
            raise DataError("Skenario tidak dikenal.")
        if (isinstance(lat, bool) or isinstance(lon, bool)
                or not isinstance(lat, (int, float)) or not isinstance(lon, (int, float))
                or not math.isfinite(lat) or not math.isfinite(lon)
                or not -90 <= lat <= 90 or not -180 <= lon <= 180):
            raise DataError("lat/lon harus berupa angka koordinat yang valid.")
        scenario = self.scenarios[scenario_id]
        destinations = [self.places[str(i)] for i in scenario["place_ids"]]
        x, y = self.from_wgs.transform(lon, lat)
        if not math.isfinite(x) or not math.isfinite(y):
            raise RoutingError("Titik awal berada di luar cakupan proyeksi jaringan.", "too_far")
        graph = self.graph.copy()
        anchors, snaps = self._insert_points(
            graph, [Point(x, y)] + [p["point"] for p in destinations],
            ["Titik awal"] + [p["name"] for p in destinations])
        legs = []
        metric_coordinates = []
        for i, (source, target) in enumerate(zip(anchors, anchors[1:])):
            target_name = destinations[i]["name"]
            origin_name = "Lokasi awal" if i == 0 else destinations[i - 1]["name"]
            try:
                _, path = nx.single_source_dijkstra(graph, source, target, weight="weight")
            except (nx.NetworkXNoPath, nx.NodeNotFound) as exc:
                raise RoutingError(f"Tidak ada jalur yang terhubung dari {origin_name} ke {target_name}.",
                                   details={"from": origin_name, "to": target_name}) from exc
            distance = 0.0
            road_ids = []
            for a, b in zip(path, path[1:]):
                edge_key, attrs = min(graph[a][b].items(), key=lambda item: (item[1]["weight"], item[0]))
                coords = list(attrs["geometry"].coords)
                if attrs["start_node"] != a:
                    coords.reverse()
                if metric_coordinates:
                    metric_coordinates.extend(coords[1:])
                else:
                    metric_coordinates.extend(coords)
                distance += attrs["weight"]
                if not road_ids or road_ids[-1] != attrs["source_id"]:
                    road_ids.append(attrs["source_id"])
            legs.append({"from": origin_name, "to": target_name, "to_id": destinations[i]["id"],
                         "distance_m": distance, "road_ids": road_ids})
        if not metric_coordinates:
            # Jalur panjang nol tetap GeoJSON valid, tanpa mengarang jarak.
            snapped = snaps[0]["coordinates"]
            geometry = {"type": "LineString", "coordinates": [snapped, snapped]}
        else:
            geometry = mapping(transform(self.to_wgs.transform, LineString(metric_coordinates)))
        total = sum(leg["distance_m"] for leg in legs)
        return collection([{
            "type": "Feature", "geometry": geometry,
            "properties": {
                "route_id": scenario["id"], "route_name": scenario["name"],
                "color": scenario.get("color", "#176b50"), "is_example": True,
                "total_distance_m": total, "total_distance_km": total / 1000,
                "start": {"lat": lat, "lon": lon},
                "visits": [{"id": p["id"], "name": p["name"]} for p in destinations],
                "legs": legs, "snapping": snaps,
                "method": "Dijkstra; panjang ruas dalam meter; graf tak berarah",
                "note": "Jarak akses dari titik asli ke jalan terdekat tidak termasuk total.",
            },
        }])

    def export_prepared(self, output_dir):
        output = Path(output_dir)
        files = (("wisata_budaya.geojson", self.places_geojson()),
                 ("jalan_yogyakarta.geojson", self.roads_geojson()),
                 ("network_report.json", self.report))
        inputs = {(self.base / self.config[key]).resolve() for key in ("roads_file", "places_file")}
        if any((output / filename).resolve() in inputs for filename, _ in files):
            raise DataError("Keluaran akan menimpa data sumber. Gunakan --output-dir yang berbeda.")
        output.mkdir(parents=True, exist_ok=True)
        for filename, data in files:
            (output / filename).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Persiapan data dan ekspor simulasi rute wisata.")
    parser.add_argument("--config", type=Path, default=ROOT / "config.json")
    parser.add_argument("--prepare", action="store_true", help="Ekspor data WGS84 dan laporan jaringan.")
    parser.add_argument("--scenario", help="ID skenario yang diekspor, misalnya rute-1.")
    parser.add_argument("--lat", type=float)
    parser.add_argument("--lon", type=float)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    try:
        network = TourismNetwork(args.config)
        if args.prepare:
            network.export_prepared(args.output_dir)
        if args.scenario:
            if args.lat is None or args.lon is None:
                parser.error("Ekspor rute memerlukan --lat dan --lon.")
            args.output_dir.mkdir(parents=True, exist_ok=True)
            route = network.calculate_route(args.scenario, args.lat, args.lon)
            (args.output_dir / "rute_wisata.geojson").write_text(
                json.dumps(route, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"Jarak: {route['features'][0]['properties']['total_distance_km']:.2f} km")
        print(f"Jaringan: {network.graph.number_of_nodes()} node, {network.graph.number_of_edges()} ruas, "
              f"{network.report['components']} komponen. Wisata: {len(network.places)}.")
        print(f"Perlu diperiksa: {len(network.report['issues'])} catatan, "
              f"{len(network.report['unconnected_crossings'])} perpotongan tanpa vertex bersama.")
    except (DataError, RoutingError) as exc:
        parser.exit(1, f"Kesalahan: {exc}\n")


if __name__ == "__main__":
    main()
