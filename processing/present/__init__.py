from collections import defaultdict
from datetime import timedelta
from functools import cache
import logging
import itertools
from multiprocessing.managers import DictProxy
import os
from typing import Iterable
from django.conf import settings
from django.db import IntegrityError, transaction
from django import db
from django.db import connection
import shapely

from django.core.cache import cache
from timepred.models import (
    RawVehicleData,
    TripInstance,
    VehicleCache,
    VehicleStopTime,
)
from django.contrib.gis.db.models.functions import Distance, Length, LineLocatePoint
from django.contrib.gis.geos import LineString, Point
from django.db.models import Max, Min, QuerySet, Q, prefetch_related_objects
from timepred.processing.future.strategy import (
    EstimationStrategy,
    SingleStopStrategy,
    get_average_travel_times,
    round_to_n_seconds,
)
from timepred.processing.geohelper import remove_closest_segments
from multigtfs.models.feed import Feed
from multigtfs.models.route import Route
from multigtfs.models.stop_time import StopTime
from multigtfs.models.trip import Trip
from timepred.processing.present import guess
from timepred.processing.present.guess import guess_delay, guess_vehicle_data
from timepred.processing.present.update import update_vehicle_data
import timepred.processing.future as future

from multiprocessing import Pool, Manager, Process, Queue

STRATEGY: EstimationStrategy = SingleStopStrategy(
    20, get_average_travel_times, round_to_n_seconds(15), True
)

m = Manager()
vehicle_queue: "Queue[RawVehicleData]" = Queue(1000)
result_queue: "Queue[tuple[int, VehicleCache | None]]" = Queue(1000)
vehicle_cache: "DictProxy[int, VehicleCache]" = m.dict()
vehicle_by_trip: dict[int, VehicleCache] = {}


def init(interactive: bool):
    guess.init(interactive)

    db.connections.close_all()

    nproc = getattr(settings, "TIMEPRED_NPROC", 2)
    for _ in range(nproc):
        p = Process(
            target=_process_raw_data,
            args=(vehicle_queue, result_queue, vehicle_cache),
        )
        p.start()

    for vc in VehicleCache.objects.all():
        vehicle_cache[vc.vehicle_id] = vc
        vehicle_by_trip[vc.trip_id] = vc


def is_valid(rd: RawVehicleData) -> bool:
    return (
        rd.route_name != ""
        and -90.0 <= rd.latitude <= 90.0
        and -180.0 <= rd.longitude <= 180.0
    )


def process_departure(old_vc: VehicleCache, vc: VehicleCache) -> None:
    F = f"process_departure({old_vc}, {vc})"
    logging.debug(F)

    if old_vc.current_vehiclestoptime is None:
        return

    vst = old_vc.current_vehiclestoptime
    logging.debug(f"{F} vst == {vst}")
    if vst.trip_instance.id is None:
        return

    if vst.stoptime.shape_dist_traveled + 20 < vc.shape_dist:  # type: ignore
        vst.departure_time = old_vc.timestamp
        vst.save()
        vc.current_vehiclestoptime = None


def process_arrival(old_vc: VehicleCache, new_vc: VehicleCache):
    F = f"process_arrival({old_vc}, {new_vc})"
    logging.debug(F)

    next_next_stoptime = (
        old_vc.next_stoptime.stop_sequence + 1 == new_vc.next_stoptime.stop_sequence
    )

    if not next_next_stoptime:
        return

    current_stoptime = old_vc.next_stoptime
    if new_vc.trip_instance.id is not None and abs(current_stoptime.shape_dist_traveled - new_vc.shape_dist) < 30:  # type: ignore
        vst = VehicleStopTime(
            stoptime=current_stoptime,
            arrival_time=new_vc.timestamp,
            trip_instance=new_vc.trip_instance,
        )
        vst.save()
        new_vc.current_vehiclestoptime = vst
        future.estimate_and_save_stoptime_predictions(vst, STRATEGY)

    elif (
        old_vc.trip_instance.id is not None
        and current_stoptime.shape_dist_traveled < new_vc.shape_dist  # type:ignore
        and old_vc.shape_dist < current_stoptime.shape_dist_traveled  # type:ignore
    ):
        total_dist = new_vc.shape_dist - old_vc.shape_dist
        dist_to_stop = (
            current_stoptime.shape_dist_traveled - old_vc.shape_dist  # type:ignore
        )
        dist_part = dist_to_stop / total_dist

        total_time = new_vc.timestamp - old_vc.timestamp
        time_to_stop = total_time * dist_part
        stop_time = old_vc.timestamp + time_to_stop
        vst = VehicleStopTime(
            stoptime=current_stoptime,
            arrival_time=stop_time,
            departure_time=stop_time,
            trip_instance=old_vc.trip_instance,
        )
        vst.save()
        future.estimate_and_save_stoptime_predictions(vst, STRATEGY)


def process_stoptime(vc: VehicleCache) -> VehicleStopTime | None:
    F = f"process_stoptime({vc})"

    old_vc = vehicle_cache.get(vc.vehicle_id)
    if old_vc is None or old_vc.timestamp < vc.timestamp - timedelta(minutes=5):
        return

    process_departure(old_vc, vc)

    process_arrival(old_vc, vc)


def delete(vc: VehicleCache):
    logging.debug(f"delete({vc})")
    vehicle_cache.pop(vc.vehicle_id, None)
    trip_vc = vehicle_by_trip.get(vc.trip_id)
    if vc.trip_instance.id is not None:
        vc.trip_instance.delete()
    if trip_vc is not None and trip_vc.vehicle_id == vc.vehicle_id:
        vehicle_by_trip.pop(vc.trip_id, None)


class Context:
    def __init__(
        self, vehicle_queue, result_queue: "Queue[tuple[int, VehicleCache | None]]"
    ):
        self.vehicle_queue = vehicle_queue
        self.result_queue = result_queue
        self.waiting = set()
        self.processed = []
        self.invalid = set()

    def wait_for(self, vehicle_id: int | None):
        F = f"Context.wait_for({vehicle_id})"

        if vehicle_id is not None and vehicle_id not in self.waiting:
            return

        unsaved = []
        while len(self.waiting) > 0:
            id, other_res = self.result_queue.get()
            self.processed.append(other_res)
            if other_res is not None:
                unsaved.append(other_res)
            logging.debug(f"{F} got result for {id}: {other_res}")

            self.waiting.remove(id)

            if id == vehicle_id:
                break

        for vc in sorted(unsaved, key=lambda vc: vc.timestamp):
            if vc.vehicle_id in self.invalid:
                self.invalid.remove(vc.vehicle_id)
                continue

            save(self, vc)

    def put(self, rd: RawVehicleData):
        F = f"put({rd})"
        logging.debug(F)

        if rd.vehicle_id in self.waiting:
            self.wait_for(rd.vehicle_id)

        logging.debug(f"{F} put")
        self.waiting.add(rd.vehicle_id)
        self.vehicle_queue.put(rd)

    def mark_invalid(self, vehicle_id: int):
        self.invalid.add(vehicle_id)


def save(ctx: Context, vc: VehicleCache):
    F = f"save({vc}):"
    logging.debug(F)

    if vc.trip_instance.id is None:
        vc.trip_instance.save()

    other = vehicle_by_trip.get(vc.trip_id)
    if other and other.vehicle_id != vc.vehicle_id:
        resolve_double_trip(ctx, vc)
        return

    process_stoptime(vc)
    old_vc = vehicle_cache.get(vc.vehicle_id)
    if old_vc is not None and old_vc.trip_id != vc.trip_id:
        vehicle_by_trip.pop(old_vc.trip_id, None)
    vehicle_cache[vc.vehicle_id] = vc
    vehicle_by_trip[vc.trip_id] = vc

    logging.debug(f"{F} vehicle_by_trip[{vc.trip_id}] == {other}")
    logging.debug(f"{F} vehicle_cache[{vc.vehicle_id}] = {vc}")


def process_updated_data(
    rd: RawVehicleData, old_vc: VehicleCache
) -> VehicleCache | None:
    F = f"process_updated_data({rd}, {old_vc}):"
    logging.debug(F)

    updated_vc = update_vehicle_data(rd, old_vc)
    if updated_vc is not None and updated_vc.trip_instance.id is None:
        if updated_vc.trip_instance.trip_id == old_vc.trip_instance.trip_id:
            updated_vc.trip_instance = old_vc.trip_instance
    logging.debug(f"{F} updated_vc == {updated_vc}")

    return updated_vc


def process_new_data(rd: RawVehicleData) -> VehicleCache | None:
    F = f"process_new_data({rd}):"
    logging.debug(F)

    new_vc = guess_vehicle_data(rd)
    logging.debug(f"{F} new_vc == {new_vc}")

    return new_vc


def _process_raw_data(
    vehicle_queue: "Queue[RawVehicleData]",
    result_queue: "Queue[tuple[int, VehicleCache | None]]",
    vehicle_cache: dict[int, VehicleCache],
) -> None:
    while True:
        rd = vehicle_queue.get()

        F = f"{os.getpid()}_process_raw_data({rd})"
        logging.debug(F)

        if not is_valid(rd):
            logging.debug(f"{F} rd is invalid")
            result_queue.put((rd.vehicle_id, None))
            continue

        old_vc = vehicle_cache.get(rd.vehicle_id)
        logging.debug(f"{F} old_vc == {old_vc}")
        if old_vc is not None and (
            timedelta(0) < rd.timestamp - old_vc.timestamp < timedelta(minutes=5)
        ):
            ret = process_updated_data(rd, old_vc)
        elif old_vc is not None and rd.timestamp == old_vc.timestamp:
            ret = old_vc
        else:
            ret = process_new_data(rd)

        logging.debug(f"{F} ret == {ret}")
        result_queue.put((rd.vehicle_id, ret))


def process_many_data(rds: Iterable[RawVehicleData]) -> list[VehicleCache | None]:
    F = f"process_many_data(...)"
    logging.debug(F)

    ctx = Context(vehicle_queue, result_queue)

    for rd in rds:
        logging.debug(f"{F} process {rd}")
        rd.processed = True

        ctx.wait_for(rd.vehicle_id)

        logging.debug(f"{F} adding {rd}")

        ctx.put(rd)

    logging.debug(f"{F} finished iterating, waiting for {len(ctx.waiting)}")
    ctx.wait_for(None)

    with transaction.atomic():
        VehicleCache.objects.all().delete()
        VehicleCache.objects.bulk_create(vehicle_cache.values())
        RawVehicleData.objects.bulk_update(rds, ["processed"])

    return ctx.processed


def resolve_double_trip(ctx: Context, vc: VehicleCache, exclude_trips: list[Trip] = []):
    F = f"resolve_double_trip({vc}, {exclude_trips})"
    logging.debug(F)

    trip = vc.trip
    other = vehicle_by_trip.get(trip.id)
    logging.debug(f"{F} other == {other}")
    if other is None:
        return

    if abs(vc.timestamp - other.timestamp) > timedelta(minutes=5):
        ctx.mark_invalid(other.vehicle_id)
        delete(other)
        save(ctx, vc)

    delay = guess_delay(trip, vc.raw)
    other_delay = guess_delay(trip, other.raw)

    logging.debug(f"{F} delay, other_delay == {delay}, {other_delay}")
    if delay is None or other_delay is None:
        return

    if abs(delay) < abs(other_delay):
        ctx.mark_invalid(other.vehicle_id)
        new = guess_vehicle_data(other.raw, [trip])
        logging.debug(f"{F} new_other == {new}")

        delete(other)
        save(ctx, vc)
    else:
        ctx.mark_invalid(vc.vehicle_id)
        delete(vc)
        new = guess_vehicle_data(vc.raw, exclude_trips + [trip])
        logging.debug(f"{F} new == {new}")

    if new is not None:
        if new.trip_id in vehicle_by_trip:
            resolve_double_trip(ctx, new, exclude_trips + [new.trip])
        else:
            save(ctx, new)


def print_vehicle_info(vehicle_id: int):
    vc = VehicleCache.objects.get(pk=vehicle_id)
    if vc is None:
        return

    info = f"""
trip == {vc.trip.__dict__}
route == {vc.route.__dict__}
next_stoptime == {vc.next_stoptime.__dict__}
next_stoptime.stop == {vc.next_stoptime.stop.__dict__}
timestamp == {vc.timestamp}
raw == {vc.raw.__dict__}
position == {vc.position}"""

    print(info)
