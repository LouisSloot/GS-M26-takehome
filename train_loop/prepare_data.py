"""
Steps 1-3: Load 1-turn and 2-turn JSONL, filter, serialize to single string, stratified train/val split.

Reads: train_formatted/1_turn.jsonl, train_formatted/2_turn_completed.jsonl
Writes: train_loop/data/train.jsonl, train_loop/data/val.jsonl, train_loop/data/split_stats.json

Each output line: {"text": str, "label": "harmful"|"unharmful", "category": str, "convo_length": 1|2}
"""

import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Allow running as script from repo root: python train_loop/prepare_data.py
_REPO_ROOT = Path(__file__).resolve().parent.parent
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from train_loop.config import (
    DATA_DIR,
    ONE_TURN_JSONL,
    SPLIT_SEED,
    SPLIT_STATS_JSON,
    STRATIFY_BY_CATEGORY,
    STRATIFY_BY_LABEL,
    TRAIN_JSONL,
    TWO_TURN_COMPLETED_JSONL,
    VAL_JSONL,
    VAL_RATIO,
    VALID_LABELS,
)


def serialize_1turn(messages: list[dict]) -> str:
    """User content only."""
    if not messages or messages[0].get("role") != "user":
        return ""
    return (messages[0].get("content") or "").strip()


def serialize_2turn(messages: list[dict]) -> str:
    """User: ... \\n\\n Assistant: ... (same format as token-count script and training)."""
    parts = []
    for m in messages:
        role = (m.get("role") or "").capitalize()
        content = (m.get("content") or "").strip()
        parts.append(f"{role}: {content}")
    return "\n\n".join(parts)


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def filter_and_serialize_1turn(path: Path) -> list[dict]:
    rows = load_jsonl(path)
    out = []
    for row in rows:
        label = (row.get("label") or "").strip().lower()
        if label not in VALID_LABELS:
            continue
        messages = row.get("messages") or []
        if len(messages) < 1:
            continue
        text = serialize_1turn(messages)
        if not text:
            continue
        out.append({
            "text": text,
            "label": label,
            "category": row.get("category") or "unknown",
            "convo_length": 1,
        })
    return out


def filter_and_serialize_2turn(path: Path) -> list[dict]:
    rows = load_jsonl(path)
    out = []
    for row in rows:
        label = (row.get("label") or "").strip().lower()
        if label not in VALID_LABELS:
            continue
        messages = row.get("messages") or []
        if len(messages) < 2:
            continue
        # Require non-empty assistant content
        assistant = next((m for m in messages if (m.get("role") or "").lower() == "assistant"), None)
        if not assistant or not (assistant.get("content") or "").strip():
            continue
        text = serialize_2turn(messages)
        if not text:
            continue
        out.append({
            "text": text,
            "label": label,
            "category": row.get("category") or "unknown",
            "convo_length": 2,
        })
    return out


def stratified_split(
    examples: list[dict],
    val_ratio: float,
    seed: int,
    stratify_by_label: bool,
    stratify_by_category: bool,
) -> tuple[list[dict], list[dict]]:
    """Split into train/val preserving label (and optionally category) proportions."""
    rng = random.Random(seed)

    if stratify_by_category and stratify_by_label:
        # Group by (category, label)
        groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for ex in examples:
            key = (ex["category"], ex["label"])
            groups[key].append(ex)
    elif stratify_by_label:
        groups = defaultdict(list)
        for ex in examples:
            groups[ex["label"]].append(ex)
    else:
        groups = {"_": examples}

    train, val = [], []
    for key, group in groups.items():
        rng.shuffle(group)
        n_val = max(0, int(len(group) * val_ratio))
        if n_val == 0 and group and val_ratio > 0:
            n_val = 1  # at least one in val if we have any
        val.extend(group[:n_val])
        train.extend(group[n_val:])

    rng.shuffle(train)
    rng.shuffle(val)
    return train, val


def main() -> int:
    if not ONE_TURN_JSONL.exists():
        print(f"Missing {ONE_TURN_JSONL}", file=sys.stderr)
        return 1
    if not TWO_TURN_COMPLETED_JSONL.exists():
        print(f"Missing {TWO_TURN_COMPLETED_JSONL}", file=sys.stderr)
        return 1

    one = filter_and_serialize_1turn(ONE_TURN_JSONL)
    two = filter_and_serialize_2turn(TWO_TURN_COMPLETED_JSONL)
    examples = one + two
    random.Random(SPLIT_SEED).shuffle(examples)

    if not examples:
        print("No examples after filtering.", file=sys.stderr)
        return 1

    train, val = stratified_split(
        examples,
        val_ratio=VAL_RATIO,
        seed=SPLIT_SEED,
        stratify_by_label=STRATIFY_BY_LABEL,
        stratify_by_category=STRATIFY_BY_CATEGORY,
    )

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    for path, data in [(TRAIN_JSONL, train), (VAL_JSONL, val)]:
        with open(path, "w", encoding="utf-8") as f:
            for ex in data:
                f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    by_label_train = Counter(ex["label"] for ex in train)
    by_label_val = Counter(ex["label"] for ex in val)
    by_length_train = Counter(ex["convo_length"] for ex in train)
    by_length_val = Counter(ex["convo_length"] for ex in val)
    stats = {
        "n_train": len(train),
        "n_val": len(val),
        "n_total": len(examples),
        "n_1turn": len(one),
        "n_2turn": len(two),
        "by_label_train": dict(by_label_train),
        "by_label_val": dict(by_label_val),
        "by_convo_length_train": dict(by_length_train),
        "by_convo_length_val": dict(by_length_val),
        "val_ratio": VAL_RATIO,
        "seed": SPLIT_SEED,
    }
    with open(SPLIT_STATS_JSON, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)

    print(f"Train: {len(train)}  Val: {len(val)}  (1-turn: {len(one)}, 2-turn: {len(two)})")
    print(f"Wrote {TRAIN_JSONL}, {VAL_JSONL}, {SPLIT_STATS_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
