# Storage & Index Plan（Solr登録設計）

## 概要

本システムでは以下の役割分担を行う。

* トークン生成：アプリ側
* インデックス構築：Solr

また、トークンは**フィールド単位で生成・管理する方式**を採用する。

Solrへの接続、スキーマ設定、MongoDB `jalc.restapi` からの抽出、バッチ登録の基本的な流れは `../jalc/jalc-to-solr.ipynb` を参考にする。
ただし、既存ノートブックのコードをそのまま流用するのではなく、本リポジトリで独自実装する。
登録フィールド、トークン生成、検索対象フィールドは本実装の方針に合わせて定義する。

---

## 登録対象フィールド

論文に基づき、以下の書誌要素を使用：

```text
F = {authors, title, journal, year, volume, page}
```

後続のCC計算で使用するため、`first_author` も保存・トークン化する。
ただし今回の検索では、論文の候補検索対象 `F` に合わせて `first_author_tokens` は検索対象から除外する。

MongoDB `jalc.restapi` から取得する対象は、論文の対象に合わせて `content_type = "JA"` の文献に限定する。
抽出処理は `jalc-to-solr.ipynb` の考え方を参考にし、JaLC文書の `creator_list`, `title_list`, `journal_title_name_list`, `publication_date`, `volume`, `issue`, `first_page`, `last_page` から登録用データを構築する。

---

## Solr登録構成

### 1. Rawデータ（表示・再計算用）

| フィールド       | stored | indexed |
| ----------- | ------ | ------- |
| authors_raw | true   | false   |
| first_author_raw | true | false |
| title_raw   | true   | false   |
| journal_raw | true   | false   |
| year_raw    | true   | false   |
| volume_raw  | true   | false   |
| page_raw    | true   | false   |

rawフィールドは、著者名・論文タイトル・雑誌名などの複数表記を保持できるよう配列として登録する。
発行年・巻号・ページも、Solr上の型を揃えるため配列として扱う。
`volume_raw` は論文の「巻・号フィールド」に対応させるため、MongoDB上の `volume` と `issue` を同じ配列内に分けて保持する。

---

### 2. 検索用トークン（フィールド別）

| フィールド          | stored | indexed |
| -------------- | ------ | ------- |
| authors_tokens | false  | true    |
| first_author_tokens | false | true |
| title_tokens   | false  | true    |
| journal_tokens | false  | true    |
| year_tokens    | false  | true    |
| volume_tokens  | false  | true    |
| page_tokens    | false  | true    |

検索用トークンはインデックス専用とし、ストレージ容量を抑えるため `stored=false` とする。
トークン内容の確認は、Solrから取得するのではなく、登録処理時のログやローカルの tokenize() 実行結果で行う。

---

## トークン生成

各rawフィールドの配列要素ごとにアプリ側で tokenize() を適用し、同一フィールド内のトークン集合としてまとめる。

```python
authors_tokens = tokenize_values(authors_raw)
first_author_tokens = tokenize_values(first_author_raw)
title_tokens   = tokenize_values(title_raw)
journal_tokens = tokenize_values(journal_raw)
year_tokens    = tokenize_values(year_raw)
volume_tokens  = tokenize_values(volume_raw)
page_tokens    = tokenize_values(page_raw)
```

```python
def tokenize_values(values):
    tokens = []
    for value in values:
        tokens.extend(tokenize(value))
    return list(set(tokens))
```

---

## 実装分割方針

実装時は、処理を以下のように関数・モジュールへ分ける。

* JaLC文書が必要フィールドを持つか判定する処理
* 著者・筆頭著者・タイトル・雑誌名・年・巻号・ページを抽出する処理
* rawフィールド配列からtokensフィールドを生成する処理
* Solrスキーマを設定する処理
* MongoDBからSolrへバッチ登録する処理

既存 `jalc-to-solr.ipynb` のヘルパー関数は参考にするが、実装は本リポジトリ内で新しく行い、ノートブック依存にしない。

---

## Solr登録データ例

```json
{
  "id": "paper_001",

  "authors_raw": ["山田 太郎", "Yamada Taro"],
  "first_author_raw": ["山田 太郎", "Yamada Taro"],
  "title_raw": ["全文検索に基づく手法", "Search-Based Reference Matching"],
  "journal_raw": ["情報処理学会", "IPSJ Journal"],
  "year_raw": ["2024"],
  "volume_raw": ["12", "3"],
  "page_raw": ["1-10"],

  "authors_tokens": ["山田", "田太", "太郎", "Yamada", "Taro", "Yamada Taro"],
  "first_author_tokens": ["山田", "田太", "太郎", "Yamada", "Taro", "Yamada Taro"],
  "title_tokens": ["全文", "文検", "検索", "索に", "に基", "基づ", "づく", "く手", "手法", "Search", "Based", "Reference", "Matching", "Search Based", "Based Reference", "Reference Matching"],
  "journal_tokens": ["情報", "報処", "処理", "理学", "学会", "IPSJ", "Journal", "IPSJ Journal"],
  "year_tokens": ["2024"],
  "volume_tokens": ["12", "3"],
  "page_tokens": ["1", "10"]
}
```

---

## インデックスの役割

* 各フィールドごとに倒立インデックスを構築
* フィールド単位のトークン集合 Cf を保持

---

## 検索フロー

### 1. クエリ処理

```python
query_tokens = tokenize(reference_string)
```

---

### 2. Solr検索

複数フィールドを対象に検索を行う。
今回の検索では `first_author_tokens` は使わず、`authors_tokens` を使用する。

論理的には：

```text
C = ⋃ Cf
```

に対する検索を行う。

実装上は複数フィールド検索（edismax等）で実現する。

---

### 3. 上位K件取得

* BM25スコアによりランキング
* 上位K件を取得（実装用）
* 論文準拠では第一位候補を評価対象とする

---

## 再ランキング

取得した候補文献に対して：

1. rawデータを取得
2. 各フィールドを再トークン化
3. RC / CC / MC を計算

---

## 再ランキングで使用するフィールド

* authors_raw
* first_author_raw
* title_raw
* journal_raw
* year_raw
* volume_raw
* page_raw

※ CC計算時は first_author_raw を使用する

---

## 設計の特徴

### 1. フィールド構造の保持

* トークンをフィールドごとに管理
* 論文の Cf 構造をそのまま再現可能

---

### 2. 論文再現性

* トークン生成を完全に制御
* RC / CC / MC の計算と整合性が取れる

---

### 3. デバッグ性

* 登録処理時のログで各フィールド単位のトークンを確認可能
* 検索と評価のズレを追跡しやすい

---

## 注意点

### 1. トークナイザの一致

インデックス作成時・検索時・再ランキング時でトークナイザは完全一致させる

---

### 2. トークンの扱い

* トークンは集合として扱う
* 重複は除去する
* rawフィールドの配列要素ごとに生成したトークンを、同じフィールドのトークン配列にまとめる
* volume_raw は MongoDBの volume と issue を同じ配列内に分けて保持し、volume_tokens も同じフィールドにまとめる

---

### 3. 数字・英語の扱い

* 単語単位でトークン化
* 隣接2-gramを含める

---

## 結論

* Solrは「候補取得エンジン」
* アプリは「意味評価エンジン」

さらに、

👉 **フィールド単位トークン + 統合集合検索（C = ⋃ Cf）**

という構成で論文を忠実に再現する
