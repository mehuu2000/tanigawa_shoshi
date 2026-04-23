# Query Plan（検索処理設計）

## 概要

検索時（参考文献文字列入力）も、インデックス作成時と**完全に同一のトークン化ルール**を適用する。

---

## トークン生成ルール

* 日本語：文字2-gram
* 日本語以外（英語・数字など）：単語1-gram
* 日本語以外が連続する場合：単語2-gramを追加

---

## 入力例

```text
JaLC Reference Coverage 2026年創業
```

---

## トークン生成結果

```python
[
  "JaLC",
  "Reference",
  "Coverage",
  "2026",
  "JaLC Reference",
  "Reference Coverage",
  "Coverage 2026",
  "年創",
  "創業"
]
```

---

## トークンの扱い

* トークンは集合として扱う
* 順序は考慮しない
* 重複は除去する

---

## 検索対象フィールド

```text
F = {authors_tokens, title_tokens, journal_tokens, year_tokens, volume_tokens, page_tokens}
```

`first_author_tokens` はSolrに登録するが、今回の検索対象には含めない。
後続のCC計算で使用するためのフィールドとして扱う。

---

## 検索の考え方（重要）

論文では

```text
C = ⋃ Cf
```

として、全フィールドのトークン集合を検索対象としている。

本実装では、

👉 **複数フィールドを同時に検索することで C を再現する**

---

## クエリ生成

```python
tokens = tokenize(reference_string)
query_str = " ".join(tokens)

params = {
    "q": query_str,
    "defType": "edismax",
    "qf": "authors_tokens title_tokens journal_tokens year_tokens volume_tokens page_tokens",
    "mm": "2"
}
```

---

## 検索の意味

このクエリは以下を意味する：

```text
tokens ∈ (authors_tokens ∪ title_tokens ∪ journal_tokens ∪ ...)
```

つまり、

👉 **全フィールドの統合集合に対する検索**

---

## minimum match（mm）

```text
mm = 2
```

意味：

* 少なくとも2トークン一致した文書のみヒット

---

## 検索結果

* BM25によりスコアリング
* 上位K件を取得
* 論文準拠では第一位候補を評価対象とする

---

## 全体フロー

```text
参考文献文字列
    ↓
トークン化（アプリ）
    ↓
トークン集合生成
    ↓
複数フィールド検索（C = ⋃ Cf）
    ↓
候補取得（BM25）
    ↓
再ランキング（RC / CC / MC）
```

---

## 注意（最重要）

インデックス生成時と検索時でトークン化ルールが異なる場合、検索精度は大きく低下する。

👉 必ず同一ロジックを使用すること

---

## 設計意図

### なぜ単語2-gramを入れるのか

* フレーズ一致を強化
* 誤マッチを減らす
* BM25のスコアを適切に反映

---

## 結論

* 検索は複数フィールドを統合して行う
* トークンはアプリ側で完全制御する
* Solrは候補取得に専念させる

👉 **検索は「集合C」、評価は「RC/CC」で行う**
