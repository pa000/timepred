from datetime import date, datetime, time, timedelta
import logging
from django.db.models import Max, Min

import pytz
from timepred.models import RawVehicleData, TripInstance, VehicleCache
from multigtfs.models.feed import Feed
from multigtfs.models.feed_info import FeedInfo
from multigtfs.models.route import Route
from multigtfs.models.trip import Trip
from timepred.processing.present.get import (
    get_active_trips,
    get_next_stoptime,
    get_position,
    get_shape_dist,
)
from collections import defaultdict

from timepred.processing.present.guess.preprocessing import RouteByDate


route_by_date = None


def init(interactive: bool):
    global route_by_date
    route_by_date = RouteByDate(interactive)


def guess_route_with_date(rd: RawVehicleData, date: date) -> Route | None:
    if route_by_date is None:
        raise Exception("Module should be initialized using init")

    F = f"guess_route({rd})"

    if not rd.route_name:
        logging.debug(f"{F} no route_name")
        return None

    routes_on_date = route_by_date.get(date)
    if routes_on_date is None:
        return None

    route_info = routes_on_date.get(rd.route_name)
    if route_info is None:
        return None

    if route_info.start_time <= rd.timestamp <= route_info.end_time:
        return route_info.route

    return None


def guess_route(rd: RawVehicleData) -> Route | None:
    F = f"guess_route({rd}): "
    logging.debug(F)

    route = guess_route_with_date(rd, rd.timestamp.date())
    if route is not None:
        return route

    route = guess_route_with_date(rd, rd.timestamp.date() - timedelta(days=1))
    return route


def guess_trip(
    route: Route, rd: RawVehicleData, exclude_trips: list[Trip] = []
) -> Trip | None:
    F = f"guess_trip({route}, {rd}, {exclude_trips})"
    logging.debug(F)

    active_trips = get_active_trips(route, rd, exclude_trips)
    logging.debug(f"{F} active_trips == {active_trips}")

    if len(active_trips) == 0:
        return None
    if len(active_trips) == 1:
        return active_trips[0]

    trips_with_delay = [
        (trip, delay)
        for trip in active_trips
        if (delay := guess_delay(trip, rd)) is not None
    ]
    logging.debug(f"{F} trips_with_delay == {trips_with_delay}")

    if len(trips_with_delay) > 0:
        return min(trips_with_delay, key=lambda trip: abs(trip[1]))[0]

    return None


guess_shape_dist = get_shape_dist


def guess_delay(trip: Trip, rd: RawVehicleData) -> timedelta | None:
    F = f"guess_delay({trip}, {rd})"
    logging.debug(F)

    shape_dist = guess_shape_dist(trip, rd)
    logging.debug(f"{F} shape_dist == {shape_dist}")
    if shape_dist is None:
        return None

    next_stoptime = get_next_stoptime(trip, shape_dist)
    logging.debug(f"{F} next_stoptime == {next_stoptime}")
    if next_stoptime is None:
        return None

    if next_stoptime.departure_time.seconds < 86400:
        return timedelta(seconds=next_stoptime.departure_time.seconds) - (
            rd.timestamp - rd.timestamp.replace(hour=0, minute=0, second=0)
        )

    return timedelta(seconds=next_stoptime.departure_time.seconds) - (
        rd.timestamp
        - rd.timestamp.replace(hour=0, minute=0, second=0)
        + timedelta(days=1)
    )


def guess_next_trip(vc: VehicleCache) -> Trip | None:
    trip_id = vc.trip.trip_id

    parts = trip_id.split("_")
    if len(parts) != 2:
        return None

    try:
        num_part = int(parts[1])
    except ValueError:
        return None

    next_num_part = num_part + 1
    next_trip_id = parts[0] + "_" + str(next_num_part)

    next_trip = Trip.objects.filter(
        trip_id=next_trip_id, route__feed=vc.trip.route.feed
    ).first()

    if next_trip is None:
        return None

    if next_trip.triptime.start_time < vc.trip.triptime.end_time:
        return None

    return next_trip


def guess_vehicle_data_after_end_of_trip(
    rd: RawVehicleData, vc: VehicleCache
) -> VehicleCache | None:
    F = f"guess_vehicle_data_after_end_of_trip({rd}, {vc})"
    logging.debug(F)

    next_trip = guess_next_trip(vc)
    if next_trip is None:
        return guess_vehicle_data(rd)

    return guess_vehicle_data_with_trip(rd, next_trip)


def guess_vehicle_data(
    rd: RawVehicleData, exclude_trips: list[Trip] = []
) -> VehicleCache | None:
    F = f"guess_vehicle_data({rd}, {exclude_trips})"
    logging.debug(F)

    route = guess_route(rd)
    logging.debug(f"{F} route == {route}")
    if route is None:
        return None

    trip = guess_trip(route, rd, exclude_trips)
    logging.debug(f"{F} trip == {trip}")
    if trip is None:
        return None

    return guess_vehicle_data_with_trip(rd, trip)


def guess_vehicle_data_with_trip(rd: RawVehicleData, trip: Trip) -> VehicleCache | None:
    F = f"guess_vehicle_data_with_trip({rd}, {trip})"

    shape_dist = guess_shape_dist(trip, rd)
    logging.debug(f"{F} shape_dist == {shape_dist}")
    if shape_dist is None:
        return None

    next_stoptime = get_next_stoptime(trip, shape_dist)
    logging.debug(f"{F} next_stoptime == {next_stoptime}")
    if next_stoptime is None:
        return None

    position = get_position(rd)

    return VehicleCache(
        vehicle_id=rd.vehicle_id,
        route=trip.route,
        trip=trip,
        next_stoptime=next_stoptime,
        position=position,
        timestamp=rd.timestamp,
        shape_dist=shape_dist,
        trip_instance=TripInstance(trip=trip, started_at=rd.timestamp),
        raw=rd,
    )
