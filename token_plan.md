# Tokenization Plan（論文準拠トークン生成）

## 概要

本システムでは、論文の方針に従い以下のルールでトークンを生成する。

* 日本語：文字2-gram
* 日本語以外（英語・数字など）：単語1-gram
* 日本語以外が連続する場合：単語2-gramも追加

トークン生成はすべて **アプリ側で実施** する。

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

### 日本語2-gram

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

    # 1-gram
    result.extend(items)

    # 2-gram
    for i in range(len(items) - 1):
        result.append(items[i] + " " + items[i+1])

    return result
```

---

### 最終トークン生成

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

## ポイント

* ICUは「境界検出」のみで使用
* トークン生成は論文ルールに完全依存
* トークンは集合として扱う（重複削除）
