"""MongoDB から Solr へ JaLC 文書を登録する処理。"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from pymongo import MongoClient
import pysolr

from .config import (
    BATCH_SIZE,
    MONGODB_COLLECTION,
    MONGODB_DATABASE,
    MONGODB_URL,
    SOLR_BASE_URL,
    SOLR_CORE,
)
from .jalc_extract import build_solr_document_with_issues, has_required_doi, has_required_fields


JALC_FIND_QUERY = {"content_type": "JA"}
PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = PROJECT_ROOT / "log"

# 登録時に必要な書誌要素だけを取得する。
JALC_PROJECTION = {
    "doi": 1,
    "content_type": 1,
    "creator_list": 1,
    "title_list": 1,
    "journal_title_name_list": 1,
    "publication_date": 1,
    "volume": 1,
    "issue": 1,
    "first_page": 1,
    "last_page": 1,
}

# Solr コアの URL を返す。
def get_solr_url(solr_base_url: str, core_name: str) -> str:
    return f"{solr_base_url.rstrip('/')}/{core_name}"

# MongoDB の対象コレクションを返す。
def get_mongo_collection(
    mongodb_url: str = MONGODB_URL,
    database_name: str = MONGODB_DATABASE,
    collection_name: str = MONGODB_COLLECTION,
):
    client = MongoClient(mongodb_url)
    return client[database_name][collection_name]

# JaLCの対象コアに接続する pysolr クライアントを返す。
def get_solr_client(
    solr_base_url: str = SOLR_BASE_URL,
    core_name: str = SOLR_CORE,
    always_commit: bool = True,
    timeout: int = 60,
) -> pysolr.Solr:
    solr_url = get_solr_url(solr_base_url, core_name)
    return pysolr.Solr(solr_url, always_commit=always_commit, timeout=timeout)

# content_type=JA の JaLC 文書を取得する cursor を返す
def iter_jalc_documents(
    collection,
    limit: Optional[int] = None,
    projection: Optional[Dict[str, int]] = None,
):
    find_projection = projection or JALC_PROJECTION
    cursor = collection.find(JALC_FIND_QUERY, find_projection)
    if limit is not None:
        cursor = cursor.limit(limit)
    return cursor

# 全件登録時のスキップログファイルを作成し、そのパスを返す。
def create_skip_log_path() -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
    log_path = LOG_DIR / f"{timestamp}.log"
    log_path.touch()
    return log_path

# スキップ対象1件分の内容を JSON Lines 形式でログへ追記する。
def append_skip_log(log_path: Path, mongo_id: str, field_name: str, value: Any, reason: str) -> None:
    log_record = {
        "mongo_id": mongo_id,
        "field_name": field_name,
        "value": value,
        "reason": reason,
    }
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(log_record, ensure_ascii=False) + "\n")

# sample 側で使う。JaLC 文書列から Solr 登録用文書列を作る。
def build_documents(docs: Iterable[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    solr_documents = []
    stats = {
        "input_count": 0,
        "built_count": 0,
        "skipped_missing_doi": 0,
        "skipped_missing_required_fields": 0,
        "skipped_missing_required_token_fields": 0,
        "skipped_build_failed": 0,
    }

    for doc in docs:
        stats["input_count"] += 1

        if not has_required_doi(doc):
            stats["skipped_missing_doi"] += 1
            continue

        if not has_required_fields(doc):
            stats["skipped_missing_required_fields"] += 1
            continue

        solr_document, issues = build_solr_document_with_issues(doc)
        if solr_document is None:
            if issues:
                stats["skipped_missing_required_token_fields"] += 1
            else:
                stats["skipped_build_failed"] += 1
            continue

        solr_documents.append(solr_document)
        stats["built_count"] += 1

    return solr_documents, stats

# sample 側で使う。Solr 登録用文書列を batch 単位で Solr に送る。
def index_documents(solr: pysolr.Solr, docs: Iterable[Dict[str, Any]], batch_size: int = BATCH_SIZE) -> Dict[str, int]:
    if batch_size <= 0:
        raise ValueError("batch_size は 1 以上である必要があります。")

    batch = []
    stats = {
        "indexed_count": 0,
        "batch_count": 0,
    }

    for doc in docs:
        batch.append(doc)
        if len(batch) == batch_size:
            solr.add(batch)
            stats["indexed_count"] += len(batch)
            stats["batch_count"] += 1
            print(f"{len(batch)}件のデータを登録")
            batch = []

    if batch:
        solr.add(batch)
        stats["indexed_count"] += len(batch)
        stats["batch_count"] += 1
        print(f"{len(batch)}件のデータを登録")

    return stats

# Solr コアは残したまま、登録済み文書を全削除する。
def delete_all_documents(solr: pysolr.Solr, commit: bool = True) -> Dict[str, object]:
    solr.delete(q="*:*")

    if commit:
        solr.commit()

    return {
        "deleted_query": "*:*",
        "commit_executed": commit,
    }

# MongoDB から JA 文書を読み、Solr へ全件登録する一連の処理を行う。
def index_all(
    mongodb_url: str = MONGODB_URL,
    database_name: str = MONGODB_DATABASE,
    collection_name: str = MONGODB_COLLECTION,
    solr_base_url: str = SOLR_BASE_URL,
    core_name: str = SOLR_CORE,
    batch_size: int = BATCH_SIZE,
    limit: Optional[int] = None,
    always_commit: bool = False,
) -> Dict[str, int]:
    collection = get_mongo_collection(mongodb_url, database_name, collection_name)
    solr = get_solr_client(solr_base_url, core_name, always_commit=always_commit)
    raw_docs = iter_jalc_documents(collection, limit=limit)

    if batch_size <= 0:
        raise ValueError("batch_size は 1 以上である必要があります。")

    batch = []
    stats = {
        "input_count": 0,
        "built_count": 0,
        "indexed_count": 0,
        "batch_count": 0,
        "skipped_missing_doi": 0,
        "skipped_missing_required_fields": 0,
        "skipped_missing_required_token_fields": 0,
        "skipped_build_failed": 0,
    }
    skip_log_path = create_skip_log_path()
    print(f"skip log: {skip_log_path}")

    for doc in raw_docs:
        stats["input_count"] += 1

        if not has_required_doi(doc):
            stats["skipped_missing_doi"] += 1
            continue

        if not has_required_fields(doc):
            stats["skipped_missing_required_fields"] += 1
            continue

        solr_document, issues = build_solr_document_with_issues(doc)
        if solr_document is None:
            if issues:
                stats["skipped_missing_required_token_fields"] += 1
            else:
                stats["skipped_build_failed"] += 1
            mongo_id = str(doc.get("_id", ""))
            for issue in issues:
                append_skip_log(
                    skip_log_path,
                    mongo_id=mongo_id,
                    field_name=str(issue.get("field_name", "")),
                    value=issue.get("value"),
                    reason=str(issue.get("reason", "")),
                )
            continue

        batch.append(solr_document)
        stats["built_count"] += 1

        if len(batch) == batch_size:
            solr.add(batch)
            stats["indexed_count"] += len(batch)
            stats["batch_count"] += 1
            print(f"{len(batch)}件のデータを登録")
            batch = []

    if batch:
        solr.add(batch)
        stats["indexed_count"] += len(batch)
        stats["batch_count"] += 1
        print(f"{len(batch)}件のデータを登録")

    # 全件投入では batch ごとの commit を避け、最後にまとめて commit する。
    if not always_commit and stats["indexed_count"] > 0:
        solr.commit()
        print("最後に commit を実行")

    print("全件登録完了")
    print(f"Mongo取得した日本語書誌の件数: {stats['input_count']}")
    print(f"正常にSolrに登録できる形にビルドした件数: {stats['built_count']}")
    print(f"正常にSolrに登録できた件数: {stats['indexed_count']}")
    print("")
    print(f"DOIがな買った件数: {stats['skipped_missing_doi']}")
    print(f"必須生データが不足していた件数: {stats['skipped_missing_required_fields']}")
    print(f"値が特殊文字のみだった件数: {stats['skipped_missing_required_token_fields']}")
    print(f"カラムは存在するが、値が不足していた件数: {stats['skipped_build_failed']}")

    return stats
