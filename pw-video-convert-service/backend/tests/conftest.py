import queue as queue_mod
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, List

import pytest


@pytest.fixture(scope="session")
def tiny_clip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """5-second 320x240 test clip for fast encode tests."""
    path = tmp_path_factory.mktemp("clip") / "tiny.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", "testsrc=duration=5:size=320x240:rate=25",
            "-pix_fmt", "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


@pytest.fixture
def drain() -> Callable[..., List[dict[str, Any]]]:
    """Drain an mp.Queue until a terminal status arrives or timeout."""

    def _drain(q, timeout: float = 120.0) -> List[dict[str, Any]]:
        deadline = time.time() + timeout
        msgs: List[dict[str, Any]] = []
        while time.time() < deadline:
            try:
                msgs.append(q.get(timeout=0.2))
            except queue_mod.Empty:
                continue
            if msgs[-1].get("status") in ("completed", "failed"):
                break
        return msgs

    return _drain
