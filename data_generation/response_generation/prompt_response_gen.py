#!/usr/bin/env python3
"""
Generate 2nd-turn (assistant) responses for data/train_data/formatted/2_turn.jsonl.

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
    USER_BENIGN,
    USER_HARMFUL,
    USER_MESSAGE_SYSTEM_PROMPTS,
)
from response_generation.load_tasks import (
    get_turn3_labels,
    load_turn1_label_lookup,
    sample_target_response,
    sample_target_user3,
)

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


def generate_user_message(
    client: OpenAI,
    model: str,
    system_prompt: str,
    conversation_messages: list[dict],
) -> str:
    """Generate the next user message given [user, assistant] so far."""
    conv_text = "\n\n".join(
        f"{m['role'].capitalize()}: {m.get('content', '')}"
        for m in conversation_messages
    )
    user_content = f"Conversation so far:\n\n{conv_text}\n\nGenerate the next USER message only (output the raw message text, no labels or quotes):"
    return generate_response(client, model, system_prompt, user_content)


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


def process_record_turn3(
    idx: int,
    client: OpenAI,
    model: str,
    system_prompt: str,
    record: dict,
    turn1_label: str,
    turn2_label: str,
    target_user3: str,
) -> tuple[int, dict | None]:
    """Generate turn 3 (second user message), append to messages, compute final label."""
    messages_in = record.get("messages") or []
    if len(messages_in) < 2:
        return idx, None
    category = record.get("category", "")

    try:
        user3_content = generate_user_message(client, model, system_prompt, messages_in)
    except Exception as e:
        print(f"  [batch idx {idx}] API error: {e}", file=sys.stderr)
        return idx, None

    if not user3_content:
        return idx, None

    messages_out = messages_in + [{"role": "user", "content": user3_content}]
    final_label = "harmful" if target_user3 == USER_HARMFUL else "unharmful"
    out_rec = {
        "messages": messages_out,
        "label": final_label,
        "convo_length": 3,
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
    parser.add_argument(
        "--eval",
        action="store_true",
        help="Use eval 2-turn distribution (50/50 H/B response per prompt label)",
    )
    parser.add_argument(
        "--eval-3turn",
        action="store_true",
        help="Process 3_turn.jsonl, generate turn 2 (first assistant response) with eval 3-turn distribution",
    )
    parser.add_argument(
        "--eval-3turn-turn3",
        action="store_true",
        help="Process 3_turn_turn2_completed.jsonl, generate turn 3 (second user message) with eval 3-turn distribution",
    )
    args = parser.parse_args()

    if args.eval_3turn_turn3:
        input_filename = "3_turn_turn2_completed.jsonl"
        output_filename = "3_turn_completed.jsonl"
    elif args.eval_3turn:
        input_filename = "3_turn.jsonl"
        output_filename = "3_turn_turn2_completed.jsonl"
    else:
        input_filename = INPUT_FILENAME
        output_filename = OUTPUT_FILENAME

    input_path = args.input_dir / input_filename
    output_path = args.output_dir / output_filename

    if not input_path.exists():
        print(f"Error: input not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Backend config
    hf_url = os.environ.get("HF_INFERENCE_ENDPOINT_URL", "").strip().rstrip("/")
    hf_token = os.environ.get("HF_TOKEN", "").strip()
    harmful_model = os.environ.get("HARMFUL_RESPONSE_MODEL", "richardyoung/qwen3-32b")
    benign_model = os.environ.get("BENIGN_RESPONSE_MODEL", "anthropic/claude-3-haiku")
    or_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
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
        print(f"Dual-model: harmful -> HF ({harmful_model}), benign -> OpenRouter ({benign_model})")
    else:
        if args.backend == "huggingface":
            if not hf_url or not hf_token:
                print("Error: HF_INFERENCE_ENDPOINT_URL and HF_TOKEN must be set", file=sys.stderr)
                sys.exit(1)
            hf_client = OpenAI(base_url=f"{hf_url}/v1", api_key=hf_token)
            or_client = None
            print(f"Single backend: HuggingFace ({harmful_model})")
        else:
            if not or_key:
                print("Error: OPENROUTER_API_KEY must be set", file=sys.stderr)
                sys.exit(1)
            hf_client = None
            or_client = OpenAI(base_url=or_base, api_key=or_key)
            print(f"Single backend: OpenRouter ({benign_model})")

    random.seed(args.seed)
    if args.eval_3turn_turn3:
        print("Using eval 3-turn turn 3: generate second user message, conditioned on (turn1, turn2) labels")
        turn1_jsonl = args.input_dir / "3_turn.jsonl"
        if not turn1_jsonl.exists():
            print(f"Error: need {turn1_jsonl} for turn1 label lookup", file=sys.stderr)
            sys.exit(1)
        turn1_lookup = load_turn1_label_lookup(turn1_jsonl)
        print(f"Loaded turn1 label lookup: {len(turn1_lookup)} entries")
        if or_client is None:
            print("Error: eval-3turn-turn3 requires OpenRouter (OPENROUTER_API_KEY)", file=sys.stderr)
            sys.exit(1)
    elif args.eval_3turn:
        print("Using eval 3-turn turn 2 distribution: H prompt 50/50, B prompt 60% benign 40% harmful")
    elif args.eval:
        print("Using eval 2-turn distribution: 50% harmful, 50% benign response per prompt label")

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
            if args.eval_3turn_turn3:
                tasks_t3: list[tuple[int, dict, str, str, str, str]] = []
                for j, rec in enumerate(batch):
                    labels = get_turn3_labels(rec, turn1_lookup)
                    if labels is None:
                        content_preview = (rec.get("messages") or [{}])[0].get("content", "")[:80]
                        print(f"  [skip] turn1 not in lookup: {content_preview}...", file=sys.stderr)
                        continue
                    turn1_label, turn2_label = labels
                    target_user3 = sample_target_user3(turn1_label, turn2_label)
                    system_prompt = USER_MESSAGE_SYSTEM_PROMPTS[target_user3]
                    if use_dual and hf_client is not None and or_client is not None:
                        client, model = (
                            (hf_client, harmful_model) if target_user3 == USER_HARMFUL
                            else (or_client, benign_model)
                        )
                    else:
                        client = or_client
                        model = benign_model
                    tasks_t3.append(
                        (batch_start + j, rec, turn1_label, turn2_label, target_user3, client, model, system_prompt)
                    )

                def _run_turn3_task(task: tuple) -> tuple[int, dict | None]:
                    (idx, rec, turn1_label, turn2_label, target_user3, client, model, system_prompt) = task
                    return process_record_turn3(
                        idx, client, model, system_prompt,
                        rec, turn1_label, turn2_label, target_user3,
                    )

                with ThreadPoolExecutor(max_workers=batch_size) as executor:
                    futures = [executor.submit(_run_turn3_task, task) for task in tasks_t3]
                    results: list[tuple[int, dict | None]] = []
                    for future in as_completed(futures):
                        idx, out_rec = future.result()
                        results.append((idx, out_rec))
            else:
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
                    target_type = (
                        RESPONSE_HARMFUL
                        if args.harmful_only
                        else sample_target_response(
                            prompt_label,
                            use_eval_dist=args.eval and not args.eval_3turn,
                            use_eval_3turn_turn2=args.eval_3turn,
                        )
                    )
                    system_prompt = SYSTEM_PROMPTS.get(target_type, SYSTEM_PROMPTS["compliance"])
                    conv_label = RESPONSE_TO_CONV_LABEL.get(target_type, "unharmful")
                    if use_dual and hf_client is not None and or_client is not None:
                        client, model = (hf_client, harmful_model) if target_type == RESPONSE_HARMFUL else (or_client, benign_model)
                    else:
                        client = hf_client or or_client
                        model = harmful_model if hf_client else benign_model
                    tasks.append((batch_start + j, rec, client, model, system_prompt, conv_label, user_content, category))

                with ThreadPoolExecutor(max_workers=batch_size) as executor:
                    futures = [
                        executor.submit(process_record, idx, client, model, system_prompt, conv_label, user_content, category)
                        for idx, _rec, client, model, system_prompt, conv_label, user_content, category in tasks
                    ]
                    results = []
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
