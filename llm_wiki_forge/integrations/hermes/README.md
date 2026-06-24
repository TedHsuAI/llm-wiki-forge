# Hermes Integration Pack

This directory is the Forge-owned source of truth for the Hermes LLM Wiki integration.

Hermes should keep runtime copies of these files so its registry, skills, and Slack guard can load them locally. Forge owns the canonical versions so query behavior, tool schemas, source-search rules, and skill guidance stay versioned with the LLM Wiki runtime.

## Boundary

Hermes keeps the thin runtime surface:

- register `llm_wiki_query`
- register `llm_wiki_source_search`
- expose Forge maintenance tools such as `llm_wiki_forge_sync`
- guide Slack answers with the `llm-wiki-query` skill
- enforce read-only terminal fallbacks through the Slack guard

Forge owns the correctness behavior:

- repo update and wiki refresh
- code query orchestration
- deterministic source search
- evidence reuse and freshness validation
- compact/full payload normalization
- integration pack versioning

## Files

```text
llm_wiki_forge/integrations/hermes/
  tools/llm_wiki_query.py
  tools/llm_wiki_forge.py
  skills/llm-wiki-query/SKILL.md
  hooks/slack_readonly_guard.py
  tests/test_llm_wiki_query_tool.py
  manifest.json
```

## Install

From a Forge checkout or installed package:

```bash
python -m llm_wiki_forge integrations install-hermes --hermes-root /home/tedhsu/.hermes --dry-run
python -m llm_wiki_forge integrations install-hermes --hermes-root /home/tedhsu/.hermes
```

Use `--no-hook` when only tool and skill copies should be installed.

## Safety

Do not add platform-specific shell snippets to this pack. Command examples should use `bash`, direct Python module execution, or plain text paths.
