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

_predict = True


def init(predict: bool = True):
    global _predict
    _predict = predict


def round_to_15_seconds(dt):
    return (
        dt
        + timedelta(seconds=7)
        - timedelta(seconds=(dt.second + 7) % 15, microseconds=dt.microsecond)
    )


def get_stoptime_predictions(
    vst: VehicleStopTime, round_f=round_to_15_seconds
) -> tuple[list[StopPrediction], list[StopTimePrediction]]:
    est = estimate_travel_time_vst(vst, round_f)

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
    vst: VehicleStopTime, round_f: Callable[[datetime], datetime] = round_to_15_seconds
):
    if not _predict:
        return

    all_sps, all_stps = get_stoptime_predictions(vst, round_f)

    StopPrediction.objects.bulk_create(all_sps)
    StopTimePrediction.objects.bulk_create(all_stps)


# all_avg_tts: dict[tuple[str, str, int], list[AverageTravelTime]] = defaultdict(list)
# for avg_tt in AverageTravelTime.objects.all():
#     all_avg_tts[avg_tt.from_stop_code, avg_tt.to_stop_code, avg_tt.hour].append(avg_tt)


def get_average_tts(from_stop: str, to_stop: str, hour: int):
    return list(
        AverageTravelTime.objects.filter(
            from_stop_code=from_stop, to_stop_code=to_stop, hour=hour
        )
    )


def estimate_travel_time_vst(
    vst: VehicleStopTime, round_f: Callable[[datetime], datetime] = round_to_15_seconds
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

    for prev_st, st in zip([vst.stoptime] + next_stoptimes[:-1], next_stoptimes):
        avg_tts = get_average_tts(
            prev_st.stop.code, st.stop.code, vst.arrival_time.hour
        ) + [
            AverageTravelTime(
                count=1,
                average_travel_time=st.arrival_time.to_timedelta()
                - prev_st.arrival_time.to_timedelta(),
            )
        ]
        for est_arrival, count in est_arrivals[prev_st].items():
            # if (d := prev_st.arrival_time.delay(est_arrival)) < timedelta(minutes=-1):
            #     est_arrival -= d + timedelta(minutes=1)
            for avg_tt in avg_tts:
                est_next_arrival = vst.arrival_time + avg_tt.average_travel_time
                est_arrivals[st][round_f(est_next_arrival)] += avg_tt.count * count

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
