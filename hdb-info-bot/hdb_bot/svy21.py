"""SVY21 <-> WGS84 coordinate conversion.

data.gov.sg's "HDB Carpark Information" dataset gives carpark locations as
SVY21 (Singapore's local Transverse Mercator projection) x/y coordinates,
not lat/lng — this converts them so carparks can be plotted on Google Maps
alongside everything else, with no external API call or cost involved.

Ported from the widely-used reference implementation at
https://github.com/cgcai/SVY21 (Redfearn's transverse Mercator formulas),
using the official SVY21 projection parameters (EPSG:3414):
origin 1.366666N 103.833333E, false northing 38744.572, false easting
28001.642, on the WGS84 ellipsoid.
"""
from __future__ import annotations

import math

# WGS84 ellipsoid
_A = 6378137.0
_F = 1 / 298.257223563
_B = _A * (1 - _F)
_E2 = (2 * _F) - (_F * _F)
_E4 = _E2 * _E2
_E6 = _E4 * _E2

# SVY21 projection (EPSG:3414)
_ORIGIN_LAT = 1.366666
_ORIGIN_LON = 103.833333
_FALSE_NORTHING = 38744.572
_FALSE_EASTING = 28001.642
_SCALE_FACTOR = 1.0

_A0 = 1 - (_E2 / 4) - (3 * _E4 / 64) - (5 * _E6 / 256)
_A2 = (3.0 / 8.0) * (_E2 + (_E4 / 4) + (15 * _E6 / 128))
_A4 = (15.0 / 256.0) * (_E4 + (3 * _E6 / 4))
_A6 = 35 * _E6 / 3072


def _calc_m(lat_deg: float) -> float:
    lat_r = math.radians(lat_deg)
    return _A * (
        (_A0 * lat_r) - (_A2 * math.sin(2 * lat_r)) + (_A4 * math.sin(4 * lat_r)) - (_A6 * math.sin(6 * lat_r))
    )


def _calc_rho(sin2_lat: float) -> float:
    return (_A * (1 - _E2)) / math.pow(1 - _E2 * sin2_lat, 1.5)


def _calc_v(sin2_lat: float) -> float:
    return _A / math.sqrt(1 - _E2 * sin2_lat)


def svy21_to_wgs84(x: float, y: float) -> tuple[float, float]:
    """Convert SVY21 (easting=x, northing=y) to (latitude, longitude)."""
    n_prime = y - _FALSE_NORTHING
    m0 = _calc_m(_ORIGIN_LAT)
    m_prime = m0 + (n_prime / _SCALE_FACTOR)

    n = (_A - _B) / (_A + _B)
    n2, n3, n4 = n * n, n**3, n**4
    g = _A * (1 - n) * (1 - n2) * (1 + (9 * n2 / 4) + (225 * n4 / 64)) * (math.pi / 180)
    sigma = (m_prime * math.pi) / (180.0 * g)

    lat_prime = (
        sigma
        + ((3 * n / 2) - (27 * n3 / 32)) * math.sin(2 * sigma)
        + ((21 * n2 / 16) - (55 * n4 / 32)) * math.sin(4 * sigma)
        + (151 * n3 / 96) * math.sin(6 * sigma)
        + (1097 * n4 / 512) * math.sin(8 * sigma)
    )

    sin_lat_prime = math.sin(lat_prime)
    sin2_lat_prime = sin_lat_prime * sin_lat_prime
    rho_prime = _calc_rho(sin2_lat_prime)
    v_prime = _calc_v(sin2_lat_prime)
    psi_prime = v_prime / rho_prime
    psi2, psi3, psi4 = psi_prime**2, psi_prime**3, psi_prime**4
    t_prime = math.tan(lat_prime)
    t2, t4, t6 = t_prime**2, t_prime**4, t_prime**6

    e_prime = x - _FALSE_EASTING
    xx = e_prime / (_SCALE_FACTOR * v_prime)
    x2, x3, x5, x7 = xx**2, xx**3, xx**5, xx**7

    lat_factor = t_prime / (_SCALE_FACTOR * rho_prime)
    lat = (
        lat_prime
        - lat_factor * ((e_prime * xx) / 2)
        + lat_factor * ((e_prime * x3) / 24) * ((-4 * psi2) + (9 * psi_prime) * (1 - t2) + (12 * t2))
        - lat_factor
        * ((e_prime * x5) / 720)
        * (
            (8 * psi4) * (11 - 24 * t2)
            - (12 * psi3) * (21 - 71 * t2)
            + (15 * psi2) * (15 - 98 * t2 + 15 * t4)
            + (180 * psi_prime) * (5 * t2 - 3 * t4)
            + 360 * t4
        )
        + lat_factor * ((e_prime * x7) / 40320) * (1385 - 3633 * t2 + 4095 * t4 + 1575 * t6)
    )

    sec_lat_prime = 1.0 / math.cos(lat)
    lon = (
        math.radians(_ORIGIN_LON)
        + xx * sec_lat_prime
        - ((x3 * sec_lat_prime) / 6) * (psi_prime + 2 * t2)
        + ((x5 * sec_lat_prime) / 120)
        * ((-4 * psi3) * (1 - 6 * t2) + psi2 * (9 - 68 * t2) + 72 * psi_prime * t2 + 24 * t4)
        - ((x7 * sec_lat_prime) / 5040) * (61 + 662 * t2 + 1320 * t4 + 720 * t6)
    )

    return math.degrees(lat), math.degrees(lon)
