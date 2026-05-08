"""JaLC文書からSolr登録用データを抽出する処理。"""

import re
from itertools import permutations
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .tokenizer import is_japanese_char, tokenize_values


ENGLISH_NAME_SPLIT_PATTERN = re.compile(r"[,\.\s\-\(\)]+")

TOKEN_SOURCE_FIELDS = {
    "authors_tokens": "authors",
    "first_author_tokens": "first_author",
    "title_tokens": "title",
    "journal_tokens": "journal",
    "year_tokens": "year",
    "volume_tokens": "volume",
    "page_tokens": "page",
}

# 重複を削除しつつ、順序を保ったままリストを返す関数。空文字や None は無視する。また、余分な空白も削除する。
# jalc-to-solr.ipynbのlist(set(...))を拡張したもの
def _unique_preserve_order(values: Iterable[Optional[str]]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        if not value:
            continue
        normalized = " ".join(str(value).split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result

# 文字列に日本語文字が含まれるかを判定する関数。名前の言語を判断するために使用する。
def _contains_japanese(text: str) -> bool:
    return any(is_japanese_char(ch) for ch in text)

# 名前の言語を判断する関数。lang フィールドが "ja" の場合は日本語表記とみなす。それ以外の場合は、姓や名に日本語文字が含まれているかで判断する。
def _is_japanese_name(last_name: str, first_name: str, lang: str) -> bool:
    if lang == "ja":
        return True
    return _contains_japanese(last_name) or _contains_japanese(first_name)


# 姓と名から1つの氏名表記を作る関数。日本語表記の場合は姓と名を連結し、それ以外の場合はスペースで区切る。
def _build_full_name(last_name: str, first_name: str, is_japanese: bool) -> str:
    if not last_name:
        return first_name
    if not first_name:
        return last_name
    if is_japanese:
        return last_name + first_name
    return f"{last_name} {first_name}"

# 1つの names 要素から利用可能な氏名バリエーションを作る関数。日本語表記の場合は、フルネームと姓＋名の両方を生成する。それ以外の場合は、フルネーム、スペースで区切った名前、名の分割、イニシャルの組み合わせなどを生成する。
def _build_name_variants(name: Dict[str, Any]) -> List[str]:
    last_name = (name.get("last_name") or "").strip()
    first_name = (name.get("first_name") or "").strip()
    lang = (name.get("lang") or "").strip().lower()
    if not last_name and not first_name:
        return []

    is_japanese = _is_japanese_name(last_name, first_name, lang)
    variants = []

    full_name = _build_full_name(last_name, first_name, is_japanese)
    variants.append(full_name)

    if is_japanese and last_name and first_name:
        variants.append(f"{last_name} {first_name}")

    if not is_japanese and first_name:
        split_names = [part for part in ENGLISH_NAME_SPLIT_PATTERN.split(first_name) if part]
        initials = [part[0].upper() for part in split_names if part and re.search(r"[A-Za-z]", part[0])]

        if split_names:
            variants.extend(split_names)

        if last_name:
            variants.append(last_name)

        for length in range(1, 3):
            for perm in permutations(initials, length):
                if last_name:
                    variants.append(f"{last_name} {''.join(perm)}")
                variants.append("".join(perm))

    return _unique_preserve_order(variants)

# 1つの names 要素から、バリエーションを増やさない基本の氏名表記を1つ作る関数。英語は "姓 名"、日本語は "姓 名" を返す。
def _build_basic_name(name: Dict[str, Any]) -> Optional[str]:
    last_name = (name.get("last_name") or "").strip()
    first_name = (name.get("first_name") or "").strip()

    if not last_name and not first_name:
        return None
    if not last_name:
        return first_name
    if not first_name:
        return last_name
    return f"{last_name} {first_name}"

# JaLC文書に必要な書誌要素が揃っているかをチェックする関数。タイトル、著者、出版年、雑誌名、巻号、ページ情報のいずれかが欠けている場合は False を返す。
def has_required_fields(doc: Dict[str, Any]) -> bool:
    return bool(
        doc.get("title_list")
        and doc.get("creator_list")
        and doc.get("publication_date")
        and doc.get("journal_title_name_list")
        and (doc.get("volume") or doc.get("issue"))
        and (doc.get("first_page") or doc.get("last_page"))
    )

# JaLC文書に DOI が存在し、空文字ではないことを確認する。
def has_required_doi(doc: Dict[str, Any]) -> bool:
    return bool(str(doc.get("doi") or "").strip())

# 1つの JaLC文書から著者フィールド用の氏名バリエーションを抽出する関数。creator_list の各 creator の names から氏名バリエーションを生成し、重複を削除して返す。
def extract_authors(doc: Dict[str, Any]) -> List[str]:
    authors = []
    for creator in doc.get("creator_list") or []:
        for name in creator.get("names") or []:
            authors.extend(_build_name_variants(name))
    return _unique_preserve_order(authors)

# 1つの JaLC文書から著者フィールド用の基本表記を抽出する関数。creator_list の各 creator の names から、バリエーションを増やさない氏名表記を生成して返す。
def extract_authors_basic(doc: Dict[str, Any]) -> List[str]:
    authors = []
    for creator in doc.get("creator_list") or []:
        for name in creator.get("names") or []:
            basic_name = _build_basic_name(name)
            if basic_name:
                authors.append(basic_name)
    return _unique_preserve_order(authors)

# 1つの JaLC文書から筆頭著者フィールド用の氏名バリエーションを抽出する関数。creator_list の最初の creator の names から氏名バリエーションを生成し、重複を削除して返す。
def extract_first_author(doc: Dict[str, Any]) -> List[str]:
    creator_list = doc.get("creator_list") or []
    if not creator_list:
        return []

    first_creator = creator_list[0]
    first_author = []
    for name in first_creator.get("names") or []:
        variants = _build_name_variants(name)
        first_author.extend(variants)

        last_name = (name.get("last_name") or "").strip()
        first_name = (name.get("first_name") or "").strip()
        lang = (name.get("lang") or "").strip().lower()
        is_japanese = _is_japanese_name(last_name, first_name, lang)

        if last_name:
            first_author.append(last_name)
        elif first_name:
            first_author.append(first_name)

        if is_japanese and last_name and first_name:
            first_author.append(f"{last_name} {first_name}")

    return _unique_preserve_order(first_author)

# 1つの JaLC文書から筆頭著者フィールド用の基本表記を抽出する関数。creator_list の最初の creator の names から、バリエーションを増やさない氏名表記を生成して返す。
def extract_first_author_basic(doc: Dict[str, Any]) -> List[str]:
    creator_list = doc.get("creator_list") or []
    if not creator_list:
        return []

    first_creator = creator_list[0]
    first_author = []
    for name in first_creator.get("names") or []:
        basic_name = _build_basic_name(name)
        if basic_name:
            first_author.append(basic_name)
    return _unique_preserve_order(first_author)

# 1つの JaLC文書からタイトルフィールド用のタイトルと副題のバリエーションを抽出する関数。title_list の各 title と subtitle を組み合わせてタイトルバリエーションを生成し、重複を削除して返す。
def extract_titles(doc: Dict[str, Any]) -> List[str]:
    titles = []
    for title_data in doc.get("title_list") or []:
        title = title_data.get("title")
        subtitle = title_data.get("subtitle")
        if title:
            titles.append(title)
            if subtitle:
                titles.append(f"{title} | {subtitle}")
    return _unique_preserve_order(titles)

# 1つの JaLC文書からタイトルフィールド用の基本表記を抽出する関数。title_list の title だけを使い、subtitle は使わない。
def extract_titles_basic(doc: Dict[str, Any]) -> List[str]:
    titles = []
    for title_data in doc.get("title_list") or []:
        title = title_data.get("title")
        if title:
            titles.append(title)
    return _unique_preserve_order(titles)

# 1つの JaLC文書から雑誌名フィールド用の雑誌名のバリエーションを抽出する関数。journal_title_name_list の各 journal_title_name を抽出し、重複を削除して返す。
def extract_journals(doc: Dict[str, Any]) -> List[str]:
    journals = []
    for journal_data in doc.get("journal_title_name_list") or []:
        journal_name = journal_data.get("journal_title_name")
        if journal_name:
            journals.append(journal_name.strip())
    return _unique_preserve_order(journals)

# 1つの JaLC文書から出版年フィールド用の4桁文字列を抽出する関数。publication_date の各値から4桁の年を抽出し、重複を削除して返す。
def extract_year(doc: Dict[str, Any]) -> List[str]:
    years = []
    for value in (doc.get("publication_date") or {}).values():
        if value:
            years.append(str(value)[:4])
    return _unique_preserve_order(years)

# 1つの JaLC文書から巻号フィールド用の値を抽出する関数。volume と issue を同じ配列に分けて入れ、重複を削除して返す。
def extract_volume(doc: Dict[str, Any]) -> List[str]:
    values = [doc.get("volume"), doc.get("issue")]
    return _unique_preserve_order(values)

# 1つの JaLC文書からページフィールド用のページ範囲を抽出する関数。first_page と last_page の値からページ範囲を生成し、重複を削除して返す。
def extract_page(doc: Dict[str, Any]) -> List[str]:
    first_page = doc.get("first_page")
    last_page = doc.get("last_page")

    if not first_page and not last_page:
        return []
    if first_page and last_page:
        return [f"{first_page}-{last_page}"]
    if first_page:
        return [str(first_page)]
    return [str(last_page)]

# 1つの JaLC文書から DOI を抽出する関数。doi フィールドの値をそのまま文字列として返す。doi フィールドが存在しない場合は None を返す。
def extract_doi(doc: Dict[str, Any]) -> Optional[str]:
    doi = str(doc.get("doi") or "").strip()
    if not doi:
        return None
    return doi

# トークン化後に必須フィールドが空になっていないかをチェックする関数。空になっているフィールドがある場合はその理由などをissueとして返す。
def get_required_token_field_issues(solr_document: Dict[str, Any]) -> List[Dict[str, Any]]:
    issues = []
    for token_field_name, source_field_name in TOKEN_SOURCE_FIELDS.items():
        if not solr_document.get(token_field_name):
            issues.append(
                {
                    "reason_code": "required_token_field_empty",
                    "field_name": token_field_name,
                    "value": solr_document.get(source_field_name),
                    "reason": f"tokenize 後に必須フィールド {token_field_name} が空になったため登録しない",
                }
            )
    return issues

# 1つの JaLC文書から Solr 登録用の dict を生成する関数。必要な書誌要素が揃っていない場合は None を返す。それ以外の場合は、基本表記の著者・筆頭著者・タイトル、各 variations フィールド、雑誌名、出版年、巻号、ページ情報、DOI とそれぞれのトークン化されたバージョンを含む dict を返す。また、トークン化後に必須フィールドが空になっている場合は None を返し、その理由などを issue として返す。
def build_solr_document_with_issues(doc: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    if not has_required_doi(doc):
        return None, []

    if not has_required_fields(doc):
        return None, []

    authors = extract_authors_basic(doc)
    first_author = extract_first_author_basic(doc)
    title = extract_titles_basic(doc)
    journal = extract_journals(doc)
    year = extract_year(doc)
    volume = extract_volume(doc)
    page = extract_page(doc)
    doi = extract_doi(doc)
    authors_variations = extract_authors(doc)
    first_author_variations = extract_first_author(doc)
    title_variations = extract_titles(doc)

    if not all([authors, first_author, title, journal, year, volume, page]):
        return None, []

    solr_document = {
        "doi": doi,
        "authors": authors,
        "first_author": first_author,
        "title": title,
        "authors_variations": authors_variations,
        "first_author_variations": first_author_variations,
        "title_variations": title_variations,
        "journal": journal,
        "year": year,
        "volume": volume,
        "page": page,
        "authors_tokens": tokenize_values(authors),
        "first_author_tokens": tokenize_values(first_author),
        "title_tokens": tokenize_values(title),
        "journal_tokens": tokenize_values(journal),
        "year_tokens": tokenize_values(year),
        "volume_tokens": tokenize_values(volume),
        "page_tokens": tokenize_values(page),
    }

    token_issues = get_required_token_field_issues(solr_document)
    if token_issues:
        return None, token_issues

    return solr_document, []

# 1つの JaLC文書から Solr 登録用の dict を生成する関数。必要な書誌要素が揃っていない場合は None を返す。それ以外の場合は、基本表記の著者・筆頭著者・タイトル、各 variations フィールド、雑誌名、出版年、巻号、ページ情報、DOI とそれぞれのトークン化されたバージョンを含む dict を返す。
# こちらは確認用関数で、token_issues は返さず、トークン化後に必須フィールドが空になっている場合は None を返す。
def build_solr_document(doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    solr_document, _ = build_solr_document_with_issues(doc)
    return solr_document
