from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def slugify(text: str, max_len: int = 48) -> str:
    slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", text).strip("-")
    return (slug[:max_len] or "query").strip("-")


def iter_json_files(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return sorted(path.glob("*.json"))


def load_modules(wiki_root: Path) -> list[dict[str, Any]]:
    return [load_json(path) for path in iter_json_files(wiki_root / "Wiki" / "_data" / "modules")]


def load_symbols(wiki_root: Path) -> list[dict[str, Any]]:
    return [load_json(path) for path in iter_json_files(wiki_root / "Wiki" / "_data" / "symbols")]


def load_communities(wiki_root: Path) -> list[dict[str, Any]]:
    return [load_json(path) for path in iter_json_files(wiki_root / "Wiki" / "_data" / "communities")]
