# Query Tokenization Plan（検索時トークン生成）

## 概要

検索時（参考文献文字列入力）も、インデックス作成時と**完全に同一のトークン化ルール**を適用する。

### トークン生成ルール

* 日本語：文字2-gram
* 日本語以外（英語・数字など）：単語1-gram
* 日本語以外が連続する場合：**単語2-gramを追加**

---

## 入力例

```text
JaLC Reference Coverage 2026年創業
```

---

## トークン生成結果（修正版）

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

## トークン構成ルール

### 1. 日本語部分

文字2-gramを生成

```text
年創業 → 年創, 創業
```

---

### 2. 日本語以外（英語・数字）

#### 単語1-gram

```text
JaLC, Reference, Coverage, 2026
```

---

#### 単語2-gram（隣接語のみ）

```text
JaLC Reference
Reference Coverage
Coverage 2026
```

---

### 単語2-gramの適用条件（重要）

日本語以外の単語が連続する区間に対して適用する。

例：

```text
JaLC Reference Coverage 2026
```

→ 4単語連続として扱う

生成される2-gram：

```text
JaLC Reference
Reference Coverage
Coverage 2026
```

---

## 疑似コード

```python
def non_japanese_ngrams(tokens):
    result = []

    # 単語1-gram
    result.extend(tokens)

    # 単語2-gram（隣接）
    for i in range(len(tokens) - 1):
        result.append(tokens[i] + " " + tokens[i + 1])

    return result
```

---

## トークンの扱い

* トークンは**集合（set）として扱う**
* 順序は考慮しない
* 重複は除去する

---

## 最終クエリ生成

```python
tokens = tokenize(reference_string)
query_str = " ".join(tokens)

params = {
    "q": f"all_tokens:({query_str})",
    "mm": "2"
}
```

---

## 注意（最重要）

インデックス生成時とクエリ生成時でトークン化ルールが異なる場合、
検索精度は大きく低下する。

👉 必ず同一ロジックを使用すること

---

## 設計意図

### なぜ単語2-gramを入れるのか

* フレーズ一致を強化
* 誤マッチを減らす
* BM25のスコアを適切に反映

---

## 効果比較

### 単語1-gramのみ

```text
JaLC
Reference
Coverage
```

→ 部分一致が多くノイズ増加

---

### 1-gram + 2-gram

```text
JaLC Reference
Reference Coverage
Coverage 2026
```

→ より正確な一致

---

## 全体フロー

```text
参考文献文字列
    ↓
トークン化（アプリ）
    ↓
トークン集合生成
    ↓
クエリ文字列生成
    ↓
Solr検索（BM25）
```

---

## 結論

* 検索時もインデックス時と同一トークン化が必須
* 英語は「単語 + 隣接2-gram」を必ず含める
* トークンは集合として扱う

👉 **クエリの質が検索精度を決める**
