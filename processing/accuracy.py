from multiprocessing import Pool

pool = Pool(10)
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from multigtfs.models.stop_time import StopTime
from timepred.models import StopPrediction, StopTimePrediction, VehicleStopTime
import tqdm
from functools import partial

from timepred.processing.future.strategy import EstimationStrategy
import timepred.processing.future as future


def test_accuracy(
    strategy: EstimationStrategy, date: date, skip_preprocessing: bool = False
):
    StopPrediction.objects.all().delete()
    if not skip_preprocessing:
        strategy.preprocess_travel_times(before=datetime.combine(date, time(0)))

    N = VehicleStopTime.objects.filter(arrival_time__date=date).count()
    vsts = VehicleStopTime.objects.filter(arrival_time__date=date)

    all_sps = []
    all_stps = []
    for sps, stps in tqdm.tqdm(
        pool.imap_unordered(
            partial(future.get_stoptime_predictions, strategy=strategy),
            vsts.iterator(5000),
        ),
        total=vsts.count(),
    ):
        if len(all_stps) > 50000:
            StopPrediction.objects.bulk_create(all_sps)
            StopTimePrediction.objects.bulk_create(all_stps)
            all_sps = []
            all_stps = []

        all_sps.extend(sps)
        all_stps.extend(stps)

    StopPrediction.objects.bulk_create(all_sps)
    StopTimePrediction.objects.bulk_create(all_stps)
    all_sps = []
    all_stps = []

    results: dict[int, list[bool]] = defaultdict(list)
    for vst in tqdm.tqdm(vsts.iterator(5000), total=vsts.count()):
        if vst.arrival_time is None:
            continue

        preds = StopTimePrediction.objects.filter(
            stop_prediction__stoptime=vst.stoptime,
            stop_prediction__trip_instance=vst.trip_instance,
        )
        real_arrival_minute = vst.arrival_time.replace(second=0, microsecond=0)

        for stp in preds:
            result = real_arrival_minute == stp.time
            prob = int(stp.probability * 100)
            results[prob].append(result)

    results_ratio = {p: sum(r) / len(r) for p, r in results.items() if len(r) > 0}

    return sorted(results_ratio.items(), key=lambda p: p[0])


def save_to_file(results: list[tuple[int, float]], filename: str):
    with open(filename, "w") as file:
        file.write("probability,score\n")
        for p, r in results:
            file.write(f"{p},{r*100}\n")


def check_accuracy(after: datetime, before: datetime):
    vsts = VehicleStopTime.objects.filter(
        arrival_time__lte=before, arrival_time__gte=after
    )
    N = vsts.count()

    results: dict[int, list[bool]] = defaultdict(list)
    for vst in tqdm.tqdm(vsts.iterator(5000), total=vsts.count()):
        if vst.arrival_time is None:
            continue

        preds = StopTimePrediction.objects.filter(
            stop_prediction__stoptime=vst.stoptime,
            stop_prediction__trip_instance=vst.trip_instance,
        )
        real_arrival_minute = vst.arrival_time.replace(second=0, microsecond=0)

        for stp in preds:
            result = real_arrival_minute == stp.time
            prob = int(stp.probability * 100)
            results[prob].append(result)

    results_ratio = {p: sum(r) / len(r) for p, r in results.items() if len(r) > 0}

    return sorted(results_ratio.items(), key=lambda p: p[0])
