"""Load 2-turn tasks: seed prompts + sampled target response type."""

import csv
import json
import random
from pathlib import Path
from typing import Iterator

from expansion_pipeline.seed_utils import load_prompts_from_csv
from response_generation.config import (
    CATEGORY_FOLDERS,
    EVAL_3TURN_TURN3_DIST,
    PROMPT_BENIGN_DIST,
    PROMPT_HARMFUL_DIST,
    EVAL_PROMPT_BENIGN_DIST,
    EVAL_PROMPT_HARMFUL_DIST,
    EVAL_3TURN_TURN2_PROMPT_BENIGN_DIST,
    EVAL_3TURN_TURN2_PROMPT_HARMFUL_DIST,
    RESPONSE_COMPLIANCE,
    RESPONSE_OVERREFUSAL,
    RESPONSE_HARMFUL,
    SEED_PROMPTS_DIR,
    USER_BENIGN,
    USER_HARMFUL,
)


def load_all_prompts(seed_dir: Path) -> list[dict]:
    """Load all prompts from expanded_all. Returns [{prompt, category, prompt_label}]."""
    prompts = []
    for category in CATEGORY_FOLDERS:
        cat_path = seed_dir / category
        if not cat_path.is_dir():
            continue
        for prompt_label, filename in [
            ("harmful", "harmful_prompts.csv"),
            ("unharmful", "unharmful_prompts.csv"),
        ]:
            csv_path = cat_path / filename
            if not csv_path.exists():
                continue
            texts = load_prompts_from_csv(csv_path)
            for text in texts:
                prompts.append({
                    "user_prompt": text,
                    "category": category,
                    "prompt_label": prompt_label,
                })
    return prompts


def sample_target_response(
    prompt_label: str,
    use_eval_dist: bool = False,
    use_eval_3turn_turn2: bool = False,
) -> str:
    """Sample target response type given prompt label (harmful | unharmful)."""
    if use_eval_3turn_turn2:
        dist = (
            EVAL_3TURN_TURN2_PROMPT_HARMFUL_DIST
            if prompt_label == "harmful"
            else EVAL_3TURN_TURN2_PROMPT_BENIGN_DIST
        )
    elif use_eval_dist:
        dist = EVAL_PROMPT_HARMFUL_DIST if prompt_label == "harmful" else EVAL_PROMPT_BENIGN_DIST
    else:
        dist = PROMPT_HARMFUL_DIST if prompt_label == "harmful" else PROMPT_BENIGN_DIST
    # Filter out zero-probability types for cleaner sampling
    types = [t for t, p in dist.items() if p > 0]
    weights = [dist[t] for t in types]
    return random.choices(types, weights=weights, k=1)[0]


def generate_tasks(
    seed_dir: Path,
    num_tasks: int | None = None,
    seed: int | None = 42,
    shuffle: bool = True,
) -> Iterator[dict]:
    """
    Generate 2-turn tasks: each has user_prompt, category, prompt_label, target_response_type.
    If num_tasks is None, yields one task per prompt. Otherwise samples with replacement.
    """
    if seed is not None:
        random.seed(seed)

    prompts = load_all_prompts(seed_dir)
    if not prompts:
        return

    if num_tasks is None:
        num_tasks = len(prompts)

    # Sample prompts (with replacement if num_tasks > len(prompts))
    sampled = random.choices(prompts, k=num_tasks)
    if shuffle:
        random.shuffle(sampled)

    for p in sampled:
        target = sample_target_response(p["prompt_label"])
        yield {
            "user_prompt": p["user_prompt"],
            "category": p["category"],
            "prompt_label": p["prompt_label"],
            "target_response_type": target,
        }


def load_turn1_label_lookup(turn1_jsonl_path: Path) -> dict[str, str]:
    """
    Build a lookup from turn-1 user content -> turn-1 label.
    Load 3_turn.jsonl (stubs with one user message) and map messages[0]["content"] -> label.
    Used to get turn1_label when generating turn 3, since turn2_completed only stores turn2 label.
    """
    lookup: dict[str, str] = {}
    with open(turn1_jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            msgs = rec.get("messages") or []
            if not msgs or msgs[0].get("role") != "user":
                continue
            content = (msgs[0].get("content") or "").strip()
            label = rec.get("label", "unharmful")
            if content:
                lookup[content] = label
    return lookup


def sample_target_user3(turn1_label: str, turn2_label: str) -> str:
    """Sample USER_BENIGN or USER_HARMFUL for turn 3 given (turn1_label, turn2_label)."""
    key = (turn1_label, turn2_label)
    dist = EVAL_3TURN_TURN3_DIST.get(key, {USER_BENIGN: 0.5, USER_HARMFUL: 0.5})
    types = [t for t, p in dist.items() if p > 0]
    weights = [dist[t] for t in types]
    if not types:
        return USER_BENIGN
    return random.choices(types, weights=weights, k=1)[0]


def get_turn3_labels(record: dict, turn1_lookup: dict[str, str]) -> tuple[str, str] | None:
    """
    Extract (turn1_label, turn2_label) from a 3_turn_turn2_completed record.
    turn1_label: from lookup of messages[0]["content"] in 3_turn.jsonl
    turn2_label: from record["label"] (conv label after turn 2 = assistant response label)
    Returns None if turn1_content not found in lookup.
    """
    msgs = record.get("messages") or []
    if len(msgs) < 2 or msgs[0].get("role") != "user":
        return None
    turn1_content = (msgs[0].get("content") or "").strip()
    turn1_label = turn1_lookup.get(turn1_content)
    if turn1_label is None:
        return None
    turn2_label = record.get("label", "unharmful")
    return (turn1_label, turn2_label)
