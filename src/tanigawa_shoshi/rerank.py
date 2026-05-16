"""候補文献へのスコア付与・再ランキング・閾値判定処理。"""

from typing import Any, Dict, Iterable, List, Optional, Sequence

from .scoring import (
    build_candidate_cc_token_sets,
    build_candidate_field_token_sets,
    build_reference_token_set,
    compute_cc,
    compute_mc,
    compute_rc,
)


SUPPORTED_SCORE_NAMES = {"rc", "cc", "mc", "bm25_score"}


# 検索結果候補 1 件へ RC / CC / MC を付与する。
def _score_candidate(
    reference_tokens: Sequence[str],
    candidate: Dict[str, Any],
    *,
    field_names: Optional[Sequence[str]] = None,
    bm25_rank: int,
) -> Dict[str, Any]:
    candidate_field_tokens = build_candidate_field_token_sets(
        candidate,
        field_names=field_names,
    )
    candidate_field_variants = build_candidate_cc_token_sets(
        candidate,
        field_names=field_names,
    )
    rc = compute_rc(
        reference_tokens,
        candidate_field_tokens,
        field_names=field_names,
    )
    cc = compute_cc(
        reference_tokens,
        candidate_field_tokens,
        candidate_field_variants,
        field_names=field_names,
    )
    mc = compute_mc(rc, cc)

    return {
        "doi": candidate.get("doi"),
        "title": (candidate.get("title") or [""])[0],
        "bm25_score": candidate.get("score"),
        "bm25_rank": bm25_rank,
        "field_names": list(field_names) if field_names is not None else None,
        "rc": rc,
        "cc": cc,
        "mc": mc,
        "candidate_field_tokens": candidate_field_tokens,
        "candidate_field_variants": candidate_field_variants,
        "candidate": candidate,
    }


# 参考文献文字列と候補群から、各候補へ RC / CC / MC を付与する。
def score_candidates(
    reference_text: str,
    candidates: Iterable[Dict[str, Any]],
    field_names: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    reference_tokens = build_reference_token_set(reference_text)

    scored_candidates: List[Dict[str, Any]] = []
    for bm25_rank, candidate in enumerate(candidates, start=1):
        scored_candidates.append(
            _score_candidate(
                reference_tokens,
                candidate,
                field_names=field_names,
                bm25_rank=bm25_rank,
            )
        )

    return scored_candidates


# 指定スコアで候補群を並べ替える。同点時は BM25 順を優先する。
def rerank_candidates(
    scored_candidates: Iterable[Dict[str, Any]],
    score_name: str,
) -> List[Dict[str, Any]]:
    if score_name not in SUPPORTED_SCORE_NAMES:
        raise ValueError(f"未対応の score_name です: {score_name}")

    return sorted(
        list(scored_candidates),
        key=lambda candidate: (
            -(candidate.get(score_name) or 0.0),
            candidate.get("bm25_rank") or 0,
        ),
    )


# 並べ替え済み候補群の 1 位候補を返す。候補がない場合は None を返す。
def select_top_candidate(
    ranked_candidates: Sequence[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not ranked_candidates:
        return None
    return ranked_candidates[0]


# 閾値以上かどうかを返す。
def apply_threshold(score: float, threshold: float) -> bool:
    return score >= threshold
