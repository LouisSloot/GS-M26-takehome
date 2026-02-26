"""
Steps 4-5: Load prepared JSONL, tokenize with DeBERTa (left truncation), PyTorch Dataset and DataLoaders.

Expects train_loop/data/train.jsonl and val.jsonl from prepare_data.py.
"""

import json
import sys
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import torch
from torch.utils.data import DataLoader, Dataset

from train_loop.config import (
    LABEL_TO_ID,
    MAX_LENGTH,
    TOKENIZER_NAME,
    TRAIN_JSONL,
    TRUNCATION_SIDE,
    VAL_JSONL,
)


def load_prepared_jsonl(path: Path) -> list[dict]:
    examples = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            examples.append(json.loads(line))
    return examples


class HarmClassificationDataset(Dataset):
    """PyTorch Dataset: returns input_ids, attention_mask, labels (0/1) for DeBERTa."""

    def __init__(
        self,
        examples: list[dict],
        tokenizer,
        max_length: int = MAX_LENGTH,
        truncation_side: str = TRUNCATION_SIDE,
        label_to_id: Optional[dict[str, int]] = None,
    ):
        self.examples = examples
        self.tokenizer = tokenizer
        self.max_length = max_length
        self.label_to_id = label_to_id or LABEL_TO_ID
        # Left truncation: keep the end of the sequence (final turn)
        self.tokenizer.truncation_side = truncation_side

    def __len__(self) -> int:
        return len(self.examples)

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        ex = self.examples[idx]
        text = ex["text"]
        label = self.label_to_id[ex["label"]]

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
            "labels": torch.tensor(label, dtype=torch.long),
        }


def get_tokenizer(
    tokenizer_name: str = TOKENIZER_NAME,
    truncation_side: str = TRUNCATION_SIDE,
):
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(tokenizer_name)
    tok.truncation_side = truncation_side
    return tok


def get_datasets(
    train_path: Path = TRAIN_JSONL,
    val_path: Path = VAL_JSONL,
    tokenizer=None,
    max_length: int = MAX_LENGTH,
) -> tuple[HarmClassificationDataset, HarmClassificationDataset]:
    """Load train and val JSONL, tokenize, return train and val Dataset objects."""
    if tokenizer is None:
        tokenizer = get_tokenizer()

    train_examples = load_prepared_jsonl(train_path)
    val_examples = load_prepared_jsonl(val_path)

    train_ds = HarmClassificationDataset(
        train_examples,
        tokenizer=tokenizer,
        max_length=max_length,
    )
    val_ds = HarmClassificationDataset(
        val_examples,
        tokenizer=tokenizer,
        max_length=max_length,
    )
    return train_ds, val_ds


def get_dataloaders(
    train_path: Path = TRAIN_JSONL,
    val_path: Path = VAL_JSONL,
    tokenizer=None,
    max_length: int = MAX_LENGTH,
    train_batch_size: int = 16,
    val_batch_size: Optional[int] = None,
    num_workers: int = 0,
) -> tuple[DataLoader, DataLoader]:
    """Build train and val DataLoaders. num_workers=0 is safe in Colab."""
    train_ds, val_ds = get_datasets(
        train_path=train_path,
        val_path=val_path,
        tokenizer=tokenizer,
        max_length=max_length,
    )
    if val_batch_size is None:
        val_batch_size = train_batch_size

    train_loader = DataLoader(
        train_ds,
        batch_size=train_batch_size,
        shuffle=True,
        num_workers=num_workers,
        pin_memory=True,
    )
    val_loader = DataLoader(
        val_ds,
        batch_size=val_batch_size,
        shuffle=False,
        num_workers=num_workers,
        pin_memory=True,
    )
    return train_loader, val_loader


if __name__ == "__main__":
    # Quick sanity check: load datasets and print one batch
    import sys

    if not TRAIN_JSONL.exists() or not VAL_JSONL.exists():
        print("Run prepare_data.py first to create train.jsonl and val.jsonl.", file=sys.stderr)
        sys.exit(1)

    print("Loading tokenizer and datasets...")
    train_ds, val_ds = get_datasets()
    print(f"Train size: {len(train_ds)}  Val size: {len(val_ds)}")

    loader, _ = get_dataloaders(train_batch_size=2)
    batch = next(iter(loader))
    print("Batch keys:", batch.keys())
    print("input_ids shape:", batch["input_ids"].shape)
    print("labels:", batch["labels"].tolist())
