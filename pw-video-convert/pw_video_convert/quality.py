from typing import Dict


Q_MIN = 1
Q_MAX = 10

SVT_CRF_BY_Q: Dict[int, int] = {
    10: 14,
    9: 16,
    8: 18,
    7: 20,
    6: 23,
    5: 26,
    4: 29,
    3: 34,
    2: 39,
    1: 44,
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

# VAAPI AV1 exposes its quantizer as AV1 base_q_idx, which spans 0..255,
# unlike H.264/HEVC (0..51). Map it from the software CRF scale, where one
# CRF step is roughly four qindex steps, so both encoders stay aligned and
# low quality values actually get aggressive.
VAAPI_QP_PER_CRF = 4
VAAPI_QP_MAX = 255

VAAPI_GLOBAL_QUALITY_BY_Q: Dict[int, int] = {
    q: min(crf * VAAPI_QP_PER_CRF, VAAPI_QP_MAX)
    for q, crf in SVT_CRF_BY_Q.items()
}


def crf_for_quality(q: int) -> int:
    return SVT_CRF_BY_Q[q]


def preset_for_quality(q: int) -> str:
    return SVT_PRESET_BY_Q[q]


def vaapi_quality_for_quality(q: int) -> int:
    return VAAPI_GLOBAL_QUALITY_BY_Q[q]
