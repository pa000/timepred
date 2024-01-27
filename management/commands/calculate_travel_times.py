from datetime import date, timezone
import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from multigtfs.models.feed import Feed
from multigtfs.models.trip import Trip

import sys
import timepred.processing.past as past

logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)


class Command(BaseCommand):
    def handle(self, *args, **options):
        feed = Feed.objects.order_by("feedinfo__start_date").last()
        if feed is None:
            return

        past.calculate_travel_times(1, timezone.now())
