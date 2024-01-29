import datetime
import sys

import logging

from timepred.processing.future.strategy import NullStrategy

logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)

import warnings

warnings.filterwarnings(category=RuntimeWarning, action="ignore")

from django.core.management.base import BaseCommand
from django.db import IntegrityError
from django.db.models import Q

from timepred.models import RawVehicleData, VehicleCache
import timepred.processing.present as present
import timepred.processing.future as future
from timepred.processing.present import process_many_data

present.STRATEGY = NullStrategy
present.init(False)

BATCH_SIZE = 5000


class Command(BaseCommand):
    def handle(self, *args, **options):
        # fmt: off
        unprocessed = (
            RawVehicleData.objects
            .filter(~Q(route_name=''), processed=False, timestamp__gte='2024-01-15 23:00:00+01:00')
            .order_by("timestamp")
        )
        # fmt: on
        N = unprocessed.count()
        i = 0
        print()
        start_time = None
        batch = []
        for rd in unprocessed.iterator(chunk_size=50000):
            batch.append(rd)

            if len(batch) < BATCH_SIZE:
                continue

            if start_time is None:
                start_time = datetime.datetime.now()

            results = process_many_data(batch)
            batch = []

            i += len(results)
            avg = (datetime.datetime.now() - start_time).total_seconds() / i
            remaining = datetime.timedelta(seconds=(N - i) * avg)
            print(
                f"\033[F\r{i}/{N}  {1/avg:.2f}/s  ETA:{remaining} {' '*10}",
                file=sys.stderr,
            )

            print(
                f"\r{results.count(None)} / {len(results)}{' '*30}",
                end="",
                file=sys.stderr,
            )

        if len(batch) > 0:
            process_many_data(batch)
