"""Uji jarak, topologi, snapping, dan kontrak API menggunakan unittest."""

import json
import math
import shutil
import unittest
import uuid
from pathlib import Path

from shapely.geometry import LineString, Point, mapping

from app import create_app
from network import DataError, ROOT, RoutingError, TourismNetwork, collection

BASE_X, BASE_Y = 430000, 9137500


def xy(x, y=0):
    return [BASE_X + x, BASE_Y + y]


def road(coords, road_id=1):
    geometry = LineString(coords)
    return {"type": "Feature", "geometry": mapping(geometry),
            "properties": {"OBJECTID": road_id, "Shape_Length": geometry.length}}


def place(coords, place_id=1):
    return {"type": "Feature", "geometry": mapping(Point(coords)),
            "properties": {"OBJECTID": place_id, "Nama_Objek": f"Wisata {place_id}"}}


class FixtureTests(unittest.TestCase):
    def setUp(self):
        self.test_root = ROOT / ".qa" / "test-data"
        self.directory = self.test_root / uuid.uuid4().hex
        self.directory.mkdir(parents=True)

    def tearDown(self):
        # Hanya hapus direktori fixture yang dibuat pengujian ini.
        if self.directory.resolve().parent != self.test_root.resolve():
            raise RuntimeError("Direktori fixture berada di luar root pengujian.")
        shutil.rmtree(self.directory)

    def network(self, roads, places, ids=None, **overrides):
        config = {
            "roads_file": "roads.geojson", "places_file": "places.geojson",
            "source_crs": "EPSG:32749", "metric_crs": "EPSG:32749",
            "endpoint_snap_tolerance_m": 1, "max_location_snap_m": 150,
            "scenarios": [{"id": "test", "name": "Uji", "place_ids": ids or [1]}],
            **overrides,
        }
        for name, data in (("roads.geojson", collection(roads)),
                           ("places.geojson", collection(places)), ("config.json", config)):
            (self.directory / name).write_text(json.dumps(data), encoding="utf-8")
        return TourismNetwork(self.directory / "config.json")

    def calculate(self, network, coordinate):
        lon, lat = network.to_wgs.transform(*coordinate)
        return network.calculate_route("test", lat, lon)["features"][0]

    def test_multiple_points_on_one_edge(self):
        net = self.network([road([xy(0), xy(100)])], [place(xy(40), 1), place(xy(90), 2)], [1, 2])
        nodes, edges = net.graph.number_of_nodes(), net.graph.number_of_edges()
        result = self.calculate(net, xy(10))
        self.assertAlmostEqual(result["properties"]["total_distance_m"], 80, places=4)
        self.assertAlmostEqual(result["properties"]["legs"][0]["distance_m"], 30, places=4)
        self.assertEqual((net.graph.number_of_nodes(), net.graph.number_of_edges()), (nodes, edges))
        self.assertAlmostEqual(self.calculate(net, xy(70))["properties"]["total_distance_m"], 80, places=4)

    def test_parallel_edges_and_reversed_geometry(self):
        net = self.network([road([xy(0), xy(50, 60), xy(100)], 1), road([xy(0), xy(100)], 2)],
                           [place(xy(100), 1), place(xy(0), 2)], [1, 2])
        result = self.calculate(net, xy(0))
        self.assertEqual(net.graph.number_of_edges(), 2)
        self.assertAlmostEqual(result["properties"]["total_distance_m"], 200, places=4)
        self.assertEqual(result["properties"]["legs"][0]["road_ids"], [2])
        projected = [net.from_wgs.transform(*p) for p in result["geometry"]["coordinates"]]
        self.assertAlmostEqual(sum(math.dist(a, b) for a, b in zip(projected, projected[1:])), 200, places=4)
        self.assertAlmostEqual(projected[-1][0], BASE_X, places=4)

    def test_shared_interior_vertex_is_junction(self):
        net = self.network([road([xy(0), xy(50), xy(100)], 1), road([xy(50), xy(50, 50)], 2)], [place(xy(100))])
        self.assertEqual(net.graph.number_of_edges(), 3)
        self.assertAlmostEqual(self.calculate(net, xy(50, 50))["properties"]["total_distance_m"], 100, places=4)

    def test_visual_crossing_is_not_connected(self):
        net = self.network([road([xy(0), xy(100)], 1), road([xy(50, -50), xy(50, 50)], 2)], [place(xy(50, 50))])
        self.assertEqual(net.report["components"], 2)
        self.assertEqual(len(net.report["unconnected_crossings"]), 1)
        with self.assertRaises(RoutingError) as caught:
            self.calculate(net, xy(0))
        self.assertEqual(caught.exception.code, "unreachable")

    def test_endpoint_snap_within_one_meter(self):
        net = self.network([road([xy(0), xy(100)], 1), road([xy(100.5), xy(200)], 2)], [place(xy(200))])
        self.assertEqual(net.report["components"], 1)
        self.assertEqual(len(net.report["endpoint_snaps"]), 1)
        self.assertAlmostEqual(self.calculate(net, xy(0))["properties"]["total_distance_m"], 200, places=4)

    def test_endpoint_outside_tolerance_stays_disconnected(self):
        net = self.network([road([xy(0), xy(100)], 1), road([xy(102), xy(200)], 2)], [place(xy(200))])
        self.assertEqual(net.report["components"], 2)
        with self.assertRaises(RoutingError):
            self.calculate(net, xy(0))

    def test_multi_line_and_duplicate_validation(self):
        multi = {"type": "Feature", "geometry": {"type": "MultiLineString",
                 "coordinates": [[xy(0), xy(100)], [xy(100), xy(200)]]},
                 "properties": {"OBJECTID": 1, "Shape_Length": None}}
        invalid = {"type": "Feature", "geometry": None, "properties": {"OBJECTID": 3}}
        net = self.network([multi, road([xy(100), xy(0)], 2), invalid], [place(xy(200))])
        self.assertEqual(net.graph.number_of_edges(), 2)
        self.assertEqual(len(net.report["issues"]), 3)
        self.assertAlmostEqual(self.calculate(net, xy(0))["properties"]["total_distance_m"], 200, places=4)

    def test_snapping_limit(self):
        net = self.network([road([xy(0), xy(100)])], [place(xy(100))])
        with self.assertRaises(RoutingError) as caught:
            self.calculate(net, xy(0, 151))
        self.assertEqual(caught.exception.code, "too_far")

    def test_access_distance_is_excluded(self):
        net = self.network([road([xy(0), xy(100)])], [place(xy(90, 30))])
        result = self.calculate(net, xy(10, 20))["properties"]
        self.assertAlmostEqual(result["total_distance_m"], 80, places=4)
        self.assertAlmostEqual(result["snapping"][0]["distance_m"], 20, places=4)
        self.assertAlmostEqual(result["snapping"][1]["distance_m"], 30, places=4)

    def test_zero_distance_route(self):
        net = self.network([road([xy(0), xy(100)])], [place(xy(50))])
        result = self.calculate(net, xy(50))
        self.assertAlmostEqual(result["properties"]["total_distance_m"], 0, places=4)
        self.assertEqual(len(result["geometry"]["coordinates"]), 2)

    def test_invalid_road_data(self):
        with self.assertRaises(DataError):
            self.network([{"type": "Feature", "geometry": None}], [place(xy(50))])

    def test_invalid_scenario(self):
        with self.assertRaises(DataError):
            self.network([road([xy(0), xy(100)])], [place(xy(50))], [99])

    def test_invalid_metric_crs_reports_data_error(self):
        with self.assertRaises(DataError):
            self.network([road([xy(0), xy(100)])], [place(xy(50))], metric_crs="invalid")

    def test_far_destination_is_named_in_error(self):
        net = self.network([road([xy(0), xy(100)])], [place(xy(50, 200))])
        with self.assertRaises(RoutingError) as caught:
            self.calculate(net, xy(0))
        self.assertIn("Wisata 1", str(caught.exception))

    def test_export_does_not_overwrite_source(self):
        net = self.network([road([xy(0), xy(100)])], [place(xy(50))])
        source = self.directory / "jalan_yogyakarta.geojson"
        shutil.copyfile(self.directory / "roads.geojson", source)
        net.config["roads_file"] = source.name
        before = source.read_bytes()
        with self.assertRaises(DataError):
            net.export_prepared(self.directory)
        self.assertEqual(source.read_bytes(), before)

    def test_unreachable_api_returns_422(self):
        net = self.network([road([xy(0), xy(100)], 1), road([xy(500), xy(600)], 2)], [place(xy(600))])
        client = create_app(network=net).test_client()
        lon, lat = net.to_wgs.transform(*xy(0))
        response = client.post("/api/rute", json={"scenario_id": "test", "start": {"lat": lat, "lon": lon}})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json["error"]["code"], "unreachable")

    def test_missing_data_keeps_page_available(self):
        app = create_app(self.directory / "missing.json")
        app.logger.disabled = True
        client = app.test_client()
        with client.get("/") as response:
            self.assertEqual(response.status_code, 200)
        self.assertEqual(client.get("/api/wisata").status_code, 503)


class ActualDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.network = TourismNetwork()
        cls.client = create_app(network=cls.network).test_client()

    def test_wgs84_markers_and_data(self):
        response = self.client.get("/api/wisata")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json["features"]), 6)
        for feature in response.json["features"]:
            lon, lat = feature["geometry"]["coordinates"]
            self.assertTrue(110.3 < lon < 110.5)
            self.assertTrue(-7.9 < lat < -7.7)
        self.assertNotIn("crs", response.json)
        self.assertEqual(len(self.client.get("/api/skenario").json), 3)
        self.assertGreater(len(self.client.get("/api/jalan").json["features"]), 3000)

    def test_all_actual_scenarios_from_tugu(self):
        lon, lat = self.network.to_wgs.transform(self.network.places["6"]["point"].x, self.network.places["6"]["point"].y)
        before = (self.network.graph.number_of_nodes(), self.network.graph.number_of_edges())
        for scenario in self.network.scenarios.values():
            with self.subTest(scenario=scenario["id"]):
                response = self.client.post("/api/rute", json={"scenario_id": scenario["id"], "start": {"lat": lat, "lon": lon}})
                self.assertEqual(response.status_code, 200, response.json)
                feature = response.json["features"][0]
                props = feature["properties"]
                self.assertEqual([p["id"] for p in props["visits"]], scenario["place_ids"])
                self.assertAlmostEqual(props["total_distance_m"], sum(leg["distance_m"] for leg in props["legs"]), places=6)
                projected = [self.network.from_wgs.transform(*p) for p in feature["geometry"]["coordinates"]]
                distance = sum(math.dist(a, b) for a, b in zip(projected, projected[1:]))
                self.assertAlmostEqual(props["total_distance_m"], distance, delta=.02)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual((self.network.graph.number_of_nodes(), self.network.graph.number_of_edges()), before)

    def test_invalid_api_inputs(self):
        valid = {"scenario_id": "rute-1", "start": {"lat": -7.8, "lon": 110.36}}
        cases = [None, [], {}, {"start": {}}, {**valid, "scenario_id": []},
                 {**valid, "scenario_id": "unknown"}, {**valid, "start": {"lat": True, "lon": 110}},
                 {**valid, "start": {"lat": "-7.8", "lon": 110}},
                 {**valid, "start": {"lat": float("nan"), "lon": 110}},
                 {**valid, "start": {"lat": 91, "lon": 110}}]
        for body in cases:
            with self.subTest(body=body):
                response = self.client.post("/api/rute", data=json.dumps(body), content_type="application/json")
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json["error"]["code"], "invalid_input")
        self.assertEqual(self.client.post("/api/rute", data="{", content_type="application/json").status_code, 400)
        self.assertEqual(self.client.post("/api/rute", data="not json").status_code, 400)

    def test_start_outside_yogyakarta(self):
        response = self.client.post("/api/rute", json={"scenario_id": "rute-1", "start": {"lat": -6.2, "lon": 106.8}})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json["error"]["code"], "too_far")
        self.assertNotIn("features", response.json)

    def test_static_files_are_explicit(self):
        for path in ("/", "/style.css", "/app.js"):
            with self.client.get(path) as response:
                self.assertEqual(response.status_code, 200)
        for path in ("/config.json", "/app.py", "/data/../config.json"):
            self.assertEqual(self.client.get(path).status_code, 404)


if __name__ == "__main__":
    unittest.main()
