from __future__ import annotations

import importlib
import sys
from types import ModuleType


def load_generator(monkeypatch):
    scripts = ModuleType("scripts")
    update_wiki = ModuleType("scripts.update_wiki")
    update_wiki.build_inventory = lambda wiki_root: {"items": []}
    update_wiki.is_under_any = lambda path, roots: False
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
