from hypothesis import given
from hypothesis.extra.django import TestCase, from_model
import hypothesis.strategies as st

from timepred.models import RawVehicleData
from multigtfs.models.feed import Feed
from multigtfs.models.route import Route
from multigtfs.models.trip import Trip
from processing.present.guess import guess_route


# Create your tests here.
class ServiceTestCase(TestCase):
    @given(route=routes, rd=rds)
    def test_guess_route(self, route: Route, rd: RawVehicleData):
        rd.route_id = route.route_id
        rd.route_name = route.route_id

        guessed_route = guess_route(rd)
        assert guessed_route is None or guessed_route.id == route.id
