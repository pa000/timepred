let map = L.map('map', {
  attributionControl: false
}).setView([51.115039, 17.033088], 13);

L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '&copy; <a href="http://www.openstreetmap.org/copyright">OpenStreetMap</a>'
}).addTo(map);

L.control.attribution({
  position: 'topright'
}).addTo(map);

let lineShapeGroup = L.featureGroup().addTo(map);
let markerGroup = L.featureGroup().addTo(map);

function renderDetails(details) {
  let shape_prev = details.shape_prev;
  let shape_next = details.shape_next;
  let stops = details.stops;

  console.log(details);

  lineShapeGroup.clearLayers();
  L.polyline(shape_next, { weight: 8, color: '#000000' }).addTo(lineShapeGroup);
  L.polyline(shape_next, { weight: 6 }).addTo(lineShapeGroup);

  L.polyline(shape_prev, { weight: 8, opacity: 0.6, color: '#000000' }).addTo(lineShapeGroup);

  for (let i in stops) {
    let stop = stops[i]
    let color = stop.stop_id == details.next_stop_id ?
      'darkviolet' : 'black';
    color = stop.stop_id == details.current_stop_id ? 'orange' : color;

    L.circleMarker(stop.geometry, { radius: 5, color: color, fill: true, fillOpacity: 1 }).addTo(lineShapeGroup);
    L.circleMarker(stop.projected, { radius: 3, color: color, fill: true, fillOpacity: 1 }).addTo(lineShapeGroup);
  }

  L.circleMarker(details.shape_pos, { radius: 6, color: 'orange', fillOpacity: 1, fill: true }).addTo(markerGroup);

  markerGroup.bringToFront();
}

function renderVehicles(vehicles, callback) {
  markerGroup.clearLayers();
  for (vehicle of vehicles) {
    renderVehicle(vehicle, callback);
  }
}

function renderVehicle(vehicle, callback) {
  let latlon = vehicle.position;
  let color = (ctx.detailsType == 'vehicle' && vehicle.vehicle_id == ctx.detailsId) ? 'cyan' : '#3388ff';
  L.circleMarker(latlon, { radius: 12, color: 'black', fillOpacity: 1, fill: true }).addTo(markerGroup);
  L.circleMarker(latlon, { radius: 10, fillOpacity: 1, fill: true, color: color })
    .bindTooltip(vehicle.route_name + ' (' + vehicle.vehicle_id + ')',
      { permanent: true, direction: 'auto' })
    .on('click', () => callback(vehicle.vehicle_id))
    .addTo(markerGroup);
}

function clear() {
  markerGroup.clearLayers();
}
