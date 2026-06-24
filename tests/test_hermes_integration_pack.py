import json
from importlib import resources


FORBIDDEN_TOKENS = (
    "power" + "shell",
    "p" + "wsh",
    "copy" + "-item",
    "set" + "-content",
    "get" + "-childitem",
    "wsl" + ".localhost",
)


def integration_root():
    return resources.files("llm_wiki_forge.integrations").joinpath("hermes")


def test_hermes_integration_manifest_targets_expected_files():
    root = integration_root()
    manifest = json.loads(root.joinpath("manifest.json").read_text(encoding="utf-8"))

    entries = []
    for section in ("tools", "skills", "hooks", "tests"):
        entries.extend(manifest["install"][section])

    targets = {entry["target"] for entry in entries}
    assert "hermes-agent/tools/llm_wiki_query.py" in targets
    assert "hermes-agent/tools/llm_wiki_forge.py" in targets
    assert "skills/llm-wiki-query/SKILL.md" in targets
    assert "agent-hooks/slack_readonly_guard.py" in targets
    assert "hermes-agent/tests/tools/test_llm_wiki_query_tool.py" in targets

    for entry in entries:
        assert root.joinpath(entry["source"]).is_file()


def test_hermes_integration_pack_avoids_windows_shell_syntax():
    root = integration_root()
    offenders = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        for token in FORBIDDEN_TOKENS:
            if token in text:
                offenders.append(f"{path.name}:{token}")
    assert offenders == []
