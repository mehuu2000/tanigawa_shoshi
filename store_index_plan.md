# Storage & Index Plan（Solr登録設計）

## 概要

本システムでは、

* トークン生成：アプリ側
* インデックス構築：Solr

という役割分担を行う。

---

## 登録対象フィールド

論文に基づき、以下の書誌要素を使用：

```
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

### 2. 検索用トークン

| フィールド      | stored | indexed |
| ---------- | ------ | ------- |
| all_tokens | false  | true    |

---

## all_tokens の生成

```python
all_tokens = set(
    authors_tokens +
    title_tokens +
    journal_tokens +
    year_tokens +
    volume_tokens +
    page_tokens
)
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

  "all_tokens": [
    "全文", "文検", "検索",
    "山田", "田太", "太郎",
    "情報", "報処", "処理",
    "2024", "12", "1", "10"
  ]
}
```

---

## インデックスの役割

* `all_tokens` を使って倒立インデックスを構築
* 初期検索はこのフィールドのみ使用

---

## 検索フロー

### 1. クエリ処理

```python
query_tokens = tokenize(reference_string)
```

---

### 2. Solr検索

* 対象：`all_tokens`
* 条件：OR検索（部分一致）

---

### 3. 上位K件取得

BM25スコアで候補取得

---

### 4. 再ランキング

取得した候補に対して：

1. rawデータを取得
2. 各フィールドを再トークン化
3. RC / CC / MC を計算

---

## 再ランキングで使うデータ

Solrから取得：

* authors_raw
* title_raw
* journal_raw
* year_raw
* volume_raw
* page_raw

---

## 設計のメリット

### 1. ストレージ削減

* field別 tokens を保存しない

### 2. 柔軟性

* トークナイザ変更が容易

### 3. 論文再現性

* RC / CC / MC を正しく計算可能

---

## 注意点

* トークナイザは検索時と再ランキング時で完全一致させる
* `all_tokens` は重複排除して登録する
* 数字・英語は単語単位で扱う

---

## 結論

* Solrは「候補取得エンジン」
* アプリは「意味評価エンジン」

という構成で分離する
