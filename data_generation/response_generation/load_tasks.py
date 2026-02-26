"""Load 2-turn tasks: seed prompts + sampled target response type."""

import csv
import random
from pathlib import Path
from typing import Iterator

from expansion_pipeline.seed_utils import load_prompts_from_csv
from response_generation.config import (
    CATEGORY_FOLDERS,
    PROMPT_BENIGN_DIST,
    PROMPT_HARMFUL_DIST,
    RESPONSE_COMPLIANCE,
    RESPONSE_OVERREFUSAL,
    RESPONSE_HARMFUL,
    SEED_PROMPTS_DIR,
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


def sample_target_response(prompt_label: str) -> str:
    """Sample target response type given prompt label (harmful | unharmful)."""
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
