"""Satu server lokal untuk halaman peta dan API analisis jaringan."""

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge, UnsupportedMediaType

from network import DataError, ROOT, RoutingError, TourismNetwork


def create_app(config_path=ROOT / "config.json", network=None):
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
    app.json.ensure_ascii = False
    startup_error = None
    if network is None:
        try:
            network = TourismNetwork(config_path)
        except DataError as exc:
            startup_error = str(exc)
            app.logger.error("Data jaringan tidak siap: %s", startup_error)
    app.extensions["tourism_network"] = network
    # Konversi data peta sekali, bukan pada setiap permintaan.
    places = network.places_geojson() if network else None
    roads = network.roads_geojson() if network else None

    @app.get("/")
    def index():
        return send_from_directory(ROOT, "index.html")

    @app.get("/style.css")
    def styles():
        return send_from_directory(ROOT, "style.css")

    @app.get("/app.js")
    def javascript():
        return send_from_directory(ROOT, "app.js")

    @app.get("/data/photos/<path:filename>")
    def photo(filename):
        return send_from_directory(ROOT / "data" / "photos", filename)

    @app.before_request
    def require_network():
        if request.path.startswith("/api/") and network is None:
            return jsonify(error={"code": "data_unavailable", "message": startup_error}), 503

    @app.get("/api/wisata")
    def wisata():
        return jsonify(places)

    @app.get("/api/jalan")
    def jalan():
        return jsonify(roads)

    @app.get("/api/skenario")
    def skenario():
        return jsonify(network.scenarios_json())

    @app.post("/api/rute")
    def rute():
        try:
            body = request.get_json()
            if not isinstance(body, dict) or not isinstance(body.get("start"), dict):
                raise DataError("Kirim scenario_id dan start berisi lat/lon.")
            scenario_id = body.get("scenario_id")
            if not isinstance(scenario_id, str):
                raise DataError("scenario_id harus berupa teks.")
            start = body["start"]
            result = network.calculate_route(scenario_id, start.get("lat"), start.get("lon"))
            response = jsonify(result)
            response.headers["Cache-Control"] = "no-store"
            return response
        except (BadRequest, UnsupportedMediaType, DataError) as exc:
            message = str(exc) if isinstance(exc, DataError) else "Isi permintaan harus JSON yang valid."
            return jsonify(error={"code": "invalid_input", "message": message}), 400
        except RoutingError as exc:
            return jsonify(error={"code": exc.code, "message": str(exc), "details": exc.details}), 422

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_error):
        return jsonify(error={"code": "invalid_input", "message": "Permintaan terlalu besar."}), 400

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=False)
