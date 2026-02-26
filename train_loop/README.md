# Train loop: JSONL → PyTorch dataset (steps 1–5)

## Steps

1. **prepare_data.py** (steps 1–3): Load `train_formatted/1_turn.jsonl` and `2_turn_completed.jsonl`, filter valid labels and completed 2-turn, serialize to single string (`User: ...\n\nAssistant: ...`), stratified train/val split.  
   **Output:** `train_loop/data/train.jsonl`, `val.jsonl`, `split_stats.json`.

2. **dataset.py** (steps 4–5): Load prepared JSONL, tokenize with DeBERTa (max_length=512, **left truncation**), expose PyTorch `Dataset` and `get_dataloaders()`.

## Usage

From repo root:

```bash
# 1. Generate train/val splits (run once after data updates)
python train_loop/prepare_data.py

# 2. In training code
from train_loop.dataset import get_dataloaders, get_tokenizer

train_loader, val_loader = get_dataloaders(train_batch_size=16, num_workers=0)
```

## Dependencies

- **prepare_data.py:** stdlib only.
- **dataset.py:** `torch`, `transformers`, and for DeBERTa tokenizer: `sentencepiece`, `protobuf`.

```bash
pip install torch transformers sentencepiece protobuf
```

## Config

Edit `train_loop/config.py` for paths, `VAL_RATIO`, `STRATIFY_BY_CATEGORY`, `MAX_LENGTH`, etc.
