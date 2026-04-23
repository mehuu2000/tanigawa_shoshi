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

---

### 2. 検索用トークン（フィールド別）

| フィールド          | stored | indexed |
| -------------- | ------ | ------- |
| authors_tokens | false  | true    |
| title_tokens   | false  | true    |
| journal_tokens | false  | true    |
| year_tokens    | false  | true    |
| volume_tokens  | false  | true    |
| page_tokens    | false  | true    |

---

## トークン生成

各フィールドに対してアプリ側で tokenize() を適用する。

```python
authors_tokens = tokenize(authors_raw)
title_tokens   = tokenize(title_raw)
journal_tokens = tokenize(journal_raw)
year_tokens    = tokenize(year_raw)
volume_tokens  = tokenize(volume_raw)
page_tokens    = tokenize(page_raw)
```

---

## Solr登録データ例

```json
{
  "id": "paper_001",

  "authors_raw": "山田 太郎",
  "title_raw": "全文検索に基づく手法",
  "journal_raw": "情報処理学会",
  "year_raw": "2024",
  "volume_raw": "12",
  "page_raw": "1-10",

  "authors_tokens": ["山田", "田太", "太郎"],
  "title_tokens": ["全文", "文検", "検索", "索に", "に基", "基づ", "づく", "く手", "手法"],
  "journal_tokens": ["情報", "報処", "処理", "理学", "学会"],
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

---

## 注意点

### 1. トークナイザの一致

インデックス作成時・検索時・再ランキング時でトークナイザは完全一致させる

---

### 2. トークンの扱い

* トークンは集合として扱う
* 重複は除去する

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
