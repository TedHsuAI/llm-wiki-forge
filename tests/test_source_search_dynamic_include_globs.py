import json

from llm_wiki_forge.resources.scripts.query_runtime import source_search


def _write_registry(path, wiki_root, source_root, platforms):
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "roots": [
                    {
                        "id": "test",
                        "wiki_root": str(wiki_root),
                        "source_root": str(source_root),
                        "platforms": platforms,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_source_search_uses_registry_language_globs(tmp_path, monkeypatch):
    wiki_root = tmp_path / "wiki"
    source_root = tmp_path / "src"
    wiki_root.mkdir()
    source_root.mkdir()
    registry = tmp_path / "registry.json"
    _write_registry(registry, wiki_root, source_root, ["typescript"])
    monkeypatch.setattr(source_search, "DEFAULT_WIKI_REGISTRY", registry)

    (source_root / "handler.ts").write_text("const needleValue = 1;\n", encoding="utf-8")

    result = source_search.search_source(wiki_root=wiki_root, patterns=["needleValue"])

    assert result["total_count"] == 1
    assert result["matches"][0]["path"].endswith("handler.ts")
    contract = result["search_contract"]
    assert "*.ts" in contract["include_globs"]
    assert "typescript" in contract["include_profile"]["language_hints"]


def test_source_search_uses_wiki_scope_language_globs(tmp_path, monkeypatch):
    wiki_root = tmp_path / "wiki"
    source_root = tmp_path / "src"
    wiki_root.mkdir()
    source_root.mkdir()
    registry = tmp_path / "registry.json"
    _write_registry(registry, wiki_root, source_root, [])
    monkeypatch.setattr(source_search, "DEFAULT_WIKI_REGISTRY", registry)
    (wiki_root / "wiki.scope.json").write_text(
        json.dumps(
            {
                "repos": [
                    {
                        "logicalName": "PyRepo",
                        "actualRoot": str(source_root),
                        "platform": "python",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (source_root / "worker.py").write_text("needle_value = True\n", encoding="utf-8")

    result = source_search.search_source(wiki_root=wiki_root, patterns=["needle_value"])

    assert result["total_count"] == 1
    assert result["matches"][0]["path"].endswith("worker.py")
    assert "*.py" in result["search_contract"]["include_globs"]


def test_source_search_uses_ios_language_globs(tmp_path, monkeypatch):
    wiki_root = tmp_path / "wiki"
    source_root = tmp_path / "src"
    wiki_root.mkdir()
    source_root.mkdir()
    registry = tmp_path / "registry.json"
    _write_registry(registry, wiki_root, source_root, [])
    monkeypatch.setattr(source_search, "DEFAULT_WIKI_REGISTRY", registry)
    (wiki_root / "wiki.scope.json").write_text(
        json.dumps(
            {
                "repos": [
                    {
                        "logicalName": "IOSRepo",
                        "actualRoot": str(source_root),
                        "platform": "ios",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (source_root / "AppDelegate.swift").write_text("let iosNeedle = true\n", encoding="utf-8")

    result = source_search.search_source(wiki_root=wiki_root, patterns=["iosNeedle"])

    assert result["total_count"] == 1
    assert result["matches"][0]["path"].endswith("AppDelegate.swift")
    assert "*.swift" in result["search_contract"]["include_globs"]
    assert "swift" in result["search_contract"]["include_profile"]["language_hints"]


def test_source_search_keeps_sql_opt_in(tmp_path, monkeypatch):
    wiki_root = tmp_path / "wiki"
    source_root = tmp_path / "src"
    wiki_root.mkdir()
    source_root.mkdir()
    registry = tmp_path / "registry.json"
    _write_registry(registry, wiki_root, source_root, ["typescript"])
    monkeypatch.setattr(source_search, "DEFAULT_WIKI_REGISTRY", registry)
    (source_root / "schema.sql").write_text("CREATE TABLE NeedleTable (id int);\n", encoding="utf-8")

    without_sql = source_search.search_source(wiki_root=wiki_root, patterns=["NeedleTable"])
    with_sql = source_search.search_source(wiki_root=wiki_root, patterns=["NeedleTable"], include_sql=True)

    assert without_sql["total_count"] == 0
    assert "*.sql" not in without_sql["search_contract"]["include_globs"]
    assert with_sql["total_count"] == 1
    assert with_sql["matches"][0]["path"].endswith("schema.sql")
    assert "*.sql" in with_sql["search_contract"]["include_globs"]
