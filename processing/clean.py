from timepred.models import TripInstance, VehicleStopTime
from django.db.models import Count, Q, F, Exists, OuterRef


def remove_unmonotonic_trip_instances():
    for ti in TripInstance.objects.all():
        vsts = list(
            ti.vehiclestoptime_set.order_by("stoptime__stop_sequence").values_list(
                "arrival_time", flat=True
            )
        )
        if sorted(vsts) != vsts:
            ti.delete()


def remove_empty_single_trip_instances():
    TripInstance.objects.annotate(vsts=Count("vehiclestoptime")).filter(
        vsts__lte=1
    ).delete()


def remove_trip_instances_with_incorrect_stops():
    vsts = VehicleStopTime.objects.filter(
        ~Q(stoptime__trip_id=F("trip_instance__trip_id"))
    )
    for ti in set(vst.trip_instance for vst in vsts):
        ti.delete()


def remove_vehiclestoptimes_that_happened_later():
    VehicleStopTime.objects.filter(
        Exists(
            VehicleStopTime.objects.filter(
                trip_instance__trip_id=OuterRef("trip_instance__trip_id"),
                trip_instance__started_at__date=OuterRef(
                    "trip_instance__started_at__date"
                ),
                trip_instance__started_at__gt=OuterRef("trip_instance__started_at"),
                stoptime__stop_sequence=OuterRef("stoptime__stop_sequence"),
            )
        )
    ).delete()


def remove_incorrect_data():
    remove_vehiclestoptimes_that_happened_later()
    remove_unmonotonic_trip_instances()
    remove_empty_single_trip_instances()
    remove_trip_instances_with_incorrect_stops()
