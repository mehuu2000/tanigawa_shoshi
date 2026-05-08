## notebooks/03_setup_solr_schema.ipynb
--
#### schema を確認し、不足フィールドを追加する
result = ensure_schema(SOLR_BASE_URL, SOLR_CORE)
pprint(result)

```
{'added_fields': ['doi',
                  'authors',
                  'first_author',
                  'title',
                  'authors_variations',
                  'first_author_variations',
                  'title_variations',
                  'journal',
                  'year',
                  'volume',
                  'page',
                  'all_tokens'],
 'deprecated_fields': [],
 'existing_field_count_after': 17,
 'existing_field_count_before': 5,
 'expected_fields': ['doi',
                     'authors',
                     'first_author',
                     'title',
                     'authors_variations',
                     'first_author_variations',
                     'title_variations',
                     'journal',
                     'year',
                     'volume',
                     'page',
                     'all_tokens'],
 'mismatched_fields': []}
```


## notebooks/06_index_all_to_solr.ipynb
--
#### トークン化処理をした結果から文字になってしまったもの
{doi: '10.3327/jaesjb.52.4_187'}
タイトル：[ ・ ]
↑何これ

#### 全文書登録

以下の数値は DOI 必須化・重複 DOI スキップ追加前の過去実行記録。
現行コードで再実行すると、DOI がなかった件数・DOI が重複していた件数も別項目として表示される。

99m 15.2s

10000件のデータを登録
10000件のデータを登録
10000件のデータを登録
8795件のデータを登録
最後に commit を実行
全件登録完了
Mongo取得した日本語書誌の件数: 11936840
正常にSolrに登録できる形にビルドした件数: 9558795
正常にSolrに登録できた件数: 9558795

DOIがなかった件数: 未計測
DOIが重複していた件数: 未計測
必須生データが不足していた件数: 2377785
値が特殊文字のみだった件数: 85
カラムは存在するが、値が不足していた件数: 175
{'batch_count': 956,
 'built_count': 9558795,
 'indexed_count': 9558795,
 'input_count': 11936840,
 'skipped_build_failed': 175,
 'skipped_missing_required_fields': 2377785,
 'skipped_missing_required_token_fields': 85}
