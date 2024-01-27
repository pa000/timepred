import logging
from timepred.models import RawVehicleData, VehicleCache, VehicleStopTime
from timepred.processing.present.get import (
    get_next_stoptime,
    get_position,
    get_shape_dist,
)

from .guess import guess_vehicle_data, guess_vehicle_data_after_end_of_trip


def update_shape_dist(rd: RawVehicleData, vc: VehicleCache):
    return get_shape_dist(vc, rd)


def update_vehicle_data(rd: RawVehicleData, vc: VehicleCache) -> VehicleCache | None:
    F = f"update_vehicle_data({rd}, {vc})"
    logging.debug(F)

    trip = vc.trip

    shape_dist = update_shape_dist(rd, vc)
    logging.debug(f"{F} shape_dist == {shape_dist}")
    if shape_dist is None:
        return guess_vehicle_data(rd)

    if shape_dist <= vc.next_stoptime.shape_dist_traveled - 20:  # type: ignore
        next_stoptime = vc.next_stoptime
    else:
        next_stoptime = get_next_stoptime(trip, shape_dist)
    logging.debug(f"{F} next_stoptime == {next_stoptime}")
    if next_stoptime is None:
        return guess_vehicle_data_after_end_of_trip(rd, vc)

    return VehicleCache(
        vehicle_id=rd.vehicle_id,
        route=vc.route,
        trip=vc.trip,
        next_stoptime=next_stoptime,
        position=get_position(rd),
        timestamp=rd.timestamp,
        shape_dist=shape_dist,
        current_vehiclestoptime=vc.current_vehiclestoptime,
        raw=rd,
        trip_instance=vc.trip_instance,
    )
