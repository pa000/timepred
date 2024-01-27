class Past {
  constructor(lines, startTime) {
    this.lines = lines;
    if (lines.length == 0) {
      return;
    }

    $('#timerange').change(this.updatePositions.bind(this))

    fetch(`/history?lines=${lines.join("&lines=")}&` +
       new URLSearchParams({
        startTime: startTime.format(),
      })
    )
    .then(response => response.json())
    .then(vehicleHistory => {
      this.vehicleHistory = vehicleHistory;
      $('#timerange').attr({
        min: 1,
        max: vehicleHistory.length
      })
      $('#past').show();
    })
  }

  destroy() {
    $('#past').hide();
    clear();
  }

  reconstructState() {
    let end = $('#timerange').val();
    let state = new Map();
    let time = undefined;
    for (let vehicle of this.vehicleHistory.slice(0, end)) {
      state.set(vehicle.vehicle_id, vehicle);
      time = vehicle.timestamp;
    }
    $('#curtime').html(time);
    return state.values();
  }
  
  updatePositions() {
    let state = this.reconstructState();
    renderVehicles(state, () => {});
  }
}
