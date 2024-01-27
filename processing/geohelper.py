from django.db.models import Exists, OuterRef
import shapely

from multigtfs.models.stop_time import StopTime
from multigtfs.models.trip import Trip


def cut(
    line: shapely.LineString, distance: float
) -> tuple[shapely.LineString, shapely.LineString]:
    # Cuts a line in two at a distance from its starting point
    if distance <= 0.0 or distance >= line.length:
        return (shapely.LineString([]), shapely.LineString(line))
    coords = list(line.coords)
    for i, p in enumerate(coords):
        pd = line.project(shapely.Point(p))
        if pd == distance:
            return (shapely.LineString(coords[: i + 1]), shapely.LineString(coords[i:]))
        if pd > distance:
            cp = line.interpolate(distance)
            return (
                shapely.LineString(coords[:i] + [(cp.x, cp.y)]),
                shapely.LineString([(cp.x, cp.y)] + coords[i:]),
            )

    assert False


def remove_closest_segments(
    shape: shapely.LineString, point: shapely.Point, dist: float
) -> tuple[shapely.LineString, shapely.LineString]:
    distance = shape.project(point)
    max_dist_left = distance - dist
    min_dist_right = distance + dist
    empty = shapely.LineString([])

    coords = list(shape.coords)
    left = 0
    N = len(coords)
    right = N - 1
    while left != right:
        middle = (left + right) // 2
        mp = coords[middle]
        md = shape.project(shapely.Point(mp))
        if md <= distance:
            left = middle + 1
        else:
            right = middle

    while left >= 1:
        ld = shape.project(shapely.Point(coords[left - 1]))
        if max_dist_left < ld:
            left -= 1
        else:
            break

    while right < N:
        rd = shape.project(shapely.Point(coords[right]))
        if rd < min_dist_right:
            right += 1
        else:
            break

    return (
        shapely.LineString(coords[:left]) if left > 1 else empty,
        shapely.LineString(coords[right:]) if right < N - 1 else empty,
    )


def fix_unmonotone_stops():
    flipped_stops = StopTime.objects.filter(
        Exists(
            StopTime.objects.filter(
                trip_id=OuterRef("trip_id"),
                stop_sequence__gt=OuterRef("stop_sequence"),
                shape_dist_traveled__lt=OuterRef("shape_dist_traveled"),
            )
        )
    )
    trips = set(st.trip for st in flipped_stops)
    N = len(trips)
    for i, trip in enumerate(trips):
        print(f"\r{i}/{N}", end="")
        fix_unmonotone_stops_trip(trip)


def get_flipped_stoptimes(stop_times: list[StopTime]):
    return [
        st1
        for st1 in stop_times
        for st2 in stop_times
        if st1.stop_sequence < st2.stop_sequence
        and st1.shape_dist_traveled > st2.shape_dist_traveled  # type: ignore
        or st1.stop_sequence > st2.stop_sequence
        and st1.shape_dist_traveled < st2.shape_dist_traveled  # type: ignore
    ]


def fix_unmonotone_stops_trip(trip: Trip):
    stop_times = list(trip.stoptime_set.order_by("stop_sequence").all())

    possible_shape_dists = dict()
    for st in stop_times:
        position = st.stop.point.clone()
        position.transform(WROCLAW_UTM)
        position = shapely.Point(position.coords)

        shape = st.trip.geometry.clone()
        shape.transform(WROCLAW_UTM)
        shape = shapely.LineString(shape.coords)

        dist_threshold = max(50, shape.distance(position) * 4)

        def get_sensible_shape_dists(
            shape: shapely.LineString, dist: float
        ) -> list[float]:
            if shape.is_empty:
                return []
            if shape.distance(position) > dist_threshold:
                return []

            sd = dist + shape.project(position)

            left, right = remove_closest_segments(shape, position, 0)
            left_sd = get_sensible_shape_dists(left, dist)
            if right.is_empty:
                right_sd = []
            else:
                right_sd = get_sensible_shape_dists(
                    right, dist + shape.project(shapely.Point(right.coords[0]))
                )

            return [sd] + left_sd + right_sd

        possible_shape_dists[st] = get_sensible_shape_dists(shape, 0)

    def find_sensible(prefix: list[StopTime], suffix: list[StopTime], alpha: float):
        if len(suffix) == 0:
            if len(get_flipped_stoptimes(prefix)) == 0:
                return prefix
            return None

        for sd in possible_shape_dists[suffix[0]]:
            if sd < alpha:
                continue
            suffix[0].shape_dist_traveled = sd
            if sensible := find_sensible(prefix + [suffix[0]], suffix[1:], sd):
                return sensible

        return None

    sensible = find_sensible([], stop_times, 0)
    if sensible is None:
        print(possible_shape_dists)
        print(trip)
        return
    for st in sensible:
        st.save()
