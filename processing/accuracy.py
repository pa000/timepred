from collections import defaultdict
from datetime import date, datetime, time, timedelta
from multigtfs.models.stop_time import StopTime
from timepred.models import StopPrediction, StopTimePrediction, VehicleStopTime
import tqdm
from timepred.processing.future.strategy import EstimationStrategy
from timepred.processing.parallel import ParallelManager

from multiprocessing import Pool

pool = Pool(8)

import timepred.processing.future as future


def test_accuracy(strategy: EstimationStrategy, date: date):
    StopPrediction.objects.all().delete()
    strategy.preprocess_travel_times(before=datetime.combine(date, time(0)))

    N = VehicleStopTime.objects.filter(arrival_time__date=date).count()
    vsts = VehicleStopTime.objects.filter(arrival_time__date=date)

    all_sps = []
    all_stps = []
    for sps, stps in tqdm.tqdm(
        pool.imap_unordered(future.get_stoptime_predictions, vsts.iterator(5000)),
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
            stop_prediction__stoptime=vst.stoptime
        )
        real_arrival_minute = vst.arrival_time.replace(second=0, microsecond=0)

        for stp in preds:
            result = (
                real_arrival_minute == stp.time
                or (vst.arrival_time + timedelta(seconds=10)).replace(
                    second=0, microsecond=0
                )
                == stp.time
            )
            prob = int(stp.probability * 100)
            results[prob].append(result)

    results_ratio = {p: sum(r) / len(r) for p, r in results.items() if len(r) > 0}

    return sorted(results_ratio.items(), key=lambda p: p[0])
