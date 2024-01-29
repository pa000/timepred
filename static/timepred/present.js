class Present {
  constructor() {
    this.interval = setInterval(this.updatePositions.bind(this), 3000);
    this.detailsType = null;
    this.detailsId = null;
    this.lines = [];
    $('#lines').show();
  }

  destroy() {
    clearInterval(this.interval);
    $('#lines').hide();
    clear();
  }

  showStopDetails() {
    if (this.detailsType != 'stop' || this.detailsId == null)
      return;

    fetch(`/stop?stop_code=${this.detailsId}`)
      .then(response => response.json())
      .then(details => {
        $('#details').html(details.view);
    });
  }

  showVehicleDetails() {
    if (this.detailsType != 'vehicle' || this.detailsId == null)
      return;

    fetch(`/details?vehicle_id=${this.detailsId}`)
      .then(response => response.json())
      .then(details => {
        if (!this.lines.includes(details.route_name))
          this.toggleLine(details.route_name)
        renderDetails(details);

        $('#details').html(details.view);
      });
  }

  showDetails() {
    if (this.detailsType == 'vehicle')
      this.showVehicleDetails();
    else if (this.detailsType == 'stop')
      this.showStopDetails();
  }

  updatePositions() {
    if (this.lines.length == 0) {
      clear();
      $('#details').hide();
      $('#history').hide();
      return;
    }
    $('#history').show();

    fetch(`/vehicles?lines=${this.lines.join('&lines=')}`)
      .then(response => response.json())
      .then(vehicles =>
        renderVehicles(vehicles, vehicleId => {
          this.detailsId = vehicleId;
          this.detailsType = 'vehicle';
          $('#details').show();
          this.showDetails();
        }));

    this.showDetails();
  }

  setDetails(type, id) {
    if (type != 'stop' && type != 'vehicle')
      return;

    this.detailsType = type;
    this.detailsId = id;
    $('#details').show();
    this.showDetails();
  }

  toggleLine(line) {
    let i = this.lines.indexOf(line);
    if (i < 0) {
      this.lines.push(line)
      this.setLines(this.lines)
    } else {
      this.setLines(this.lines.toSpliced(i, 1))
    }
  }

  setLines(l) {
    for (let line of this.lines) {
      $(`#line-${line}`).removeClass('chosen');
    }

    this.lines = l;

    for (let line of this.lines) {
      $(`#line-${line}`).addClass('chosen');
    }

    this.updatePositions();
  }
}
