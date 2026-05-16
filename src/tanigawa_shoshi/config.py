"""プロジェクト全体で使う設定値。"""

from pathlib import Path

MONGODB_URL = "mongodb://localhost:27017"
MONGODB_DATABASE = "jalc"
MONGODB_COLLECTION = "restapi"

SOLR_BASE_URL = "http://localhost:8983/solr"
SOLR_CORE = "tanigawa_paper_jalc"

BATCH_SIZE = 10000

SEARCH_FIELD = "all_tokens"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVALUATION_DATA_DIR = PROJECT_ROOT / "data" / "evaluation"
SAMPLED_SOURCE_DOCS_PATH = EVALUATION_DATA_DIR / "sampled_source_docs.json"
POSITIVE_EXAMPLES_PATH = EVALUATION_DATA_DIR / "positive_examples.json"
NEGATIVE_EXAMPLES_PATH = EVALUATION_DATA_DIR / "negative_examples.json"
