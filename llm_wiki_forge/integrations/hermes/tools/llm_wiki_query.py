#!/usr/bin/env python3
"""Hermes tool registrations for Forge-owned LLM Wiki query behavior."""

from __future__ import annotations

from typing import Any

from llm_wiki_forge.query_adapter import (
    LLM_WIKI_QUERY_SCHEMA,
    LLM_WIKI_SOURCE_SEARCH_SCHEMA,
    _runtime_available as _forge_runtime_available,
    llm_wiki_query_tool as _forge_llm_wiki_query_tool,
    llm_wiki_source_search_tool as _forge_llm_wiki_source_search_tool,
)

from tools.registry import registry


def _runtime_available() -> bool:
    return _forge_runtime_available()


def llm_wiki_query_tool(args: dict[str, Any], **kwargs: Any) -> str:
    return _forge_llm_wiki_query_tool(args, **kwargs)


def llm_wiki_source_search_tool(args: dict[str, Any], **kwargs: Any) -> str:
    return _forge_llm_wiki_source_search_tool(args, **kwargs)


registry.register(
    name="llm_wiki_query",
    toolset="llm-wiki",
    schema=LLM_WIKI_QUERY_SCHEMA,
    handler=llm_wiki_query_tool,
    check_fn=_runtime_available,
    description=LLM_WIKI_QUERY_SCHEMA["description"],
    emoji="🔎",
)

registry.register(
    name="llm_wiki_source_search",
    toolset="llm-wiki",
    schema=LLM_WIKI_SOURCE_SEARCH_SCHEMA,
    handler=llm_wiki_source_search_tool,
    check_fn=_runtime_available,
    description=LLM_WIKI_SOURCE_SEARCH_SCHEMA["description"],
    emoji="🔎",
)
