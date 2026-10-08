from pathlib import Path

import app.core.config  # noqa: F401  # installs pw-video-convert on sys.path
from pw_video_convert import cli


def test_encode_once_reports_progress(tiny_clip: Path, tmp_path: Path):
    out = tmp_path / "out.mkv"
    seen: list[float] = []

    code = cli.encode_once(
        tiny_clip, out, q=10, use_hw=False, container="mkv",
        progress_fn=lambda fraction, seconds_left: seen.append(fraction),
    )

    assert code == 0
    assert out.is_file() and out.stat().st_size > 0
    assert seen, "progress_fn must be called at least once"
    assert all(0.0 <= f <= 1.0 for f in seen)


def test_encode_once_cancel_returns_130_and_removes_output(
    tiny_clip: Path, tmp_path: Path
):
    out = tmp_path / "cancelled.mkv"

    code = cli.encode_once(
        tiny_clip, out, q=10, use_hw=False, container="mkv",
        progress_fn=lambda fraction, seconds_left: None,
        cancel_fn=lambda: True,
    )

    assert code == 130
    assert not out.exists()


def test_encode_once_default_args_still_work(tiny_clip: Path, tmp_path: Path):
    """Backward compat: no progress_fn/cancel_fn -> terminal printer path."""
    out = tmp_path / "compat.mkv"

    code = cli.encode_once(tiny_clip, out, q=10, use_hw=False, container="mkv")

    assert code == 0
    assert out.is_file()


def test_encode_once_resizes_to_requested_frame(tiny_clip: Path, tmp_path: Path):
    from pw_video_convert import probe

    out = tmp_path / "resized.mkv"
    code = cli.encode_once(
        tiny_clip, out, q=10, use_hw=False, container="mkv", resolution="128x128",
    )

    assert code == 0
    video = probe.get_media_info(str(out))["video"]
    assert (video["width"], video["height"]) == (128, 128)


def test_encode_once_keeps_supported_source_size(tiny_clip: Path, tmp_path: Path):
    from pw_video_convert import probe

    out = tmp_path / "same.mkv"
    code = cli.encode_once(tiny_clip, out, q=10, use_hw=False, container="mkv")

    assert code == 0
    video = probe.get_media_info(str(out))["video"]
    assert (video["width"], video["height"]) == (320, 240)
