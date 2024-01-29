from datetime import date, timezone
import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from multigtfs.models.feed import Feed
from multigtfs.models.trip import Trip

import sys
from timepred.processing.present import STRATEGY

logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)


class Command(BaseCommand):
    def handle(self, *args, **options):
        STRATEGY.preprocess_travel_times()
