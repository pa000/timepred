from collections.abc import Collection, Iterable
import logging
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone
from typing import Any, ClassVar, Self
from django.contrib.gis.db import models as gis
from django.db import DEFAULT_DB_ALIAS, connection, models
from multigtfs.models.route import Route
from multigtfs.models.stop_time import StopTime
from multigtfs.models.trip import Trip
from timepred.processing.constants import WROCLAW_TZ


class AverageTravelTime(models.Model):
    from_stop_code = models.CharField(max_length=255, db_index=True)
    to_stop_code = models.CharField(max_length=255, db_index=True)
    bin = models.IntegerField()
    average_travel_time = models.DurationField()
    hour = models.IntegerField()
    count = models.IntegerField()


class TravelTime(models.Model):
    from_vehiclestoptime = models.ForeignKey(
        "VehicleStopTime",
        on_delete=models.CASCADE,
        related_name="from_vehiclestoptimes",
    )
    to_vehiclestoptime = models.ForeignKey(
        "VehicleStopTime",
        on_delete=models.CASCADE,
        related_name="to_vehiclestoptimes",
    )
    from_stop_code = models.CharField(max_length=255, db_index=True)
    to_stop_code = models.CharField(max_length=255, db_index=True)
    travel_time = models.DurationField()


class TripInstance(models.Model):
    id: int
    trip_id: int
    vehiclestoptime_set: models.Manager["VehicleStopTime"]

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE)
    started_at = models.DateTimeField()

    def __str__(self) -> str:
        return f"TI{self.id}-{self.trip_id}"


class StopPrediction(models.Model):
    stoptimeprediction_set: models.Manager["StopTimePrediction"]

    stop_code = models.CharField(max_length=255, db_index=True)
    stoptime = models.ForeignKey(StopTime, on_delete=models.CASCADE)
    trip_instance = models.ForeignKey(TripInstance, on_delete=models.CASCADE)
    made_at = models.ForeignKey(StopTime, on_delete=models.CASCADE, related_name="+")


class StopTimePrediction(models.Model):
    stop_prediction = models.ForeignKey(StopPrediction, on_delete=models.CASCADE)
    probability = models.FloatField()
    time = models.DateTimeField()

    @classmethod
    def from_db(
        cls, db: str | None, field_names: Collection[str], values: Collection[Any]
    ) -> Self:
        values = list(values)
        if "time" in field_names:
            i = field_names.index("time")
            values[i] = values[i].astimezone(WROCLAW_TZ)
        return super().from_db(db, field_names, values)


class RawVehicleData(models.Model):
    vehicle_id = models.SmallIntegerField()
    route_id = models.CharField(max_length=5, db_index=True)
    route_name = models.CharField(max_length=5, null=True)
    brigade_id = models.SmallIntegerField(db_index=True)
    timestamp = models.DateTimeField(db_index=True)
    latitude = models.FloatField()
    longitude = models.FloatField()
    processed = models.BooleanField(default=False, db_index=True)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

    @classmethod
    def from_db(
        cls, db: str | None, field_names: Collection[str], values: Collection[Any]
    ) -> Self:
        values = list(values)
        if "timestamp" in field_names:
            i = field_names.index("timestamp")
            values[i] = values[i].astimezone(WROCLAW_TZ)
        return super().from_db(db, field_names, values)

    def __str__(self) -> str:
        return f"R{self.pk}-{self.vehicle_id}-{self.route_id}{self.brigade_id}-{self.route_name}-{self.timestamp}"


class VehicleStopTime(models.Model):
    id: int
    trip_instance_id: int

    trip_instance = models.ForeignKey(TripInstance, on_delete=models.CASCADE)
    stoptime = models.ForeignKey(StopTime, on_delete=models.CASCADE)
    arrival_time = models.DateTimeField(null=True)
    departure_time = models.DateTimeField(null=True)

    @classmethod
    def from_db(
        cls, db: str | None, field_names: Collection[str], values: Collection[Any]
    ) -> Self:
        values = list(values)
        if "arrival_time" in field_names:
            i = field_names.index("arrival_time")
            if values[i] is not None:
                values[i] = values[i].astimezone(WROCLAW_TZ)
        if "departure_time" in field_names:
            i = field_names.index("departure_time")
            if values[i] is not None:
                values[i] = values[i].astimezone(WROCLAW_TZ)
        return super().from_db(db, field_names, values)

    def __str__(self) -> str:
        return f"{self.id}-{self.trip_instance.id}:{self.stoptime}-{self.arrival_time}"

    def next(self) -> "VehicleStopTime | None":
        if self.trip_instance is None:
            return None

        return self.trip_instance.vehiclestoptime_set.filter(
            stoptime__stop_sequence=self.stoptime.stop_sequence + 1
        ).first()


class VehicleCache(models.Model):
    next_stoptime_id: int
    trip_id: int
    trip_instance_id: int

    vehicle_id = models.SmallIntegerField(primary_key=True, db_index=True)
    route = models.ForeignKey(Route, on_delete=models.CASCADE, db_index=True)
    trip = models.OneToOneField(Trip, on_delete=models.CASCADE, db_index=True)
    next_stoptime = models.ForeignKey(StopTime, on_delete=models.CASCADE)
    position = gis.PointField()
    timestamp = models.DateTimeField(db_index=True)
    raw = models.ForeignKey(RawVehicleData, on_delete=models.CASCADE)
    shape_dist = models.FloatField()
    current_vehiclestoptime = models.ForeignKey(
        VehicleStopTime, on_delete=models.SET_NULL, null=True
    )
    trip_instance = models.OneToOneField(TripInstance, on_delete=models.CASCADE)

    @classmethod
    def from_db(
        cls, db: str | None, field_names: Collection[str], values: Collection[Any]
    ) -> Self:
        values = list(values)
        if "timestamp" in field_names:
            i = field_names.index("timestamp")
            values[i] = values[i].astimezone(WROCLAW_TZ)
        return super().from_db(db, field_names, values)

    def __str__(self) -> str:
        return f"C{self.vehicle_id}-{self.shape_dist:.0f}m-[{self.trip_instance.id}:{self.trip_id}-{self.next_stoptime_id}]"
