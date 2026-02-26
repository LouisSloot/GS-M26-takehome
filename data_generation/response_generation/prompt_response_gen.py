#!/usr/bin/env python3
"""
Generate 2nd-turn (assistant) responses for train_formatted/2_turn.jsonl.

Reads 2_turn.jsonl (stubs: one user message per record). For each record:
- Samples target response type from conditional distribution (prompt label → compliance/overrefusal/harmful).
- Calls LLM with the appropriate system prompt.
- Appends completed record to 2_turn_completed.jsonl: messages = [user, assistant], label, convo_length=2, category.

Resume: if 2_turn_completed.jsonl exists, skips that many input lines and appends only new results.

Uses two models by default:
  - Harmful responses: HF Inference Endpoint (HF_* env vars)
  - Benign responses (compliance/overrefusal): OpenRouter (OPENROUTER_* env vars)

With --backend huggingface or --backend openrouter, uses a single backend for all responses.

  --harmful-only   Only process records with label "harmful" (e.g. to rebalance after HF endpoint outage).
  --start-line N   Start from 1-based line N in the input file; overrides resume-from-completed-file skip.

Usage:
  python scripts/prompt_response_gen.py
  python scripts/prompt_response_gen.py --backend openrouter
  python scripts/prompt_response_gen.py --harmful-only --start-line 1
"""

import argparse
import json
import os
import random
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI

from response_generation.config import (
    RESPONSE_HARMFUL,
    RESPONSE_TO_CONV_LABEL,
    SYSTEM_PROMPTS,
    TRAIN_FORMATTED_DIR,
)
from response_generation.load_tasks import sample_target_response

INPUT_FILENAME = "2_turn.jsonl"
OUTPUT_FILENAME = "2_turn_completed.jsonl"


def count_lines(path: Path) -> int:
    with open(path, encoding="utf-8") as f:
        return sum(1 for _ in f)


def load_input_lines(path: Path, skip: int) -> list[dict]:
    """Load records from JSONL, skipping first `skip` lines."""
    records = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i < skip:
                continue
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def generate_response(client: OpenAI, model: str, system_prompt: str, user_content: str) -> str:
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        max_tokens=1024,
    )
    content = (resp.choices[0].message.content or "").strip()
    return content


def process_record(
    idx: int,
    client: OpenAI,
    model: str,
    system_prompt: str,
    conv_label: str,
    user_content: str,
    category: str,
) -> tuple[int, dict | None]:
    """Process one record; return (index, out_rec) or (index, None) on failure."""
    try:
        assistant_content = generate_response(client, model, system_prompt, user_content)
    except Exception as e:
        print(f"  [batch idx {idx}] API error: {e}", file=sys.stderr)
        return idx, None

    if not assistant_content:
        return idx, None

    out_rec = {
        "messages": [
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": assistant_content},
        ],
        "label": conv_label,
        "convo_length": 2,
        "category": category,
    }
    return idx, out_rec


def main():
    parser = argparse.ArgumentParser(
        description="Generate 2nd-turn responses for 2_turn.jsonl, append to 2_turn_completed.jsonl"
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=TRAIN_FORMATTED_DIR,
        help="Directory containing 2_turn.jsonl",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=TRAIN_FORMATTED_DIR,
        help="Directory for 2_turn_completed.jsonl",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=int(os.environ.get("TWO_TURN_BATCH_SIZE", "8")),
        help="Number of concurrent requests per batch (higher = faster, risk of rate limits/OOM)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for sampling target response type",
    )
    parser.add_argument(
        "--max-records",
        type=int,
        default=None,
        help="Max records to process (default: all remaining after resume)",
    )
    parser.add_argument(
        "--backend",
        type=str,
        choices=("huggingface", "openrouter"),
        default=None,
        help="API backend (default: auto-detect from HF_INFERENCE_ENDPOINT_URL else OpenRouter)",
    )
    parser.add_argument(
        "--harmful-only",
        action="store_true",
        help="Only process records with label 'harmful'",
    )
    parser.add_argument(
        "--start-line",
        type=int,
        default=None,
        metavar="N",
        help="Start from 1-based line N in the input file (overrides resume skip)",
    )
    args = parser.parse_args()

    input_path = args.input_dir / INPUT_FILENAME
    output_path = args.output_dir / OUTPUT_FILENAME

    if not input_path.exists():
        print(f"Error: input not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Backend config
    hf_url = os.environ.get("HF_INFERENCE_ENDPOINT_URL", "").strip().rstrip("/")
    hf_token = os.environ.get("HF_TOKEN", "").strip()
    hf_model = os.environ.get("HF_MODEL", "richardyoung/qwen3-32b")
    or_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    or_model = os.environ.get("OPENROUTER_MODEL", "anthropic/claude-3-haiku")
    or_base = (os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1") or "").strip().rstrip("/")
    if not or_base.endswith("/v1"):
        or_base = f"{or_base}/v1" if or_base else "https://openrouter.ai/api/v1"

    # Single-backend mode (--backend set) or dual-model (default)
    use_dual = args.backend is None
    if use_dual:
        if not hf_url or not hf_token:
            print("Error: for dual-model mode, HF_INFERENCE_ENDPOINT_URL and HF_TOKEN must be set (harmful model)", file=sys.stderr)
            sys.exit(1)
        if not or_key:
            print("Error: for dual-model mode, OPENROUTER_API_KEY must be set (benign model)", file=sys.stderr)
            sys.exit(1)
        hf_client = OpenAI(base_url=f"{hf_url}/v1", api_key=hf_token)
        or_client = OpenAI(base_url=or_base, api_key=or_key)
        print(f"Dual-model: harmful -> HF ({hf_model}), benign -> OpenRouter ({or_model})")
    else:
        if args.backend == "huggingface":
            if not hf_url or not hf_token:
                print("Error: HF_INFERENCE_ENDPOINT_URL and HF_TOKEN must be set", file=sys.stderr)
                sys.exit(1)
            hf_client = OpenAI(base_url=f"{hf_url}/v1", api_key=hf_token)
            or_client = None
            print(f"Single backend: HuggingFace ({hf_model})")
        else:
            if not or_key:
                print("Error: OPENROUTER_API_KEY must be set", file=sys.stderr)
                sys.exit(1)
            hf_client = None
            or_client = OpenAI(base_url=or_base, api_key=or_key)
            print(f"Single backend: OpenRouter ({or_model})")

    random.seed(args.seed)

    if args.start_line is not None:
        n_skip = max(0, args.start_line - 1)
        print(f"Start line {args.start_line}: skipping first {n_skip} input lines")
    else:
        n_skip = 0
        if output_path.exists():
            n_skip = count_lines(output_path)
            print(f"Resume: skipping first {n_skip} input lines (already in {output_path})")

    records = load_input_lines(input_path, n_skip)
    if args.harmful_only:
        before = len(records)
        records = [r for r in records if r.get("label") == "harmful"]
        print(f"Harmful-only: {len(records)}/{before} records")
    if args.max_records is not None:
        records = records[: args.max_records]

    total = len(records)
    if total == 0:
        print("Nothing to do.")
        return

    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_file = open(output_path, "a", encoding="utf-8")
    n_written = 0
    batch_size = args.batch_size

    try:
        for batch_start in range(0, total, batch_size):
            batch = records[batch_start : batch_start + batch_size]
            batch_end = batch_start + len(batch)

            # Pre-compute tasks in main thread (deterministic sampling order)
            tasks: list[tuple[int, OpenAI, str, str, str, str, str]] = []
            for j, rec in enumerate(batch):
                messages_in = rec.get("messages") or []
                if not messages_in or messages_in[0].get("role") != "user":
                    continue
                user_content = (messages_in[0].get("content") or "").strip()
                if not user_content:
                    continue
                prompt_label = rec.get("label", "unharmful")
                category = rec.get("category", "")
                target_type = RESPONSE_HARMFUL if args.harmful_only else sample_target_response(prompt_label)
                system_prompt = SYSTEM_PROMPTS.get(target_type, SYSTEM_PROMPTS["compliance"])
                conv_label = RESPONSE_TO_CONV_LABEL.get(target_type, "unharmful")
                if use_dual and hf_client is not None and or_client is not None:
                    client, model = (hf_client, hf_model) if target_type == RESPONSE_HARMFUL else (or_client, or_model)
                else:
                    client = hf_client or or_client
                    model = hf_model if hf_client else or_model
                tasks.append((batch_start + j, rec, client, model, system_prompt, conv_label, user_content, category))

            with ThreadPoolExecutor(max_workers=batch_size) as executor:
                futures = [
                    executor.submit(process_record, idx, client, model, system_prompt, conv_label, user_content, category)
                    for idx, _rec, client, model, system_prompt, conv_label, user_content, category in tasks
                ]
                results: list[tuple[int, dict | None]] = []
                for future in as_completed(futures):
                    idx, out_rec = future.result()
                    results.append((idx, out_rec))

            # Sort by index and write in order (preserves input->output mapping)
            results.sort(key=lambda x: x[0])
            for idx, out_rec in results:
                if out_rec is not None:
                    out_file.write(json.dumps(out_rec, ensure_ascii=False) + "\n")
                    n_written += 1
            out_file.flush()

            if batch_end % 100 <= len(batch) or batch_end == total:
                print(f"  {batch_end}/{total}")

    finally:
        out_file.close()

    print(f"Done. Wrote {n_written} records to {output_path}")


if __name__ == "__main__":
    main()
