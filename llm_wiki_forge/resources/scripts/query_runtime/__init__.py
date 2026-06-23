"""LLM Wiki query runtime.

This package turns a user question into a scoped evidence pack. It is deliberately
small and deterministic at first; LangGraph orchestration can wrap these tools
after the individual nodes are easy to test.
"""

