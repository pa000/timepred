from datetime import datetime
import logging
from django.db import connection

from timepred.models import AverageTravelTime, TravelTime, VehicleStopTime


def calculate_travel_times(
    n: int | None, *, after: datetime | None = None, before: datetime | None = None
):
    TravelTime.objects.all().delete()
    with connection.cursor() as cursor:
        cursor.execute(
            (
                f"""INSERT INTO timepred_traveltime(travel_time, from_vehiclestoptime_id, to_vehiclestoptime_id, from_stop_code, to_stop_code)
            SELECT
                vst2.arrival_time - vst1.arrival_time as "travel_time",
                vst1.id as "from_vehiclestoptime_id",
                vst2.id as "to_vehiclestoptime_id",
                s1.code AS "from_stop_code",
                s2.code AS "to_stop_code"
            FROM {VehicleStopTime._meta.db_table} vst1
            JOIN {VehicleStopTime._meta.db_table} vst2 ON vst1.trip_instance_id = vst2.trip_instance_id
            JOIN stop_time st1 ON st1.id = vst1.stoptime_id
            JOIN stop_time st2 ON st2.id = vst2.stoptime_id
            JOIN stop s1 ON st1.stop_id = s1.id
            JOIN stop s2 ON st2.stop_id = s2.id
            WHERE 
                vst1.id <> vst2.id
                AND st1.stop_sequence < st2.stop_sequence
                AND vst1.arrival_time is not null
                AND vst2.arrival_time is not null"""
                + (
                    f" AND vst1.arrival_time <= '{before}'"
                    if before is not None
                    else ""
                )
                + (f" AND vst1.arrival_time >= '{after}'" if after is not None else "")
                + (
                    f" AND st2.stop_sequence - {n} <= st1.stop_sequence"
                    if n is not None
                    else ""
                )
            ),
        )


def calculate_average_travel_times(bin_dur: int):
    AverageTravelTime.objects.all().delete()
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO {AverageTravelTime._meta.db_table}(from_stop_code, to_stop_code, bin, hour, average_travel_time, count)
            SELECT
                tt.from_stop_code AS from_stop_code,
                tt.to_stop_code AS to_stop_code,
                extract(epoch from (tt.travel_time - min_tt.min_travel_time))::integer / {bin_dur} AS bin,
                extract(hour from vst.arrival_time) as hour,
                avg(travel_time) AS average_travel_time,
                count(*) AS count
            FROM {TravelTime._meta.db_table} tt
            JOIN (
                SELECT from_stop_code, to_stop_code, min(travel_time) as min_travel_time
                FROM {TravelTime._meta.db_table} in_tt
                WHERE in_tt.travel_time >= '0'::interval
                GROUP BY (in_tt.from_stop_code, in_tt.to_stop_code)
            ) min_tt ON tt.from_stop_code = min_tt.from_stop_code AND tt.to_stop_code = min_tt.to_stop_code
            JOIN {VehicleStopTime._meta.db_table} vst ON vst.id = tt.from_vehiclestoptime_id
            WHERE tt.travel_time >= '0'::interval
                AND vst.arrival_time is not null
            GROUP BY (tt.from_stop_code, tt.to_stop_code, extract (hour from vst.arrival_time), extract (epoch from (tt.travel_time - min_tt.min_travel_time))::integer / {bin_dur})
"""
        )
