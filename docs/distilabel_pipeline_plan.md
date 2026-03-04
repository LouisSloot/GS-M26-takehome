# Distilabel Pipeline Plan: Prompt Expansion

## Overview

A distilabel pipeline that expands ~4.5k seed prompts into ~45k variations by applying 1–3 randomly sampled axes per expansion, repeated ~10 times per seed.

---

## Pipeline Architecture

```
┌─────────────────────────┐     ┌─────────────────────────────┐     ┌──────────────────┐
│  LoadSeedsFromCSV       │────▶│  PromptExpansionTask        │────▶│  ExportExpanded   │
│  (GeneratorStep)        │     │  (custom TextGeneration)    │     │  (optional)       │
└─────────────────────────┘     └─────────────────────────────┘     └──────────────────┘
         │                                    │
         │  seed_prompt, category, label      │  expanded_prompt, seed_prompt,
         │  + 10×(1-3 random axes)            │  category, label, axes_used
         ▼                                    ▼
    ~45k rows in batches                  ~45k expanded prompts
```

---

## Step 1: `LoadSeedsFromCSV` (GeneratorStep)

**Purpose**: Load all seed prompts from the 18 CSVs (9 categories × harmful/unharmful), create 10 expansion tasks per seed with randomly sampled axes.

**Data source**: `data/train_data/raw_seeds/<Category>/harmful_prompts.csv` and `unharmful_prompts.csv` (default `--data-dir` is `data/train_data/raw_seeds/generated`; pass `--data-dir data/train_data/raw_seeds` if seeds live directly under `raw_seeds`)

**Category folder mapping** (from `categories.txt`):

- Child_Sexual_Abuse_and_Exploitation_and_Sex_Crimes
- Self-Harm_and_Suicide
- Illegal_Activities_and_Violent_Crimes
- Intellectual_Property_or_Copyright_Violations
- Privacy_or_PII_Violations
- Defamation_Libel_or_Slander
- Defrauding_Scamming_Spamming_or_Phishing
- Espionage_Spying_Stalking_Hacking_or_Doxing
- CBRN

**Output columns**:
| Column | Type | Description |
|-------------|--------|--------------------------------------------------|
| `seed_prompt` | str | Original prompt text |
| `category` | str | Category name (folder name) |
| `label` | str | `"harmful"` or `"unharmful"` |
| `axes` | str | JSON array of 1–3 axis names, e.g. `["Hypothetical", "Casual / Conversational"]` |

**Logic**:

1. For each category folder, read `harmful_prompts.csv` and `unharmful_prompts.csv`.
2. For each prompt row:
   - Sample `num_axes` ∈ {1, 2, 3} (30%/50%/20%).
   - Sample `num_axes` distinct axes from the full list (see below), one per category if possible.
   - Emit 9 rows per seed (default `num_variations_per_seed`): `{seed_prompt, category, label, axes}`.
3. Optionally shuffle all rows for better batch diversity.
4. Yield in batches of `batch_size` (e.g. 32–64).

**Axis taxonomy** (from `expansion_pipeline/config.py`):

```python
AXES = {
    "intent": ["Direct", "Hypothetical", "Fictional", "Educational", "Professional", "Inverse/Reverse Psychology"],
    "delivery": ["Highly specific and technical", "Vague and broad", "Implicit/Coded"],
    "style": ["Formal", "Casual", "Non-native phrasing", "Overly verbose", "Terse"],
    "emotional": ["Neutral", "Urgent", "Aggressive", "Flattering", "Guilt-tripping"],
    "format": ["Code", "Social Media Post", "Step-by-step tutorial or bulleted list", "Formal essay or email"],
}
```

**Sampling strategy**: For each expansion, pick 1–3 axes such that no two come from the same category (e.g. don’t pick both "Overly verbose" and "Terse"). Flatten the full list and sample without replacement from different categories.

---

## Step 2: `PromptExpansionTask` (custom TextGeneration)

**Purpose**: For each `{seed_prompt, category, label, axes}`, ask the LLM to rewrite the prompt according to the axes while preserving intent and label.

**Inherits**: `TextGeneration` (or equivalent base task).

**Input columns**: `seed_prompt`, `category`, `label`, `axes`

**Output columns**: `expanded_prompt`, `seed_prompt`, `category`, `label`, `axes`

**System prompt** (concise):

```
You are a data augmentation assistant. Your task is to rewrite user prompts in different styles while preserving their exact intent and pragmatic function (request vs. question vs. informational).

CRITICAL: Do not change whether the prompt is a harmful request or an innocuous question. If the original asks "why is X illegal?" do not rewrite it as "how do I do X?". Preserve the label.
```

**User prompt template**:

```
Rewrite the following user prompt according to these variation axes: {axes}

Original prompt: "{seed_prompt}"

Category: {category}
Label: {label}

Output ONLY the rewritten prompt, nothing else. The rewritten prompt must:
1. Preserve the exact intent and label of the original
2. Apply all specified axes (framing, delivery, style, emotional tone, or output format)
3. Be a single coherent user message
```

**`format_input`**: Build chat with system + user prompt, substituting `{axes}`, `{seed_prompt}`, `{category}`, `{label}`. Parse `axes` from JSON string to human-readable list for the prompt.

**`format_output`**: LLM response is the expanded prompt. Strip whitespace, validate non-empty. Return `{expanded_prompt: response, seed_prompt, category, label, axes}`.

**LLM**: Llama 3.1-8B-Instruct via one of:

- `vLLM` (local)
- `TransformersLLM` (local)
- `InferenceEndpointsLLM` (Hugging Face)
- `TogetherLLM` / `GroqLLM` (hosted)

**Generation kwargs**: `temperature=0.7` (some diversity), `max_new_tokens=256`.

---

## Step 3: ExportExpandedStep (implemented)

**Purpose**: Write expanded prompts to CSV and track distribution stats. For `structure="flat"`: `data/train_data/raw_seeds/expanded_all/<Category>/{harmful,unharmful}_prompts.csv`. For `structure="eval"`: `data/test_data/expanded/<Category>/<n>_turn/{harmful,unharmful}_prompts.csv`.

**Output files**:

- `data/train_data/raw_seeds/expanded_all/<Category>/harmful_prompts.csv` (flat) – one expanded prompt per line
- `data/train_data/raw_seeds/expanded_all/<Category>/unharmful_prompts.csv` (flat)
- `data/test_data/expanded/<Category>/<n>_turn/{harmful,unharmful}_prompts.csv` (eval)
- `expansion_stats.json` in the output dir – distribution stats (total, by_category, by_label, by_category_label, by_num_axes, axes_used)

---

## Implementation Notes

### File structure

```
data_generation/expansion_pipeline/
├── __init__.py
├── config.py              # AXES, DEFAULT_DATA_DIR, EXPANDED_OUTPUT_DIR, batch sizes
├── export_expanded.py     # ExportExpandedStep
├── load_seeds.py          # LoadSeedsFromCSV GeneratorStep
├── prompt_expansion.py    # PromptExpansionTask (custom TextGeneration)
├── run_pipeline.py        # Pipeline assembly + execution (load_seeds >> expand >> export)
└── seed_utils.py          # load_all_seeds, load_all_seeds_from_eval_dir, sample_axes
```

### Seed CSV format

- Harmful: one prompt per line, optional header `"prompt"` or raw text.
- Unharmful: same.
- Handle quoted CSV (prompts with commas).

### Deduplication (optional post-step)

After expansion, run a simple near-duplicate filter:

- Embed `expanded_prompt` with a small model (e.g. sentence-transformers).
- Drop rows with cosine similarity > 0.95 to any other.
- Can be a separate script, not necessarily in the distilabel DAG.

### Resume / checkpointing

Distilabel supports `offset` for GeneratorSteps. For long runs, consider:

- Saving progress periodically.
- Or splitting by category and running 9 smaller pipelines, then merging.

### Error handling

- Retry failed LLM calls (distilabel may have built-in retries).
- Log rows where `expanded_prompt` is empty or suspiciously similar to `seed_prompt`.
- Optionally validate that boundary-style unharmful prompts weren’t flipped.

---

## Runtime Parameters

| Parameter                 | Suggested | Description                        |
| ------------------------- | --------- | ---------------------------------- |
| `batch_size`              | 32        | Rows per batch from GeneratorStep  |
| `input_batch_size`        | 32        | Rows per batch for PromptExpansion |
| `temperature`             | 0.7       | LLM sampling temperature           |
| `max_new_tokens`          | 256       | Max length of expanded prompt      |
| `num_variations_per_seed` | 9         | Expansion tasks per seed (default) |
| `axes_per_variation`      | 1–3       | Random sample size                 |

---

## Execution

From repo root (requires `cd data_generation` or `PYTHONPATH`):

```bash
python data_generation/expansion_pipeline/run_pipeline.py [--structure flat|eval] [--data-dir PATH] [--output-dir PATH] [--num-variations 9] [--max-tasks N]
```

Or from code (run from `data_generation/` or with that in path):

```python
# run_pipeline.py
from distilabel.pipeline import Pipeline
from expansion_pipeline.load_seeds import LoadSeedsFromCSV
from expansion_pipeline.prompt_expansion import PromptExpansionTask
from expansion_pipeline.export_expanded import ExportExpandedStep
# Uses OpenAILLM via OpenRouter by default; set OPENROUTER_API_KEY

with Pipeline(name="prompt-expansion") as pipeline:
    load_seeds = LoadSeedsFromCSV(name="load_seeds", data_dir=..., num_variations_per_seed=9, batch_size=16)
    expand = PromptExpansionTask(name="expand", llm=llm, input_batch_size=16)
    export = ExportExpandedStep(name="export", output_dir=..., input_batch_size=16)
    load_seeds >> expand >> export
pipeline.run(use_cache=False)
```

---

## Downstream: Conversation Simulation

The expanded prompts feed into:

1. **sample_prompts_to_jsonl.py** — Assigns turn-length per prompt (train: 50% 1-turn, 50% 2-turn; eval: 25/35/40% for 1/2/3-turn), writes `data/train_data/formatted/1_turn.jsonl`, `2_turn.jsonl` (and eval equivalents). Reads from `data/train_data/raw_seeds/expanded_all` by default.
2. **response_generation/prompt_response_gen.py** — Generates assistant responses for 2-turn and 3-turn stubs via OpenRouter/HF endpoints.
3. Output: `data/train_data/formatted/1_turn.jsonl`, `2_turn_completed.jsonl` (and `3_turn_completed.jsonl` for eval).
