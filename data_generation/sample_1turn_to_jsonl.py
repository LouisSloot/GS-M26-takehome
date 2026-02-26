#!/usr/bin/env python3
"""
Assign each prompt from seed_prompts/expanded_all to a turn length and write JSONL files.

For each prompt: assign turn 1 (50%) or 2 (50%).
Output: train_formatted/1_turn.jsonl, 2_turn.jsonl (OpenAI format).

Usage:
  python data_generation/sample_1turn_to_jsonl.py
  python data_generation/sample_1turn_to_jsonl.py --seed 42 --output-dir /path/to/train_formatted
"""

import argparse
import csv
import json
import random
import sys
from pathlib import Path

# Repo root (parent of data_generation/)
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "data_generation"))

from expansion_pipeline.config import CATEGORY_FOLDERS

SEED_DIR = REPO_ROOT / "seed_prompts" / "expanded_all"
OUTPUT_DIR = REPO_ROOT / "train_formatted"

# Turn distribution: 50% 1-turn, 50% 2-turn
TURN_DIST = {1: 0.50, 2: 0.50}


def load_prompts_from_csv(path: Path) -> list[str]:
    """Load prompts from a CSV file. Handles quoted prompts and skips headers."""
    prompts = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            prompt = row[0].strip()
            if prompt.lower() == "prompt" and len(prompts) == 0:
                continue
            if prompt:
                prompts.append(prompt)
    return prompts


def load_all_prompts(seed_dir: Path) -> list[dict]:
    """Load all prompts from expanded_all. Returns [{user_prompt, category, prompt_label}]."""
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
            for text in load_prompts_from_csv(csv_path):
                prompts.append({
                    "user_prompt": text,
                    "category": category,
                    "prompt_label": prompt_label,
                })
    return prompts


def main():
    parser = argparse.ArgumentParser(
        description="Assign prompts to turn lengths and write OpenAI-format JSONL by turn."
    )
    parser.add_argument(
        "--seed-dir",
        type=Path,
        default=SEED_DIR,
        help="Directory containing category subdirs with harmful_prompts.csv / unharmful_prompts.csv",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="Output directory for 1_turn.jsonl, 2_turn.jsonl",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed",
    )
    args = parser.parse_args()

    if not args.seed_dir.is_dir():
        print(f"Error: seed dir not found: {args.seed_dir}", file=sys.stderr)
        sys.exit(1)

    prompts = load_all_prompts(args.seed_dir)
    if not prompts:
        print("No prompts found.", file=sys.stderr)
        sys.exit(1)

    random.seed(args.seed)

    turns = [1, 2, 3]
    weights = [TURN_DIST[t] for t in turns]
    by_turn: dict[int, list[dict]] = {1: [], 2: []}
    for p in prompts:
        t = random.choices(turns, weights=weights, k=1)[0]
        by_turn[t].append(p)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    for turn, items in by_turn.items():
        out_path = args.output_dir / f"{turn}_turn.jsonl"
        with open(out_path, "w", encoding="utf-8") as f:
            for p in items:
                rec = {
                    "messages": [{"role": "user", "content": p["user_prompt"]}],
                    "label": p["prompt_label"],
                    "convo_length": turn,
                    "category": p["category"],
                }
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"Wrote {len(items)} records to {out_path}")


if __name__ == "__main__":
    main()
