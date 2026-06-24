from __future__ import annotations

import sys

from llm_wiki_forge import cli


def test_ensure_python_uses_current_python_without_creating_venv(tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_WIKI_PYTHON", raising=False)

    python_path = cli.ensure_python(tmp_path)

    assert python_path == cli.Path(sys.executable)
    assert not (tmp_path / ".venv").exists()


def test_ensure_python_fails_bad_env_without_creating_venv(tmp_path, monkeypatch):
    missing = tmp_path / "missing-python"
    monkeypatch.setenv("LLM_WIKI_PYTHON", str(missing))

    try:
        cli.ensure_python(tmp_path)
    except SystemExit:
        pass
    else:
        raise AssertionError("expected bad LLM_WIKI_PYTHON to fail")

    assert not (tmp_path / ".venv").exists()
