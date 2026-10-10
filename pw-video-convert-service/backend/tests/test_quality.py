import app.core.config  # noqa: F401  # installs pw-video-convert on sys.path
from pw_video_convert import quality

QUALITIES = list(range(quality.Q_MIN, quality.Q_MAX + 1))

# AV1 base_q_idx (what VAAPI exposes via -global_quality) spans 0..255,
# unlike H.264/HEVC where the scale is 0..51.
AV1_QP_MIN = 0
AV1_QP_MAX = 255


def test_vaapi_qp_within_av1_range():
    for q in QUALITIES:
        assert AV1_QP_MIN <= quality.vaapi_quality_for_quality(q) <= AV1_QP_MAX


def test_vaapi_qp_is_aggressive_at_lowest_quality():
    # q=1 means "small and acceptable": its QP must sit deep in the AV1
    # scale, otherwise VAAPI stays in the high-quality/low-QP region and the
    # output ends up larger than an already efficient source.
    assert quality.vaapi_quality_for_quality(1) >= 150


def test_vaapi_qp_decreases_as_quality_rises():
    values = [quality.vaapi_quality_for_quality(q) for q in QUALITIES]
    assert values == sorted(values, reverse=True)


def test_vaapi_qp_tracks_software_crf_scale():
    for q in QUALITIES:
        assert quality.vaapi_quality_for_quality(q) == quality.crf_for_quality(q) * 4


def test_software_crf_is_aggressive_at_lowest_quality():
    assert quality.crf_for_quality(1) >= 40


def test_software_crf_increases_as_quality_rises():
    values = [quality.crf_for_quality(q) for q in QUALITIES]
    assert values == sorted(values, reverse=True)
