from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType


def load_generator(monkeypatch):
    scripts = ModuleType("scripts")
    update_wiki = ModuleType("scripts.update_wiki")
    update_wiki.build_inventory = lambda wiki_root: {"items": []}
    update_wiki.is_under_any = lambda path, roots: any(
        Path(path).resolve().is_relative_to(Path(root).resolve()) for root in roots
    )
    monkeypatch.setitem(sys.modules, "scripts", scripts)
    monkeypatch.setitem(sys.modules, "scripts.update_wiki", update_wiki)
    sys.modules.pop("llm_wiki_forge.resources.scripts.generate_module_wiki", None)
    return importlib.import_module("llm_wiki_forge.resources.scripts.generate_module_wiki")


def test_retrofit_const_chain_resolves_imported_base(monkeypatch):
    generator = load_generator(monkeypatch)
    base_constants = generator.resolve_kotlin_string_constants(
        """
        class AppApiPath {
            companion object {
                const val APP_API = "AppApi"
            }
        }
        """
    )
    text = """
        private const val CREDIT = "/Credit"
        const val CO_BRANDER_CARD_STATUS = "/CoBranderCardStatus"
        const val APP_API_CREDIT_CO_BRANDER_CARD_STATUS = APP_API + CREDIT + CO_BRANDER_CARD_STATUS

        interface CreditApi {
            @POST(APP_API_CREDIT_CO_BRANDER_CARD_STATUS)
            suspend fun status()
        }
    """

    assert generator.extract_retrofit_surface(text, base_constants) == [
        "POST AppApi/Credit/CoBranderCardStatus"
    ]


def test_source_files_skip_resolved_exclude_paths(tmp_path, monkeypatch):
    generator = load_generator(monkeypatch)
    app_file = tmp_path / "app" / "src" / "main" / "java" / "App.kt"
    shared_file = tmp_path / "Android55688AppAPI" / "api" / "src" / "main" / "java" / "Api.kt"
    app_file.parent.mkdir(parents=True)
    shared_file.parent.mkdir(parents=True)
    app_file.write_text("class App", encoding="utf-8")
    shared_file.write_text("class Api", encoding="utf-8")

    files = generator.source_files_for_item(
        {
            "resolvedPath": str(tmp_path),
            "resolvedExcludePaths": [str(tmp_path / "Android55688AppAPI")],
        },
        "android",
    )

    assert files == [app_file.resolve()]
