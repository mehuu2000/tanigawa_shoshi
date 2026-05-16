"""評価データ作成用の元メタデータ取得・保存処理。"""

import json
import random
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from bson import ObjectId

from .config import (
    MONGODB_COLLECTION,
    MONGODB_DATABASE,
    MONGODB_URL,
    SAMPLED_SOURCE_DOCS_PATH,
)
from .jalc_extract import extract_doi, has_required_doi, has_required_fields
from .solr_indexer import JALC_PROJECTION, get_mongo_collection


SOURCE_DOC_PROJECTION = {
    "_id": 1,
    **JALC_PROJECTION,
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
