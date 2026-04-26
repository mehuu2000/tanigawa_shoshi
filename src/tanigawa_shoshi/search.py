"""参考文献文字列に対する Solr 検索処理。"""

from typing import Dict, List, Optional

import pysolr

from .config import SEARCH_FIELDS, SOLR_BASE_URL, SOLR_CORE
from .solr_indexer import get_solr_client
from .tokenizer import tokenize

DEFAULT_MM = "2"    # mm(Minimum Match)：検索クエリのtokenが最低N個以上一致した文書だけを対象とする
DEFAULT_ROWS = 10   # rows：検索結果の最大件数(上位N件)を指定する


# 参考文献文字列をトークン化し、検索用 token 配列を返す。
def build_query_tokens(reference_text: str) -> List[str]:
    return tokenize(reference_text)


# token 配列を Solr の q パラメータへ渡す文字列に変換する。
def build_query_string(tokens: List[str]) -> str:
    return " ".join(tokens)


# 検索対象フィールドを qf パラメータ文字列に変換する。
def build_qf(fields: Optional[List[str]] = None) -> str:
    target_fields = fields or SEARCH_FIELDS
    return " ".join(target_fields)


# Solr 検索パラメータを組み立てる。
def build_search_params(
    reference_text: str,
    rows: int = DEFAULT_ROWS,
    mm: str = DEFAULT_MM,
    fields: Optional[List[str]] = None,
) -> Dict[str, object]:
    tokens = build_query_tokens(reference_text)
    query_string = build_query_string(tokens)

    # edismax(Extended DisMax Query Parser)：検索対象を複数フィールドに指定できるクエリパーサー(qfで指定したフィールドに対して一括で検索をかけることができる)
    # "fl": "*,score"：検索結果に全てのフィールドとスコアを返す
    return {
        "q": query_string,
        "defType": "edismax",
        "qf": build_qf(fields),
        "mm": mm,
        "rows": rows,
        "fl": "*,score",
    }


# Solr に検索を投げ、候補文献を取得する。
def search_reference(
    reference_text: str,
    rows: int = DEFAULT_ROWS,
    mm: str = DEFAULT_MM,
    fields: Optional[List[str]] = None,
    solr: Optional[pysolr.Solr] = None,
    solr_base_url: str = SOLR_BASE_URL,
    core_name: str = SOLR_CORE,
):
    tokens = build_query_tokens(reference_text)
    params = build_search_params(reference_text, rows=rows, mm=mm, fields=fields)

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
