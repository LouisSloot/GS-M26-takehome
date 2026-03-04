# GS-M26 Takehome: Harm Monitor

Binary harmful/unharmful classifier for multi-turn conversations, built with DeBERTa-v3-base fine-tuned on synthetic data across 9 harm categories (CBRN, Child Safety, Defamation, Defrauding, Espionage, Illegal Activities, IP/Copyright, Privacy, Self-Harm).

---

## Data Generation

1. **Seed prompts** — ~500 prompts per category, 60/40 harmful/unharmful, curated from `allenai/wildguardmix` + manual expansion.
2. **Expansion** — Distilabel pipeline (`expansion_pipeline/`) expands seeds via LLM along axes (intent, delivery, style, emotional tone, format) to ~45k variations:
   ```bash
   cd data_generation && python expansion_pipeline/run_pipeline.py [--structure flat|eval] [--max-tasks N]
   ```
3. **Turn assignment** — Sample prompts into train (50% 1-turn, 50% 2-turn) or eval (25/35/40% for 1/2/3-turn) JSONL stubs:
   ```bash
   python data_generation/sample_prompts_to_jsonl.py --distribution train
   python data_generation/sample_prompts_to_jsonl.py --distribution eval --output-dir data/test_data/formatted
   ```
4. **Response generation** — Generate assistant replies for 2-turn (and 3-turn) stubs via OpenRouter/HF endpoints:
   ```bash
   python data_generation/response_generation/prompt_response_gen.py [--backend openrouter]
   ```
   Output: `data/train_data/formatted/1_turn.jsonl`, `2_turn_completed.jsonl` (and test equivalents).

Requires: `OPENROUTER_API_KEY`, optional `HF_*` for Hugging Face endpoints. See `docs/distilabel_pipeline_plan.md` for expansion details.

---

## Training

1. **Prepare splits** — Load formatted JSONL, serialize conversations, stratified train/val:
   ```bash
   python train_loop/prepare_data.py
   ```
2. **Train** — Fine-tune DeBERTa-v3-base on binary harm classification:
   ```bash
   python train_loop/train.py --output_dir ./models/deberta_finetuned [--epochs 3] [--batch_size 16]
   ```

Data: `train_loop/data/train.jsonl`, `val.jsonl`. Config: `train_loop/config.py` (paths, max length 512, left truncation, etc.).

---

## Evaluation

Evaluate a trained checkpoint on the test set:

```bash
python eval/eval_deberta.py --model_path models/deberta_finetuned --output results/eval_deberta.json
```

Reports **AUPR**, **ROC-AUC**, **FPR @ TPR 90%**, **FPR @ TPR 95%** on `eval/data/test.jsonl`. Optional LLM baseline: `python eval/eval_baseline.py`.
