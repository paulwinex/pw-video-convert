from pathlib import Path


def test_default_output_dir_is_video_output():
    from app.core.config import DEFAULT_OUTPUT_DIR

    assert DEFAULT_OUTPUT_DIR == Path("output")
    assert DEFAULT_OUTPUT_DIR.is_dir()


def test_pw_video_convert_is_importable():
    import app.core.config  # noqa: F401  # installs pw-video-convert on sys.path

    from pw_video_convert import cli

    assert hasattr(cli, "encode_once")
    assert hasattr(cli, "resolve_output")
