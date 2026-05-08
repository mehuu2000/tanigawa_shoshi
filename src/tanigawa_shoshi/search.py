"""参考文献文字列に対する Solr 検索処理。"""

import re
from typing import Dict, List, Optional

import pysolr

from .config import SEARCH_FIELD, SOLR_BASE_URL, SOLR_CORE
from .solr_indexer import get_solr_client
from .tokenizer import tokenize_values

DEFAULT_ROWS = 10   # rows：検索結果の最大件数(上位N件)を指定する

REFERENCE_SPLIT_PATTERN = re.compile(r"[,，、:：\[\]［］\(\)（）]+")


# 参考文献文字列を区切り記号で疑似フィールド配列に分割する。
def split_reference_values(reference_text: str) -> List[str]:
    if not reference_text:
        return []
    return [value.strip() for value in REFERENCE_SPLIT_PATTERN.split(reference_text) if value.strip()]


# 参考文献文字列をトークン化し、検索用 token 配列を返す。
def build_query_tokens(reference_text: str) -> List[str]:
    return tokenize_values(split_reference_values(reference_text))


# token 配列を Solr の q パラメータへ渡す文字列に変換する。
def escape_query_token(token: str) -> str:
    if any(ch.isspace() for ch in token):
        return f'"{token}"'
    return token


def build_query_string(tokens: List[str]) -> str:
    return " ".join(escape_query_token(token) for token in tokens)


# 検索対象の統合トークンフィールドを返す。
def build_search_field(field: Optional[str] = None) -> str:
    return field or SEARCH_FIELD


# Solr 検索パラメータを組み立てる。
def build_search_params(
    reference_text: str,
    rows: int = DEFAULT_ROWS,
    field: Optional[str] = None,
) -> Dict[str, object]:
    tokens = build_query_tokens(reference_text)
    query_string = build_query_string(tokens)

    # all_tokens 単一フィールドに対して、統合トークン集合 C = ⋃Cf の候補検索を行う。
    # "fl": "*,score"：検索結果に全てのフィールドとスコアを返す
    return {
        "q": query_string,
        "df": build_search_field(field),
        "rows": rows,
        "fl": "*,score",
    }


# Solr に検索を投げ、候補文献を取得する。
def search_reference(
    reference_text: str,
    rows: int = DEFAULT_ROWS,
    field: Optional[str] = None,
    solr: Optional[pysolr.Solr] = None,
    solr_base_url: str = SOLR_BASE_URL,
    core_name: str = SOLR_CORE,
):
    tokens = build_query_tokens(reference_text)
    params = build_search_params(reference_text, rows=rows, field=field)

    if not tokens:
        return {
            "tokens": [],
            "params": params,
            "results": [],
        }

    search_client = solr or get_solr_client(solr_base_url, core_name)
    query_string = params["q"]
    search_kwargs = dict(params)
    del search_kwargs["q"]
    results = search_client.search(query_string, **search_kwargs)

    return {
        "tokens": tokens,
        "params": params,
        "results": results,
    }
