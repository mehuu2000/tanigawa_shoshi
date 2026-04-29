"""論文方針に合わせたトークン化ユーティリティ。"""

from typing import Iterable, List, Optional, Set

try:
    from icu import BreakIterator, Locale, UnicodeString
except ImportError as exc:
    raise ImportError(
        "PyICU が必要です。仮想環境で `pip install PyICU` を実行してください。"
    ) from exc


# Unicodeコードポイントの範囲で日本語文字を定義する。これらの範囲に属する文字はすべて日本語文字とみなす。
# トークンとして残す日本語文字の主な範囲。
# 句読点や中点などの記号は含めず、文字として扱いたいものだけを拾う。
JAPANESE_RANGES = (
    (0x3400, 0x4DBF),  # CJK統合漢字拡張A (㐀 ~ 䶿, 追加漢字の範囲)
    (0x4E00, 0x9FFF),  # CJK統合漢字 (一 ~ 鿿, 学・漢などの一般的な漢字を含む)
    (0x3041, 0x3096),  # ひらがな (ぁ ~ ゖ, あ ~ ん を含む)
    (0x309D, 0x309F),  # ひらがな反復記号など (ゝ ~ ゟ)
    (0x30A1, 0x30FA),  # カタカナ (ァ ~ ヺ, ア ~ ン を含む)
    (0x30FD, 0x30FF),  # カタカナ反復記号など (ヽ ~ ヿ)
    (0x31F0, 0x31FF),  # カタカナ拡張 (ㇰ ~ ㇿ, 小書きカタカナを含む)
    (0xFF66, 0xFF9F),  # 半角カタカナ (ｦ ~ ﾟ, ｱ ~ ﾝ を含む)
)

# 上記の範囲に含まれないが、トークンとして残す日本語文字。
# "々"：佐々木
# "〆"：締 の代わりに使われることがある
# "〇"：〇年
# "ヶ"：一ヶ月
# "ヵ"：ヵ所
# "ー"：データベース
JAPANESE_EXTRA_CHARS = {"々", "〆", "〇", "ヶ", "ヵ", "ー"}

# 文字が日本語の文字種に属するかを判定する処理(属する場合はTrueを返す)
def is_japanese_char(ch: str) -> bool:
    if not ch:
        return False
    if ch in JAPANESE_EXTRA_CHARS:
        return True
    code = ord(ch) # 文字をUnicodeコードポイントに変換
    return any(start <= code <= end for start, end in JAPANESE_RANGES)

# ICUで分割した単位の先頭文字列が対象
# 先頭を日本語文字か判定する処理を呼び出す
def is_japanese_token(token: str) -> bool:
    if not token:
        return False
    return is_japanese_char(token[0])

# ICUのBreakIteratorを使って単語境界を取り、特殊文字・デリミタを除外した単語のリストを返す処理
def split_units(text: str) -> List[str]:
    if not text:
        return []

    # 引数のテキストをICUのBreakIteratorを使って単語単位で分割する。日本語のルールに従うため、
    # Localeを日本語に設定する。
    # 例："I am 佐々木です" 
    # → UnicodeString("I am 佐々木です") 
    # → BreakIteratorで "I", " ", "am", " ", "佐々木", "です"
    # → iterator
    # 文字　　　:  I  _  am  _  佐々木  です
    # 境界index:  0  1  2   4  5      8   10
    iterator = BreakIterator.createWordInstance(Locale.getJapanese())
    unicode_text = UnicodeString(text)
    iterator.setText(unicode_text)

    # 境界ごとに文字列を切り出して、ICUのルールに従って単語として扱うかを判定する。
    # 単語のリストを作成する。
    units: List[str] = []
    start = iterator.first()
    for end in iterator:
        unit = str(unicode_text[start:end])
        status = iterator.getRuleStatus()
        # status == 0 は空白や記号など、単語として扱わない境界。
        is_word_like = status != 0
        if is_word_like and unit.strip():
            units.append(unit)
        start = end

    return units

# 隣接する単語を日本語列と非日本語列にまとめる処理
# 例：["JaLC", "Reference", "Coverage", "2026", "年", "創業", "Yesterday"]
# [
#   { "type": "non_japanese_seq", "items": ["JaLC", "Reference", "Coverage", "2026"] },
#   { "type": "japanese", "items": ["年創業"] },
#   { "type": "non_japanese_seq", "items": ["Yesterday"] }
# ]
def build_segments(units: Iterable[str]) -> List[dict]:
    unit_list = list(units)
    if not unit_list:
        return []

    segments: List[dict] = []
    current_type = None
    current_items: List[str] = []

    for unit in unit_list:
        if is_japanese_token(unit):
            unit_type = "japanese"
        else:
            unit_type = "non_japanese_seq"

        # 最初の単語の場合は、current_typeを設定してcurrent_itemsに追加するだけで次に進む。
        if current_type is None:
            current_type = unit_type
            current_items = [unit]
            continue

        # 現在の単語のタイプが前の単語と同じなら、current_itemsに追加して次に進む。
        if unit_type == current_type:
            current_items.append(unit)
            continue
        
        if current_type == "japanese":
            # 日本語列は単語を連結して1つの文字列にまとめる。例：["年", "創業"] → "年創業"
            segments.append({"type": "japanese", "items": ["".join(current_items)]})
        else:
            # 非日本語列は単語のリストをそのまま保持する。例：["JaLC", "Reference", "Coverage", "2026"]
            segments.append({"type": "non_japanese_seq", "items": current_items[:]})

        # 新しいタイプに合わせてcurrent_typeを更新し、current_itemsを新しい単語で初期化する。
        current_type = unit_type
        current_items = [unit]

    if current_type == "japanese":
        segments.append({"type": "japanese", "items": ["".join(current_items)]})
    else:
        segments.append({"type": "non_japanese_seq", "items": current_items[:]})

    return segments


# 日本語文字列から文字2-gramを生成する処理。1文字ならその1文字を返す。
def char_2gram(text: str) -> List[str]:
    if len(text) == 1:
        return [text]
    if len(text) < 2:
        return []
    
    tokens: List[str] = []
    for index in range(len(text) - 1):
        gram = text[index : index + 2]
        tokens.append(gram)

    return tokens

# 非日本語列から単語1-gramと隣接単語2-gramを生成する。
def non_japanese_ngrams(items: Iterable[str]) -> List[str]:
    # 空文字を除いた単語列を作る
    words = [item for item in items if item]
    if not words:
        return []

    # 単語1-gramを追加する
    tokens = words[:]
    # 隣接単語2-gramを追加する
    for index in range(len(words) - 1):
        bigram = words[index] + " " + words[index + 1]
        tokens.append(bigram)
        
    return tokens

# トークンの順序を保ちながら、重複を除去する処理。空文字は除外する。
def _unique_preserve_order(values: Iterable[str]) -> List[str]:
    seen: Set[str] = set()
    unique_values: List[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            unique_values.append(value)
    return unique_values

# フィールド値1つに対するトークン化。
def tokenize(text: str) -> List[str]:
    units = split_units(text)
    segments = build_segments(units)

    tokens: List[str] = []
    for segment in segments:
        segment_type = segment["type"]
        items = segment["items"]
        if segment_type == "japanese":
            tokens.extend(char_2gram(items[0]))
        elif segment_type == "non_japanese_seq":
            tokens.extend(non_japanese_ngrams(items))

    return _unique_preserve_order(tokens)

# 配列フィールド全体に対するトークン化
def tokenize_values(values: Iterable[Optional[str]]) -> List[str]:
    tokens: List[str] = []
    for value in values:
        if value:
            tokens.extend(tokenize(value))
    return _unique_preserve_order(tokens)
