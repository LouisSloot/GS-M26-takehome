# DeBERTa-v3-base finetuning pipeline for binary harm classification

High-level pipeline for full finetuning of `microsoft/deberta-v3-base` on your 1-turn + 2-turn conversation data (~10–15k examples) for binary harmful/unharmful classification. Assumes Colab with A100.

---

## 1. Data loading and merging

**Inputs**

- `data/train_data/formatted/1_turn.jsonl` — user-only; `messages`: `[{role: "user", content}]`; `label`, `category`, `convo_length: 1`
- `data/train_data/formatted/2_turn_completed.jsonl` — user + assistant; same schema with `convo_length: 2`

**Steps**

1. Load both JSONL files; filter to rows that have a valid `label` in `{"harmful", "unharmful"}`.
2. For 2-turn: use only rows where the assistant message exists (no empty or placeholder). If you later merge `2_turn.jsonl`, exclude rows that are still “pending” (e.g. no `assistant` content).
3. Optional: keep `category` for stratified splits and analysis; do not use as a training target (binary harm only).

**Hiccup**

- **Incomplete 2-turn**: `2_turn.jsonl` is larger than `2_turn_completed.jsonl`; many rows may be mid-generation. Either train only on `2_turn_completed.jsonl` for now, or add a “completed” flag and filter so the training set is consistent.

---

## 2. Conversation → single string (serialization)

DeBERTa is a single-sequence encoder. Turn the conversation into one string per example.

**Recommended format** (as implemented in `prepare_data.py`)

- **1-turn**: use the user `content` as-is.
- **2-turn**: `"User: {user_content}\n\nAssistant: {assistant_content}"` (double newline between turns). Stick to this for train and inference.

**Why include the assistant**

- Harm label is for the *conversation*: e.g. harmful prompt + refusal → unharmful; harmful prompt + complying response → harmful. So the model must see both turns.

**Hiccup**

- **Length**: Many 2-turn assistant replies are long (e.g. 500+ words). With 512 subword limit you will truncate; see next section.

---

## 3. Train/validation split

- **Ratio**: e.g. 90/10 or 85/15.
- **Stratify** by `label` so train and val have similar harmful/unharmful ratio.
- **Optional**: Also stratify by `category` so each category is represented in both splits (helps if some categories are rare).
- **Shuffle**: Use a fixed seed for reproducibility.

**Hiccup**

- **Category imbalance**: Some categories may have few examples; stratification by both label and category can leave some val buckets tiny. If so, stratify only by label and accept that some categories may be under-represented in val.

---

## 4. Tokenization and length handling

- **Model**: `microsoft/deberta-v3-base` (HF `AutoTokenizer` + `AutoModelForSequenceClassification`).
- **Max length**: 512 tokens (DeBERTa default). No change needed unless you explicitly want to try 256 to save memory.

**Truncation strategy (important)**

- 512 tokens is often tight for long 2-turn conversations. Options:
  1. **Truncate from the right** (default): keep the start of the convo (user + start of assistant). Simple but can drop the part where the model “complies” or “refuses.”
  2. **Truncate from the left**: keep the end (tail of user + full assistant). Better when the *ending* (e.g. assistant response) is most predictive.
  3. **“Last turn only” for long convos**: if token count > 512, pass only `"User: ...\nAssistant: ..."` for the last exchange (and optionally a short prefix like “Previous context omitted”). Ensures the decision is made from the final turn.
  4. **Two-pass**: train one model on “user only” and one on “full convo” then ensemble (more complex; only if needed).

**Recommendation**

- **Truncate from the left** so the final turn is always kept: the monitor's classification is weighted toward the conversation's final turn (e.g. user's harmful ask = violation; assistant's refusal = not a violation). Use `truncation_side="left"` or take the last 512 token IDs.

**Implementation**

- Use `return_tensors="pt"`, `padding="longest"` (or `max_length`), `max_length=512`, and **left-side truncation** (`truncation_side="left"`). For batching, `padding="max_length"` is simpler and deterministic.

**Data note:** On `2_turn_completed.jsonl`, ~37% of 2-turn conversations exceed 512 tokens (median 394, p90 1080, max 1255). Use left truncation first; if results are poor, consider iterating (e.g. last-turn-only for long convos, or other compression).

---

## 5. Dataset and DataLoader

- Build a PyTorch `Dataset` that returns `input_ids`, `attention_mask`, `labels` (0/1 for unharmful/harmful).
- **Label mapping**: e.g. `unharmful → 0`, `harmful → 1` (or the reverse; be consistent with `id2label` in the config).
- **Batch size**: On A100 (40GB), DeBERTa-v3-base can typically use batch size 16–32; start with 16 and increase if memory allows.
- **Dataloader**: `num_workers=0` in Colab to avoid fork issues, or 2 if stable.

---

## 6. Model and training setup

- **Model**: `AutoModelForSequenceClassification.from_pretrained("microsoft/deberta-v3-base", num_labels=2)`.
- **Loss**: `CrossEntropyLoss` (standard for 2-class). If you have meaningful class imbalance (e.g. 60/40), use `weight=torch.tensor([w0, w1])` or `Trainer`’s `compute_loss` override with weighted CE.
- **Optimizer**: AdamW (e.g. lr 2e-5 for full finetuning).
- **Scheduler**: Linear warmup over 10% of steps then linear decay to 0 (or `get_linear_schedule_with_warmup`).
- **Epochs**: 2–3; with ~10–15k examples, more can overfit. Use early stopping on val loss or val F1 (e.g. 1–2 epochs patience).
- **Regularization**: Dropout is already in the model; 0.1 is typical. Weight decay 0.01 in AdamW.

**Hugging Face Trainer**

- Use `Trainer` with `TrainingArguments`: `output_dir`, `num_train_epochs`, `per_device_train_batch_size`, `learning_rate`, `warmup_ratio`, `logging_steps`, `eval_strategy="steps"`, `save_strategy="steps"`, `load_best_model_at_end=True`, `metric_for_best_model="eval_f1"` (or `eval_loss`). Pass a custom `compute_metrics` that returns accuracy, F1, precision, recall.

**Hiccup**

- **Overfitting**: Dataset size is moderate. If val loss goes up while train loss keeps decreasing, stop earlier or add more dropout / reduce epochs.

---

## 7. Evaluation and threshold

- **Metrics**: Accuracy, macro F1 (or binary F1 for the “harmful” class), precision, recall, ROC-AUC. Focus on F1 and precision/recall for the harmful class (depending on whether you care more about catching harm vs avoiding false positives).
- **Threshold**: Default 0.5. If the class distribution at inference differs from training, or you want to bias toward recall vs precision, tune the decision threshold on the validation set (e.g. maximize F1 or minimize a weighted cost).

**Hiccup**

- **Label imbalance**: Your notes target 60/40 benign/harmful; actual data may differ. Use stratified split and consider class weights or threshold tuning so the model isn’t biased toward the majority class.

---

## 8. Saving and inference

- **Save**: Full model + tokenizer (e.g. `model.save_pretrained(...)`, `tokenizer.save_pretrained(...)`), or push to Hub. Keep the same serialization format (e.g. `"User: ...\n\nAssistant: ..."`) in config/docs so inference matches training.
- **Inference**: Tokenize the serialized conversation (same max_length and truncation as training), run `model(**inputs).logits`, apply softmax and use the chosen threshold for the harmful class.

---

## 9. Checklist summary

| Step | Action | Potential issue |
|------|--------|------------------|
| 1 | Load 1_turn + 2_turn_completed; filter valid + completed | Incomplete 2-turn rows if merging 2_turn.jsonl |
| 2 | Serialize to "User: ...\n\nAssistant: ..." (double newline) | Consistency at inference |
| 3 | Stratified train/val by label (and optionally category) | Tiny val buckets if stratifying by category |
| 4 | Tokenize with max_length=512, **left truncation** (keep final turn) | Long 2-turn convos truncated; wrong part dropped |
| 5 | Dataset: input_ids, attention_mask, labels 0/1 | Label mapping consistent with config |
| 6 | DeBERTa-v3-base + 2-class head; AdamW 2e-5; 2–3 epochs; early stop; optional class weights | Overfitting; imbalance |
| 7 | Eval: F1, precision, recall, AUC; optional threshold tune on val | Default 0.5 suboptimal if distribution shift |
| 8 | Save model + tokenizer; document serialization | Inference format mismatch |

---

## 10. Implementation (actual files)

| Step | Script | Output |
|------|--------|--------|
| 1–3 | `train_loop/prepare_data.py` | `train_loop/data/train.jsonl`, `val.jsonl`, `split_stats.json` |
| 4–5 | `train_loop/dataset.py` | PyTorch Dataset, `get_dataloaders()`, `get_tokenizer()` |
| 6 | `train_loop/train.py` | Model checkpoints, tokenizer in `--output_dir` |
| 7–8 | `eval/eval_deberta.py` | AUPR, ROC-AUC, FPR@TPR; optional JSON output |

Config: `train_loop/config.py` (paths, `MAX_LENGTH=512`, `TRUNCATION_SIDE="left"`, label mapping).

---

## 11. Colab / environment

- **Dependencies**: `transformers`, `datasets`, `torch`, `scikit-learn` (for metrics), `accelerate` (optional, for `Trainer`).
- **GPU**: Use “GPU” runtime (A100 if available). DeBERTa-v3-base fits comfortably; you can try gradient accumulation if you need a larger effective batch size.
- **Reproducibility**: Set `transformers.set_seed(42)`, and fix `numpy`/`torch`/`random` seeds in the notebook.

---

## 12. Optional extensions

- **Category as auxiliary signal**: Train a single binary classifier (as above) first; optionally add an auxiliary head for category (multi-class) with a small weight to encourage category-aware representations (multi-task).
- **3-turn**: When `3_turn.jsonl` is ready, add the same serialization (e.g. `"User: ...\nAssistant: ...\nUser: ..."` or last two turns if length is an issue) and merge into the same training set so one model handles 1/2/3-turn.
- **Calibration**: If you care about confidence (e.g. for human review queue), add temperature scaling or Platt scaling on val after training.

This pipeline should get you from your current JSONL to a deployable DeBERTa harm classifier with minimal surprises; the main levers to tune are truncation strategy, class weighting, and decision threshold.
