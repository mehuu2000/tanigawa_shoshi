# Storage & Index Plan（Solr登録設計）

## 概要

本システムでは以下の役割分担を行う。

* トークン生成：アプリ側
* インデックス構築：Solr

また、トークンは**フィールド単位で生成・管理する方式**を採用する。

---

## 登録対象フィールド

論文に基づき、以下の書誌要素を使用：

```text
F = {authors, title, journal, year, volume, page}
```

MongoDB `jalc.restapi` から取得する対象は、論文の対象に合わせて `content_type = "JA"` の文献に限定する。

---

## Solr登録構成

### 1. Rawデータ（表示・再計算用）

| フィールド       | stored | indexed |
| ----------- | ------ | ------- |
| authors_raw | true   | false   |
| title_raw   | true   | false   |
| journal_raw | true   | false   |
| year_raw    | true   | false   |
| volume_raw  | true   | false   |
| page_raw    | true   | false   |

rawフィールドは、著者名・論文タイトル・雑誌名などの複数表記を保持できるよう配列として登録する。
発行年・巻・ページも、Solr上の型を揃えるため配列として扱う。

---

### 2. 検索用トークン（フィールド別）

| フィールド          | stored | indexed |
| -------------- | ------ | ------- |
| authors_tokens | true   | true    |
| title_tokens   | true   | true    |
| journal_tokens | true   | true    |
| year_tokens    | true   | true    |
| volume_tokens  | true   | true    |
| page_tokens    | true   | true    |

※ 今回は勉強用の実装として、Solrに保存されたトークンを検索結果や管理画面から確認できるよう `stored=true` とする。
本番運用で容量を優先する場合は、rawフィールドから同一ロジックで再生成できるため `stored=false` も選択肢になる。

---

## トークン生成

各rawフィールドの配列要素ごとにアプリ側で tokenize() を適用し、同一フィールド内のトークン集合としてまとめる。

```python
authors_tokens = tokenize_values(authors_raw)
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

## Solr登録データ例

```json
{
  "id": "paper_001",

  "authors_raw": ["山田 太郎", "Yamada Taro"],
  "title_raw": ["全文検索に基づく手法", "Search-Based Reference Matching"],
  "journal_raw": ["情報処理学会", "IPSJ Journal"],
  "year_raw": ["2024"],
  "volume_raw": ["12"],
  "page_raw": ["1-10"],

  "authors_tokens": ["山田", "田太", "太郎", "Yamada", "Taro", "Yamada Taro"],
  "title_tokens": ["全文", "文検", "検索", "索に", "に基", "基づ", "づく", "く手", "手法", "Search", "Based", "Reference", "Matching", "Search Based", "Based Reference", "Reference Matching"],
  "journal_tokens": ["情報", "報処", "処理", "理学", "学会", "IPSJ", "Journal", "IPSJ Journal"],
  "year_tokens": ["2024"],
  "volume_tokens": ["12"],
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
* title_raw
* journal_raw
* year_raw
* volume_raw
* page_raw

※ CC計算時は authors_raw から first author を抽出して使用する

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

* 各フィールド単位でトークンを確認可能
* 検索と評価のズレを追跡しやすい
* 学習目的のため、検索用トークンもSolrに保存して目視確認できるようにする

---

## 注意点

### 1. トークナイザの一致

インデックス作成時・検索時・再ランキング時でトークナイザは完全一致させる

---

### 2. トークンの扱い

* トークンは集合として扱う
* 重複は除去する
* rawフィールドの配列要素ごとに生成したトークンを、同じフィールドのトークン配列にまとめる

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
