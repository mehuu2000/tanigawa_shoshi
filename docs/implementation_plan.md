# Implementation Plan（実装構成・実装順）

## 目的

今回の実装範囲は、MongoDB `jalc.restapi` の JaLC 文献データから、論文方針に沿った統合トークン `all_tokens` を生成し、Solrへ登録・インデックス作成し、参考文献文字列から簡単な検索を行うところまでとする。

RC / CC / MC によるスコアリングと閾値判定は後続フェーズで実装する。

---

## 実装方針

既存の `../jalc/jalc-to-solr.ipynb` は、JaLC文書の扱い方、Solr接続、スキーマ設定、バッチ登録の考え方を参考にする。
ただし、コードは流用せず、このリポジトリ内で独自に実装する。

メインの実行は notebook で行う。
ただし、主要ロジックを notebook へ直書きしすぎず、責務ごとに関数・モジュールへ分ける。
notebook は実行手順、途中確認、ログ確認、少件数実験、全件実行の操作面を担当し、主要ロジックはPythonモジュール側に置く。

---

## 想定ディレクトリ構成

```text
tanigawa_shoshi/
  docs/
    rough_plan.md
    token_plan.md
    store_index_plan.md
    query_plan.md
    implementation_plan.md
    evaluation_plan.md

  src/
    tanigawa_shoshi/
      __init__.py
      config.py
      tokenizer.py
      jalc_extract.py
      solr_schema.py
      solr_indexer.py
      search.py
      evaluation_data.py
      scoring.py
      rerank.py
      evaluation.py

  notebooks/
    01_check_tokenizer.ipynb
    02_check_jalc_extract.ipynb
    03_setup_solr_schema.ipynb
    04_index_sample_to_solr.ipynb
    05_search_sample.ipynb
    06_index_all_to_solr.ipynb
    07_sample_source_docs.ipynb
    08_build_evaluation_data.ipynb
    09_check_scoring.ipynb
    10_run_evaluation.ipynb
```

`notebooks/` をメインの実行場所とする。
必要に応じて補助スクリプトを追加してもよいが、基本方針としては notebook からモジュールを呼び出して実行する。

---

## モジュール責務

### `config.py`

接続先や実行設定を管理する。

想定内容：

* MongoDB URL
* MongoDB database / collection
* Solr URL / core
* batch size
* 検索対象フィールド

### `tokenizer.py`

論文準拠のトークン化を実装する。
分割には PyICU の `BreakIterator` を使用する。

想定関数：

* `is_japanese_char(ch)`
* `is_japanese_token(token)`
* `split_units(text)`
* `build_segments(units)`
* `char_2gram(text)`
* `non_japanese_ngrams(items)`
* `tokenize(text)`
* `tokenize_values(values)`

### `jalc_extract.py`

MongoDB上のJaLC文書をSolr登録用データへ変換する。

想定関数：

* `has_required_fields(doc)`
* `extract_authors(doc)`
* `extract_authors_basic(doc)`
* `extract_first_author(doc)`
* `extract_first_author_basic(doc)`
* `extract_titles(doc)`
* `extract_titles_basic(doc)`
* `extract_journals(doc)`
* `extract_year(doc)`
* `extract_volume(doc)`
* `extract_page(doc)`
* `build_solr_document(doc)`

保存フィールド：

```text
doi
authors
first_author
title
authors_variations
first_author_variations
title_variations
journal
year
volume
page
```

`doi` は単一値で保持する。
`volume` には MongoDB の `volume` と `issue` を同じ配列内に分けて入れる。

検索用統合トークンフィールド：

```text
all_tokens
```

### `solr_schema.py`

Solrのスキーマ設定を行う。

想定関数：

* `add_fields(solr_base_url, core_name)`
* `ensure_schema(solr_base_url, core_name)`

保存フィールドは `stored=true, indexed=false, docValues=false`。
ただし `doi` は単一値かつ必須、その他の保存フィールドは multiValued を想定する。
検索用の `all_tokens` は `stored=false, indexed=true, docValues=false`。

### `solr_indexer.py`

MongoDBから文献を取得し、Solrへバッチ登録する。

想定関数：

* `iter_jalc_documents(collection)`
* `build_documents(docs)`
* `index_documents(solr, docs, batch_size)`
* `index_all()`

対象文献は `content_type = "JA"` に限定する。
`doi` が存在しない文書はその場でスキップし、DOI 不足スキップ件数として他の raw 必須不足とは別に集計する。
登録対象として採用済みの DOI はアプリ側の `set` で保持し、同じ DOI を持つ後続文書はスキップして DOI 重複スキップ件数として集計する。
raw データの必須項目が揃っていても、`all_tokens` が空になる文書は登録対象から除外する。
全件登録開始時に `log/YYYY_MM_DD_HH_MM_SS.log` を作成し、tokenize 後に必須 token field が空になった文書だけを MongoDB `_id`・対象フィールド・元の値・理由の形式で1行ずつ追記する。

### `search.py`

参考文献文字列をトークン化し、Solrへ検索を投げる。

想定関数：

* `build_query_tokens(reference_text)`
* `search_reference(reference_text, rows=10)`

今回の検索対象：

```text
all_tokens
```

`first_author` は登録するが、`all_tokens` の生成元には含めず、今回の検索対象にはしない。

### `evaluation_data.py`

評価用の元メタデータ、無加工正例、正例、負例の生成と保存を担当する。

想定内容：

* MongoDB からの評価対象サンプリング
* `base_positive_examples.json` の生成
* `positive_examples.json` の生成
* `negative_examples.json` の生成
* タイトル書換え依頼結果の反映

### `scoring.py`

候補 1 件に対する RC / CC / MC 計算を担当する。

想定内容：

* `R` の生成
* `Cf` の生成
* `Cvf` の生成
* `compute_rc()`
* `compute_cc()`
* `compute_mc()`

### `rerank.py`

候補群に対するスコア付与、再ランキング、閾値判定を担当する。

想定内容：

* `score_candidates()`
* `rerank_candidates()`
* `select_top_candidate()`
* `apply_threshold()`

### `evaluation.py`

単一件評価・全件評価・方式別集計を担当する。

想定内容：

* `evaluate_single_example()`
* `evaluate_positive_example()`
* `evaluate_negative_example()`
* `evaluate_dataset()`
* `summarize_results()`

---

## Notebook責務

### `notebooks/01_check_tokenizer.ipynb`

トークナイザの動作を確認する。
`docs/token_plan.md` の例を使い、日本語2-gram、非日本語1-gram、非日本語2-gramを確認する。

### `notebooks/02_check_jalc_extract.ipynb`

MongoDBから少件数のJaLC文書を取得し、保存フィールドとトークンフィールドへの変換を確認する。

### `notebooks/03_setup_solr_schema.ipynb`

Solr core に必要なフィールドを追加する。
実行前に対象 core が存在していることを確認する。

### `notebooks/04_index_sample_to_solr.ipynb`

少件数の文献をSolrへ登録し、保存フィールド・検索対象フィールド・件数を確認する。

### `notebooks/05_search_sample.ipynb`

参考文献文字列を入力し、Solr検索結果を確認する。

### `notebooks/06_index_all_to_solr.ipynb`

全件登録用のnotebook。
実行前にSolr core、既存データ削除有無、batch size、ログ出力、中断時の扱いを確認する。

---

## 実装順

### 1. 最小パッケージ構成を作る

`src/tanigawa_shoshi/` と `notebooks/` を作成する。
まずは import できる最小状態を作る。

### 2. トークナイザを実装する

`tokenizer.py` を実装する。
`docs/token_plan.md` の例を使って、手動確認できるようにする。

確認項目：

* 日本語は文字2-gramになる
* 英数字は単語1-gramになる
* 非日本語連続列は単語2-gramも生成する
* 重複が除去される

### 3. JaLC文書抽出処理を実装する

`jalc_extract.py` を実装する。
`../jalc/jalc-to-solr.ipynb` の抽出ロジックを参考にしつつ、保存フィールド名は本実装の方針に合わせる。

確認項目：

* `doi` が取得できる
* `authors` が基本表記で配列取得できる
* `first_author` が基本表記で配列取得できる
* `title` が subtitle を含まず取得できる
* `authors` が配列で取れる
* `first_author` が配列で取れる
* `authors_variations` が複数表記を保持する
* `first_author_variations` が複数表記を保持する
* `title_variations` が複数表記を保持する
* `journal` が略称・言語違いを保持する
* `year` が配列で取れる
* `volume` に `volume` と `issue` が分かれて入る
* `page` がページ範囲として取れる

### 4. Solr登録用ドキュメント生成を実装する

保存フィールドから `all_tokens` を生成し、Solr登録用dictを作る。

確認項目：

* 保存フィールドは `stored=true` 用の値として残る
* `all_tokens` は `authors`, `title`, `journal`, `year`, `volume`, `page` から生成する
* `first_author` は `all_tokens` の生成元に含めない

### 5. Solrスキーマ設定を実装する

`solr_schema.py` を実装し、`notebooks/03_setup_solr_schema.ipynb` から実行する。

確認項目：

* 保存フィールド: `stored=true`, `indexed=false`, `docValues=false`
* `all_tokens`: `stored=false`, `indexed=true`, `docValues=false`
* `doi` は単一値かつ必須
* それ以外の保存フィールドと `all_tokens` は multiValued=true
* 旧 `*_tokens` field が既存 core に残っている場合はエラーにする
* 再実行しても壊れにくい

### 6. 小件数でSolr登録する

`solr_indexer.py` を実装し、`notebooks/04_index_sample_to_solr.ipynb` から実行する。

最初は `limit=10` や `limit=100` で動作確認する。

確認項目：

* MongoDBへ接続できる
* `content_type = "JA"` の文献だけを対象にする
* Solrへ登録できる
* Solrで `*:*` 検索して件数が増える
* 保存フィールドが取得できる

### 7. 簡単な検索を実装する

`search.py` を実装し、`notebooks/05_search_sample.ipynb` から実行する。

検索には標準検索フィールド `df` を使い、対象フィールドは以下にする。

```text
all_tokens
```

確認項目：

* 入力文字列がトークン化される
* `first_author` は `all_tokens` の生成元に含めない
* Solrから候補文献が返る
* DOIやtitleなど保存フィールドが表示できる

### 8. 全件登録前の確認

全件登録は重いので、実行前に以下を確認する。

* Solr core名
* 既存データを削除するか追記するか
* batch size
* ログ出力の粒度
* 中断・再実行時の扱い

---

## 今回は実装しないもの

以下は後続フェーズで扱う。

* RC / CC / MC のスコアリング
* 論文記載閾値の適用
* 同定成功 / 同定なしの判定
* 評価用 positive / negative データ生成
* 検索件数 K の最適化
