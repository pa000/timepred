from datetime import date
import os
from pathlib import Path
from django.core.management.base import BaseCommand
import gtfs_kit as gk
from multigtfs.models.feed import Feed
import requests
from multigtfs.models.feed_info import FeedInfo
import logging

logging.basicConfig(level=logging.DEBUG)

URL = "https://www.wroclaw.pl/open-data/87b09b32-f076-4475-8ec9-6020ed1f9ac0/OtwartyWroclaw_rozklad_jazdy_GTFS.zip"


class Command(BaseCommand):
    def handle(self, *args, **options):
        filename = self.download_feed()
        if filename is None:
            return

        feed = gk.read_feed(Path(filename), dist_units="km")
        feed_start_date = gk.helpers.datestr_to_date(
            feed.feed_info["feed_start_date"][0]
        )

        last_date = self.get_latest_feed_start_date()
        if feed_start_date > last_date:  # type: ignore
            logging.debug(feed_start_date)
            name = feed_start_date or str(date.today())
            feed = Feed.objects.create(name=name)
            feed.import_gtfs(filename)

        os.remove(filename)

    def download_feed(self) -> str | None:
        filename = URL.split("/")[-1]
        logging.debug(f"{filename}...")
        response = requests.get(URL)
        if not response.ok:
            logging.debug("not ok")
            return None
        else:
            logging.debug("ok")

        with open(filename, mode="wb") as file:
            file.write(response.content)

        return filename

    def get_latest_feed_start_date(self) -> date | None:
        feed = (
            FeedInfo.objects.filter(start_date__isnull=False)
            .order_by("start_date")
            .last()
        )
        if feed is None:
            return None

        return feed.start_date
