#!/usr/bin/env python3
"""
Assign each prompt from seed_prompts/expanded_all to a turn length and write JSONL files.

For each prompt: assign turn 1 (20%), 2 (40%), or 3 (40%) per notes.txt.
Output: train_formatted/1_turn.jsonl, 2_turn.jsonl, 3_turn.jsonl

Usage:
  python scripts/sample_1turn_to_jsonl.py
  python scripts/sample_1turn_to_jsonl.py --seed 42
"""

import argparse
import json
import random
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from response_generation.config import SEED_PROMPTS_DIR, TRAIN_FORMATTED_DIR
from response_generation.load_tasks import load_all_prompts

# Turn distribution: 20% 1-turn, 40% 2-turn, 40% 3-turn
TURN_DIST = {1: 0.20, 2: 0.40, 3: 0.40}


def main():
    parser = argparse.ArgumentParser(description="Assign prompts to turn lengths and write JSONL by turn.")
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

    seed_dir = SEED_PROMPTS_DIR
    if not seed_dir.is_dir():
        print(f"Error: seed dir not found: {seed_dir}", file=sys.stderr)
        sys.exit(1)

    prompts = load_all_prompts(seed_dir)
    if not prompts:
        print("No prompts found.", file=sys.stderr)
        sys.exit(1)

    random.seed(args.seed)

    # Assign turn length to each prompt
    turns = [1, 2, 3]
    weights = [TURN_DIST[t] for t in turns]
    by_turn: dict[int, list[dict]] = {1: [], 2: [], 3: []}
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
