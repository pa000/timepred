from collections import defaultdict
import itertools
import json
from typing import Callable
from timepred.models import (
    AverageTravelTime,
    StopPrediction,
    StopTimePrediction,
    TravelTime,
    TripInstance,
    VehicleCache,
    VehicleStopTime,
)
from multigtfs.models.stop_time import StopTime
from datetime import datetime, time, timedelta

from timepred.processing.future.strategy import EstimationStrategy


def get_stoptime_predictions(
    vst: VehicleStopTime, strategy: EstimationStrategy
) -> tuple[list[StopPrediction], list[StopTimePrediction]]:
    est = estimate_travel_time_vst(vst, strategy)

    all_sps = []
    all_stps = []
    for st, ests in est.items():
        sp = StopPrediction(
            stop_code=st.stop.code,
            stoptime=st,
            trip_instance=vst.trip_instance,
            made_at=vst.stoptime,
        )
        stps = [
            StopTimePrediction(stop_prediction=sp, probability=p, time=time)
            for time, p in ests.items()
            if p >= 0.05
        ]
        all_stps.extend(stps)
        all_sps.append(sp)

    return all_sps, all_stps


def estimate_and_save_stoptime_predictions(
    vst: VehicleStopTime, strategy: EstimationStrategy
):
    all_sps, all_stps = get_stoptime_predictions(vst, strategy)

    StopPrediction.objects.bulk_create(all_sps)
    StopTimePrediction.objects.bulk_create(all_stps)


def estimate_travel_time_vst(
    vst: VehicleStopTime, strategy: EstimationStrategy
) -> dict[StopTime, dict[datetime, float]]:
    if vst is None or vst.arrival_time is None:
        return {}

    est_arrivals: dict[StopTime, dict[datetime, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    est_arrivals[vst.stoptime][vst.arrival_time] = 1

    st_tt: dict[StopTime, dict[datetime, float]] = defaultdict(dict)
    next_stoptimes = list(
        vst.trip_instance.trip.stoptime_set.select_related("stop")
        .filter(stop_sequence__gt=vst.stoptime.stop_sequence)
        .order_by("stop_sequence")
    )

    est_arrivals = strategy.estimate_travel_time(vst, next_stoptimes)

    for st in est_arrivals:
        arrivals_by_minute: dict[datetime, int] = defaultdict(int)
        total_count = 0
        for est_arrival, count in est_arrivals[st].items():
            arrivals_by_minute[est_arrival.replace(second=0, microsecond=0)] += count
            total_count += count

        for arrival, count in arrivals_by_minute.items():
            st_tt[st][arrival] = count / total_count

    st_tt.pop(vst.stoptime, None)
    return st_tt
