"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const mobile = window.matchMedia("(max-width: 700px)");
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const kilometers = new Intl.NumberFormat("id-ID", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const state = {
    ready: false, places: [], scenarios: [], markers: new Map(), start: null, selectedPlace: null,
    result: null, picking: false, calculating: false, locating: false,
    requestId: 0, locationId: 0, controller: null, messageTimer: null,
  };
  let map, placesLayer, roadsLayer, routeLayer, startLayer, legend;

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function icon(name) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    node.classList.add("icon");
    node.setAttribute("aria-hidden", "true");
    const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", `#icon-${name}`);
    node.append(use);
    return node;
  }

  function safeColor(value) {
    return /^#[0-9a-f]{6}$/i.test(value || "") ? value : "#176b50";
  }

  function notice(id, message, error = false) {
    const node = $(id);
    node.textContent = message;
    node.classList.toggle("notice-error", error);
    node.classList.remove("notice-loading");
    node.hidden = !message;
  }

  function mapMessage(message, persistent = false) {
    clearTimeout(state.messageTimer);
    $("map-message").textContent = message;
    $("map-message").hidden = !message;
    if (message && !persistent) state.messageTimer = setTimeout(() => { $("map-message").hidden = true; }, 7000);
  }

  function setSidebar(open) {
    $("sidebar").classList.toggle("is-open", open);
    $("panel-toggle").setAttribute("aria-expanded", String(open));
    $("mobile-explore").hidden = open;
  }

  function setTab(name) {
    for (const tab of ["wisata", "rute"]) {
      const selected = name === tab;
      $(`tab-${tab}`).classList.toggle("is-active", selected);
      $(`tab-${tab}`).setAttribute("aria-selected", String(selected));
      $(`tab-${tab}`).tabIndex = selected ? 0 : -1;
      $(`panel-${tab}`).hidden = !selected;
    }
  }

  async function fetchJSON(url, options) {
    let response;
    try {
      response = await fetch(url, options);
    } catch (error) {
      if (error.name === "AbortError") throw error;
      throw new Error("Server tidak dapat dihubungi. Pastikan server Python masih berjalan.");
    }
    let data;
    try { data = await response.json(); }
    catch { throw new Error("Server mengembalikan data yang tidak dapat dibaca."); }
    if (!response.ok) throw new Error(data.error?.message || "Data gagal dimuat.");
    return data;
  }

  function touristIcon(number, color = "#176b50") {
    if (number) return L.divIcon({
      className: "tourist-marker",
      html: `<span class="number-marker" style="background:${safeColor(color)}">${Number(number)}</span>`,
      iconSize: [28, 28], iconAnchor: [14, 14], popupAnchor: [0, -17],
    });
    return L.divIcon({
      className: "tourist-marker",
      html: '<svg class="marker-pin" viewBox="0 0 30 36" aria-hidden="true"><path d="M15 34S2 22 2 15a13 13 0 0 1 26 0c0 7-13 19-13 19Z"/><circle cx="15" cy="14" r="4"/></svg>',
      iconSize: [29, 35], iconAnchor: [14.5, 34], popupAnchor: [0, -31],
    });
  }

  function photoNode(value) {
    if (!value) return null;
    try {
      const url = new URL(value, window.location.origin);
      if (!["http:", "https:"].includes(url.protocol)) return null;
      const image = element("img", "place-photo");
      image.src = url.href;
      image.alt = "Foto lokasi wisata";
      image.loading = "lazy";
      image.addEventListener("error", () => { image.hidden = true; }, { once: true });
      return image;
    } catch { return null; }
  }

  function placeContent(feature, popup = false) {
    const props = feature.properties;
    const content = element("div", popup ? "popup-detail" : "detail-content");
    const photo = photoNode(props.photo);
    if (photo) content.append(photo);
    content.append(element("h3", "", props.name));
    for (const key of ["category", "address", "description"]) {
      if (props[key]) content.append(element("p", "", props[key]));
    }
    const [lon, lat] = feature.geometry.coordinates;
    content.append(element("p", "popup-coordinate", `${lat.toFixed(5)}, ${lon.toFixed(5)}`));
    if (!popup) {
      const button = element("button", "button button-outline button-full", "Lihat lokasi pada peta");
      button.addEventListener("click", () => selectPlace(feature.properties.id));
      content.append(button);
    }
    return content;
  }

  function selectPlace(id) {
    const feature = state.places.find((p) => String(p.properties.id) === String(id));
    const marker = state.markers.get(String(id));
    if (!feature || !marker) return;
    state.selectedPlace = String(id);
    setPicking(false);
    if (!placesLayer.hasLayer(marker)) placesLayer.addLayer(marker);
    if (!map.hasLayer(placesLayer)) placesLayer.addTo(map);
    map.setView(marker.getLatLng(), Math.max(map.getZoom(), 16), { animate: !reducedMotion });
    marker.openPopup();
    document.querySelectorAll(".place-item").forEach((button) => {
      const selected = button.dataset.id === String(id);
      button.classList.toggle("is-selected", selected);
      button.setAttribute("aria-pressed", String(selected));
    });
    $("detail-content").replaceChildren(placeContent(feature));
    $("place-detail").hidden = false;
    if (mobile.matches) setSidebar(false);
  }

  function renderPlaces() {
    const query = $("search").value.trim().toLocaleLowerCase("id");
    const category = $("category").value;
    const filtered = state.places.filter((p) => p.properties.name.toLocaleLowerCase("id").includes(query)
      && (!category || p.properties.category === category));
    $("place-list").replaceChildren();
    placesLayer.clearLayers();
    for (const feature of filtered) {
      const id = String(feature.properties.id);
      placesLayer.addLayer(state.markers.get(id));
      const button = element("button", "place-item");
      button.dataset.id = id;
      const selected = state.selectedPlace === id;
      button.classList.toggle("is-selected", selected);
      button.setAttribute("aria-pressed", String(selected));
      const index = state.places.indexOf(feature) + 1;
      const text = element("span");
      text.append(element("span", "place-name", feature.properties.name),
        element("span", "place-meta", feature.properties.category || "Lihat lokasi di peta"));
      button.append(element("span", "place-number", String(index).padStart(2, "0")), text, icon("arrow"));
      button.addEventListener("click", () => selectPlace(id));
      $("place-list").append(button);
    }
    $("place-count").textContent = `${filtered.length} dari ${state.places.length}`;
    $("search-empty").hidden = filtered.length > 0;
  }

  function selectedScenario() {
    return state.scenarios.find((s) => s.id === $("scenario").value);
  }

  function renderVisits() {
    const scenario = selectedScenario();
    const visits = scenario?.visits || [];
    const properties = state.result?.features[0].properties;
    $("visit-count").textContent = `${visits.length} wisata`;
    $("visit-list").replaceChildren();
    visits.forEach((visit, index) => {
      const item = element("li", "visit-item");
      const text = element("span");
      text.append(element("span", "visit-name", visit.name));
      const leg = properties?.legs[index];
      if (leg) text.append(element("span", "visit-distance", `${kilometers.format(leg.distance_m / 1000)} km dari ${leg.from}`));
      item.append(element("span", "visit-number", String(index + 1)), text);
      $("visit-list").append(item);
    });
  }

  function updateButtons() {
    $("calculate-button").disabled = !state.ready || !state.start || !selectedScenario() || state.calculating || state.locating || state.picking;
    $("calculate-label").textContent = state.calculating ? "Menghitung jalur…" : "Hitung rute";
    $("locate-button").disabled = !state.ready || state.locating;
    $("pick-button").disabled = !state.ready;
    $("clear-route").disabled = !state.result && !state.calculating;
    $("download-route").disabled = !state.result;
  }

  function refreshLegend() {
    if (!legend) return;
    const properties = state.result?.features[0].properties;
    const line = legend.querySelector(".legend-line");
    line.style.background = safeColor(properties?.color);
    legend.querySelector(".legend-route-name").textContent = properties?.route_name || "Rute simulasi";
    $("map-caption").textContent = properties
      ? `${properties.route_name} · ${kilometers.format(properties.total_distance_km)} km${map.hasLayer(routeLayer) ? "" : " (disembunyikan)"}`
      : `${state.places.length} lokasi wisata budaya`;
  }

  function clearRoute(clearNotice = true) {
    state.requestId += 1;
    state.controller?.abort();
    state.controller = null;
    state.calculating = false;
    state.result = null;
    routeLayer?.clearLayers();
    state.markers.forEach((marker) => marker.setIcon(touristIcon()));
    $("route-summary").hidden = true;
    if (clearNotice) notice("route-status", "");
    renderVisits();
    refreshLegend();
    updateButtons();
  }

  function setPicking(picking) {
    state.picking = picking;
    $("app-shell").classList.toggle("is-picking", picking);
    $("pick-button").classList.toggle("is-picking", picking);
    $("pick-button").setAttribute("aria-pressed", String(picking));
    if (picking) {
      state.locationId += 1;
      state.locating = false;
      resetLocateButton();
      map.closePopup();
      const bounds = L.latLngBounds(state.places.map((p) => [p.geometry.coordinates[1], p.geometry.coordinates[0]]));
      map.stop();
      const startOutside = state.start && !bounds.pad(.25).contains([state.start.lat, state.start.lon]);
      if (startOutside || !map.getBounds().intersects(bounds)) {
        map.fitBounds(bounds, { padding: [65, 65], maxZoom: 15, animate: false });
      }
      mapMessage("Klik pada peta untuk memilih titik awal perjalanan.", true);
      if (mobile.matches) setSidebar(false);
    } else if ($("map-message").textContent.startsWith("Klik pada peta")) mapMessage("");
    updateButtons();
  }

  function resetLocateButton() {
    $("locate-button").replaceChildren(icon("locate"), document.createTextNode("Gunakan lokasi saya"));
  }

  function setStart(lat, lon, source, accuracy) {
    clearRoute();
    state.start = { lat, lon };
    state.locating = false;
    resetLocateButton();
    setPicking(false);
    startLayer.clearLayers();
    const startIcon = L.divIcon({ className: "start-marker", html: "<span></span>", iconSize: [21, 21], iconAnchor: [10.5, 10.5] });
    const marker = L.marker([lat, lon], { icon: startIcon, title: "Titik awal perjalanan", zIndexOffset: 500 });
    marker.bindPopup(element("div", "popup-detail", `Titik awal · ${lat.toFixed(5)}, ${lon.toFixed(5)}`));
    startLayer.addLayer(marker);
    if (Number.isFinite(accuracy) && accuracy > 0) startLayer.addLayer(L.circle([lat, lon], {
      radius: accuracy, color: "#176b50", weight: 1, fillOpacity: .07, interactive: false,
    }));
    $("start-label").textContent = `${source} · ${lat.toFixed(5)}, ${lon.toFixed(5)}`;
    $("start-status").classList.add("is-set");
    const accuracyNote = Number.isFinite(accuracy) ? ` Akurasi lokasi sekitar ${Math.round(accuracy)} m.` : "";
    notice("route-status", `Titik awal dipilih. Pilih skenario lalu hitung rute.${accuracyNote}`);
    map.setView([lat, lon], 16, { animate: false });
    if (mobile.matches) { setTab("rute"); setSidebar(true); }
    updateButtons();
  }

  function locate() {
    setPicking(false);
    if (!navigator.geolocation || !window.isSecureContext) {
      notice("route-status", "GPS memerlukan browser yang mendukung lokasi dan HTTPS atau localhost. Gunakan pilihan titik awal di peta.", true);
      return;
    }
    state.locating = true;
    const id = ++state.locationId;
    $("locate-button").replaceChildren(icon("locate"), document.createTextNode("Mencari lokasi…"));
    notice("route-status", "Mencari lokasi. Izinkan akses lokasi pada browser.");
    updateButtons();
    navigator.geolocation.getCurrentPosition((position) => {
      if (id !== state.locationId) return;
      setStart(position.coords.latitude, position.coords.longitude, "GPS", position.coords.accuracy);
    }, (error) => {
      if (id !== state.locationId) return;
      state.locating = false;
      resetLocateButton();
      const messages = {
        1: "Izin lokasi ditolak. Kamu tetap bisa memilih titik awal dengan klik peta.",
        2: "Lokasi belum dapat ditemukan. Coba lagi atau pilih titik awal di peta.",
        3: "Pencarian lokasi melewati batas waktu. Coba lagi atau pilih titik awal di peta.",
      };
      notice("route-status", messages[error.code] || "GPS tidak tersedia. Pilih titik awal di peta.", true);
      updateButtons();
    }, { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 });
  }

  async function calculate() {
    
    if (!state.start || !selectedScenario() || state.calculating) return;
    clearRoute(false);
    const id = ++state.requestId;
    state.controller = new AbortController();
    state.calculating = true;
    notice("route-status", "Menghitung jalur pada jaringan jalan…");
    updateButtons();
    try {
      const data = await fetchJSON("/api/rute", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scenario_id: selectedScenario().id, start: state.start }),
        signal: state.controller.signal,
      });
      if (id !== state.requestId) return;
      const feature = data?.features?.[0];
      if (data.type !== "FeatureCollection" || feature?.geometry?.type !== "LineString"
        || !Number.isFinite(feature.properties?.total_distance_km)) throw new Error("Hasil rute tidak valid.");
      state.result = data;
      const properties = feature.properties;
      const color = safeColor(properties.color);
      const line = L.geoJSON(data, { style: { color, weight: 5, opacity: .9, lineCap: "round" } });
      routeLayer.addLayer(line);
      properties.snapping.forEach((snap) => routeLayer.addLayer(L.circleMarker([snap.coordinates[1], snap.coordinates[0]], {
        radius: 4, color, weight: 1.5, fillColor: "#fff", fillOpacity: 1, dashArray: "2 2",
      }).bindPopup(element("div", "popup-detail", `Posisi pada jaringan · ${Math.round(snap.distance_m)} m dari titik asli`))));
      if (!map.hasLayer(routeLayer)) routeLayer.addTo(map);
      properties.visits.forEach((visit, index) => {
        const marker = state.markers.get(String(visit.id));
        if (marker) {
          marker.setIcon(touristIcon(index + 1, color));
          if (!placesLayer.hasLayer(marker)) placesLayer.addLayer(marker);
        }
      });
      if (!map.hasLayer(placesLayer)) placesLayer.addTo(map);
      $("total-distance").textContent = kilometers.format(properties.total_distance_km);
      $("result-route-name").textContent = properties.route_name;
      $("route-stop-count").textContent = `${properties.visits.length} wisata · urutan skenario tetap`;
      $("route-summary").hidden = false;
      renderVisits();
      refreshLegend();
      map.fitBounds(line.getBounds(), { padding: mobile.matches ? [35, 55] : [65, 65], maxZoom: 17, animate: !reducedMotion });
      notice("route-status", "Rute berhasil dihitung. Titik awal dan wisata disesuaikan ke ruas terdekat; penanda lingkaran kecil menunjukkan posisi pada jaringan.");
      if (mobile.matches) { setSidebar(false); mapMessage(`${properties.route_name}: ${kilometers.format(properties.total_distance_km)} km. Buka panel untuk rincian.`); }
    } catch (error) {
      if (error.name !== "AbortError" && id === state.requestId) notice("route-status", error.message, true);
    } finally {
      if (id === state.requestId) {
        state.calculating = false;
        state.controller = null;
        updateButtons();
      }
    }
  }

  function fitWisata(reset = true) {
    if (!state.ready || !state.places.length) return;
    setPicking(false);
    if (reset) {
      clearRoute();
      $("search").value = "";
      $("category").value = "";
      $("place-detail").hidden = true;
      state.selectedPlace = null;
      renderPlaces();
    }
    if (!map.hasLayer(placesLayer)) placesLayer.addTo(map);
    const bounds = L.latLngBounds(state.places.map((p) => [p.geometry.coordinates[1], p.geometry.coordinates[0]]));
    map.fitBounds(bounds, { padding: [65, 65], maxZoom: 15, animate: !reducedMotion });
  }

  function initializeMap() {
    map = L.map("map", { zoomControl: false, zoomAnimation: !reducedMotion, fadeAnimation: !reducedMotion,
      markerZoomAnimation: !reducedMotion }).setView([-7.8004, 110.3671], 14);
    const tiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);
    let tileErrorShown = false;
    tiles.on("tileerror", () => {
      if (!tileErrorShown && !state.picking) {
        tileErrorShown = true;
        mapMessage("Peta dasar belum dapat dimuat. Periksa koneksi internet; titik dan rute tetap dapat digunakan.");
      }
    });
    placesLayer = L.featureGroup().addTo(map);
    routeLayer = L.featureGroup().addTo(map);
    startLayer = L.featureGroup().addTo(map);
    roadsLayer = L.geoJSON(null, { style: { color: "#748a7d", weight: 1.4, opacity: .5 }, renderer: L.canvas() });
    L.control.zoom({ position: "topright" }).addTo(map);
    L.control.layers(null, { "Lokasi wisata": placesLayer, "Jaringan jalan": roadsLayer, "Rute simulasi": routeLayer }, { position: "topright" }).addTo(map);
    L.control.scale({ imperial: false, position: "bottomleft" }).addTo(map);
    const FitControl = L.Control.extend({
      options: { position: "topright" },
      onAdd() {
        const container = element("div", "leaflet-control fit-control");
        const button = element("button");
        button.title = "Reset peta ke seluruh wisata";
        button.setAttribute("aria-label", button.title);
        button.append(icon("locate"));
        button.addEventListener("click", () => fitWisata());
        container.append(button);
        L.DomEvent.disableClickPropagation(container);
        return container;
      },
    });
    new FitControl().addTo(map);
    const Legend = L.Control.extend({
      options: { position: "bottomright" },
      onAdd() {
        legend = element("div", "map-legend");
        legend.append(element("div", "legend-title", "KETERANGAN PETA"));
        for (const [symbol, label, labelClass] of [["legend-dot", "Lokasi wisata"], ["legend-start", "Titik awal"],
          ["legend-line", "Rute simulasi", "legend-route-name"], ["legend-anchor", "Posisi pada jaringan"]]) {
          const row = element("div", "legend-row");
          row.append(element("span", symbol), element("span", labelClass, label));
          legend.append(row);
        }
        L.DomEvent.disableClickPropagation(legend);
        return legend;
      },
    });
    new Legend().addTo(map);
    map.on("click", (event) => {
      if (state.picking) setStart(event.latlng.lat, event.latlng.lng, "Pilihan peta");
    });
    map.on("overlayadd overlayremove", refreshLegend);
  }

  async function loadData() {
    try {
      const [places, roads, scenarios] = await Promise.all([
        fetchJSON("/api/wisata"), fetchJSON("/api/jalan"), fetchJSON("/api/skenario"),
      ]);
      if (places.type !== "FeatureCollection" || !Array.isArray(places.features) || !places.features.length
        || roads.type !== "FeatureCollection" || !Array.isArray(roads.features)
        || !Array.isArray(scenarios) || !scenarios.length) throw new Error("Data wisata, jalan, atau skenario tidak valid.");
      state.places = places.features;
      state.scenarios = scenarios;
      if (Number.isFinite(scenarios[0].max_location_snap_m)) $("about-snap-limit").textContent = String(scenarios[0].max_location_snap_m);
      for (const feature of state.places) {
        if (feature.geometry?.type !== "Point" || !feature.properties?.name) throw new Error("Ada lokasi wisata yang tidak valid.");
        const [lon, lat] = feature.geometry.coordinates;
        const marker = L.marker([lat, lon], { icon: touristIcon(), title: feature.properties.name });
        marker.bindPopup(placeContent(feature, true));
        marker.on("click", () => selectPlace(feature.properties.id));
        state.markers.set(String(feature.properties.id), marker);
      }
      roadsLayer.addData(roads);
      const categories = [...new Set(state.places.map((p) => p.properties.category).filter(Boolean))].sort();
      for (const category of categories) {
        const option = element("option", "", category);
        option.value = category;
        $("category").append(option);
      }
      $("category-field").hidden = !categories.length;
      $("scenario").replaceChildren();
      for (const scenario of scenarios) {
        const option = element("option", "", `${scenario.name} · ${scenario.visits.length} wisata`);
        option.value = scenario.id;
        $("scenario").append(option);
      }
      state.ready = true;
      $("scenario").disabled = false;
      $("search").disabled = false;
      notice("app-status", "");
      renderPlaces();
      renderVisits();
      refreshLegend();
      updateButtons();
      fitWisata(false);
    } catch (error) {
      state.ready = false;
      notice("app-status", error.message, true);
      $("map-caption").textContent = "Data belum dapat dimuat";
    } finally { $("app-shell").setAttribute("aria-busy", "false"); }
  }

  function bindEvents() {
    for (const name of ["wisata", "rute"]) {
      $(`tab-${name}`).addEventListener("click", () => setTab(name));
      $(`tab-${name}`).addEventListener("keydown", (event) => {
        if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
          event.preventDefault();
          const next = event.key === "Home" ? "wisata" : event.key === "End" ? "rute" : name === "wisata" ? "rute" : "wisata";
          setTab(next); $(`tab-${next}`).focus();
        }
      });
    }
    $("panel-toggle").addEventListener("click", () => setSidebar(!$("sidebar").classList.contains("is-open")));
    $("panel-close").addEventListener("click", () => setSidebar(false));
    $("mobile-explore").addEventListener("click", () => setSidebar(true));
    $("search").addEventListener("input", renderPlaces);
    $("category").addEventListener("change", renderPlaces);
    $("detail-close").addEventListener("click", () => { $("place-detail").hidden = true; });
    $("scenario").addEventListener("change", () => clearRoute());
    $("locate-button").addEventListener("click", locate);
    $("pick-button").addEventListener("click", () => setPicking(!state.picking));
    $("calculate-button").addEventListener("click", calculate);
    $("clear-route").addEventListener("click", () => clearRoute());
    $("download-route").addEventListener("click", () => {
      if (!state.result) return;
      const blob = new Blob([JSON.stringify(state.result, null, 2)], { type: "application/geo+json" });
      const url = URL.createObjectURL(blob);
      const anchor = element("a");
      anchor.href = url; anchor.download = "rute_wisata.geojson";
      document.body.append(anchor); anchor.click(); anchor.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
    $("about-button").addEventListener("click", () => $("about-dialog").showModal());
    $("about-close").addEventListener("click", () => $("about-dialog").close());
    $("about-dialog").addEventListener("click", (event) => {
      if (event.target === $("about-dialog")) {
        const rect = $("about-dialog").getBoundingClientRect();
        if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) $("about-dialog").close();
      }
    });
    document.addEventListener("keydown", (event) => { if (event.key === "Escape") { setPicking(false); if (mobile.matches) setSidebar(false); } });
    mobile.addEventListener("change", () => { setSidebar(false); map?.invalidateSize(); });
  }

  bindEvents();
  if (typeof L === "undefined") {
    notice("app-status", "Library peta gagal dimuat. Periksa koneksi internet lalu muat ulang halaman.", true);
    $("app-shell").setAttribute("aria-busy", "false");
    return;
  }
  initializeMap();
  loadData();
})();
