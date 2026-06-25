from llm_wiki_forge.resources.scripts.query_runtime.models import QueryRun


def test_query_run_omits_empty_hybrid_ranking(tmp_path):
    run = QueryRun(question="test", wiki_root=tmp_path)

    assert "hybrid_ranking" not in run.to_dict()


def test_query_run_serializes_compact_hybrid_ranking(tmp_path):
    run = QueryRun(question="test", wiki_root=tmp_path)
    run.hybrid_ranking = {
        "enabled": True,
        "mode": "shadow",
        "k": 60,
        "candidate_unit": "module_id",
        "applied_to_decision": False,
        "signals": [
            {
                "source": "router",
                "candidate_count": 2,
                "ranked_module_ids": ["module.a", "module.b", "module.c", "module.d", "module.e", "module.f"],
                "raw_scores": {"module.a": 1.0},
            }
        ],
        "source_search_probe": {
            "query": "DispatchRule",
            "patterns": ["DispatchRule"],
            "total_count": 3,
            "truncated": False,
            "matches": [{"path": "/tmp/raw-match.cs"}],
            "shadow_only": True,
            "probe_strategy": "question_terms",
        },
        "candidates": [
            {
                "rank": index,
                "module_id": f"module.{index}",
                "name": f"Module {index}",
                "solution_group": "Test",
                "rrf_score": 1 / index,
                "sources": ["router"],
                "ranks": {"router": index},
                "raw_scores": {"router": 1.0},
            }
            for index in range(1, 7)
        ],
        "soft_influence": {"enabled": True, "applied": False, "reason": "no keyword probe matches"},
    }

    hybrid = run.to_dict()["hybrid_ranking"]

    assert hybrid["enabled"] is True
    assert hybrid["mode"] == "shadow"
    assert hybrid["k"] == 60
    assert len(hybrid["top_candidates"]) == 5
    assert hybrid["top_candidates"][0]["module_id"] == "module.1"
    assert hybrid["top_candidates"][0]["rrf_score"] == 1.0
    assert "raw_scores" not in hybrid["top_candidates"][0]
    assert "candidates" not in hybrid
    assert hybrid["signals"][0]["ranked_module_ids"] == ["module.a", "module.b", "module.c", "module.d", "module.e"]
    assert "raw_scores" not in hybrid["signals"][0]
    assert "matches" not in hybrid["source_search_probe"]
