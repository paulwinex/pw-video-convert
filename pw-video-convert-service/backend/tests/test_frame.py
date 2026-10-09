import pytest

import app.core.config  # noqa: F401  # installs pw-video-convert on sys.path
from pw_video_convert import frame


@pytest.mark.parametrize("text,expected", [
    ("1920x1080", (1920, 1080)),
    ("640x480", (640, 480)),
    (" 1920x1080 ", (1920, 1080)),
])
def test_parse_resolution_valid(text, expected):
    assert frame.parse_resolution(text) == expected


@pytest.mark.parametrize("text", [
    "", "1920", "1920X1080", "x1080", "1920x", "1920x1080p", "0x1080", "1920x0", "-1x100",
])
def test_parse_resolution_invalid(text):
    with pytest.raises(ValueError):
        frame.parse_resolution(text)


@pytest.mark.parametrize("src,expected", [
    ((1918, 1080), (1920, 1088)),
    ((1920, 1080), (1920, 1088)),
    ((1280, 720), (1280, 720)),
    ((640, 360), (640, 368)),
    ((854, 480), (896, 480)),
    ((320, 240), (320, 240)),
    ((426, 240), (448, 240)),
    ((100, 563), (128, 576)),
    ((64, 64), (128, 80)),
])
def test_av1_supported_size(src, expected):
    assert frame.av1_supported_size(*src) == expected


@pytest.mark.parametrize("src,box,expected", [
    ((1920, 1080), (1920, 1080), (1920, 1080)),   # exact fit -> no scaling
    ((640, 360), (1920, 1080), (640, 360)),        # never upscale
    ((3840, 2160), (1920, 1080), (1920, 1080)),    # 16:9 downscale
    ((1920, 1200), (1920, 1080), (1728, 1080)),    # height-limited
    ((1000, 1000), (500, 400), (400, 400)),        # width-limited
    ((3834, 2160), (1920, 1080), (1916, 1080)),    # odd result floored to even
    ((1917, 1080), (1920, 1080), (1917, 1080)),    # fits as-is, odd kept
])
def test_fit_within(src, box, expected):
    assert frame.fit_within(*src, *box) == expected


def test_plan_without_resolution_is_untouched_when_supported():
    plan = frame.plan_video(320, 240)
    assert plan["source"] == (320, 240)
    assert plan["box"] == (320, 240)
    assert plan["scaled"] == (320, 240)
    assert plan["final"] == (320, 240)
    assert plan["filters"] == []


def test_plan_without_resolution_pads_to_supported():
    plan = frame.plan_video(1918, 1080)
    assert plan["scaled"] == (1918, 1080)
    assert plan["final"] == (1920, 1088)
    assert plan["filters"] == ["pad=1920:1088:(ow-iw)/2:(oh-ih)/2:color=black"]


def test_plan_with_resolution_fits_then_aligns():
    plan = frame.plan_video(320, 240, (128, 128))
    assert plan["scaled"] == (128, 96)
    assert plan["final"] == (128, 128)
    assert plan["filters"] == [
        "scale=128:96",
        "pad=128:128:(ow-iw)/2:(oh-ih)/2:color=black",
    ]


def test_plan_smaller_source_is_centered_in_larger_box():
    plan = frame.plan_video(640, 360, (1920, 1080))
    assert plan["scaled"] == (640, 360)          # no upscaling
    assert plan["final"] == (1920, 1088)          # aligned target box
    assert plan["filters"] == ["pad=1920:1088:(ow-iw)/2:(oh-ih)/2:color=black"]


def test_plan_accepts_list_resolution():
    plan = frame.plan_video(320, 240, [128, 128])
    assert plan["box"] == (128, 128)
    assert plan["scaled"] == (128, 96)
    assert plan["final"] == (128, 128)


@pytest.mark.parametrize("value,expected", [
    (None, None),
    ("1920x1080", (1920, 1080)),
    ([1920, 1080], (1920, 1080)),
    ((1920, 1080), (1920, 1080)),
])
def test_coerce_resolution_valid(value, expected):
    assert frame.coerce_resolution(value) == expected


@pytest.mark.parametrize("value", [
    "", "1920", "0x1080", "1920x1080p", [1920], [1920, 1080, 720],
    [0, 1080], [1920, -1], ["a", "b"],
])
def test_coerce_resolution_invalid(value):
    with pytest.raises(ValueError):
        frame.coerce_resolution(value)


def test_plan_final_always_covers_scaled():
    for source in [(1917, 1080), (640, 480), (426, 240), (100, 100), (3840, 2160)]:
        for res in [None, (1920, 1080), (1280, 720), (100, 100)]:
            plan = frame.plan_video(*source, res)
            assert plan["final"][0] >= plan["scaled"][0]
            assert plan["final"][1] >= plan["scaled"][1]
