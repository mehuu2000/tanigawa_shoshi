"""評価データ作成用の元メタデータ取得・保存処理。"""

import json
import random
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from bson import ObjectId

from .config import (
    BASE_POSITIVE_EXAMPLES_PATH,
    MONGODB_COLLECTION,
    MONGODB_DATABASE,
    MONGODB_URL,
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
CITATION_STYLE_ORDER = ["ipsj", "jsai", "lsj"]

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
    parts.append(f"pp. {reference_fields['page']}")
    return ", ".join(parts)


# 情報処理学会形式の参考文献文字列を組み立てる。
def _format_ipsj_reference(reference_fields: Dict[str, Any]) -> str:
    authors_text = ", ".join(reference_fields["authors"])
    suffix = _build_english_bibliography_suffix(reference_fields)
    return (
        f"{authors_text}：{reference_fields['title']}, "
        f"{reference_fields['journal']}, {suffix}, {reference_fields['year']}"
    )


# 人工知能学会形式の参考文献文字列を組み立てる。
def _format_jsai_reference(reference_fields: Dict[str, Any]) -> str:
    authors_text = ", ".join(reference_fields["authors"])
    suffix = _build_english_bibliography_suffix(reference_fields)
    return (
        f"{authors_text}：{reference_fields['title']}, "
        f"{reference_fields['journal']}, {suffix} ({reference_fields['year']})"
    )


# 日本言語学会形式の参考文献文字列を組み立てる。
def _format_lsj_reference(reference_fields: Dict[str, Any]) -> str:
    authors_text = "・".join(reference_fields["authors"])
    volume_issue = reference_fields["volume"]
    if reference_fields["volume"] and reference_fields["issue"]:
        volume_issue = f"{reference_fields['volume']}({reference_fields['issue']})"
    elif not reference_fields["volume"]:
        volume_issue = reference_fields["issue"]
    return (
        f"{authors_text}（{reference_fields['year']}）"
        f"「{reference_fields['title']}」"
        f"『{reference_fields['journal']}』"
        f"{volume_issue}: {reference_fields['page']}."
    )


# 引用スタイル名に応じて参考文献文字列を組み立てる。
def _build_reference_text(style: str, reference_fields: Dict[str, Any]) -> str:
    if style == "ipsj":
        return _format_ipsj_reference(reference_fields)
    if style == "jsai":
        return _format_jsai_reference(reference_fields)
    if style == "lsj":
        return _format_lsj_reference(reference_fields)
    raise ValueError(f"未対応の引用スタイルです: {style}")


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
