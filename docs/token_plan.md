# Tokenization Plan（論文準拠トークン生成）

## 概要

本システムでは、論文の方針に従い以下のルールでトークンを生成する。

* 日本語：文字2-gram
* 日本語以外（英語・数字など）：単語1-gram
* 日本語以外が連続する場合：単語2-gramも追加

トークン生成はすべて **アプリ側で実施** する。

また、本トークン化処理は

* インデックス作成時
* 検索時（クエリ）
* 再ランキング時（RC / CC / MC）

のすべてで**同一ロジックを使用する**。

---

## 処理の流れ

1. 文字列を ICU 等で分割（擬似的な単位）
2. 日本語 / 非日本語の判定
3. 日本語連続列・非日本語連続列に再構成
4. 各ブロックごとにトークン生成

---

## データ構造

```python
[
  { "type": "non_japanese_seq", "items": ["JaLC", "Reference", "Coverage", "2026"] },
  { "type": "japanese", "items": ["年創業"] }
]
```

---

## トークンの扱い（重要）

* トークンは **集合（set）として扱う**
* 順序は考慮しない
* 重複は除去する

これはRC / CCの計算（集合演算）に対応するためである。

---

## 疑似コード

### 日本語判定

```python
def is_japanese_char(ch):
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF or  # 漢字
        0x3040 <= code <= 0x309F or  # ひらがな
        0x30A0 <= code <= 0x30FF     # カタカナ
    )

def is_japanese_token(token):
    return any(is_japanese_char(ch) for ch in token)
```

---

### セグメント生成

```python
def build_segments(units):
    segments = []
    jp_buffer = []
    nonjp_buffer = []

    def flush_jp():
        nonlocal jp_buffer
        if jp_buffer:
            segments.append({
                "type": "japanese",
                "items": ["".join(jp_buffer)]
            })
            jp_buffer = []

    def flush_nonjp():
        nonlocal nonjp_buffer
        if nonjp_buffer:
            segments.append({
                "type": "non_japanese_seq",
                "items": nonjp_buffer[:]
            })
            nonjp_buffer = []

    for unit in units:
        if is_japanese_token(unit):
            flush_nonjp()
            jp_buffer.append(unit)
        else:
            flush_jp()
            nonjp_buffer.append(unit)

    flush_jp()
    flush_nonjp()

    return segments
```

---

### 日本語トークン生成（文字2-gram）

```python
def char_2gram(text):
    if len(text) < 2:
        return []
    return [text[i:i+2] for i in range(len(text)-1)]
```

---

### 非日本語トークン生成

```python
def non_japanese_ngrams(items):
    result = []

    # 単語1-gram
    result.extend(items)

    # 単語2-gram（連続列に対して）
    for i in range(len(items) - 1):
        result.append(items[i] + " " + items[i+1])

    return result
```

---

## 最終トークン生成

```python
def generate_tokens(segments):
    tokens = []

    for seg in segments:
        if seg["type"] == "japanese":
            text = seg["items"][0]
            tokens.extend(char_2gram(text))

        elif seg["type"] == "non_japanese_seq":
            tokens.extend(non_japanese_ngrams(seg["items"]))

    return list(set(tokens))  # 重複除去
```

---

## 最終関数

```python
def tokenize(text):
    units = icu_like_split(text)  # ICU分割
    segments = build_segments(units)
    tokens = generate_tokens(segments)
    return tokens
```

---

## フィールド単位での使用方法

本関数は以下のようにフィールド単位で適用する。

```python
title_tokens = tokenize(title)
authors_tokens = tokenize(authors)
journal_tokens = tokenize(journal)
...
```

---

## 注意事項

### 1. クエリとインデックスの一致

インデックス作成時と検索時でトークン化ロジックが異なる場合、検索精度は大きく低下する。

👉 必ず同一関数を使用する

---

### 2. 非日本語2-gramの定義

単語2-gramは「日本語以外の単語が連続する区間」に対してのみ適用する。

例：

```text
JaLC Reference Coverage 2026
```

→ 生成される2-gram：

```text
JaLC Reference
Reference Coverage
Coverage 2026
```

---

### 3. 日本語1文字の扱い

日本語1文字のみの場合：

```text
年 → トークンなし
```

となる（2-gramが生成できないため）。

---

### 4. ICUの役割

* ICUは単語分割ではなく「境界検出」のみに使用する
* 実際のトークン生成はすべて本ロジックで行う

---

## 結論

* トークン生成は完全にアプリ側で制御する
* フィールド単位でトークンを生成する
* クエリ・インデックス・再ランキングで同一処理を適用する

👉 本処理がシステム全体の精度を決定する最重要部分である
