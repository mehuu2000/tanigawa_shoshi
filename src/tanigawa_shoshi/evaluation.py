"""単一件評価・全件評価・集計処理。"""

from typing import Any, Dict, Iterable, List, Optional, Sequence

from .rerank import apply_threshold, rerank_candidates, score_candidates, select_top_candidate
from .search import search_reference


DEFAULT_THRESHOLDS = {
    "rc": 0.9375,
    "cc": 0.8730,
    "mc": 0.8623,
}
THRESHOLDED_SCORE_NAMES = ("rc", "cc", "mc")
SUPPORTED_EVALUATION_MODES = {"positive", "negative", "auto"}
POSITIVE_OUTCOME_NAMES = ("detected", "missed", "false_positive")
NEGATIVE_OUTCOME_NAMES = ("true_negative", "false_positive")


# 閾値 dict を正規化し、RC / CC / MC の 3 値を揃えて返す。
def _normalize_thresholds(thresholds: Optional[Dict[str, float]] = None) -> Dict[str, float]:
    if thresholds is None:
        return DEFAULT_THRESHOLDS.copy()

    normalized = DEFAULT_THRESHOLDS.copy()
    for score_name in THRESHOLDED_SCORE_NAMES:
        if score_name in thresholds:
            normalized[score_name] = float(thresholds[score_name])
    return normalized


# スコア付き候補から、評価結果へ保存しやすい最小情報を抜き出す。
def _summarize_candidate(candidate: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if candidate is None:
        return None

    return {
        "doi": candidate.get("doi"),
        "title": candidate.get("title"),
        "bm25_score": candidate.get("bm25_score"),
        "bm25_rank": candidate.get("bm25_rank"),
        "rc": candidate.get("rc"),
        "cc": candidate.get("cc"),
        "mc": candidate.get("mc"),
    }


# 方式ごとの 1 位候補と閾値判定結果をまとめる。
def _build_method_result(
    score_name: str,
    ranked_candidates: Sequence[Dict[str, Any]],
    threshold: Optional[float] = None,
    *,
    include_ranked_candidates: bool = False,
) -> Dict[str, Any]:
    top_candidate = select_top_candidate(ranked_candidates)
    top_candidate_summary = _summarize_candidate(top_candidate)

    method_result = {
        "score_name": score_name,
        "candidate_count": len(ranked_candidates),
        "top_candidate": top_candidate_summary,
        "threshold": threshold,
        "threshold_pass": (
            apply_threshold(top_candidate[score_name], threshold)
            if top_candidate is not None and threshold is not None
            else None
        ),
    }

    if include_ranked_candidates:
        method_result["ranked_candidates"] = [
            _summarize_candidate(candidate) for candidate in ranked_candidates
        ]

    return method_result


# 正例評価時の方式別 outcome を返す。
def _evaluate_positive_outcome(method_name: str, method_result: Dict[str, Any], doi: Optional[str]) -> str:
    top_candidate = method_result["top_candidate"]
    if top_candidate is None:
        return "missed"

    if method_name == "bm25":
        return "detected" if doi and top_candidate["doi"] == doi else "false_positive"

    if not method_result["threshold_pass"]:
        return "missed"

    return "detected" if doi and top_candidate["doi"] == doi else "false_positive"


# 負例評価時の方式別 outcome を返す。
def _evaluate_negative_outcome(method_name: str, method_result: Dict[str, Any]) -> str:
    top_candidate = method_result["top_candidate"]
    if method_name == "bm25":
        return "true_negative" if top_candidate is None else "false_positive"

    if top_candidate is None or not method_result["threshold_pass"]:
        return "true_negative"
    return "false_positive"


# 1 件分の検索・スコア付与・方式別順位をまとめて返す共通処理。
def _evaluate_example(
    example: Dict[str, Any],
    thresholds: Optional[Dict[str, float]] = None,
    *,
    rows: int = 100,
    include_ranked_candidates: bool = False,
) -> Dict[str, Any]:
    normalized_thresholds = _normalize_thresholds(thresholds)
    search_result = search_reference(example["reference_text"], rows=rows)
    candidates = list(search_result["results"])
    scored_candidates = score_candidates(
        example["reference_text"],
        candidates,
        field_names=example.get("field_names"),
    )

    bm25_ranked_candidates = rerank_candidates(scored_candidates, "bm25_score")
    method_results = {
        "bm25": _build_method_result(
            "bm25_score",
            bm25_ranked_candidates,
            threshold=None,
            include_ranked_candidates=include_ranked_candidates,
        )
    }

    for score_name in THRESHOLDED_SCORE_NAMES:
        ranked_candidates = rerank_candidates(scored_candidates, score_name)
        method_results[score_name] = _build_method_result(
            score_name,
            ranked_candidates,
            threshold=normalized_thresholds[score_name],
            include_ranked_candidates=include_ranked_candidates,
        )

    return {
        "example_id": example.get("example_id"),
        "label": example.get("label"),
        "doi": example.get("doi"),
        "style": example.get("style"),
        "field_names": list(example.get("field_names") or []),
        "reference_text": example.get("reference_text"),
        "rows": rows,
        "thresholds": normalized_thresholds,
        "search": {
            "tokens": search_result["tokens"],
            "params": search_result["params"],
            "candidate_count": len(candidates),
        },
        "method_results": method_results,
    }


# 1 件の参考文献文字列に対して、中間確認向けの詳細評価結果を返す。
def evaluate_single_example(
    example: Dict[str, Any],
    thresholds: Optional[Dict[str, float]] = None,
    *,
    rows: int = 100,
) -> Dict[str, Any]:
    return _evaluate_example(
        example,
        thresholds,
        rows=rows,
        include_ranked_candidates=True,
    )


# 正例 1 件に対する評価結果を返す。
def evaluate_positive_example(
    example: Dict[str, Any],
    thresholds: Optional[Dict[str, float]] = None,
    *,
    rows: int = 100,
) -> Dict[str, Any]:
    evaluation_result = _evaluate_example(
        example,
        thresholds,
        rows=rows,
        include_ranked_candidates=False,
    )

    method_outcomes = {}
    for method_name, method_result in evaluation_result["method_results"].items():
        method_outcomes[method_name] = _evaluate_positive_outcome(
            method_name,
            method_result,
            example.get("doi"),
        )

    evaluation_result["method_outcomes"] = method_outcomes
    return evaluation_result


# 負例 1 件に対する評価結果を返す。
def evaluate_negative_example(
    example: Dict[str, Any],
    thresholds: Optional[Dict[str, float]] = None,
    *,
    rows: int = 100,
) -> Dict[str, Any]:
    evaluation_result = _evaluate_example(
        example,
        thresholds,
        rows=rows,
        include_ranked_candidates=False,
    )

    method_outcomes = {}
    for method_name, method_result in evaluation_result["method_results"].items():
        method_outcomes[method_name] = _evaluate_negative_outcome(
            method_name,
            method_result,
        )

    evaluation_result["method_outcomes"] = method_outcomes
    return evaluation_result


# 全件評価結果から方式別件数を集計する。
def summarize_results(results: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    result_list = list(results)
    labels = {str(result.get("label") or "").strip().lower() for result in result_list}

    summary = {
        "input_count": len(result_list),
        "methods": {
            "bm25": {},
            "rc": {},
            "cc": {},
            "mc": {},
        },
    }

    expected_outcomes = set()
    if "positive" in labels:
        expected_outcomes.update(POSITIVE_OUTCOME_NAMES)
    if "negative" in labels:
        expected_outcomes.update(NEGATIVE_OUTCOME_NAMES)

    for method_summary in summary["methods"].values():
        for outcome_name in expected_outcomes:
            method_summary[f"{outcome_name}_count"] = 0

    for result in result_list:
        for method_name, outcome in (result.get("method_outcomes") or {}).items():
            method_summary = summary["methods"].setdefault(method_name, {})
            count_key = f"{outcome}_count"
            method_summary[count_key] = method_summary.get(count_key, 0) + 1

    return summary


# 複数件の参考文献文字列に対して、正例または負例の全件評価を行う。
def evaluate_dataset(
    examples: Iterable[Dict[str, Any]],
    thresholds: Optional[Dict[str, float]] = None,
    *,
    rows: int = 100,
    mode: str = "positive",
) -> Dict[str, Any]:
    if mode not in SUPPORTED_EVALUATION_MODES:
        raise ValueError(f"未対応の mode です: {mode}")

    results: List[Dict[str, Any]] = []
    for example in examples:
        example_label = str(example.get("label") or "").strip().lower()
        effective_mode = mode
        if mode == "auto":
            if example_label not in {"positive", "negative"}:
                raise ValueError("mode='auto' では example['label'] に positive / negative が必要です。")
            effective_mode = example_label

        if effective_mode == "positive":
            results.append(
                evaluate_positive_example(
                    example,
                    thresholds,
                    rows=rows,
                )
            )
        else:
            results.append(
                evaluate_negative_example(
                    example,
                    thresholds,
                    rows=rows,
                )
            )

    return {
        "mode": mode,
        "rows": rows,
        "thresholds": _normalize_thresholds(thresholds),
        "results": results,
        "summary": summarize_results(results),
    }
