from __future__ import annotations

import sys

from llm_wiki_forge import cli


def assert_parse_fails(args: list[str]) -> None:
    try:
        cli.build_parser().parse_args(args)
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected parse failure")


def test_ensure_python_uses_current_python_without_creating_venv(tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_WIKI_PYTHON", raising=False)

    python_path = cli.ensure_python(tmp_path)

    assert python_path == cli.Path(sys.executable)
    assert not (tmp_path / ".venv").exists()


def test_mutating_commands_require_user_provided_roots():
    assert_parse_fails(["build", "--repo", "D:/src/app"])
    assert_parse_fails(["update", "--wiki-root", "D:/wiki", "--repo-key", "App"])
    assert_parse_fails(["sync", "--wiki-root", "D:/wiki", "--repo-key", "App"])
    assert_parse_fails(["repo", "add", "--repo", "D:/src/app", "--wiki-root", "D:/wiki"])
    assert_parse_fails(["integrations", "install-hermes"])

    args = cli.build_parser().parse_args(
        [
            "repo",
            "add",
            "--repo",
            "D:/src/app",
            "--wiki-root",
            "D:/wiki",
            "--source-root",
            "D:/src",
        ]
    )

    assert args.source_root == "D:/src"


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
