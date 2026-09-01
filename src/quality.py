#!/usr/bin/python3

from typing import Dict


Q_MIN = 1
Q_MAX = 10

BITRATE_MULTIPLIER: Dict[int, float] = {
    1: 0.30,
    2: 0.345,
    3: 0.396,
    4: 0.454,
    5: 0.520,
    6: 0.597,
    7: 0.684,
    8: 0.784,
    9: 0.899,
    10: 1.000,
}

SVT_PRESET_BY_Q: Dict[int, str] = {
    1: '10',
    2: '10',
    3: '9',
    4: '8',
    5: '8',
    6: '7',
    7: '6',
    8: '6',
    9: '5',
    10: '4',
}

TOLERANCE_PERCENT = 20.0


def multiplier_for_quality(q: int) -> float:
    return BITRATE_MULTIPLIER[q]
