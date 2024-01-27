let ctx = new Present();
let chosenTime = moment();

$(function () {
  $('#details').hide();
  $('#history').hide();
  $('#past').hide();
  $('#timepicker').daterangepicker({
    timePicker: true,
    timePicker24Hour: true,
    startDate: moment().subtract(15, 'minutes'),
    endDate: moment(),
    maxDate: moment(),
    singleDatePicker: true,
    locale: {
      format: "DD.MM HH:mm"
    }
  }, start => chosenTime = start);
});

function showHistory() {
  lines = ctx.lines;
  ctx.destroy();
  ctx = new Past(lines, chosenTime);
}

function exitHistory() {
  ctx.destroy();
  ctx = new Present();
}
