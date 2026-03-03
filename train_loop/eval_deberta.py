#!/usr/bin/env python3
"""
Evaluate trained DeBERTa classifier on eval dataset.

Loads a local DeBERTa checkpoint, runs inference on test_data_outputs/formatted/*.jsonl,
and reports: AUPR, ROC-AUC, FPR @ TPR 90%, FPR @ TPR 95%.
Also outputs a 10-sample subset of predicted probabilities for deliverables.

Usage:
  python train_loop/eval_deberta.py --model_path outputs/deberta-harm-v1
  python train_loop/eval_deberta.py --model_path outputs/deberta-harm-v1/checkpoint-2200 --data_dir test_data_outputs/formatted
  python train_loop/eval_deberta.py --model_path outputs/deberta-harm-v1 --max_samples 500 --output results/eval_deberta.json
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch
from sklearn.metrics import (
    average_precision_score,
    roc_auc_score,
    roc_curve,
)
from torch.utils.data import DataLoader, Dataset
from transformers import AutoModelForSequenceClassification, AutoTokenizer

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from train_loop.config import (
    LABEL_TO_ID,
    MAX_LENGTH,
    TRUNCATION_SIDE,
)


def serialize_messages(messages: list[dict]) -> str:
    """Convert messages to 'User: ... \\n\\n Assistant: ...' format (same as training)."""
    parts = []
    for m in messages:
        role = (m.get("role") or "user").capitalize()
        content = (m.get("content") or "").strip()
        parts.append(f"{role}: {content}")
    return "\n\n".join(parts)


def load_jsonl(path: Path) -> list[dict]:
    examples = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            examples.append(json.loads(line))
    return examples


class EvalDataset(Dataset):
    """Dataset that yields tokenized text for inference."""

    def __init__(self, examples: list[dict], tokenizer, max_length: int = MAX_LENGTH):
        self.examples = examples
        self.tokenizer = tokenizer
        self.max_length = max_length
        tokenizer.truncation_side = TRUNCATION_SIDE

    def __len__(self) -> int:
        return len(self.examples)

    def __getitem__(self, idx: int) -> dict:
        ex = self.examples[idx]
        messages = ex.get("messages", [])
        text = serialize_messages(messages) if messages else ""
        enc = self.tokenizer(
            text,
            max_length=self.max_length,
            padding="max_length",
            truncation=True,
            return_tensors="pt",
        )
        return {
            "input_ids": enc["input_ids"].squeeze(0),
            "attention_mask": enc["attention_mask"].squeeze(0),
        }


@torch.no_grad()
def run_inference(
    model,
    dataloader: DataLoader,
    device: torch.device,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (probs_harmful, labels, valid_mask)."""
    model.eval()
    all_probs = []

    for batch in dataloader:
        input_ids = batch["input_ids"].to(device)
        attention_mask = batch["attention_mask"].to(device)
        logits = model(input_ids=input_ids, attention_mask=attention_mask).logits
        probs = torch.softmax(logits, dim=1)
        prob_harmful = probs[:, LABEL_TO_ID["harmful"]].cpu().numpy()
        all_probs.append(prob_harmful)

    probs_arr = np.concatenate(all_probs)
    labels = np.array([
        LABEL_TO_ID.get((ex.get("label") or "").strip().lower(), -1)
        for ex in dataloader.dataset.examples
    ])
    # Filter to valid labels only for metric computation
    valid = labels >= 0
    return probs_arr, labels, valid


def fpr_at_tpr(y_true: np.ndarray, y_prob: np.ndarray, tpr_target: float) -> float:
    """Compute FPR at the threshold where TPR >= tpr_target."""
    fpr, tpr, _ = roc_curve(y_true, y_prob, pos_label=1)
    idx = np.searchsorted(tpr, tpr_target, side="left")
    if idx >= len(fpr):
        return float(fpr[-1])
    return float(fpr[idx])


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate DeBERTa classifier on eval dataset")
    parser.add_argument(
        "--model_path",
        type=Path,
        default=REPO_ROOT / "outputs" / "deberta-harm-v1",
        help="Path to DeBERTa checkpoint (default: outputs/deberta-harm-v1)",
    )
    parser.add_argument(
        "--data_dir",
        type=Path,
        default=REPO_ROOT / "test_data_outputs" / "formatted",
        help="Directory containing *_turn.jsonl (default: test_data_outputs/formatted)",
    )
    parser.add_argument(
        "--files",
        nargs="+",
        default=["1_turn", "2_turn", "3_turn"],
        help="JSONL filenames without .jsonl",
    )
    parser.add_argument(
        "--batch_size",
        type=int,
        default=32,
        help="Batch size for inference",
    )
    parser.add_argument(
        "--max_samples",
        type=int,
        default=None,
        help="Limit samples for quick runs",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write results JSON (metrics + 10-sample subset)",
    )
    parser.add_argument(
        "--n_sample_display",
        type=int,
        default=10,
        help="Number of samples to include in output (default: 10)",
    )
    args = parser.parse_args()

    model_path = args.model_path if args.model_path.is_absolute() else REPO_ROOT / args.model_path
    data_dir = args.data_dir if args.data_dir.is_absolute() else REPO_ROOT / args.data_dir

    if not model_path.exists():
        print(f"Error: model path not found: {model_path}", file=sys.stderr)
        return 1
    if not data_dir.is_dir():
        print(f"Error: data dir not found: {data_dir}", file=sys.stderr)
        return 1

    # Resolve checkpoint: use checkpoint-N if model_path doesn't have config.json
    if not (model_path / "config.json").exists():
        checkpoints = sorted(model_path.glob("checkpoint-*/config.json"))
        if checkpoints:
            model_path = checkpoints[-1].parent
        else:
            print(f"Error: no config.json in {model_path}", file=sys.stderr)
            return 1

    # Load eval data
    examples = []
    for name in args.files:
        path = data_dir / f"{name}.jsonl"
        if not path.exists():
            print(f"Warning: {path} not found, skipping", file=sys.stderr)
            continue
        loaded = load_jsonl(path)
        examples.extend(loaded)
        print(f"Loaded {len(loaded)} from {path}")

    if not examples:
        print("No examples to evaluate.", file=sys.stderr)
        return 1

    if args.max_samples is not None:
        examples = examples[: args.max_samples]
        print(f"Limited to {len(examples)} samples")

    # Load model and tokenizer
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tokenizer = AutoTokenizer.from_pretrained(str(model_path))
    model = AutoModelForSequenceClassification.from_pretrained(str(model_path))
    model.to(device)

    dataset = EvalDataset(examples, tokenizer)
    dataloader = DataLoader(dataset, batch_size=args.batch_size, shuffle=False)

    probs, labels, valid = run_inference(model, dataloader, device)
    probs_valid = probs[valid]
    labels_valid = labels[valid]
    examples_valid = [ex for ex, v in zip(examples, valid) if v]

    if len(labels_valid) == 0:
        print("No valid labels.", file=sys.stderr)
        return 1

    aupr = average_precision_score(labels_valid, probs_valid, pos_label=1)
    roc_auc = roc_auc_score(labels_valid, probs_valid)
    fpr_90 = fpr_at_tpr(labels_valid, probs_valid, 0.90)
    fpr_95 = fpr_at_tpr(labels_valid, probs_valid, 0.95)

    print(f"\n--- DeBERTa Eval ({model_path}) ---")
    print(f"  Samples: {len(labels_valid)}")
    print(f"  AUPR: {aupr:.4f}")
    print(f"  ROC-AUC: {roc_auc:.4f}")
    print(f"  FPR @ TPR 90%: {fpr_90:.4f}")
    print(f"  FPR @ TPR 95%: {fpr_95:.4f}")

    # 10-sample subset for deliverables
    n_sample = min(args.n_sample_display, len(examples_valid))
    indices = np.linspace(0, len(examples_valid) - 1, n_sample, dtype=int)
    sample_results = []
    for i in indices:
        ex = examples_valid[i]
        text = serialize_messages(ex.get("messages", []))
        sample_results.append({
            "text_preview": text[:200] + "..." if len(text) > 200 else text,
            "label": ex.get("label"),
            "prob_harmful": float(probs_valid[i]),
        })
    print(f"\n--- {n_sample}-sample subset (predicted probabilities) ---")
    for s in sample_results:
        print(f"  label={s['label']} prob_harmful={s['prob_harmful']:.4f}")

    if args.output:
        out_path = args.output if args.output.is_absolute() else REPO_ROOT / args.output
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "model_path": str(model_path),
            "n_samples": len(labels_valid),
            "metrics": {"AUPR": aupr, "ROC_AUC": roc_auc, "FPR_at_TPR_90": fpr_90, "FPR_at_TPR_95": fpr_95},
            "sample_predictions": sample_results,
        }
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        print(f"\nWrote {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
