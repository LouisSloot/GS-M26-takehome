#!/usr/bin/env python3
"""
Format eval expanded prompts to JSONL files.

Loads from data/test_data/expanded/{category}/{n}_turn/{harmful,unharmful}_prompts.csv
and writes to data/test_data/formatted/1_turn.jsonl, 2_turn.jsonl, 3_turn.jsonl.

No sampling—turn and label are determined by the directory structure.

Usage:
  python data_generation/test_scripts/format_eval_prompts.py
  python data_generation/test_scripts/format_eval_prompts.py --input-dir /path/to/expanded --output-dir /path/to/formatted
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "data_generation"))

from expansion_pipeline.seed_utils import load_all_seeds_from_eval_dir

DEFAULT_INPUT = REPO_ROOT / "data" / "test_data" / "expanded"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "test_data" / "formatted"


def main() -> int:
    parser = argparse.ArgumentParser(description="Format eval expanded prompts to JSONL by turn.")
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"Expanded prompts dir (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output dir for *_turn.jsonl (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args()

    input_dir = args.input_dir if args.input_dir.is_absolute() else REPO_ROOT / args.input_dir
    output_dir = args.output_dir if args.output_dir.is_absolute() else REPO_ROOT / args.output_dir

    if not input_dir.is_dir():
        print(f"Error: input dir not found: {input_dir}", file=sys.stderr)
        return 1

    seeds = load_all_seeds_from_eval_dir(input_dir)
    if not seeds:
        print("No prompts found.", file=sys.stderr)
        return 1

    # Group by turn_type (1, 2, 3)
    by_turn: dict[int, list[dict]] = {1: [], 2: [], 3: []}
    for s in seeds:
        t = s["turn_type"]
        if t in by_turn:
            by_turn[t].append(s)

    output_dir.mkdir(parents=True, exist_ok=True)

    for turn, items in sorted(by_turn.items()):
        if not items:
            continue
        out_path = output_dir / f"{turn}_turn.jsonl"
        with open(out_path, "w", encoding="utf-8") as f:
            for s in items:
                rec = {
                    "messages": [{"role": "user", "content": s["seed_prompt"]}],
                    "label": s["label"],
                    "convo_length": turn,
                    "category": s["category"],
                }
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"Wrote {len(items)} records to {out_path}")

    total = sum(len(items) for items in by_turn.values())
    print(f"Total: {total} records")

    return 0


if __name__ == "__main__":
    sys.exit(main())
