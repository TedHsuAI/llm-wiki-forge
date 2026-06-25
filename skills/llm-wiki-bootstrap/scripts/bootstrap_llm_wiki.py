#!/usr/bin/env python3
"""Compatibility wrapper for the Forge-owned bootstrap implementation."""

from __future__ import annotations

from llm_wiki_forge.resources.bootstrap_llm_wiki import main


if __name__ == "__main__":
    raise SystemExit(main())
