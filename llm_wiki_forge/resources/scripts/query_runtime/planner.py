from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .router import tokenize


def _symbol_name(symbol: str) -> str:
    symbol = symbol.strip()
    if symbol.startswith("."):
        symbol = symbol[1:]
    return symbol.replace("()", "")


def method_name_from_signature(signature: str) -> str | None:
    signature = re.sub(r"^\[[^\]]+\]\s*", "", signature.strip())
    match = re.search(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", signature)
    if not match:
        return None
    # Return the last method-looking identifier before the parameter list.
    candidates = re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", signature)
    return candidates[-1] if candidates else None


def score_method_candidate(question_tokens: set[str], method_name: str, signature: str) -> int:
    haystack = f"{method_name} {signature}".lower()
    score = sum(1 for token in question_tokens if token and token in haystack)
    # Domain-biased fallback: job/dispatch/fare questions should prefer job and fare methods.
    if {"job", "dispatch", "搜車", "派車"} & question_tokens and "job" in haystack:
        score += 2
    if {"fare", "price", "小費", "付款"} & question_tokens and any(term in haystack for term in ("fare", "price", "pay", "bill", "tran")):
        score += 2
    return score


def intent_terms(question_tokens: set[str]) -> set[str]:
    terms: set[str] = set(question_tokens)
    if {"付款", "payment", "pay", "bill", "fare", "price", "車資", "小費"} & question_tokens:
        terms.update({"payment", "pay", "bill", "fare", "price", "meter", "meterprice", "estimatedfare"})
    if {"固定車資", "taxiplusv2", "isfixedprice", "fixedprice", "make", "quotation"} & question_tokens:
        terms.update(
            {
                "taxiplusv2",
                "quotation",
                "quotation_make",
                "makequotation",
                "createquotation",
                "writequotation2db",
                "isfixedprice",
                "fixedprice",
                "fixedpricecards",
                "cardquotation",
                "taxiplusquotation",
                "taxifarecalc",
            }
        )
    if {"路線圖", "畫圖", "direction", "directions", "routes", "polyline", "google"} & question_tokens:
        terms.update(
            {
                "direction",
                "directions",
                "directionjson",
                "routes",
                "computeroutes",
                "computeroutesdirectionsadapter",
                "polyline",
                "tripbase",
                "google",
            }
        )
    if {"rank", "排序", "快取", "cache"} & question_tokens:
        terms.update({"rank", "ranklookup", "queue", "cache"})
    if {"tdc", "dispatch", "派車", "batch", "批次"} & question_tokens:
        terms.update({"tdc", "dispatch", "dispatchbatch", "batch", "svcworker"})
    if {"ive", "車機", "socket"} & question_tokens:
        terms.update({"ive", "vehicle", "socket"})
    return terms


def explain_plan_candidate(question: str, path: str, focus_symbols: list[str], module_id: str = "") -> dict[str, Any]:
    tokens = set(tokenize(question))
    desired = intent_terms(tokens)
    scoped_path = " ".join(Path(str(path)).parts[-6:])
    scoped_haystack = scoped_path.replace("\\", " ").replace("/", " ").lower()
    haystack = f"{scoped_path} {' '.join(focus_symbols)} {module_id}".replace("\\", " ").replace("/", " ").lower()
    common_tokens = {"api", "webapi", "tgds", "taxiplus", "controller", "tcs", "mics", "baseclass"}
    matched_intent_terms = sorted(term for term in desired if term and term not in common_tokens and term in haystack)
    path_matched_intent_terms = sorted(term for term in matched_intent_terms if term in scoped_haystack)
    matched_query_tokens = sorted(
        token for token in tokens if token and token not in common_tokens and token in haystack
    )
    score = (len(matched_intent_terms) * 2) + (len(path_matched_intent_terms) * 3) + len(matched_query_tokens)
    if {"payment", "付款", "pay", "bill"} & tokens and "paymentcontroller" in scoped_haystack:
        score += 18
    if {"固定車資", "taxiplusv2", "isfixedprice", "fixedprice"} & tokens:
        if "taxiplusv2service" in scoped_haystack:
            score += 18
        if "cardquotation" in scoped_haystack:
            score += 14
        if "quotation_make" in scoped_haystack:
            score += 10
        if "taxifarecalc" in scoped_haystack:
            score += 8
        if "estimatedfare" in scoped_haystack or "meterprice" in scoped_haystack:
            score -= 8
    if {"路線圖", "畫圖", "routes", "direction", "directions", "google"} & tokens:
        if "computeroutesdirectionsadapter" in scoped_haystack:
            score += 18
        if "taxiplusv2service" in scoped_haystack:
            score += 12
    if "tdc" in tokens and ("coreservers tdc" in scoped_haystack or "tgds.coreservers.tdc" in module_id.lower()):
        score += 8
        if "svcworker" in scoped_haystack:
            score += 6
        if "dispatchbatch" in scoped_haystack:
            score += 6
    return {
        "score": score,
        "scoped_path": scoped_path,
        "matched_intent_terms": matched_intent_terms,
        "path_matched_intent_terms": path_matched_intent_terms,
        "matched_query_tokens": matched_query_tokens,
        "ignored_common_tokens": sorted(token for token in tokens if token in common_tokens),
    }


def score_plan_candidate(question: str, path: str, focus_symbols: list[str], module_id: str = "") -> int:
    return int(explain_plan_candidate(question, path, focus_symbols, module_id)["score"])


def community_focus_symbols_for_path(path: str, community: dict[str, Any], question: str, limit: int = 6) -> list[str]:
    stem = Path(str(path)).stem
    stem_lower = stem.lower()
    tokens = set(tokenize(question))
    symbols: list[str] = [stem]

    for raw_symbol in community.get("core_symbols") or []:
        symbol = _symbol_name(str(raw_symbol))
        if not symbol or symbol.endswith(".cs"):
            continue
        symbol_lower = symbol.lower()
        if stem_lower in symbol_lower or symbol_lower in stem_lower:
            symbols.append(symbol)

    if stem_lower == "meterprice":
        symbols.append("CalcMeterPrice")
    if "payment" in stem_lower:
        symbols.append("PaymentController")
    path_lower = str(path).lower()
    if {"fare", "price", "車資", "小費"} & tokens and any(
        term in path_lower for term in ("fare", "price", "meter", "estimatedfare")
    ):
        symbols.extend(["CalcMeterPrice", "EstimatedFareController", "Taxi"])
    if {"固定車資", "taxiplusv2", "isfixedprice", "fixedprice", "make", "quotation"} & tokens:
        if "taxiplusv2service" in path_lower:
            symbols.extend(["CalculateAllCardQuotations", "CalculateSingleCardQuotationInternal", "CalculateMeterFare"])
        if "quotation_make" in path_lower:
            symbols.extend(["Make", "MakeQuotation", "MakeQuotationOnJob", "CreateQuotation", "WriteQuotation2DB"])
        if "taxifarecalc" in path_lower:
            symbols.extend(["TaxiPlusQuotation"])
        if "cardquotation" in path_lower:
            symbols.extend(["CardQuotation"])
        if "cardtypeconfig" in path_lower:
            symbols.extend(["CardTypeConfigItem", "CardTypeConfigLoader", "GetFixedPriceCards"])
    if {"路線圖", "畫圖", "direction", "directions", "routes", "polyline", "google"} & tokens:
        if "taxiplusv2service" in path_lower:
            symbols.extend(["TryGetGoogleRoutesDirection", "CalculateAllCardQuotations", "CalculateSingleCardQuotationInternal"])
        if "computeroutesdirectionsadapter" in path_lower:
            symbols.extend(["Adapt", "MapStep", "BuildBounds", "SerializeLegacyDirectionsJson"])

    deduped: list[str] = []
    for symbol in symbols:
        if symbol not in deduped:
            deduped.append(symbol)
        if len(deduped) >= limit:
            break
    return deduped


def method_focus_symbols(hint: dict[str, Any], question: str, limit: int = 5) -> list[str]:
    contract = hint.get("technical_contract") or {}
    signatures = [
        *[str(item) for item in contract.get("route_surface") or []],
        *[str(item) for item in contract.get("public_methods") or []],
    ]
    question_tokens = set(tokenize(question))
    scored: list[tuple[int, str]] = []
    for signature in signatures:
        name = method_name_from_signature(signature)
        if not name:
            continue
        scored.append((score_method_candidate(question_tokens, name, signature), name))
    scored.sort(key=lambda item: item[0], reverse=True)
    names: list[str] = []
    for score, name in scored:
        if score <= 0 and names:
            continue
        if name not in names:
            names.append(name)
        if len(names) >= limit:
            break
    return names


def plan_extraction(
    community_hits: list[dict[str, Any]],
    symbol_hints: list[dict[str, Any]],
    question: str = "",
    max_files: int = 8,
) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    seen: set[str] = set()

    for hint in symbol_hints:
        for path in hint.get("source_paths") or []:
            if not path or path in seen:
                continue
            seen.add(path)
            method_symbols = method_focus_symbols(hint, question)
            focus_symbols = method_symbols or [hint.get("name") or hint.get("id")]
            module_id = str(hint.get("module_id") or "")
            intent_trace = explain_plan_candidate(question, path, focus_symbols, module_id)
            plan.append(
                {
                    "repo_id": hint.get("solution_group") or hint.get("project") or "",
                    "module_id": module_id,
                    "file_path": path,
                    "focus_symbols": focus_symbols,
                    "reason": "symbol hint matched query; method candidates preferred" if method_symbols else "symbol hint matched query",
                    "priority": 1,
                    "intent_score": intent_trace["score"],
                    "intent_trace": intent_trace,
                    "source": "symbol_hint",
                    "method_level": bool(method_symbols),
                }
            )

    for community in community_hits:
        for path in community.get("source_files") or []:
            if not path or path in seen:
                continue
            if Path(str(path)).suffix.lower() not in {".cs", ".kt", ".kts", ".java", ".swift", ".m", ".mm", ".h"}:
                continue
            seen.add(str(path))
            module_id = str(community.get("module_id") or "")
            symbols = community_focus_symbols_for_path(str(path), community, question)
            intent_trace = explain_plan_candidate(question, str(path), symbols, module_id)
            plan.append(
                {
                    "repo_id": module_id.split(".")[0],
                    "module_id": module_id,
                    "file_path": path,
                    "focus_symbols": symbols,
                    "reason": f"community hit {community.get('id')} matched query",
                    "priority": 2,
                    "intent_score": intent_trace["score"],
                    "intent_trace": intent_trace,
                    "source": "community_hit",
                    "community_id": community.get("id"),
                }
            )

    plan.sort(key=lambda item: (int(item.get("intent_score") or 0), -int(item.get("priority") or 9)), reverse=True)
    return plan[:max_files]
