"""プロジェクト全体で使う設定値。"""

MONGODB_URL = "mongodb://localhost:27017"
MONGODB_DATABASE = "jalc"
MONGODB_COLLECTION = "restapi"

SOLR_BASE_URL = "http://localhost:8983/solr"
SOLR_CORE = "tanigawa_paper_jalc"

BATCH_SIZE = 10000

SEARCH_FIELDS = [
    "authors_tokens",
    "title_tokens",
    "journal_tokens",
    "year_tokens",
    "volume_tokens",
    "page_tokens",
]
