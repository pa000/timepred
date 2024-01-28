from django.core.management.base import BaseCommand
import zoneinfo
from django.db import IntegrityError
from timepred.models import RawVehicleData, VehicleCache
from typing import Dict
import logging

from timepred.processing.constants import WROCLAW_TZ

logging.basicConfig(level=logging.DEBUG)

import datetime
import random
import requests
import time
import warnings
import timepred.processing.present as present
from timepred.processing.present import process_many_data

present.init(True)

import cProfile

warnings.filterwarnings("ignore", category=RuntimeWarning)


URL = "https://www.wroclaw.pl/open-data/api/action/datastore_search?resource_id=17308285-3977-42f7-81b7-fdd168c210a2"


def sleep_until(t: datetime.datetime):
    time.sleep(max(0, (t - datetime.datetime.now()).total_seconds()))


class Command(BaseCommand):
    def handle(self, *args, **options):
        # cProfile.runctx("self._handle()", globals(), locals(), "profil")
        self._handle()

    def _handle(self, *args, **options):
        last_raw_data: dict[int, RawVehicleData] = {
            rd.vehicle_id: rd
            for rd in RawVehicleData.objects.filter(
                timestamp__gte=datetime.datetime.now(WROCLAW_TZ)
                - datetime.timedelta(minutes=5)
            )
            .order_by("vehicle_id", "-timestamp")
            .distinct("vehicle_id")
        }
        while True:
            start_time = datetime.datetime.now()
            logging.debug(f"Start time: {start_time}")

            next_loop_time = start_time + datetime.timedelta(seconds=5)

            raw_data = self.get_raw_data()
            if raw_data is None:
                logging.debug("raw_data is None")
                sleep_until(next_loop_time)
                continue

            updated_raw_data = self.get_updated_data(last_raw_data, raw_data)
            logging.info(f"len(updated_data): {len(updated_raw_data)}")
            RawVehicleData.objects.bulk_create(updated_raw_data.values())

            process_many_data(updated_raw_data.values())

            VehicleCache.objects.filter(
                timestamp__lt=datetime.datetime.now(WROCLAW_TZ)
                - datetime.timedelta(minutes=5)
            ).delete()

            end_time = datetime.datetime.now()
            logging.debug(f"End time: {end_time}")
            logging.info(f"Elapsed: {end_time - start_time}")

            last_raw_data = raw_data

            sleep_until(next_loop_time)

    def get_updated_data(
        self, old_data: dict[int, RawVehicleData], new_data: dict[int, RawVehicleData]
    ) -> dict[int, RawVehicleData]:
        return {
            k: new_data[k]
            for k in new_data
            if k not in old_data
            or old_data[k].timestamp < new_data[k].timestamp
            and datetime.datetime.now(WROCLAW_TZ) - new_data[k].timestamp
            <= datetime.timedelta(minutes=5)
        }

    def get_raw_data(self) -> Dict[int, RawVehicleData] | None:
        try:
            response = requests.get(self.get_url())
        except:
            return None
        if response.status_code != 200:
            logging.error(
                f"response.status_code == {response.status_code}. response.text == {response.text}"
            )
            return None

        try:
            data = response.json()
        except requests.exceptions.JSONDecodeError:
            logging.error(f"Decode failed. response.text == {response.text}")
            return None

        if not data["success"]:
            logging.error(f"Request failed. response.text == {response.text}")
            return None

        records = data["result"]["records"]
        cur_data = {
            p.vehicle_id: p for r in records if (p := self.parse_record(r)) is not None
        }

        del data["result"]["records"]
        logging.info(f"get_raw_data: {len(records)} records, {len(cur_data)} parsed")

        return cur_data

    def parse_record(self, record) -> RawVehicleData | None:
        timestamp = record["Data_Aktualizacji"]
        if "." not in timestamp:
            timestamp = timestamp + ".0"
        timestamp = datetime.datetime.strptime(
            timestamp, "%Y-%m-%d %H:%M:%S.%f"
        ).replace(tzinfo=WROCLAW_TZ)
        try:
            return RawVehicleData(
                vehicle_id=int(record["Nr_Boczny"]),
                route_id=record["Brygada"][:-2],
                brigade_id=int(record["Brygada"][-2:]),
                route_name=record["Nazwa_Linii"],
                latitude=record["Ostatnia_Pozycja_Szerokosc"],
                longitude=record["Ostatnia_Pozycja_Dlugosc"],
                timestamp=timestamp,
            )
        except ValueError:
            return None

    def get_url(self) -> str:
        return URL + f"&limit={random.randint(1000, 15000)}"
