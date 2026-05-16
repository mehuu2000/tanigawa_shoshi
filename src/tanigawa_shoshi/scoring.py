"""RC / CC / MC 計算用のトークン生成とスコア計算処理。"""

from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from .search import split_reference_values
from .tokenizer import tokenize_values


DEFAULT_FIELD_TOKEN_NAMES = ["authors", "first_author", "title", "journal", "year", "volume", "page"]
DEFAULT_RC_FIELD_NAMES = ["authors", "title", "journal", "year", "volume", "page"]
DEFAULT_CC_FIELD_NAMES = ["first_author", "title", "journal", "year", "volume", "page"]
CC_FIELD_ALIASES = {
    "authors": "first_author",
}
SUPPORTED_FIELD_NAMES = ["authors", "first_author", "title", "journal", "year", "volume", "page"]


# 重複を除外しながら、順序を保ったまま文字列リストを返す。
def _unique_preserve_order(values: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


# Solr 文書や評価データの field 値を、空要素を除いた文字列配列へ正規化する。
def _normalize_values(value: Any) -> List[str]:
    if value is None:
        return []

    if isinstance(value, (list, tuple)):
        values = value
    else:
        values = [value]

    normalized_values = []
    for item in values:
        text = str(item).strip()
        if text:
            normalized_values.append(text)
    return normalized_values


# RC / CC 計算で使う field_names を正規化し、順序を保って返す。
def _normalize_field_names(
    field_names: Optional[Sequence[str]] = None,
    *,
    for_cc: bool = False,
) -> List[str]:
    if field_names is None:
        default_field_names = DEFAULT_CC_FIELD_NAMES if for_cc else DEFAULT_RC_FIELD_NAMES
        return default_field_names[:]

    normalized_field_names: List[str] = []
    for field_name in field_names:
        normalized_name = str(field_name).strip()
        if not normalized_name:
            continue
        if for_cc:
            normalized_name = CC_FIELD_ALIASES.get(normalized_name, normalized_name)
        if normalized_name not in SUPPORTED_FIELD_NAMES:
            raise ValueError(f"未対応の field_name です: {field_name}")
        normalized_field_names.append(normalized_name)

    return _unique_preserve_order(normalized_field_names)


# RC 計算で使う Cf を field ごとに統合して C を作る。
def _build_candidate_union_token_set(
    candidate_field_tokens: Dict[str, List[str]],
    field_names: Optional[Sequence[str]] = None,
) -> List[str]:
    selected_field_names = _normalize_field_names(field_names, for_cc=False)
    tokens: List[str] = []
    for field_name in selected_field_names:
        tokens.extend(candidate_field_tokens.get(field_name) or [])
    return _unique_preserve_order(tokens)


# R ∩ C または R ∩ Cvf の被覆率計算で使う共通処理。
def _compute_coverage(reference_token_set: Set[str], candidate_tokens: Sequence[str]) -> float:
    candidate_token_set = set(candidate_tokens)
    if not candidate_token_set:
        return 0.0
    return len(reference_token_set & candidate_token_set) / len(candidate_token_set)


# 参考文献文字列全体をトークン化し、R として使う token 集合を返す。
def build_reference_token_set(
    reference_text: str,
    field_names: Optional[Sequence[str]] = None,
) -> List[str]:
    del field_names  # 現状の R は reference 全体の token 集合として扱う。
    reference_values = split_reference_values(reference_text)
    return tokenize_values(reference_values)


# 候補文献の stored field から RC / CC 共通利用用の Cf を field ごとに生成する。
def build_candidate_field_token_sets(
    doc: Dict[str, Any],
    field_names: Optional[Sequence[str]] = None,
) -> Dict[str, List[str]]:
    selected_field_names = (
        DEFAULT_FIELD_TOKEN_NAMES[:]
        if field_names is None
        else _normalize_field_names(field_names, for_cc=False)
    )
    if field_names is not None and "first_author" not in selected_field_names:
        # Cf は RC / CC の共通中間表現として扱うため、明示 field_names が RC 向けでも
        # CC 側で必要になる first_author は追加しておく。
        selected_field_names.append("first_author")

    candidate_field_tokens: Dict[str, List[str]] = {}
    for field_name in selected_field_names:
        candidate_field_tokens[field_name] = tokenize_values(
            _normalize_values(doc.get(field_name))
        )
    return candidate_field_tokens


# 候補文献の CC 用 Cvf を、field ごとの token 集合列として生成する。
def build_candidate_cc_token_sets(
    doc: Dict[str, Any],
    field_names: Optional[Sequence[str]] = None,
) -> Dict[str, List[List[str]]]:
    selected_field_names = _normalize_field_names(field_names, for_cc=True)
    candidate_cc_tokens: Dict[str, List[List[str]]] = {}

    for field_name in selected_field_names:
        if field_name == "first_author":
            variant_values = _normalize_values(doc.get("first_author_variations"))
            if not variant_values:
                variant_values = _normalize_values(doc.get("first_author"))
            candidate_cc_tokens[field_name] = [
                tokenize_values([value]) for value in variant_values if tokenize_values([value])
            ]
            continue

        if field_name == "title":
            variant_values = _normalize_values(doc.get("title_variations"))
            if not variant_values:
                variant_values = _normalize_values(doc.get("title"))
            candidate_cc_tokens[field_name] = [
                tokenize_values([value]) for value in variant_values if tokenize_values([value])
            ]
            continue

        if field_name == "journal":
            variant_values = _normalize_values(doc.get("journal"))
            candidate_cc_tokens[field_name] = [
                tokenize_values([value]) for value in variant_values if tokenize_values([value])
            ]
            continue

        field_tokens = tokenize_values(_normalize_values(doc.get(field_name)))
        candidate_cc_tokens[field_name] = [field_tokens] if field_tokens else []

    return candidate_cc_tokens


# R と Cf から統合候補集合 C を作り、RC = |R ∩ C| / |R| を返す。
def compute_rc(
    reference_tokens: Sequence[str],
    candidate_field_tokens: Dict[str, List[str]],
    field_names: Optional[Sequence[str]] = None,
) -> float:
    reference_token_set = set(reference_tokens)
    if not reference_token_set:
        return 0.0

    candidate_union_tokens = _build_candidate_union_token_set(
        candidate_field_tokens,
        field_names=field_names,
    )
    return len(reference_token_set & set(candidate_union_tokens)) / len(reference_token_set)


# R と Cf / Cvf から CCf を求め、その平均として CC を返す。
def compute_cc(
    reference_tokens: Sequence[str],
    candidate_field_tokens: Dict[str, List[str]],
    candidate_field_variants: Dict[str, List[List[str]]],
    field_names: Optional[Sequence[str]] = None,
) -> float:
    selected_field_names = _normalize_field_names(field_names, for_cc=True)
    if not selected_field_names:
        return 0.0

    reference_token_set = set(reference_tokens)
    field_scores: List[float] = []

    for field_name in selected_field_names:
        variant_token_sets = candidate_field_variants.get(field_name) or []
        if variant_token_sets:
            field_score = max(
                _compute_coverage(reference_token_set, variant_tokens)
                for variant_tokens in variant_token_sets
            )
        else:
            field_score = _compute_coverage(
                reference_token_set,
                candidate_field_tokens.get(field_name) or [],
            )
        field_scores.append(field_score)

    return sum(field_scores) / len(field_scores)


# RC と CC の調和平均として MC を返す。
def compute_mc(rc: float, cc: float) -> float:
    if rc < 0 or cc < 0:
        raise ValueError("RC / CC は 0 以上である必要があります。")
    if rc + cc == 0:
        return 0.0
    return 2 * rc * cc / (rc + cc)
