#!/usr/bin/env python3
"""
Assign prompts from data/train_data/raw_seeds to turn lengths and write OpenAI-format JSONL files.

Supports two distribution presets:
  - train: 50% 1-turn, 50% 2-turn
  - eval:  20% 1-turn, 40% 2-turn, 40% 3-turn

Output: {output_dir}/1_turn.jsonl, 2_turn.jsonl, [3_turn.jsonl if eval]

Usage:
  python data_generation/sample_prompts_to_jsonl.py --distribution train
  python data_generation/sample_prompts_to_jsonl.py --distribution eval --output-dir test_formatted
  python data_generation/sample_prompts_to_jsonl.py --distribution train --seed 42 --seed-dir /path/to/expanded_all
"""

import argparse
import json
import random
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from response_generation.config import SEED_PROMPTS_DIR, TRAIN_FORMATTED_DIR
from response_generation.load_tasks import load_all_prompts

# Distribution presets: {turn: weight}
DISTRIBUTIONS = {
    "train": {1: 0.50, 2: 0.50},
    "eval": {1: 0.20, 2: 0.40, 3: 0.40},
}


def main():
    parser = argparse.ArgumentParser(
        description="Assign prompts to turn lengths and write OpenAI-format JSONL by turn."
    )
    parser.add_argument(
        "--distribution",
        choices=list(DISTRIBUTIONS),
        default="train",
        help="Turn distribution preset: train (50/50 for 1–2 turns) or eval (20/40/40 for 1–3 turns)",
    )
    parser.add_argument(
        "--seed-dir",
        type=Path,
        default=SEED_PROMPTS_DIR,
        help="Directory with category subdirs containing harmful_prompts.csv / unharmful_prompts.csv",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=TRAIN_FORMATTED_DIR,
        help="Output directory for *_turn.jsonl files",
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

    turn_dist = DISTRIBUTIONS[args.distribution]
    turns = list(turn_dist.keys())
    weights = [turn_dist[t] for t in turns]
    by_turn: dict[int, list[dict]] = {t: [] for t in turns}

    random.seed(args.seed)

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
