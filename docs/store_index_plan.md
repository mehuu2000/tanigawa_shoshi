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
ただし今回の検索では、論文の候補検索対象 `F` に合わせて `first_author` は `all_tokens` の生成元から除外する。
また、`doi` は `jalc-to-solr.ipynb` と同様に保持し、必須項目として扱う。
`id` はアプリ側では指定せず、Solr 側の自動生成設定に任せる。

MongoDB `jalc.restapi` から取得する対象は、論文の対象に合わせて `content_type = "JA"` の文献に限定する。
抽出処理は `jalc-to-solr.ipynb` の考え方を参考にし、JaLC文書の `creator_list`, `title_list`, `journal_title_name_list`, `publication_date`, `volume`, `issue`, `first_page`, `last_page` から登録用データを構築する。

---

## Solr登録構成

### 1. 保存データ（表示・再計算用）

| フィールド       | stored | indexed | docValues |
| ----------- | ------ | ------- | --------- |
| doi | true | false | false |
| authors | true   | false   | false |
| first_author | true | false | false |
| title   | true   | false   | false |
| authors_variations | true | false | false |
| first_author_variations | true | false | false |
| title_variations | true | false | false |
| journal | true   | false   | false |
| year    | true   | false   | false |
| volume  | true   | false   | false |
| page    | true   | false   | false |

`doi` は `jalc-to-solr.ipynb` に合わせて単一値で保持し、存在しない文書は Solr 登録対象から除外する。
`authors`, `first_author`, `title` は検索とトークン化の基準になる基本表記を保持する。
`authors_variations`, `first_author_variations`, `title_variations` は、従来の複数表記を保持する補助フィールドとして登録する。
それ以外の保存フィールドは、雑誌名などの複数表記を保持できるよう配列として登録する。
発行年・巻号・ページも、Solr上の型を揃えるため配列として扱う。
保存フィールド名は論文の書誌要素名に合わせ、`*_raw` とはしない。
`volume` は論文の「巻・号フィールド」に対応させるため、MongoDB上の `volume` と `issue` を同じ配列内に分けて保持する。

---

### 2. 検索用統合トークン

| フィールド | stored | indexed | docValues |
| --------- | ------ | ------- | --------- |
| all_tokens | false | true | false |

`all_tokens` は候補検索用の統合トークン集合 `C = ⋃Cf` として使う。
`first_author` は CC 計算用なので、`all_tokens` の生成元には含めない。
旧スキーマで作成したフィールド別 `*_tokens` が既存 core に残っている場合、現行の登録文書では値を送らないため、その core は作り直すか旧 field を削除してから使う。

---

## トークン生成

各保存フィールドの配列要素ごとにアプリ側で tokenize() を適用し、同一フィールド内のトークン集合としてまとめる。
ただし、`authors_variations`, `first_author_variations`, `title_variations` はトークン化せず、保存専用とする。

```python
all_tokens     = unique_preserve_order(
    tokenize_values(authors)
    + tokenize_values(title)
    + tokenize_values(journal)
    + tokenize_values(year)
    + tokenize_values(volume)
    + tokenize_values(page)
)
```

```python
def tokenize_values(values):
    tokens = []
    for value in values:
        tokens.extend(tokenize(value))
    return unique_preserve_order(tokens)
```

DOI が存在しない文書は、他の必須項目検査やトークン生成に進む前に Solr 登録対象から除外し、DOI 不足スキップ件数として集計する。
また、登録対象として採用済みの DOI はアプリ側の `set` で保持し、同じ DOI を持つ後続文書は Solr 登録対象から除外して DOI 重複スキップ件数として集計する。

raw データ上は必須項目が存在していても、特殊文字のみのタイトルのように tokenize() の結果が空集合になる文書がある。
このような文書は `all_tokens` の required 制約を満たせないため、Solr 登録対象から除外する。
除外時は `log/` 配下の時刻付きログファイルへ、tokenize 後に必須トークンが空になった文書の MongoDB `_id`・対象フィールド・元の値・理由を記録する。

---

## 実装分割方針

実装時は、処理を以下のように関数・モジュールへ分ける。

* JaLC文書が必要フィールドを持つか判定する処理
* 著者・筆頭著者・タイトル・雑誌名・年・巻号・ページを抽出する処理
* 保存フィールド配列から `all_tokens` を生成する処理
* Solrスキーマを設定する処理
* MongoDBからSolrへバッチ登録する処理

既存 `jalc-to-solr.ipynb` のヘルパー関数は参考にするが、実装は本リポジトリ内で新しく行い、ノートブック依存にしない。

---

## Solr登録データ例

```json
{
  "authors": ["山田 太郎", "Yamada Taro"],
  "first_author": ["山田 太郎", "Yamada Taro"],
  "authors_variations": ["山田太郎", "山田 太郎", "Yamada Taro", "Yamada", "Taro"],
  "first_author_variations": ["山田太郎", "山田 太郎", "山田", "Yamada Taro", "Yamada", "Taro"],
  "doi": "10.0000/example",
  "title": ["全文検索に基づく手法", "Search-Based Reference Matching"],
  "title_variations": ["全文検索に基づく手法", "Search-Based Reference Matching", "全文検索に基づく手法 | 副題例"],
  "journal": ["情報処理学会", "IPSJ Journal"],
  "year": ["2024"],
  "volume": ["12", "3"],
  "page": ["1-10"],

  "all_tokens": ["山田", "田太", "太郎", "Yamada", "Taro", "Yamada Taro", "全文", "文検", "検索", "索に", "に基", "基づ", "づく", "く手", "手法", "Search", "Based", "Reference", "Matching", "Search Based", "Based Reference", "Reference Matching", "情報", "報処", "処理", "理学", "学会", "IPSJ", "Journal", "IPSJ Journal", "2024", "12", "3", "1", "10", "1 10"]
}
```

---

## インデックスの役割

* `all_tokens` に対して倒立インデックスを構築
* フィールド単位のトークン集合 Cf は後続フェーズで保存フィールドから再トークン化して作る

---

## 検索フロー

### 1. クエリ処理

```python
query_tokens = tokenize(reference_string)
```

---

### 2. Solr検索

検索は `all_tokens` 単一フィールドを対象に行う。
`all_tokens` は `authors`, `title`, `journal`, `year`, `volume`, `page` から生成したトークンを統合した `C = ⋃Cf` に対応する。
`first_author` は検索対象には含めず、後続の CC 計算で使用する。

---

### 3. 上位K件取得

* BM25スコアによりランキング
* 上位K件を取得（実装用）
* 第一位候補の評価は後続フェーズで扱う

---

## 後続フェーズの再ランキング

今回の実装ではRC / CC / MCは計算しない。
Solr登録では、後続フェーズで計算できるよう保存フィールドを保持する。

取得した候補文献に対して：

1. 保存データを取得
2. 各フィールドを再トークン化
3. RC / CC / MC を計算

---

## 後続フェーズの再ランキングで使用するフィールド

* authors
* first_author
* title
* journal
* year
* volume
* page

※ CC計算時は first_author を使用する

---

## 設計の特徴

### 1. フィールド構造の保持

* トークンをフィールドごとに管理
* 論文の Cf 構造をそのまま再現可能

---

### 2. 論文再現性

* トークン生成を完全に制御
* 後続フェーズのRC / CC / MC計算と整合性が取れる

---

### 3. デバッグ性

* 登録処理時のログで各フィールド単位のトークンを確認可能
* 検索と評価のズレを追跡しやすい

---

## 注意点

### 1. トークナイザの一致

インデックス作成時・検索時・後続フェーズの再ランキング時でトークナイザは完全一致させる

---

### 2. トークンの扱い

* トークンは集合として扱う
* 重複は除去する
* 保存フィールドの配列要素ごとに生成したトークンを、同じフィールドのトークン配列にまとめる
* volume は MongoDBの volume と issue を同じ配列内に分けて保持し、all_tokens 生成時も同じフィールドとしてまとめる

---

### 3. 数字・英語の扱い

* 単語単位でトークン化
* 隣接2-gramを含める

---

## 結論

* Solrは「候補取得エンジン」
* 後続フェーズではアプリを「意味評価エンジン」として扱う

さらに、

👉 **フィールド単位トークン + 統合集合検索（C = ⋃ Cf）**

という構成で論文を忠実に再現する
