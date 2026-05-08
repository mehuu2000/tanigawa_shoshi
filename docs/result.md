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
                  'authors_tokens',
                  'first_author_tokens',
                  'title_tokens',
                  'journal_tokens',
                  'year_tokens',
                  'volume_tokens',
                  'page_tokens'],
 'existing_field_count_after': 23,
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
                     'authors_tokens',
                     'first_author_tokens',
                     'title_tokens',
                     'journal_tokens',
                     'year_tokens',
                     'volume_tokens',
                     'page_tokens'],
 'mismatched_fields': []}
```


## notebooks/06_index_all_to_solr.ipynb
--
#### トークン化処理をした結果から文字になってしまったもの
{doi: '10.3327/jaesjb.52.4_187'}
タイトル：[ ・ ]
↑何これ

#### 全文書登録
99m 15.2s

10000件のデータを登録
10000件のデータを登録
10000件のデータを登録
8795件のデータを登録
最後に commit を実行
全件登録完了
読み込み件数: 11936840
登録対象件数: 9558795
登録件数: 9558795
raw 必須不足スキップ件数: 2377785
token 必須不足スキップ件数: 85
その他スキップ件数: 175
{'batch_count': 956,
 'built_count': 9558795,
 'indexed_count': 9558795,
 'input_count': 11936840,
 'skipped_build_failed': 175,
 'skipped_missing_required_fields': 2377785,
 'skipped_missing_required_token_fields': 85}
