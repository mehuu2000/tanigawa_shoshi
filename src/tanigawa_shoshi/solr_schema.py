"""Solrスキーマ設定処理。"""

import json
from typing import Dict, List, Optional
from urllib import error, parse, request


SAVED_FIELDS = [
    {
        "name": "doi",
        "type": "string",
        "stored": True,
        "indexed": False,
        "required": False,
        "multiValued": False,
    },
    {
        "name": "authors",
        "type": "string",
        "stored": True,
        "indexed": False,
        "required": True,
        "multiValued": True,
    },
    {
        "name": "first_author",
        "type": "string",
        "stored": True,
        "indexed": False,
        "required": True,
        "multiValued": True,
    },
    {
        "name": "title",
        "type": "string",
        "stored": True,
        "indexed": False,
        "required": True,
        "multiValued": True,
    },
    {
        "name": "journal",
        "type": "string",
        "stored": True,
        "indexed": False,
        "required": True,
        "multiValued": True,
    },
    {
        "name": "year",
        "type": "string",
        "stored": True,
        "indexed": False,
        "required": True,
        "multiValued": True,
    },
    {
        "name": "volume",
        "type": "string",
        "stored": True,
        "indexed": False,
        "required": True,
        "multiValued": True,
    },
    {
        "name": "page",
        "type": "string",
        "stored": True,
        "indexed": False,
        "required": True,
        "multiValued": True,
    },
]

TOKEN_FIELDS = [
    {
        "name": "authors_tokens",
        "type": "string",
        "stored": False,
        "indexed": True,
        "required": True,
        "multiValued": True,
    },
    {
        "name": "first_author_tokens",
        "type": "string",
        "stored": False,
        "indexed": True,
        "required": True,
        "multiValued": True,
    },
    {
        "name": "title_tokens",
        "type": "string",
        "stored": False,
        "indexed": True,
        "required": True,
        "multiValued": True,
    },
    {
        "name": "journal_tokens",
        "type": "string",
        "stored": False,
        "indexed": True,
        "required": True,
        "multiValued": True,
    },
    {
        "name": "year_tokens",
        "type": "string",
        "stored": False,
        "indexed": True,
        "required": True,
        "multiValued": True,
    },
    {
        "name": "volume_tokens",
        "type": "string",
        "stored": False,
        "indexed": True,
        "required": True,
        "multiValued": True,
    },
    {
        "name": "page_tokens",
        "type": "string",
        "stored": False,
        "indexed": True,
        "required": True,
        "multiValued": True,
    },
]

# Schema API のURLを返す。
def get_schema_url(solr_base_url: str, core_name: str) -> str:
    return f"{solr_base_url.rstrip('/')}/{core_name}/schema"

# 今回必要な全フィールド定義を返す。
def get_expected_fields() -> List[Dict[str, object]]:
    return SAVED_FIELDS + TOKEN_FIELDS

# 引数を指定して、Schema APIにリクエストを送る共通関数。レスポンスを Jsonとして返す。
def _request_json(url: str, method: str = "GET", payload: Optional[Dict] = None) -> Dict:
    """Schema API に JSON リクエストを送る。"""
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = request.Request(url=url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Schema API request failed: {exc.code} {body}") from exc

# 既存のフィールド定義を name -> field の辞書で返す。
def get_existing_fields(solr_base_url: str, core_name: str) -> Dict[str, Dict]:
    schema_url = get_schema_url(solr_base_url, core_name)
    query = parse.urlencode({"showDefaults": "true"})
    result = _request_json(f"{schema_url}/fields?{query}")
    fields = result.get("fields", [])
    return {field["name"]: field for field in fields}

# まだ作成されていないフィールド定義だけを返す。
def get_missing_fields(solr_base_url: str, core_name: str) -> List[Dict[str, object]]:
    existing_fields = get_existing_fields(solr_base_url, core_name)
    missing_fields = []
    for field in get_expected_fields():
        if field["name"] not in existing_fields:
            missing_fields.append(field)
    return missing_fields

# 不足しているフィールドだけを add-field で追加する。
def add_fields(solr_base_url: str, core_name: str) -> Dict:
    missing_fields = get_missing_fields(solr_base_url, core_name)
    if not missing_fields:
        return {"added_fields": [], "message": "No missing fields."}

    schema_url = get_schema_url(solr_base_url, core_name)
    payload = {"add-field": missing_fields}
    _request_json(schema_url, method="POST", payload=payload)
    return {"added_fields": [field["name"] for field in missing_fields]}

# 必要フィールドが揃うように schema を確認・追加する。
# 最後に元のフィールド数、最終的なフィールド数、追加されたフィールド名のリストを返す。
def ensure_schema(solr_base_url: str, core_name: str) -> Dict:
    before_fields = get_existing_fields(solr_base_url, core_name)
    add_result = add_fields(solr_base_url, core_name)
    after_fields = get_existing_fields(solr_base_url, core_name)

    return {
        "existing_field_count_before": len(before_fields),
        "existing_field_count_after": len(after_fields),
        "expected_fields": [field["name"] for field in get_expected_fields()],
        "added_fields": add_result.get("added_fields", []),
    }
