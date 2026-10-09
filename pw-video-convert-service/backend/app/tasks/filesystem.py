from __future__ import annotations

import os
from pathlib import Path


from fastapi import HTTPException


def safe_resolve(root: Path, rel: str) -> Path:
    """
    Превращает относительный путь в абсолютный, гарантируя,
    что итог лежит внутри root. Иначе 403.
    """
    rel = (rel or "").strip().lstrip("/")
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=403, detail="Path escapes user root")
    return candidate


def get_user_root() -> Path:
    """
    Возвращает корень файловой песочницы пользователя.

    FastAPI-эндпоинт для файлового эксплорера.

    Роут: GET /fs?path=<relative>&mime=<pattern>&mime=<pattern>

    Вход:
      path — путь относительно корня пользователя (пустая строка = корень).
             Разделитель в URL — всегда "/", на диске конвертируется сам.
      mime — список MIME-паттернов (повторяющийся query-параметр,
             допускаются wildcard'ы, напр. "video/*"). Если список задан,
             файлы без подходящего типа отбрасываются; каталоги отдаются
             всегда (нужны для навигации).

    Выход (JSON):
      {
        "path": "docs/sub",
        "entries": [
          {
            "name": "report.pdf",
            "path": "docs/sub/report.pdf",
            "is_dir": false,
            "size": 123456,
            "created": "2025-01-01T12:00:00",
            "modified": "2025-01-02T13:30:00"
          },
          ...
        ]
      }

    Гарантии:
      * отдаются только каталоги/файлы, лежащие внутри user_root;
      * симлинки НЕ разыменовываются при обходе (follow_symlinks=False),
        чтобы нельзя было выйти за пределы корня;
      * каталоги идут первыми, затем файлы; внутри групп — по имени.

    """
    root = Path(os.environ.get("USER_FS_ROOT", "~")).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root
