from __future__ import annotations

import argparse
from pathlib import Path

from .code_provider import DynamicCodeProvider
from .io import write_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract scoped source code evidence")
    parser.add_argument("--wiki-root", default=".", help="Path to llm-wiki root")
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--file", action="append", required=True, dest="files")
    parser.add_argument("--symbol", action="append", dest="symbols")
    parser.add_argument("--out", help="Optional JSON output path")
    parser.add_argument("--max-chars", type=int, default=20000)
    parser.add_argument("--question", default="", help="Optional query text used to rank large-method chunks")
    args = parser.parse_args(argv)

    provider = DynamicCodeProvider(Path(args.wiki_root))
    result = provider.get_context(
        repo_id=args.repo_id,
        file_paths=args.files,
        focus_symbols=args.symbols,
        max_chars=args.max_chars,
        query=args.question,
    )

    if args.out:
        out = Path(args.out)
        if not out.is_absolute():
            out = Path(args.wiki_root) / out
        write_json(out, result)
        print(f"output: {out.resolve()}")

    print(f"evidence_count: {len(result['code_evidence'])}")
    print(f"error_count: {len(result['errors'])}")
    for item in result["code_evidence"]:
        print(
            f"- {item['symbol'] or item['kind']} "
            f"{item['file_path']}:{item['start_line']}-{item['end_line']} "
            f"method={item['extraction_method']} confidence={item['confidence']}"
        )
    for error in result["errors"]:
        print(f"- ERROR {error['file_path']}: {error['error']}")

    return 0 if result["code_evidence"] and not result["errors"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
