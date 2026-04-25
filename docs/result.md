### notebooks/03_setup_solr_schema.ipynb
--
# schema を確認し、不足フィールドを追加する
result = ensure_schema(SOLR_BASE_URL, SOLR_CORE)
pprint(result)

```
{'added_fields': ['doi',
                  'authors',
                  'first_author',
                  'title',
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
 'existing_field_count_after': 20,
 'existing_field_count_before': 5,
 'expected_fields': ['doi',
                     'authors',
                     'first_author',
                     'title',
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
                     'page_tokens']}
```