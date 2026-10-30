#!/usr/bin/env python3
import sys
import os
import json
import subprocess
import urllib.error
import urllib.request

from PyQt5.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QListWidget, QSlider, QLineEdit, QPushButton, QFileDialog, QComboBox,
    QCheckBox, QInputDialog, QMessageBox
)
from PyQt5.QtCore import Qt

CONFIG_PATH = os.path.expanduser("~/.config/pw-convert.json")
DEFAULT_BASE_URL = os.getenv("PW_CONV_HOST_URL") or "http://192.168.0.155:8055"
REMAP_PATH = "/mnt/NAS"

DEFAULTS = {
    "quality": 5,
}


def validate_output(text: str):
    text = text.strip()
    if not text:
        return "", None
    if text.startswith("~"):
        return None, "Output must not contain '~'"
    if os.path.isabs(text):
        return None, "Output must be a relative path"
    if len(text) >= 2 and text[1] == ":":
        return None, "Output must be a relative path"
    if os.path.isfile(text):
        return None, f"Output must be a directory, not a file: {text}"
    return text, None


def load_config():
    cfg = DEFAULTS.copy()
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            if isinstance(data.get("quality"), int):
                cfg["quality"] = max(1, min(10, data["quality"]))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return cfg


def save_config(cfg):
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except OSError as e:
        print(f"Failed to save config: {e}", file=sys.stderr)


def add_task(base_url: str, payload: dict) -> dict:
    url = f"{base_url}/tasks"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(body).get("detail", body)
        except json.JSONDecodeError:
            detail = body
        raise RuntimeError(f"API error {e.code}: {detail}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"cannot reach {base_url}: {e.reason}") from None


def probe_tracks(file_path: str) -> list:
    """Read the audio track list from the local file with ffprobe.

    The submitter machine has direct access to the file, so no service
    round-trip (and no path remapping) is needed for the track listing.
    """
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a",
        "-show_entries",
        "stream=index,codec_name,channels,bit_rate:stream_tags=language,title",
        "-of", "json",
        file_path,
    ]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    except FileNotFoundError:
        raise RuntimeError(
            "ffprobe not found; install ffmpeg on this machine"
        ) from None
    except subprocess.CalledProcessError as e:
        detail = (e.output or b"").decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"ffprobe failed: {detail[:300]}") from None

    tracks = []
    for position, stream in enumerate(json.loads(out).get("streams", [])):
        tags = stream.get("tags") or {}
        try:
            bitrate = int(stream.get("bit_rate", 0) or 0) or None
        except (TypeError, ValueError):
            bitrate = None
        tracks.append({
            "track": position + 1,
            "index": stream.get("index"),
            "codec": stream.get("codec_name", ""),
            "channels": int(stream.get("channels", 1) or 1),
            "language": tags.get("language"),
            "title": tags.get("title"),
            "stream_bitrate": bitrate,
        })
    return tracks


def track_label(track: dict) -> str:
    parts = [f"#{track.get('track')}"]
    if track.get("language"):
        parts.append(track["language"])
    if track.get("title"):
        parts.append(track["title"])
    parts.append(track.get("codec") or "?")
    parts.append(f"{track.get('channels', '?')}ch")
    return " · ".join(parts)


class AudioTracksDialog(QDialog):
    """Checkbox list of a file's audio tracks; all checked by default.

    Also allows attaching external audio files, each with a user-supplied
    label; they are muxed in as extra Opus tracks by the converter.
    """

    def __init__(self, file_name: str, tracks: list, selected: list,
                 added: list = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Audio tracks — {file_name}")
        self._boxes = []
        self._ok = None
        self._added = [dict(item) for item in (added or [])]

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Select audio tracks to keep in {file_name}:"))
        keep = set(selected) if selected else {t.get("track") for t in tracks}
        for track in tracks:
            box = QCheckBox(track_label(track))
            box.setChecked(track.get("track") in keep)
            box.stateChanged.connect(self._update_ok)
            self._boxes.append((track.get("track"), box))
            layout.addWidget(box)

        # --- External audio files ---
        layout.addWidget(QLabel("External audio files (added as Opus tracks):"))
        self.add_list = QListWidget()
        layout.addWidget(self.add_list)
        a_btns = QHBoxLayout()
        add_btn = QPushButton("Add audio file\u2026")
        add_btn.clicked.connect(self.on_add_file)
        remove_btn = QPushButton("Remove selected")
        remove_btn.clicked.connect(self.on_remove_file)
        a_btns.addWidget(add_btn)
        a_btns.addWidget(remove_btn)
        a_btns.addStretch(1)
        layout.addLayout(a_btns)
        self._refresh_add_list()

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self._ok = QPushButton("OK")
        self._ok.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(self._ok)
        layout.addLayout(buttons)
        self._update_ok()

    def _refresh_add_list(self):
        self.add_list.clear()
        for item in self._added:
            self.add_list.addItem(f"[{item['label']}] {os.path.basename(item['path'])}")

    def on_add_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select audio file", os.path.dirname(self._added[-1]["path"])
            if self._added else os.path.expanduser("~")
        )
        if not path:
            return
        name = os.path.basename(path)
        label, ok = QInputDialog.getText(
            self, "Track label", f"How to label the audio track from {name}?:"
        )
        if not ok:
            return
        label = label.strip() or f"External audio {len(self._added) + 1}"
        self._added.append({"path": os.path.abspath(path), "label": label})
        self._refresh_add_list()

    def on_remove_file(self):
        row = self.add_list.currentRow()
        if 0 <= row < len(self._added):
            del self._added[row]
            self._refresh_add_list()

    def added(self) -> list:
        return [dict(item) for item in self._added]

    def _update_ok(self, *args):
        if self._ok is not None:
            self._ok.setEnabled(bool(self.selected()))

    def selected(self) -> list:
        return sorted(n for n, box in self._boxes if box.isChecked())


class ConvertDialog(QDialog):
    def __init__(self, files, parent=None):
        super().__init__(parent)
        self.files = files
        self.abs_files = [os.path.abspath(f) for f in files]
        # per-file audio selection: {abs_path: [1-based track numbers]};
        # missing entry = keep all tracks. audio_add: {abs_path: [{path,label}]}
        self.audio_sel = {}
        self.audio_add = {}
        self.track_cache = {}
        self.setWindowTitle(f"PW Convert [{DEFAULT_BASE_URL}]")
        self.resize(600, 400)

        cfg = load_config()

        layout = QVBoxLayout(self)

        # --- Files list ---
        layout.addWidget(QLabel("Files:"))
        self.file_list = QListWidget()
        self.file_list.addItems(files if files else ["(no files provided)"])
        self.file_list.setSelectionMode(QListWidget.SingleSelection)
        self.file_list.currentRowChanged.connect(lambda _: self._update_audio_summary())
        layout.addWidget(self.file_list)

        # --- Quality ---
        q_layout = QHBoxLayout()
        q_layout.addWidget(QLabel("Quality:"))
        self.quality_slider = QSlider(Qt.Horizontal)
        self.quality_slider.setRange(1, 10)
        self.quality_slider.setValue(int(cfg["quality"]))
        self.quality_slider.setTickPosition(QSlider.TicksBelow)
        self.quality_slider.setTickInterval(1)
        self.quality_value = QLabel(str(cfg["quality"]))
        self.quality_value.setMinimumWidth(20)
        self.quality_slider.valueChanged.connect(
            lambda v: self.quality_value.setText(str(v))
        )
        q_layout.addWidget(self.quality_slider)
        q_layout.addWidget(self.quality_value)
        layout.addLayout(q_layout)

        # --- Output ---
        o_layout = QHBoxLayout()
        o_layout.addWidget(QLabel("Output:"))
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("optional subfolder, leave empty for default")
        o_layout.addWidget(self.output_edit)
        layout.addLayout(o_layout)

        # --- Resolution ---
        r_layout = QHBoxLayout()
        r_layout.addWidget(QLabel("Resolution:"))
        self.resolution_combo = QComboBox()
        for text, data in [
            ("Original", None),
            ("2K (2560x1440)", [2560, 1440]),
            ("Full HD (1920x1080)", [1920, 1080]),
            ("HD (1280x720)", [1280, 720]),
        ]:
            self.resolution_combo.addItem(text, data)
        r_layout.addWidget(self.resolution_combo)
        layout.addLayout(r_layout)

        # --- Audio tracks (per selected file) ---
        a_layout = QHBoxLayout()
        self.audio_btn = QPushButton("Audio tracks\u2026")
        self.audio_btn.clicked.connect(self.on_audio_tracks)
        self.audio_summary = QLabel("")
        a_layout.addWidget(self.audio_btn)
        a_layout.addWidget(self.audio_summary, 1)
        layout.addLayout(a_layout)
        if self.files:
            self.file_list.setCurrentRow(0)
        else:
            self._update_audio_summary()

        # --- Submit ---
        self.paused_cb = QCheckBox("Create paused")
        layout.addWidget(self.paused_cb)
        self.submit_btn = QPushButton("Submit")
        self.submit_btn.clicked.connect(self.on_submit)
        layout.addWidget(self.submit_btn)

    def _current_abs(self):
        row = self.file_list.currentRow()
        if 0 <= row < len(self.abs_files):
            return self.abs_files[row]
        return None

    def _update_audio_summary(self):
        path = self._current_abs()
        if path is None:
            self.audio_summary.setText("")
            return
        total = len(self.track_cache.get(path, []))
        sel = self.audio_sel.get(path)
        if sel is None:
            text = f"all ({total})" if total else "all"
        else:
            joined = ",".join(str(n) for n in sel)
            text = f"{joined} (of {total})" if total else joined
        adds = self.audio_add.get(path, [])
        if adds:
            text += f" +{len(adds)} ext"
        self.audio_summary.setText(text)

    def on_audio_tracks(self):
        path = self._current_abs()
        if not path:
            return
        if path not in self.track_cache:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                tracks = probe_tracks(path)
            except RuntimeError as e:
                QApplication.restoreOverrideCursor()
                QMessageBox.warning(self, "Probe failed", f"{path}:\n{e}")
                return
            else:
                QApplication.restoreOverrideCursor()
            self.track_cache[path] = tracks
        tracks = self.track_cache[path]
        if not tracks:
            QMessageBox.information(
                self, "Audio tracks", "This file has no audio tracks."
            )
            return
        current = self.audio_sel.get(path) or [t["track"] for t in tracks]
        dlg = AudioTracksDialog(
            os.path.basename(path), tracks, current,
            added=self.audio_add.get(path, []), parent=self,
        )
        if dlg.exec_() == QDialog.Accepted:
            sel = dlg.selected()
            if sel and len(sel) < len(tracks):
                self.audio_sel[path] = sel
            else:
                self.audio_sel.pop(path, None)
            self.audio_add[path] = dlg.added()
            self._update_audio_summary()


    def on_submit(self):
        quality = self.quality_slider.value()

        output, err = validate_output(self.output_edit.text())
        if err is not None:
            QMessageBox.warning(self, "Invalid output", err)
            return
        save_config({"quality": quality})

        base_url = DEFAULT_BASE_URL.rstrip("/")
        errors = []

        for f in self.files:
            payload = {
                "input": os.path.abspath(f),
                "quality": quality,
                "output": output,
                "remap_path": REMAP_PATH
            }
            resolution = self.resolution_combo.currentData()
            if resolution is not None:
                payload["resolution"] = resolution
            audio_sel = self.audio_sel.get(os.path.abspath(f))
            if audio_sel:
                payload["audio"] = audio_sel
            audio_add = self.audio_add.get(os.path.abspath(f), [])
            if audio_add:
                payload["audio_add"] = audio_add
            if self.paused_cb.isChecked():
                payload["paused"] = True
            try:
                result = add_task(base_url, payload)
                print(
                    f"created: file={f} "
                    f"uuid={result.get('uuid')} status={result.get('status')}"
                )
            except RuntimeError as e:
                msg = f"{f}: {e}"
                print(msg, file=sys.stderr)
                errors.append(msg)
        if errors:
            QMessageBox.warning(self, "Submit errors", "\n".join(errors))
        else:
            self.accept()


def main():
    app = QApplication(sys.argv)
    files = sys.argv[1:]
    if files:
        dlg = ConvertDialog(files)
        dlg.exec_()
    else:
        QMessageBox.critical(None, 'Error', 'Source files not provided')


if __name__ == "__main__":
    main()