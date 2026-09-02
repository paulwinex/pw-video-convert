#!/usr/bin/python3

from typing import Dict


Q_MIN = 1
Q_MAX = 10

SVT_CRF_BY_Q: Dict[int, int] = {
    10: 14,
    9: 16,
    8: 18,
    7: 20,
    6: 22,
    5: 24,
    4: 26,
    3: 28,
    2: 31,
    1: 34,
}

SVT_PRESET_BY_Q: Dict[int, str] = {
    10: '6',
    9: '6',
    8: '7',
    7: '7',
    6: '8',
    5: '8',
    4: '8',
    3: '9',
    2: '9',
    1: '10',
}

VAAPI_GLOBAL_QUALITY_BY_Q: Dict[int, int] = {
    10: 28,
    9: 30,
    8: 32,
    7: 34,
    6: 36,
    5: 38,
    4: 40,
    3: 42,
    2: 44,
    1: 46,
}


def crf_for_quality(q: int) -> int:
    return SVT_CRF_BY_Q[q]


def preset_for_quality(q: int) -> str:
    return SVT_PRESET_BY_Q[q]


def vaapi_quality_for_quality(q: int) -> int:
    return VAAPI_GLOBAL_QUALITY_BY_Q[q]
