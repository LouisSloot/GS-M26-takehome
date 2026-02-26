"""Pure utility functions for seed loading and axis sampling (no distilabel dependency)."""

import csv
import random
from pathlib import Path

from expansion_pipeline.config import (
    AXES,
    CATEGORY_FOLDERS,
    CATEGORY_KEYS,
    CATEGORY_WEIGHTS,
    NUM_AXES_OPTIONS,
    NUM_AXES_WEIGHTS,
)


def load_prompts_from_csv(path: Path) -> list[str]:
    """Load prompts from a CSV file. Handles quoted prompts and skips headers."""
    prompts = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            prompt = row[0].strip()
            # Skip header row if present
            if prompt.lower() == "prompt" and len(prompts) == 0:
                continue
            if prompt:
                prompts.append(prompt)
    return prompts


def sample_axes() -> list[str]:
    """
    Sample 1-3 axes according to the specified distributions.
    num_axes: {1: 30%, 2: 55%, 3: 15%}
    categories: intent 35%, delivery 25%, emotional 20%, style 10%, format 10%
    """
    num_axes = random.choices(
        NUM_AXES_OPTIONS,
        weights=NUM_AXES_WEIGHTS,
        k=1,
    )[0]

    # Sample num_axes distinct categories (without replacement) with given weights
    available_indices = list[int](range(len(CATEGORY_KEYS)))
    chosen_categories = []

    for _ in range(num_axes):
        weights = [CATEGORY_WEIGHTS[i] for i in available_indices]
        total = sum(weights)
        probs = [w / total for w in weights]
        idx_in_available = random.choices(
            range(len(available_indices)),
            weights=probs,
            k=1,
        )[0]
        chosen_idx = available_indices[idx_in_available]
        chosen_categories.append(CATEGORY_KEYS[chosen_idx])
        available_indices.remove(chosen_idx)

    # For each chosen category, pick a random option
    axes = []
    for cat in chosen_categories:
        options = AXES[cat]
        axes.append(random.choice(options))

    return axes


def load_all_seeds(data_dir: Path) -> list[dict]:
    """Load all seed prompts from CSVs. Returns list of {seed_prompt, category, label}."""
    seeds = []
    for category in CATEGORY_FOLDERS:
        category_path = data_dir / category
        if not category_path.is_dir():
            continue

        for label, filename in [("harmful", "harmful_prompts.csv"), ("unharmful", "unharmful_prompts.csv")]:
            csv_path = category_path / filename
            if not csv_path.exists():
                continue

            prompts = load_prompts_from_csv(csv_path)
            for prompt in prompts:
                seeds.append({
                    "seed_prompt": prompt,
                    "category": category,
                    "label": label,
                })

    return seeds
