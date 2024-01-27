from datetime import datetime
import logging
from django.db import connection

from timepred.web.models import TravelTime


def calculate_travel_times(n: int, before: datetime):
    TravelTime.objects.all().delete()
    with connection.cursor() as cursor:
        cursor.execute(
            f"""INSERT INTO app_traveltime(travel_time, from_vehiclestoptime_id, to_vehiclestoptime_id, from_stop_code, to_stop_code)
            SELECT
                vst2.arrival_time - vst1.arrival_time as "travel_time",
                vst1.id as "from_vehiclestoptime_id",
                vst2.id as "to_vehiclestoptime_id",
                s1.code AS "from_stop_code",
                s2.code AS "to_stop_code"
            FROM app_vehiclestoptime vst1
            JOIN app_vehiclestoptime vst2 ON vst1.trip_instance_id = vst2.trip_instance_id
            JOIN stop_time st1 ON st1.id = vst1.stoptime_id
            JOIN stop_time st2 ON st2.id = vst2.stoptime_id
            JOIN stop s1 ON st1.stop_id = s1.id
            JOIN stop s2 ON st2.stop_id = s2.id
            WHERE 
                vst1.id <> vst2.id
                AND st2.stop_sequence - %s <= st1.stop_sequence
                AND st1.stop_sequence < st2.stop_sequence
                AND vst1.arrival_time is not null
                AND vst2.arrival_time is not null
                AND vst1.arrival_time <= %s""",
            [n, before],
        )
