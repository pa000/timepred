import datetime
import logging

from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.db.models import QuerySet, Q
import shapely
from timepred.models import RawVehicleData, VehicleCache
from timepred.processing.geohelper import remove_closest_segments
from timepred.processing.constants import WROCLAW_UTM, WSG84
from multigtfs.models.feed import Feed
from multigtfs.models.route import Route
from multigtfs.models.stop_time import StopTime
from multigtfs.models.trip import Trip


def get_position(rd: RawVehicleData) -> Point:
    return Point(rd.longitude, rd.latitude, srid=WSG84)


def get_route_ids():
    ROUTES = "route_ids"
    routes = cache.get(ROUTES)
    if routes is not None:
        return routes

    today = datetime.datetime.today()
    feed = (
        Feed.objects.filter(
            feedinfo__start_date__lte=today, feedinfo__end_date__gte=today
        )
        .order_by("-feedinfo__start_date")
        .first()
    )
    if feed is None:
        return []

    routes = list(feed.route_set.order_by("id").values_list("route_id", flat=True))
    cache.set(ROUTES, routes, timeout=60 * 60)
    return routes


def get_next_stoptime(trip: Trip, shape_dist: float) -> StopTime | None:
    return (
        trip.stoptime_set.filter(shape_dist_traveled__gte=shape_dist + 20)
        .order_by("stop_sequence")
        .first()
    )


def get_shape_dist(trip_or_vc: Trip | VehicleCache, rd: RawVehicleData) -> float | None:
    if isinstance(trip_or_vc, Trip):
        trip = trip_or_vc
        vc = None
    else:
        trip = trip_or_vc.trip
        vc = trip_or_vc

    shape = trip.geometry.clone()
    shape.transform(WROCLAW_UTM)
    shape = shapely.LineString(shape.coords)

    position = get_position(rd)
    position.transform(WROCLAW_UTM)
    position = shapely.Point(position.coords)

    def get_shape_dist_rec(shape: shapely.LineString, dist: float) -> float | None:
        if shape.is_empty:
            return None
        if shape.distance(position) > 200:
            return None

        shape_dist = dist + shape.project(position)
        possible_shape_dists: list[float] = [shape_dist]

        left, right = remove_closest_segments(shape, position, 200)
        left_sd = get_shape_dist_rec(left, dist)
        if left_sd is not None:
            possible_shape_dists.append(left_sd)
        if not right.is_empty:
            right_sd = get_shape_dist_rec(
                right, dist + shape.project(shapely.Point(right.coords[0]))
            )
            if right_sd is not None:
                possible_shape_dists.append(right_sd)

        if vc is not None:
            min_dist = vc.shape_dist
            epsilon = 10
            possible_shape_dists = [
                sd for sd in possible_shape_dists if sd >= min_dist - epsilon
            ]
        else:
            min_dist = 0

        if len(possible_shape_dists) == 0:
            return None
        return min(possible_shape_dists, key=lambda sd: sd - min_dist)

    return get_shape_dist_rec(shape, 0)


def get_active_trips(
    route: Route, rd: RawVehicleData, exclude_trips: list[Trip] = []
) -> QuerySet[Trip]:
    active_trips = route.trip_set.filter(
        brigade_id=rd.brigade_id,
    ).filter(
        Q(
            triptime__start_time__lte=rd.timestamp
            - rd.timestamp.replace(hour=0, minute=0, second=0),
            triptime__end_time__gte=rd.timestamp
            - rd.timestamp.replace(hour=0, minute=0, second=0),
            service__servicedates__date=rd.timestamp.date(),
        )
        | Q(
            # need to manually convert to int
            # because the string representation of the interval is "1 day, ..."
            # and SecondsField expects it to be HH:MM:SS
            triptime__start_time__lte=int(
                (
                    rd.timestamp
                    - rd.timestamp.replace(hour=0, minute=0, second=0)
                    + datetime.timedelta(days=1)
                ).total_seconds()
            ),
            triptime__end_time__gte=int(
                (
                    rd.timestamp
                    - rd.timestamp.replace(hour=0, minute=0, second=0)
                    + datetime.timedelta(days=1)
                ).total_seconds()
            ),
            service__servicedates__date=rd.timestamp.date()
            - datetime.timedelta(days=1),
        ),
    )

    if len(exclude_trips) > 0:
        return active_trips.exclude(id__in=[trip.id for trip in exclude_trips])
    return active_trips
