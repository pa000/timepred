from collections import defaultdict
from datetime import date, datetime, time, timedelta
from dataclasses import dataclass

from django.db.models import Max, Min

from multigtfs.models.feed import Feed
from multigtfs.models.feed_info import FeedInfo
from multigtfs.models.route import Route
from timepred.processing.constants import WROCLAW_TZ


@dataclass
class RouteInfo:
    route: Route
    start_time: datetime
    end_time: datetime


RouteByDateDict = dict[date, dict[str, RouteInfo]]


class RouteByDate:
    def __init__(self, interactive: bool) -> None:
        self.interactive = interactive
        if interactive:
            self.next_update_time = datetime.now()
        else:
            self.prepare()

    def prepare(self):
        if self.interactive:
            self.route_by_date = self.prepare_route_by_date_today()
        else:
            self.route_by_date = self.prepare_route_by_date_full()

    def prepare_route_by_date_between(
        self, start_date: date, end_date: date
    ) -> RouteByDateDict:
        rbd: RouteByDateDict = defaultdict(dict)
        while start_date <= end_date:
            feed = (
                Feed.objects.filter(
                    feedinfo__start_date__lte=start_date,
                    feedinfo__end_date__gte=start_date,
                )
                .order_by("-feedinfo__start_date")
                .first()
            )
            if feed is None:
                start_date += timedelta(days=1)
                continue

            for route in feed.route_set.annotate(
                start_time=Min("trip__triptime__start_time"),
                end_time=Max("trip__triptime__end_time"),
            ).all():
                rbd[start_date][route.route_id] = RouteInfo(
                    route=route,
                    start_time=datetime.combine(start_date, time(0, tzinfo=WROCLAW_TZ))
                    + timedelta(seconds=route.start_time.seconds),  # type: ignore
                    end_time=datetime.combine(start_date, time(0, tzinfo=WROCLAW_TZ))
                    + timedelta(seconds=route.end_time.seconds),  # type: ignore
                )

            start_date += timedelta(days=1)

        return rbd

    def prepare_route_by_date_full(self) -> RouteByDateDict:
        earliest_feed = (
            FeedInfo.objects.filter(start_date__isnull=False)
            .order_by("start_date")
            .first()
        )
        if earliest_feed is None:
            return {}

        start_date = earliest_feed.start_date
        assert start_date is not None

        latest_feed = (
            FeedInfo.objects.filter(end_date__isnull=False).order_by("end_date").last()
        )
        if latest_feed is None:
            return {}

        end_date = latest_feed.end_date
        assert end_date is not None

        return self.prepare_route_by_date_between(start_date, end_date)

    def prepare_route_by_date_today(self) -> RouteByDateDict:
        today = datetime.now(WROCLAW_TZ).date()
        return self.prepare_route_by_date_between(
            today - timedelta(days=2), today + timedelta(days=1)
        )

    def get_next_update_time(self):
        return datetime.now() + timedelta(hours=1)

    def get(self, date: date) -> dict[str, RouteInfo] | None:
        if self.interactive and datetime.now() >= self.next_update_time:
            self.next_update_time = self.get_next_update_time()
            self.prepare()

        return self.route_by_date.get(date)
