import datetime
import pytz

import shapely
from timepred.processing.future import estimate_travel_time
from timepred.processing.geohelper import cut
from timepred.processing.present.get import get_position, get_route_ids
from django.core.cache import cache
from django.contrib.gis.geos import LineString, Point
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import F, OuterRef, QuerySet, Subquery, Q
from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from multigtfs.models import StopTime

from timepred.models import RawVehicleData, StopPrediction, StopTimePrediction, VehicleCache


def index(request):
    return render(request, "app/index.html", {"lines": get_route_ids()})


class FlippedCoordsEncoder(DjangoJSONEncoder):
    def default(self, o):
        if isinstance(o, Point):
            return [o.y, o.x]
        elif isinstance(o, LineString):
            return [[c[1], c[0]] for c in o.coords]
        return super().default(o)


def vehicles(request):
    lines = request.GET.getlist("lines")
    if lines == []:
        return JsonResponse([], safe=False)

    vehicles = list(
        VehicleCache.objects.filter(route__route_id__in=lines)
        .annotate(route_name=F("route__route_id"))
        .values()
    )

    return JsonResponse(vehicles, safe=False, encoder=FlippedCoordsEncoder)


def history(request):
    start_time = request.GET.get("startTime")
    if start_time is None:
        return JsonResponse({}, safe=False)

    start_time = datetime.datetime.fromisoformat(start_time)

    lines = request.GET.getlist("lines")
    if len(lines) == 0:
        return JsonResponse({}, safe=False)

    history = RawVehicleData.objects.filter(
        timestamp__gte=start_time,
        timestamp__lte=start_time + datetime.timedelta(minutes=15),
        route_name__in=lines,
    ).order_by("timestamp")

    vehicles = [
        {
            "vehicle_id": v.vehicle_id,
            "route_name": v.route_name,
            "timestamp": v.timestamp,
            "position": get_position(v),
        }
        for v in history
    ]

    return JsonResponse(vehicles, safe=False, encoder=FlippedCoordsEncoder)


def stop(request):
    stop_code = request.GET.get("stop_code")
    if stop_code is None:
        return JsonResponse({}, safe=False)

    now = datetime.datetime.now(pytz.timezone("Europe/Warsaw"))
    day_start = now.replace(hour=0, minute=0, second=0)
    since_day_start = now - day_start
    stoptimes = StopTime.objects.select_related("trip").filter(
        Q(
            arrival_time__gte=since_day_start,
            arrival_time__lte=int(
                (since_day_start + datetime.timedelta(hours=1)).total_seconds()
            ),
        )
        | Q(
            arrival_time__gte=int(
                (since_day_start + datetime.timedelta(days=1)).total_seconds()
            ),
            arrival_time__lte=int(
                (since_day_start + datetime.timedelta(days=1, hours=1)).total_seconds()
            ),
        ),
        stop__code=stop_code,
        trip__service__servicedates__date=now.date(),
    )

    sps = (
        StopPrediction.objects.filter(
            stop_code=stop_code,
            stoptimeprediction__time__gte=now,
        )
        .select_related("trip_instance")
        .prefetch_related("stoptimeprediction_set")
        .order_by("trip_instance", "-id")
        .distinct("trip_instance")
    )

    predictions = {
        st.trip: {
            "route_name": st.trip.route.route_id,
            "headsign": st.trip.headsign,
            "probability": "b/d",
            "time": day_start
            + (st.arrival_time.to_timedelta() % datetime.timedelta(days=1)),
            "vehicle_id": None,
        }
        for st in stoptimes
    }

    for sp in sps:
        stps = sp.stoptimeprediction_set.all()
        if len(stps) == 0:
            continue

        most_likely = max(
            sp.stoptimeprediction_set.all(), key=lambda stp: stp.probability
        )
        predictions[sp.trip_instance.trip] = {
            "route_name": sp.trip_instance.trip.route.route_id,
            "headsign": sp.trip_instance.trip.headsign,
            "probability": f"{most_likely.probability * 100:.0f}%",
            "time": most_likely.time,
            "vehicle_id": VehicleCache.objects.filter(trip_instance=sp.trip_instance)
            .get()
            .vehicle_id,
        }

    print(predictions)

    return JsonResponse(
        {
            "view": render_to_string(
                "app/stop_details.html",
                {
                    "predictions": sorted(
                        predictions.values(), key=lambda p: p["time"]
                    ),
                    "stop_name": sp.stoptime.stop.name,
                },
            )
        },
        safe=False,
    )


def details(request):
    try:
        vehicle_id = int(request.GET.get("vehicle_id"))
    except ValueError:
        return JsonResponse({}, safe=False)
    try:
        vehicle = VehicleCache.objects.select_related("trip", "trip_instance").get(
            vehicle_id=vehicle_id
        )
    except VehicleCache.DoesNotExist:
        return JsonResponse({}, safe=False)
    trip = vehicle.trip
    trip_instance = vehicle.trip_instance
    if trip is None or trip_instance is None:
        return JsonResponse({}, safe=False)

    geometry = trip.geometry
    geometry.transform(32633)
    geometry_simpl = geometry.simplify(2)

    vehicle.position.transform(32633)
    simpl_dist = geometry_simpl.project(vehicle.position)
    prev, next = cut(shapely.LineString(geometry_simpl), simpl_dist)
    prev = LineString(list(prev.coords), srid=32633)
    next = LineString(list(next.coords), srid=32633)
    prev.transform(4326)
    next.transform(4326)

    geometry_simpl.transform(4326)
    shape_simpl = geometry_simpl

    stop_times: QuerySet[StopTime] = trip.stoptime_set.select_related("stop").order_by(
        "stop_sequence"
    )

    stop_times_with_real = {
        st: st
        for st in stop_times.annotate(
            real_arrival_time=Subquery(
                trip_instance.vehiclestoptime_set.filter(
                    stoptime_id=OuterRef("id")
                ).values("arrival_time")[:1]
            ),
            real_departure_time=Subquery(
                trip_instance.vehiclestoptime_set.filter(
                    stoptime_id=OuterRef("id")
                ).values("departure_time")[:1]
            ),
        )
    }

    sps = StopPrediction.objects.prefetch_related("stoptimeprediction_set").filter(
        trip_instance=trip_instance, made_at_next_stoptime=vehicle.next_stoptime
    )

    estimated_times = {}

    for sp in sps:
        if sp.stoptime.stop_sequence < vehicle.next_stoptime.stop_sequence:
            continue

        estimated_times[sp.stoptime] = sorted(
            [
                (stp.time, stp.probability)
                for stp in sp.stoptimeprediction_set.all()
                if stp.probability > 0.05
            ]
        )

    for st, ets in estimated_times.items():
        stop_times_with_real[st].estimated_times = ets

    pos = geometry.interpolate(vehicle.shape_dist)
    pos.transform(4326)

    proj: dict[StopTime, Point] = {}
    for st in stop_times:
        proj[st] = geometry.interpolate(st.shape_dist_traveled)
        proj[st].transform(4326)

    details = {
        "stop_times": stop_times_with_real,
        "next_stoptime": vehicle.next_stoptime,
        "route_name": vehicle.route.route_id,
        "headsign": trip.headsign,
    }

    return JsonResponse(
        {
            "shape_prev": prev,
            "shape_next": next,
            "stops": {
                stoptime.stop.stop_id: {
                    "stop_id": stoptime.stop.stop_id,
                    "geometry": stoptime.stop.point,
                    "projected": proj[stoptime],
                }
                for stoptime in stop_times
            },
            "next_stop_id": vehicle.next_stoptime.stop.stop_id,
            "current_stop_id": vehicle.current_vehiclestoptime.stoptime.stop.stop_id
            if vehicle.current_vehiclestoptime is not None
            else -1,
            "view": render_to_string("app/details.html", details),
            "shape_pos": pos,
        },
        safe=False,
        encoder=FlippedCoordsEncoder,
    )
