"""
Step 6: Full finetune DeBERTa-v3-base for binary harm classification.

Uses train_loop/data (train.jsonl, val.jsonl) from prepare_data.py + dataset.py.
Designed to run on Colab with A100.

Usage (Colab or local):
  python train_loop/train.py --output_dir ./outputs/deberta-harm-v1
  python train_loop/train.py --output_dir ./outputs/deberta-harm-v1 --epochs 3 --batch_size 32
"""

import argparse
import random
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import torch
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score
from transformers import (
    AutoModelForSequenceClassification,
    Trainer,
    TrainingArguments,
)
from transformers import set_seed as hf_set_seed

from train_loop.config import (
    ID_TO_LABEL,
    NUM_LABELS,
    TOKENIZER_NAME,
    TRAIN_JSONL,
    VAL_JSONL,
)
from train_loop.dataset import get_tokenizer, get_datasets


def set_seed(seed: int) -> None:
    """Set seeds for reproducibility (Colab-friendly)."""
    hf_set_seed(seed)
    torch.manual_seed(seed)
    np.random.seed(seed)
    random.seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def get_model(model_name: str = TOKENIZER_NAME, num_labels: int = NUM_LABELS):
    """Load DeBERTa-v3-base with binary classification head."""
    return AutoModelForSequenceClassification.from_pretrained(
        model_name,
        num_labels=num_labels,
        id2label=ID_TO_LABEL,
        label2id={v: k for k, v in ID_TO_LABEL.items()},
    )


def compute_metrics(eval_pred):
    """
    Return dict with accuracy, macro F1, precision, recall.
    eval_pred: EvalPrediction with predictions (logits) and label_ids.
    """
    predictions = np.argmax(eval_pred.predictions, axis=1)
    labels = eval_pred.label_ids
    return {
        "accuracy": float(accuracy_score(labels, predictions)),
        "f1": float(f1_score(labels, predictions, average="macro", zero_division=0)),
        "precision": float(precision_score(labels, predictions, average="macro", zero_division=0)),
        "recall": float(recall_score(labels, predictions, average="macro", zero_division=0)),
    }


def train(
    model,
    train_dataset,
    eval_dataset,
    tokenizer,
    output_dir: Path,
    *,
    num_epochs: int = 3,
    per_device_train_batch_size: int = 16,
    per_device_eval_batch_size: int = 16,
    learning_rate: float = 2e-5,
    warmup_ratio: float = 0.1,
    weight_decay: float = 0.01,
    logging_steps: int = 50,
    eval_strategy: str = "steps",
    eval_steps: int = 200,
    save_strategy: str = "steps",
    save_steps: int = 200,
    load_best_model_at_end: bool = True,
    metric_for_best_model: str = "eval_f1",
    greater_is_better: bool = True,
    num_workers: int = 0,  # Colab: 0 to avoid fork issues
    seed: int = 42,
    bf16: bool = True,  # A100 supports bf16 natively
) -> Trainer:
    """
    Configure Trainer and run training. Returns the Trainer after train().
    """
    set_seed(seed)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    args = TrainingArguments(
        output_dir=str(output_dir),
        num_train_epochs=num_epochs,
        per_device_train_batch_size=per_device_train_batch_size,
        per_device_eval_batch_size=per_device_eval_batch_size,
        learning_rate=learning_rate,
        warmup_ratio=warmup_ratio,
        weight_decay=weight_decay,
        logging_steps=logging_steps,
        eval_strategy=eval_strategy,
        eval_steps=eval_steps,
        save_strategy=save_strategy,
        save_steps=save_steps,
        load_best_model_at_end=load_best_model_at_end,
        metric_for_best_model=metric_for_best_model,
        greater_is_better=greater_is_better,
        bf16=bf16,
        fp16=False,
        dataloader_num_workers=num_workers,
        report_to="none",
    )

    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        tokenizer=tokenizer,
        compute_metrics=compute_metrics,
    )

    trainer.train()
    trainer.save_model(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))

    return trainer


def parse_args():
    parser = argparse.ArgumentParser(description="Finetune DeBERTa-v3-base for binary harm classification")
    parser.add_argument("--output_dir", type=str, default="./outputs/deberta-harm-v1", help="Model and checkpoint output directory")
    parser.add_argument("--data_dir", type=Path, default=None, help="Override dir containing train.jsonl, val.jsonl (default: train_loop/data)")
    parser.add_argument("--epochs", type=int, default=3, help="Number of training epochs")
    parser.add_argument("--batch_size", type=int, default=16, help="Per-device train batch size (A100: 16–32)")
    parser.add_argument("--lr", type=float, default=2e-5, help="Learning rate")
    parser.add_argument("--warmup_ratio", type=float, default=0.1, help="Warmup over this fraction of steps")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    # Add more as needed: --eval_steps, --save_steps, --fp16/--bf16, etc.
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    data_dir = args.data_dir or Path(__file__).resolve().parent / "data"
    train_jsonl = data_dir / "train.jsonl"
    val_jsonl = data_dir / "val.jsonl"

    if not train_jsonl.exists() or not val_jsonl.exists():
        print(f"Missing data: {train_jsonl} or {val_jsonl}. Run prepare_data.py first.", file=sys.stderr)
        return 1

    set_seed(args.seed)

    tokenizer = get_tokenizer()
    train_ds, val_ds = get_datasets(
        train_path=train_jsonl,
        val_path=val_jsonl,
        tokenizer=tokenizer,
    )
    model = get_model()

    train(
        model,
        train_ds,
        val_ds,
        tokenizer,
        output_dir,
        num_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        learning_rate=args.lr,
        warmup_ratio=args.warmup_ratio,
        seed=args.seed,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
