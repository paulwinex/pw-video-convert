from typing import Dict, Optional


Q_MIN = 1
Q_MAX = 10

# q=10 targets visually transparent AV1 (re-encode of an already decent
# H.264 source, only the codec changes): CRF 10 keeps the top tier in the
# near-lossless region instead of the "good but visibly compressed" CRF 14.
# Higher tiers are raised proportionally, tapering to the unchanged
# size-oriented tiers at the bottom of the scale.
SVT_CRF_BY_Q: Dict[int, int] = {
    10: 10,
    9: 13,
    8: 15,
    7: 18,
    6: 21,
    5: 25,
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

# When re-encoding from already-compressed codecs like HEVC/H.265 or AV1,
# the base quality mapping tuned for H.264 sources is too "conservative"
# (too high quality/too low CRF for the desired size reduction). Push CRF up
# (aggressively drop quality) for those sources.
REENCODE_HEAVY_SOURCE_CRFS = {
    10: 16,
    9: 19,
    8: 21,
    7: 24,
    6: 27,
    5: 31,
    4: 35,
    3: 39,
    2: 43,
    1: 47,
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

VAAPI_GLOBAL_QUALITY_BY_Q_HEAVY: Dict[int, int] = {
    q: min(crf * VAAPI_QP_PER_CRF, VAAPI_QP_MAX)
    for q, crf in REENCODE_HEAVY_SOURCE_CRFS.items()
}


_HEAVY_CODECS = {'hevc', 'h265', 'av1'}


def is_heavy_source_codec(codec_name: Optional[str]) -> bool:
    if not codec_name:
        return False
    return codec_name.lower() in _HEAVY_CODECS


def crf_for_quality(q: int, source_codec: Optional[str] = None) -> int:
    if is_heavy_source_codec(source_codec):
        return REENCODE_HEAVY_SOURCE_CRFS[q]
    return SVT_CRF_BY_Q[q]


def preset_for_quality(q: int, source_codec: Optional[str] = None) -> str:
    return SVT_PRESET_BY_Q[q]


def vaapi_quality_for_quality(q: int, source_codec: Optional[str] = None) -> int:
    if is_heavy_source_codec(source_codec):
        return VAAPI_GLOBAL_QUALITY_BY_Q_HEAVY[q]
    return VAAPI_GLOBAL_QUALITY_BY_Q[q]
