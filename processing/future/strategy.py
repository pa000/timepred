from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import datetime, timedelta
from functools import partial
from typing import Callable
from multigtfs.models.stop_time import StopTime
from timepred.models import AverageTravelTime, VehicleStopTime
import timepred.processing.past as past


class EstimationStrategy(ABC):
    def preprocess_travel_times(
        self, *, after: datetime | None = None, before: datetime | None = None
    ):
        pass

    @abstractmethod
    def estimate_travel_time(
        self, from_vst: VehicleStopTime, to_sts: list[StopTime]
    ) -> dict[StopTime, dict[datetime, int]]:
        pass


class SingleStopStrategy(EstimationStrategy):
    def __init__(
        self,
        bin_dur: int,
        get_travel_times: Callable[
            [StopTime, StopTime, VehicleStopTime], list[AverageTravelTime]
        ],
        round_f,
        wait_for_departure: bool = False,
    ):
        self.bin_dur = bin_dur
        self.get_travel_times = get_travel_times
        self.wait_for_departure = wait_for_departure
        self.round_f = round_f

    def preprocess_travel_times(
        self, *, after: datetime | None = None, before: datetime | None = None
    ):
        past.calculate_travel_times(1, after=after, before=before)
        past.calculate_average_travel_times(self.bin_dur)

    def estimate_travel_time(
        self,
        from_vst: VehicleStopTime,
        to_sts: list[StopTime],
    ) -> dict[StopTime, dict[datetime, int]]:
        est_arrivals: dict[StopTime, dict[datetime, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        round_f = self.round_f

        if from_vst.arrival_time is None:
            return {}

        est_arrivals[from_vst.stoptime][from_vst.arrival_time] = 1

        for prev_st, st in zip([from_vst.stoptime] + to_sts[:-1], to_sts):
            tts = self.get_travel_times(prev_st, st, from_vst) + [
                AverageTravelTime(
                    count=1,
                    average_travel_time=st.arrival_time.to_timedelta()
                    - prev_st.arrival_time.to_timedelta(),
                )
            ]

            for est_arrival, count in est_arrivals[prev_st].items():
                if self.wait_for_departure and (
                    d := prev_st.arrival_time.delay(est_arrival)
                ) < timedelta(minutes=-1):
                    est_arrival -= d + timedelta(minutes=1)

                for avg_tt in tts:
                    est_next_arrival = est_arrival + avg_tt.average_travel_time
                    est_arrivals[st][round_f(est_next_arrival)] += avg_tt.count * count

        est_arrivals.pop(from_vst.stoptime)

        return est_arrivals


class DirectStrategy(EstimationStrategy):
    def __init__(
        self,
        bin_dur: int,
        get_travel_times: Callable[
            [StopTime, StopTime, VehicleStopTime], list[AverageTravelTime]
        ],
        round_f,
    ):
        self.bin_dur = bin_dur
        self.get_travel_times = get_travel_times
        self.round_f = round_f

    def preprocess_travel_times(
        self, *, after: datetime | None = None, before: datetime | None = None
    ):
        past.calculate_travel_times(None, after=after, before=before)
        past.calculate_average_travel_times(self.bin_dur)

    def estimate_travel_time(
        self, from_vst: VehicleStopTime, to_sts: list[StopTime]
    ) -> dict[StopTime, dict[datetime, int]]:
        est_arrivals: dict[StopTime, dict[datetime, int]] = defaultdict(
            lambda: defaultdict(int)
        )

        round_f = self.round_f

        if from_vst.arrival_time is None:
            return {}

        for st in to_sts:
            tts = self.get_travel_times(from_vst.stoptime, st, from_vst)

            for tt in tts:
                est_next_arrival = from_vst.arrival_time + tt.average_travel_time
                est_arrivals[st][round_f(est_next_arrival)] += tt.count

        return est_arrivals


class NullStrategy(EstimationStrategy):
    def preprocess_travel_times(
        self, *, after: datetime | None = None, before: datetime | None = None
    ):
        return

    def estimate_travel_time(
        self, from_vst: VehicleStopTime, to_sts: list[StopTime]
    ) -> dict[StopTime, dict[datetime, int]]:
        return {}


def get_average_travel_times(from_st: StopTime, to_st: StopTime, vst: VehicleStopTime):
    return list(
        AverageTravelTime.objects.filter(
            from_stop_code=from_st.stop.code,
            to_stop_code=to_st.stop.code,
            hour=vst.arrival_time.hour,
        )
    )


def get_timetable_times(from_st: StopTime, to_st: StopTime, vst: VehicleStopTime):
    return [to_st.arrival_time.to_timedelta() - from_st.arrival_time.to_timedelta()]


def round_seconds(dt, n):
    return (
        dt
        + timedelta(seconds=n // 2)
        - timedelta(seconds=(dt.second + n // 2) % n, microseconds=dt.microsecond)
    )


def round_to_n_seconds(n):
    return partial(round_seconds, n=n)


single_stop_20 = SingleStopStrategy(
    20, get_average_travel_times, round_to_n_seconds(20), False
)

direct_stop_20 = DirectStrategy(20, get_average_travel_times, round_to_n_seconds(20))
