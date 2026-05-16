"""評価データ作成用の元メタデータ取得・保存処理。"""

import json
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from bson import ObjectId

from .config import (
    BASE_POSITIVE_EXAMPLES_PATH,
    MONGODB_COLLECTION,
    MONGODB_DATABASE,
    MONGODB_URL,
    NEGATIVE_EXAMPLES_PATH,
    NEGATIVE_TITLE_REWRITE_REQUESTS_PATH,
    NEGATIVE_TITLE_REWRITE_RESULTS_PATH,
    POSITIVE_EXAMPLES_PATH,
    SAMPLED_SOURCE_DOCS_PATH,
)
from .jalc_extract import (
    extract_doi,
    extract_journals,
    extract_page,
    extract_titles_basic,
    extract_volume,
    extract_year,
    has_required_doi,
    has_required_fields,
)
from .solr_indexer import JALC_PROJECTION, get_mongo_collection


SOURCE_DOC_PROJECTION = {
    "_id": 1,
    **JALC_PROJECTION,
}
DEFAULT_POSITIVE_FIELD_NAMES = ["authors", "title", "journal", "year", "volume", "page"]
DEFAULT_NEGATIVE_FIELD_NAMES = ["authors", "title", "journal", "year"]
CITATION_STYLE_ORDER = ["ipsj", "jsai", "lsj"]
TYPO_FIELD_WEIGHTS = {
    "authors": 20,
    "title": 40,
    "journal": 15,
    "year": 5,
    "volume": 5,
    "issue": 5,
    "page": 10,
}

# ObjectId や datetime を JSON 保存できる値へ再帰的に変換する。
def _normalize_for_json(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _normalize_for_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_for_json(item) for item in value]
    return value


# 文字列などの値を ObjectId へ変換する。
def _coerce_object_id(value: Any) -> ObjectId:
    if isinstance(value, ObjectId):
        return value
    if not value:
        raise ValueError("ObjectId に変換できる値を指定してください。")
    return ObjectId(str(value))


# 文字列に日本語文字が含まれるかを判定する。
def _contains_japanese_text(text: str) -> bool:
    for ch in text:
        code = ord(ch)
        if (
            0x3400 <= code <= 0x9FFF
            or 0x3040 <= code <= 0x30FF
            or 0x31F0 <= code <= 0x31FF
            or 0xFF66 <= code <= 0xFF9F
            or ch in {"々", "〆", "〇", "ヶ", "ヵ", "ー"}
        ):
            return True
    return False


# 1人分の著者名を、日本語なら姓名連結、それ以外は "姓 名" で返す。
def _build_primary_author_name(name: Dict[str, Any]) -> Optional[str]:
    last_name = (name.get("last_name") or "").strip()
    first_name = (name.get("first_name") or "").strip()
    lang = (name.get("lang") or "").strip().lower()

    if not last_name and not first_name:
        return None
    if not last_name:
        return first_name
    if not first_name:
        return last_name

    if lang == "ja" or _contains_japanese_text(last_name) or _contains_japanese_text(first_name):
        return last_name + first_name
    return f"{last_name} {first_name}"


# 各 creator について、引用文字列に使う代表著者名の配列を返す。
def _extract_primary_authors(doc: Dict[str, Any]) -> List[str]:
    authors: List[str] = []
    for creator in doc.get("creator_list") or []:
        selected_name = None
        fallback_name = None
        for name in creator.get("names") or []:
            candidate = _build_primary_author_name(name)
            if not candidate:
                continue
            if fallback_name is None:
                fallback_name = candidate
            lang = (name.get("lang") or "").strip().lower()
            if lang == "ja" or _contains_japanese_text(candidate):
                selected_name = candidate
                break
        chosen_name = selected_name or fallback_name
        if chosen_name:
            authors.append(chosen_name)
    return authors


# JaLC 文書から引用文字列生成用の基本書誌要素を取り出す。
def _extract_reference_fields(doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    authors = _extract_primary_authors(doc)
    titles = extract_titles_basic(doc)
    journals = extract_journals(doc)
    years = extract_year(doc)
    volume_values = extract_volume(doc)
    pages = extract_page(doc)

    if not all([authors, titles, journals, years, volume_values, pages]):
        return None

    volume = volume_values[0] if volume_values else ""
    issue = volume_values[1] if len(volume_values) > 1 else ""

    return {
        "authors": authors,
        "title": titles[0],
        "journal": journals[0],
        "year": years[0],
        "volume": volume,
        "issue": issue,
        "page": pages[0],
    }


# 巻・号・頁の表示部分を英語系スタイル向けに組み立てる。
def _build_english_bibliography_suffix(reference_fields: Dict[str, Any]) -> str:
    parts = []
    if reference_fields["volume"]:
        parts.append(f"Vol. {reference_fields['volume']}")
    if reference_fields["issue"]:
        parts.append(f"No. {reference_fields['issue']}")
    if reference_fields["page"]:
        parts.append(f"pp. {reference_fields['page']}")
    return ", ".join(parts)


# 情報処理学会形式の参考文献文字列を組み立てる。
def _format_ipsj_reference(reference_fields: Dict[str, Any]) -> str:
    authors_text = ", ".join(reference_fields["authors"])
    suffix = _build_english_bibliography_suffix(reference_fields)
    parts = [f"{authors_text}：{reference_fields['title']}", reference_fields["journal"]]
    if suffix:
        parts.append(suffix)
    parts.append(reference_fields["year"])
    return ", ".join(parts)


# 人工知能学会形式の参考文献文字列を組み立てる。
def _format_jsai_reference(reference_fields: Dict[str, Any]) -> str:
    authors_text = ", ".join(reference_fields["authors"])
    suffix = _build_english_bibliography_suffix(reference_fields)
    parts = [f"{authors_text}：{reference_fields['title']}", reference_fields["journal"]]
    if suffix:
        parts.append(suffix)
    return f"{', '.join(parts)} ({reference_fields['year']})"


# 日本言語学会形式の参考文献文字列を組み立てる。
def _format_lsj_reference(reference_fields: Dict[str, Any]) -> str:
    authors_text = "・".join(reference_fields["authors"])
    volume_issue = reference_fields["volume"]
    if reference_fields["volume"] and reference_fields["issue"]:
        volume_issue = f"{reference_fields['volume']}({reference_fields['issue']})"
    elif not reference_fields["volume"]:
        volume_issue = reference_fields["issue"]
    text = (
        f"{authors_text}（{reference_fields['year']}）"
        f"「{reference_fields['title']}」"
        f"『{reference_fields['journal']}』"
    )
    if volume_issue and reference_fields["page"]:
        return f"{text}{volume_issue}: {reference_fields['page']}."
    if volume_issue:
        return f"{text}{volume_issue}."
    if reference_fields["page"]:
        return f"{text}{reference_fields['page']}."
    return f"{text}."


# 引用スタイル名に応じて参考文献文字列を組み立てる。
def _build_reference_text(style: str, reference_fields: Dict[str, Any]) -> str:
    if style == "ipsj":
        return _format_ipsj_reference(reference_fields)
    if style == "jsai":
        return _format_jsai_reference(reference_fields)
    if style == "lsj":
        return _format_lsj_reference(reference_fields)
    raise ValueError(f"未対応の引用スタイルです: {style}")


# 雑誌名から学会名らしい文字列を推定して返す。
def _extract_society_name(journal: str) -> str:
    if not journal:
        return journal

    japanese_match = re.search(r"^(.+?学会)", journal)
    if japanese_match:
        return japanese_match.group(1)

    english_patterns = [
        r"(?:Journal|Transactions|Proceedings) of (?:the )?(.+?Society(?: of [A-Za-z .]+)?)$",
        r"(.+?Society(?: of [A-Za-z .]+)?)",
        r"(.+?Association(?: of [A-Za-z .]+)?)",
    ]
    for pattern in english_patterns:
        match = re.search(pattern, journal)
        if match:
            return match.group(1).strip(" .")

    return journal


# 数値文字列として扱えるかを判定する。
def _is_integer_text(value: Any) -> bool:
    return bool(value) and str(value).isdigit()


# 文字列から空白以外の 1 文字をランダムに削除する。
def _remove_one_character(value: str, rng: random.Random) -> Optional[str]:
    candidate_indexes = [index for index, ch in enumerate(value) if not ch.isspace()]
    if not candidate_indexes:
        return None
    selected_index = rng.choice(candidate_indexes)
    updated_value = value[:selected_index] + value[selected_index + 1 :]
    return updated_value if updated_value else None


# 数値文字列へ ±1 の変更を加える。
def _apply_plus_minus_one(value: str, rng: random.Random) -> Optional[str]:
    if not _is_integer_text(value):
        return None
    delta = rng.choice([-1, 1])
    return str(int(value) + delta)


# ページ文字列へ ±1 の変更を加える。
def _apply_page_plus_minus_one(value: str, rng: random.Random) -> Optional[str]:
    if not value:
        return None
    if "-" in value:
        page_parts = value.split("-")
        if len(page_parts) != 2 or not all(_is_integer_text(part) for part in page_parts):
            return None
        selected_index = rng.choice([0, 1])
        delta = rng.choice([-1, 1])
        page_parts[selected_index] = str(int(page_parts[selected_index]) + delta)
        return "-".join(page_parts)
    return _apply_plus_minus_one(value, rng)


# reference_fields へ指定の誤植を 1 件分適用する。
def _apply_typo_to_reference_fields(
    typo_field: str,
    reference_fields: Dict[str, Any],
    rng: random.Random,
) -> Optional[Dict[str, Any]]:
    if typo_field == "authors":
        authors = reference_fields["authors"]
        if len(authors) <= 1:
            return None
        return {
            "field": "authors",
            "before": authors[:],
            "after": authors[:-1],
        }

    if typo_field == "title":
        updated_title = _remove_one_character(reference_fields["title"], rng)
        if updated_title is None:
            return None
        return {
            "field": "title",
            "before": reference_fields["title"],
            "after": updated_title,
        }

    if typo_field == "journal":
        updated_journal = _remove_one_character(reference_fields["journal"], rng)
        if updated_journal is None:
            return None
        return {
            "field": "journal",
            "before": reference_fields["journal"],
            "after": updated_journal,
        }

    if typo_field == "year":
        updated_year = _apply_plus_minus_one(reference_fields["year"], rng)
        if updated_year is None:
            return None
        return {
            "field": "year",
            "before": reference_fields["year"],
            "after": updated_year,
        }

    if typo_field == "volume":
        updated_volume = _apply_plus_minus_one(reference_fields["volume"], rng)
        if updated_volume is None:
            return None
        return {
            "field": "volume",
            "before": reference_fields["volume"],
            "after": updated_volume,
        }

    if typo_field == "issue":
        updated_issue = _apply_plus_minus_one(reference_fields["issue"], rng)
        if updated_issue is None:
            return None
        return {
            "field": "issue",
            "before": reference_fields["issue"],
            "after": updated_issue,
        }

    if typo_field == "page":
        updated_page = _apply_page_plus_minus_one(reference_fields["page"], rng)
        if updated_page is None:
            return None
        return {
            "field": "page",
            "before": reference_fields["page"],
            "after": updated_page,
        }

    raise ValueError(f"未対応の誤植フィールドです: {typo_field}")


# 現在の reference_fields に対して適用可能な誤植候補を返す。
def _get_applicable_typo_fields(reference_fields: Dict[str, Any]) -> List[str]:
    applicable_fields = []
    if len(reference_fields["authors"]) > 1:
        applicable_fields.append("authors")
    if _remove_one_character(reference_fields["title"], random.Random(0)) is not None:
        applicable_fields.append("title")
    if _remove_one_character(reference_fields["journal"], random.Random(0)) is not None:
        applicable_fields.append("journal")
    if _is_integer_text(reference_fields["year"]):
        applicable_fields.append("year")
    if _is_integer_text(reference_fields["volume"]):
        applicable_fields.append("volume")
    if _is_integer_text(reference_fields["issue"]):
        applicable_fields.append("issue")
    if _apply_page_plus_minus_one(reference_fields["page"], random.Random(0)) is not None:
        applicable_fields.append("page")
    return applicable_fields


# 適用可能な誤植候補から、重み付きで重複なしに対象フィールドを選ぶ。
def _select_typo_fields(
    reference_fields: Dict[str, Any],
    typo_count: int,
    rng: random.Random,
) -> List[str]:
    selected_fields: List[str] = []
    remaining_fields = _get_applicable_typo_fields(reference_fields)

    for _ in range(min(typo_count, len(remaining_fields))):
        total_weight = sum(TYPO_FIELD_WEIGHTS[field_name] for field_name in remaining_fields)
        threshold = rng.uniform(0, total_weight)
        cumulative_weight = 0.0
        chosen_field = remaining_fields[-1]
        for field_name in remaining_fields:
            cumulative_weight += TYPO_FIELD_WEIGHTS[field_name]
            if threshold <= cumulative_weight:
                chosen_field = field_name
                break
        selected_fields.append(chosen_field)
        remaining_fields.remove(chosen_field)

    return selected_fields


# 評価用元メタデータのサンプリング条件を返す。
def _build_sampling_query() -> Dict[str, Any]:
    return {
        "content_type": "JA",
        "doi": {"$exists": True, "$ne": ""},
        "creator_list.0": {"$exists": True},
        "title_list.0": {"$exists": True},
        "journal_title_name_list.0": {"$exists": True},
        "publication_date": {"$exists": True, "$ne": {}},
        "$and": [
            {
                "$or": [
                    {"volume": {"$exists": True, "$nin": [None, ""]}},
                    {"issue": {"$exists": True, "$nin": [None, ""]}},
                ]
            },
            {
                "$or": [
                    {"first_page": {"$exists": True, "$nin": [None, ""]}},
                    {"last_page": {"$exists": True, "$nin": [None, ""]}},
                ]
            },
        ],
    }


# サンプリング条件に合う JaLC 文書の最小・最大 _id を返す。
def get_source_doc_id_bounds(
    collection=None,
    mongodb_url: str = MONGODB_URL,
    database_name: str = MONGODB_DATABASE,
    collection_name: str = MONGODB_COLLECTION,
) -> Tuple[ObjectId, ObjectId]:
    source_collection = (
        collection
        if collection is not None
        else get_mongo_collection(
            mongodb_url,
            database_name,
            collection_name,
        )
    )
    sampling_query = _build_sampling_query()

    min_doc = source_collection.find_one(
        sampling_query,
        {"_id": 1},
        sort=[("_id", 1)],
    )
    max_doc = source_collection.find_one(
        sampling_query,
        {"_id": 1},
        sort=[("_id", -1)],
    )

    if not min_doc or not max_doc:
        raise ValueError("サンプリング条件に合う JaLC 文書が見つかりません。")

    return min_doc["_id"], max_doc["_id"]


# _id >= sampled_id 方式で評価用元メタデータをランダムに集める。
def sample_source_docs(
    sample_size: int = 50,
    *,
    seed: Optional[int] = None,
    max_attempts: Optional[int] = None,
    min_object_id: Optional[Any] = None,
    max_object_id: Optional[Any] = None,
    projection: Optional[Dict[str, int]] = None,
    collection=None,
    mongodb_url: str = MONGODB_URL,
    database_name: str = MONGODB_DATABASE,
    collection_name: str = MONGODB_COLLECTION,
) -> Dict[str, Any]:
    if sample_size <= 0:
        raise ValueError("sample_size は 1 以上である必要があります。")

    source_collection = (
        collection
        if collection is not None
        else get_mongo_collection(
            mongodb_url,
            database_name,
            collection_name,
        )
    )
    source_projection = projection or SOURCE_DOC_PROJECTION
    lower_bound, upper_bound = get_source_doc_id_bounds(
        collection=source_collection,
        mongodb_url=mongodb_url,
        database_name=database_name,
        collection_name=collection_name,
    )

    if min_object_id is not None:
        lower_bound = _coerce_object_id(min_object_id)
    if max_object_id is not None:
        upper_bound = _coerce_object_id(max_object_id)
    if lower_bound > upper_bound:
        raise ValueError("min_object_id は max_object_id 以下である必要があります。")

    rng = random.Random(seed)
    attempt_limit = max_attempts or sample_size * 50
    sampling_query = _build_sampling_query()
    lower_int = int(str(lower_bound), 16)
    upper_int = int(str(upper_bound), 16)

    docs: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()
    seen_dois: Set[str] = set()
    stats = {
        "attempt_count": 0,
        "sampled_count": 0,
        "duplicate_id_count": 0,
        "duplicate_doi_count": 0,
        "missing_candidate_count": 0,
        "rejected_missing_doi_count": 0,
        "rejected_missing_required_fields_count": 0,
    }

    while len(docs) < sample_size and stats["attempt_count"] < attempt_limit:
        stats["attempt_count"] += 1
        sampled_int = rng.randint(lower_int, upper_int)
        sampled_id = ObjectId(f"{sampled_int:024x}")
        query = dict(sampling_query)
        query["_id"] = {"$gte": sampled_id}

        doc = source_collection.find_one(
            query,
            source_projection,
            sort=[("_id", 1)],
        )
        if not doc:
            stats["missing_candidate_count"] += 1
            continue

        doc_id = str(doc.get("_id"))
        if doc_id in seen_ids:
            stats["duplicate_id_count"] += 1
            continue

        if not has_required_doi(doc):
            stats["rejected_missing_doi_count"] += 1
            continue

        doi = extract_doi(doc)
        if doi in seen_dois:
            stats["duplicate_doi_count"] += 1
            continue

        if not has_required_fields(doc):
            stats["rejected_missing_required_fields_count"] += 1
            continue

        seen_ids.add(doc_id)
        seen_dois.add(doi)
        docs.append(doc)

    stats["sampled_count"] = len(docs)

    return {
        "docs": docs,
        "stats": stats,
        "sample_size": sample_size,
        "seed": seed,
        "max_attempts": attempt_limit,
        "min_object_id": str(lower_bound),
        "max_object_id": str(upper_bound),
    }


# 元メタデータ文書列を既定パスまたは指定パスの JSON ファイルへ保存する。
def save_source_docs(
    docs: Iterable[Dict[str, Any]],
    path: Any = SAMPLED_SOURCE_DOCS_PATH,
) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_docs = [_normalize_for_json(doc) for doc in docs]
    with output_path.open("w", encoding="utf-8") as output_file:
        json.dump(normalized_docs, output_file, ensure_ascii=False, indent=2)
    return output_path


# 保存済みの元メタデータ JSON ファイルを既定パスまたは指定パスから読み込む。
def load_source_docs(path: Any = SAMPLED_SOURCE_DOCS_PATH) -> List[Dict[str, Any]]:
    input_path = Path(path)
    with input_path.open("r", encoding="utf-8") as input_file:
        return json.load(input_file)


# 例データ列を JSON ファイルへ保存する。
def save_examples(path: Any, examples: Iterable[Dict[str, Any]]) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_examples = [_normalize_for_json(example) for example in examples]
    with output_path.open("w", encoding="utf-8") as output_file:
        json.dump(normalized_examples, output_file, ensure_ascii=False, indent=2)
    return output_path


# 保存済みの例データ JSON ファイルを読み込む。
def load_examples(path: Any) -> List[Dict[str, Any]]:
    input_path = Path(path)
    with input_path.open("r", encoding="utf-8") as input_file:
        return json.load(input_file)


# 元メタデータから 3 引用スタイル分の無加工正例データを生成する。
def build_base_positive_examples(
    docs: Iterable[Dict[str, Any]],
    *,
    field_names: Optional[List[str]] = None,
    styles: Optional[List[str]] = None,
) -> Dict[str, Any]:
    style_names = styles or CITATION_STYLE_ORDER
    positive_field_names = field_names or DEFAULT_POSITIVE_FIELD_NAMES

    examples: List[Dict[str, Any]] = []
    stats = {
        "input_count": 0,
        "built_count": 0,
        "skipped_missing_doi": 0,
        "skipped_missing_required_fields": 0,
        "skipped_reference_fields_build_failed": 0,
    }

    for doc in docs:
        stats["input_count"] += 1

        if not has_required_doi(doc):
            stats["skipped_missing_doi"] += 1
            continue

        if not has_required_fields(doc):
            stats["skipped_missing_required_fields"] += 1
            continue

        doi = extract_doi(doc)
        source_id = str(doc.get("_id") or "")
        reference_fields = _extract_reference_fields(doc)
        if reference_fields is None:
            stats["skipped_reference_fields_build_failed"] += 1
            continue

        for style in style_names:
            example_id = f"{source_id}:{style}"
            examples.append(
                {
                    "example_id": example_id,
                    "source_id": source_id,
                    "label": "positive",
                    "doi": doi,
                    "style": style,
                    "field_names": positive_field_names[:],
                    "has_typos": False,
                    "reference_fields": {
                        "authors": reference_fields["authors"][:],
                        "title": reference_fields["title"],
                        "journal": reference_fields["journal"],
                        "year": reference_fields["year"],
                        "volume": reference_fields["volume"],
                        "issue": reference_fields["issue"],
                        "page": reference_fields["page"],
                    },
                    "reference_text": _build_reference_text(style, reference_fields),
                }
            )
            stats["built_count"] += 1

    return {
        "examples": examples,
        "stats": stats,
        "style_names": style_names,
        "field_names": positive_field_names,
        "default_output_path": str(BASE_POSITIVE_EXAMPLES_PATH),
    }


# 無加工正例データから、論文表2に従った誤植付き正例データを生成する。
def build_positive_examples(
    base_examples: Iterable[Dict[str, Any]],
    *,
    seed: Optional[int] = None,
) -> Dict[str, Any]:
    rng = random.Random(seed)
    examples: List[Dict[str, Any]] = []
    stats = {
        "input_count": 0,
        "built_count": 0,
        "typo_example_count": 0,
        "no_typo_example_count": 0,
        "single_typo_count": 0,
        "double_typo_count": 0,
    }

    for base_example in base_examples:
        stats["input_count"] += 1

        updated_example = {
            "example_id": base_example["example_id"],
            "source_id": base_example["source_id"],
            "label": base_example["label"],
            "doi": base_example["doi"],
            "style": base_example["style"],
            "field_names": list(base_example["field_names"]),
            "base_example_id": base_example["example_id"],
            "has_typos": False,
            "typo_details": [],
            "reference_fields": {
                "authors": list(base_example["reference_fields"]["authors"]),
                "title": base_example["reference_fields"]["title"],
                "journal": base_example["reference_fields"]["journal"],
                "year": base_example["reference_fields"]["year"],
                "volume": base_example["reference_fields"]["volume"],
                "issue": base_example["reference_fields"]["issue"],
                "page": base_example["reference_fields"]["page"],
            },
            "reference_text": base_example["reference_text"],
        }

        has_typos = rng.random() < 0.35
        if not has_typos:
            examples.append(updated_example)
            stats["built_count"] += 1
            stats["no_typo_example_count"] += 1
            continue

        typo_count = 1 if rng.random() < 0.8 else 2
        selected_fields = _select_typo_fields(updated_example["reference_fields"], typo_count, rng)
        typo_details: List[Dict[str, Any]] = []
        for typo_field in selected_fields:
            typo_result = _apply_typo_to_reference_fields(
                typo_field,
                updated_example["reference_fields"],
                rng,
            )
            if typo_result is None:
                continue
            updated_example["reference_fields"][typo_result["field"]] = typo_result["after"]
            typo_details.append(typo_result)

        if typo_details:
            updated_example["has_typos"] = True
            updated_example["typo_details"] = typo_details
            updated_example["reference_text"] = _build_reference_text(
                updated_example["style"],
                updated_example["reference_fields"],
            )
            stats["typo_example_count"] += 1
            if len(typo_details) == 1:
                stats["single_typo_count"] += 1
            elif len(typo_details) == 2:
                stats["double_typo_count"] += 1
        else:
            stats["no_typo_example_count"] += 1

        examples.append(updated_example)
        stats["built_count"] += 1

    return {
        "examples": examples,
        "stats": stats,
        "seed": seed,
        "default_output_path": str(POSITIVE_EXAMPLES_PATH),
    }


# 無加工正例データを source_id ごとにまとめる。
def _group_examples_by_source_id(base_examples: Iterable[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped_examples: Dict[str, List[Dict[str, Any]]] = {}
    for example in base_examples:
        source_id = str(example["source_id"])
        grouped_examples.setdefault(source_id, []).append(example)
    return grouped_examples


# 無加工正例 1 論文分から、負例用の共通書誌要素を作る。
def _build_negative_reference_fields(reference_fields: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    updated_fields = {
        "authors": list(reference_fields["authors"]),
        "title": reference_fields["title"],
        "journal": reference_fields["journal"],
        "year": reference_fields["year"],
        "volume": reference_fields["volume"],
        "issue": reference_fields["issue"],
        "page": reference_fields["page"],
    }
    modification_details: List[Dict[str, Any]] = []

    if len(updated_fields["authors"]) > 1:
        before_authors = updated_fields["authors"][:]
        updated_fields["authors"] = updated_fields["authors"][:-1]
        modification_details.append(
            {
                "field": "authors",
                "before": before_authors,
                "after": updated_fields["authors"][:],
            }
        )

    replaced_journal = _extract_society_name(updated_fields["journal"])
    modification_details.append(
        {
            "field": "journal",
            "before": updated_fields["journal"],
            "after": replaced_journal,
        }
    )
    updated_fields["journal"] = replaced_journal

    modification_details.append(
        {
            "field": "year",
            "before": updated_fields["year"],
            "after": "2019",
        }
    )
    updated_fields["year"] = "2019"

    if updated_fields["volume"] or updated_fields["issue"] or updated_fields["page"]:
        modification_details.append(
            {
                "field": "volume_issue_page",
                "before": {
                    "volume": updated_fields["volume"],
                    "issue": updated_fields["issue"],
                    "page": updated_fields["page"],
                },
                "after": {
                    "volume": "",
                    "issue": "",
                    "page": "",
                },
            }
        )
    updated_fields["volume"] = ""
    updated_fields["issue"] = ""
    updated_fields["page"] = ""

    return updated_fields, modification_details


# 無加工正例データから、source_id 単位で一貫した改変内容の負例データを生成する。
def build_negative_examples(
    base_examples: Iterable[Dict[str, Any]],
    *,
    field_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    negative_field_names = field_names or DEFAULT_NEGATIVE_FIELD_NAMES
    grouped_examples = _group_examples_by_source_id(base_examples)

    examples: List[Dict[str, Any]] = []
    stats = {
        "input_count": 0,
        "built_count": 0,
        "source_group_count": len(grouped_examples),
    }

    for source_id, source_examples in grouped_examples.items():
        stats["input_count"] += len(source_examples)
        base_reference_fields = source_examples[0]["reference_fields"]
        negative_reference_fields, negative_details = _build_negative_reference_fields(base_reference_fields)

        for base_example in source_examples:
            examples.append(
                {
                    "example_id": base_example["example_id"],
                    "source_id": source_id,
                    "label": "negative",
                    "doi": None,
                    "style": base_example["style"],
                    "field_names": list(negative_field_names),
                    "base_example_id": base_example["example_id"],
                    "needs_title_rewrite": True,
                    "title_rewrite_status": "pending",
                    "negative_details": negative_details,
                    "reference_fields": {
                        "authors": list(negative_reference_fields["authors"]),
                        "title": negative_reference_fields["title"],
                        "journal": negative_reference_fields["journal"],
                        "year": negative_reference_fields["year"],
                        "volume": negative_reference_fields["volume"],
                        "issue": negative_reference_fields["issue"],
                        "page": negative_reference_fields["page"],
                    },
                    "reference_text": _build_reference_text(
                        base_example["style"],
                        negative_reference_fields,
                    ),
                }
            )
            stats["built_count"] += 1

    return {
        "examples": examples,
        "stats": stats,
        "field_names": negative_field_names,
        "default_output_path": str(NEGATIVE_EXAMPLES_PATH),
    }


# source_id ごとに 1 回だけ AI でタイトル書換えを依頼するためのリクエスト一覧を作る。
def build_negative_title_rewrite_requests(negative_examples: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    grouped_examples = _group_examples_by_source_id(negative_examples)
    requests: List[Dict[str, Any]] = []

    for source_id, source_examples in grouped_examples.items():
        first_example = source_examples[0]
        title = first_example["reference_fields"]["title"]
        requests.append(
            {
                "source_id": source_id,
                "title_rewrite_status": "pending",
                "original_title": title,
                "prompt": (
                    "入力した論文タイトルを意味は同じまま別のタイトルに変換せよ。"
                    " 変換後のタイトル文字列だけを返せ。"
                    f" タイトル: {title}"
                ),
                "style_names": [example["style"] for example in source_examples],
                "example_ids": [example["example_id"] for example in source_examples],
            }
        )

    return {
        "requests": requests,
        "stats": {
            "request_count": len(requests),
        },
        "default_output_path": str(NEGATIVE_TITLE_REWRITE_REQUESTS_PATH),
    }


# タイトル書換え結果を source_id ごとの参照しやすい辞書へ変換する。
def _build_title_rewrite_result_map(
    rewrite_results: Iterable[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    result_map: Dict[str, Dict[str, Any]] = {}
    for result in rewrite_results:
        source_id = str(result.get("source_id") or "")
        rewritten_title = (result.get("rewritten_title") or "").strip()
        if not source_id:
            raise ValueError("source_id が空のタイトル書換え結果があります。")
        if not rewritten_title:
            raise ValueError(f"source_id={source_id} の rewritten_title が空です。")
        result_map[source_id] = result
    return result_map


# タイトル書換え結果を負例データへ反映し、reference_text を再生成する。
def apply_negative_title_rewrite_results(
    negative_examples: Iterable[Dict[str, Any]],
    rewrite_results: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    rewrite_result_map = _build_title_rewrite_result_map(rewrite_results)

    examples: List[Dict[str, Any]] = []
    stats = {
        "input_count": 0,
        "updated_count": 0,
        "pending_count": 0,
        "missing_rewrite_result_count": 0,
    }

    for negative_example in negative_examples:
        stats["input_count"] += 1

        existing_negative_details = list(negative_example.get("negative_details") or [])
        filtered_negative_details = [
            detail
            for detail in existing_negative_details
            if detail.get("field") != "title"
        ]
        existing_title_result = negative_example.get("title_rewrite_result") or {}
        updated_example = {
            **negative_example,
            "field_names": list(negative_example["field_names"]),
            "negative_details": filtered_negative_details,
            "reference_fields": {
                "authors": list(negative_example["reference_fields"]["authors"]),
                "title": negative_example["reference_fields"]["title"],
                "journal": negative_example["reference_fields"]["journal"],
                "year": negative_example["reference_fields"]["year"],
                "volume": negative_example["reference_fields"]["volume"],
                "issue": negative_example["reference_fields"]["issue"],
                "page": negative_example["reference_fields"]["page"],
            },
        }

        source_id = str(negative_example["source_id"])
        rewrite_result = rewrite_result_map.get(source_id)
        if rewrite_result is None:
            stats["missing_rewrite_result_count"] += 1
            stats["pending_count"] += 1
            examples.append(updated_example)
            continue

        rewritten_title = rewrite_result["rewritten_title"].strip()
        original_title = (
            existing_title_result.get("original_title")
            or rewrite_result.get("original_title")
            or updated_example["reference_fields"]["title"]
        )
        updated_example["reference_fields"]["title"] = rewritten_title
        updated_example["needs_title_rewrite"] = False
        updated_example["title_rewrite_status"] = rewrite_result.get(
            "title_rewrite_status",
            "completed",
        )
        updated_example["title_rewrite_result"] = {
            "original_title": rewrite_result.get("original_title", original_title),
            "rewritten_title": rewritten_title,
        }
        updated_example["negative_details"] = updated_example["negative_details"] + [
            {
                "field": "title",
                "before": original_title,
                "after": rewritten_title,
            }
        ]
        updated_example["reference_text"] = _build_reference_text(
            updated_example["style"],
            updated_example["reference_fields"],
        )
        examples.append(updated_example)
        stats["updated_count"] += 1

    return {
        "examples": examples,
        "stats": stats,
        "default_output_path": str(NEGATIVE_EXAMPLES_PATH),
    }


# AI 書換え済みタイトル結果の保存先向けに結果データを組み立てる。
def build_negative_title_rewrite_results(
    rewrite_requests: Iterable[Dict[str, Any]],
    rewritten_titles_by_source_id: Dict[str, str],
) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    stats = {
        "input_count": 0,
        "built_count": 0,
        "missing_source_id_count": 0,
    }

    for request in rewrite_requests:
        stats["input_count"] += 1
        source_id = str(request.get("source_id") or "")
        rewritten_title = (rewritten_titles_by_source_id.get(source_id) or "").strip()
        if not source_id or not rewritten_title:
            stats["missing_source_id_count"] += 1
            continue
        results.append(
            {
                "source_id": source_id,
                "original_title": request.get("original_title", ""),
                "rewritten_title": rewritten_title,
                "title_rewrite_status": "completed",
                "style_names": list(request.get("style_names") or []),
                "example_ids": list(request.get("example_ids") or []),
            }
        )
        stats["built_count"] += 1

    return {
        "results": results,
        "stats": stats,
        "default_output_path": str(NEGATIVE_TITLE_REWRITE_RESULTS_PATH),
    }
