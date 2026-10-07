#!/usr/bin/env python3
import sys
import os
import json
import urllib.error
import urllib.request

from PyQt5.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QListWidget, QSlider, QLineEdit, QPushButton, QFileDialog,
    QMessageBox
)
from PyQt5.QtCore import Qt

CONFIG_PATH = os.path.expanduser("~/.config/pw-convert.json")
DEFAULT_BASE_URL = os.getenv("PW_CONV_HOST_URL") or "http://192.168.0.155:8000"

DEFAULTS = {
    "quality": 5,
    "output": "output",
}


def validate_output(text: str):
    text = text.strip()
    if not text:
        return None, "Output is empty"
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
            out = data.get("output")
            if isinstance(out, str):
                normalized, _ = validate_output(out)
                if normalized is not None:
                    cfg["output"] = normalized
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


class ConvertDialog(QDialog):
    def __init__(self, files, parent=None):
        super().__init__(parent)
        self.files = files
        self.setWindowTitle(f"PW Convert [{DEFAULT_BASE_URL}]")
        self.resize(600, 300)

        cfg = load_config()

        layout = QVBoxLayout(self)

        # --- Files list ---
        layout.addWidget(QLabel("Files:"))
        self.file_list = QListWidget()
        self.file_list.addItems(files if files else ["(no files provided)"])
        self.file_list.setSelectionMode(QListWidget.NoSelection)
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
        self.output_edit = QLineEdit(cfg["output"])
        self.output_edit.setPlaceholderText("relative dir, e.g. output")
        o_layout.addWidget(self.output_edit)
        layout.addLayout(o_layout)

        # --- Submit ---
        self.submit_btn = QPushButton("Submit")
        self.submit_btn.clicked.connect(self.on_submit)
        layout.addWidget(self.submit_btn)


    def on_submit(self):
        quality = self.quality_slider.value()

        output, err = validate_output(self.output_edit.text())
        if err is not None:
            QMessageBox.warning(self, "Invalid output", err)
            return
        save_config({"quality": quality, "output": output})

        base_url = DEFAULT_BASE_URL.rstrip("/")
        errors = []

        for f in self.files:
            payload = {
                "input": os.path.abspath(f),
                "quality": quality,
                "output": output,
                "remap_path": "/mnt/NAS"
            }
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