from datetime import date, datetime
from timepred.processing.constants import WROCLAW_TZ
import re
import os
from pathlib import Path
from django.core.management.base import BaseCommand
import gtfs_kit as gk
from multigtfs.models.feed import Feed
import requests
from multigtfs.models.feed_info import FeedInfo
import logging

logging.basicConfig(level=logging.DEBUG)

HISTORY_URL = "https://opendata.cui.wroclaw.pl/dataset/rozkladjazdytransportupublicznegoplik_data/resource_history/7d10d77f-bcf3-47b2-a608-613971c4f5f8"
URL_PATTERN = 'https://www.wroclaw.pl/open-data/dataset/ff9b861f-40f0-4b12-9454-73a07ed55dc0/resource/[^/]+/download_old_version/[^"]+.zip'


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            "--all",
            action="store_true",
            help="download and import all feeds that start today or later",
        )

    def handle(self, *args, **options):
        feed_urls = self.get_feed_urls()
        for feed_url in feed_urls:
            filename = self.download_feed(feed_url)
            if filename is None:
                return

            feed = gk.read_feed(Path(filename), dist_units="km")
            feed_start_date: date = gk.helpers.datestr_to_date(
                feed.feed_info["feed_start_date"][0]
            )

            logging.debug(f"{filename} starts on {feed_start_date}")
            exists_feed = self.exists_feed_starting_on(feed_start_date)
            latest_feed = FeedInfo.objects.order_by("start_date").last()
            if latest_feed is not None and latest_feed.start_date is not None:
                latest_date = latest_feed.start_date
            else:
                latest_date = date.min

            if not exists_feed:
                logging.debug("and is a new feed")
                name = feed_start_date or str(date.today())
                feed = Feed.objects.create(name=name)
                feed.import_gtfs(filename)
            else:
                logging.debug("and already have that feed")

            os.remove(filename)

            if not options["all"] and feed_start_date <= latest_date:
                break
            if feed_start_date <= datetime.now(WROCLAW_TZ).date():
                break

    def download_feed(self, url: str) -> str | None:
        filename = url.split("/")[-1]
        logging.debug(f"{filename}...")
        response = requests.get(url)
        if not response.ok:
            logging.debug("not ok")
            return None
        else:
            logging.debug("ok")

        with open(filename, mode="wb") as file:
            file.write(response.content)

        return filename

    def exists_feed_starting_on(self, date: date) -> bool:
        return FeedInfo.objects.filter(start_date=date).exists()

    def get_feed_urls(self) -> list[str]:
        response = requests.get(HISTORY_URL)
        text = response.text
        feed_urls = re.findall(URL_PATTERN, text)

        # the url appears twice for every feed
        return feed_urls[::2]
