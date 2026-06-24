import json
from unittest.mock import patch

from tools import llm_wiki_query


def test_llm_wiki_query_delegates_to_forge_query_adapter():
    args = {"question": "固定車資怎麼算", "detail": "compact"}
    payload = {"decision": "answer_from_graph", "next_action": "answer"}

    with patch(
        "tools.llm_wiki_query._forge_llm_wiki_query_tool",
        return_value=json.dumps(payload, ensure_ascii=False),
    ) as forge_query:
        result = json.loads(llm_wiki_query.llm_wiki_query_tool(args, trace_id="t1"))

    forge_query.assert_called_once_with(args, trace_id="t1")
    assert result == payload


def test_llm_wiki_source_search_delegates_to_forge_query_adapter():
    args = {"pattern": "JobTraState", "limit": 20}
    payload = {"next_action": "read_or_answer", "matches": [{"path": "a.cs"}]}

    with patch(
        "tools.llm_wiki_query._forge_llm_wiki_source_search_tool",
        return_value=json.dumps(payload, ensure_ascii=False),
    ) as forge_search:
        result = json.loads(llm_wiki_query.llm_wiki_source_search_tool(args))

    forge_search.assert_called_once_with(args)
    assert result == payload


def test_llm_wiki_runtime_availability_comes_from_forge_adapter():
    with patch("tools.llm_wiki_query._forge_runtime_available", return_value=True):
        assert llm_wiki_query._runtime_available() is True

    with patch("tools.llm_wiki_query._forge_runtime_available", return_value=False):
        assert llm_wiki_query._runtime_available() is False


def test_llm_wiki_schemas_are_forge_owned():
    assert llm_wiki_query.LLM_WIKI_QUERY_SCHEMA["name"] == "llm_wiki_query"
    assert llm_wiki_query.LLM_WIKI_SOURCE_SEARCH_SCHEMA["name"] == "llm_wiki_source_search"
