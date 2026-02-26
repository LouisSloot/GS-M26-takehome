"""Config for DeBERTa harm-classification training (data paths, split, labels)."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Input (JSONL from data step)
TRAIN_FORMATTED_DIR = PROJECT_ROOT / "train_formatted"
ONE_TURN_JSONL = TRAIN_FORMATTED_DIR / "1_turn.jsonl"
TWO_TURN_COMPLETED_JSONL = TRAIN_FORMATTED_DIR / "2_turn_completed.jsonl"

# Output of prepare_data.py (steps 1-3)
DATA_DIR = Path(__file__).resolve().parent / "data"
TRAIN_JSONL = DATA_DIR / "train.jsonl"
VAL_JSONL = DATA_DIR / "val.jsonl"
SPLIT_STATS_JSON = DATA_DIR / "split_stats.json"

# Split
SPLIT_SEED = 42
VAL_RATIO = 0.10  # 90% train, 10% val
STRATIFY_BY_LABEL = True
STRATIFY_BY_CATEGORY = False  # set True if you want category stratification (may create tiny val buckets)

# Labels (binary: unharmful=0, harmful=1)
VALID_LABELS = frozenset({"harmful", "unharmful"})
LABEL_TO_ID = {"unharmful": 0, "harmful": 1}
ID_TO_LABEL = {0: "unharmful", 1: "harmful"}
NUM_LABELS = 2

# Tokenization (for dataset.py)
TOKENIZER_NAME = "microsoft/deberta-v3-base"
MAX_LENGTH = 512
TRUNCATION_SIDE = "left"  # keep final turn
