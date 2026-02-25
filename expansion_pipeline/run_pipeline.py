"""Run the prompt expansion pipeline: LoadSeeds -> Expand -> Export."""

import argparse
import os
import shutil
from pathlib import Path

from distilabel.pipeline import Pipeline

from expansion_pipeline.config import DEFAULT_DATA_DIR, EXPANDED_OUTPUT_DIR
from expansion_pipeline.export_expanded import ExportExpandedStep
from expansion_pipeline.load_seeds import LoadSeedsFromCSV
from expansion_pipeline.prompt_expansion import PromptExpansionTask
from expansion_pipeline.seed_utils import load_all_seeds
from dotenv import load_dotenv
load_dotenv()


def create_pipeline(
    llm,
    data_dir: Path | str = DEFAULT_DATA_DIR,
    output_dir: Path | str = EXPANDED_OUTPUT_DIR,
    num_variations_per_seed: int = 9,
    seed: int | None = 42,
    batch_size: int = 2,
    max_tasks: int | None = None,
    pipeline_name: str = "prompt-expansion",
):
    """
    Create the expansion pipeline.

    Args:
        llm: distilabel LLM instance (e.g. OllamaLLM, vLLM, InferenceEndpointsLLM)
        data_dir: Path to seed_prompts/generated
        output_dir: Path to seed_prompts/expanded_all
        num_variations_per_seed: Number of variations per seed (default 9)
        seed: Random seed for reproducibility (or None)
        batch_size: Batch size for loading and expansion
    """
    # Use str() so distilabel's YAML cache can serialize/deserialize paths safely
    data_dir_str = str(data_dir)
    output_dir_str = str(output_dir)

    # Compute total tasks for progress logging
    seeds = load_all_seeds(Path(data_dir) if isinstance(data_dir, str) else data_dir)
    total_tasks = len(seeds) * num_variations_per_seed if seeds else 0
    if max_tasks is not None:
        total_tasks = min(total_tasks, max_tasks)

    with Pipeline(name=pipeline_name) as pipeline:
        load_seeds = LoadSeedsFromCSV(
            name="load_seeds",
            data_dir=data_dir_str,
            num_variations_per_seed=num_variations_per_seed,
            seed=seed,
            batch_size=batch_size,
            max_tasks=max_tasks,
        )

        expand = PromptExpansionTask(
            name="expand",
            llm=llm,
            input_batch_size=batch_size,
        )

        export = ExportExpandedStep(
            name="export",
            output_dir=output_dir_str,
            total_tasks=total_tasks,
            input_batch_size=batch_size,  # Match expand; default 50 would buffer 25 batches before first write
        )

        load_seeds >> expand >> export

    return pipeline


def _clear_pipeline_cache() -> None:
    """Remove cached pipeline config so export uses current input_batch_size."""
    cache_dir = Path.home() / ".cache" / "distilabel" / "pipelines" / "prompt-expansion"
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
        print(f"Cleared pipeline cache: {cache_dir}")


if __name__ == "__main__":
    from distilabel.models import OpenAILLM

    # OpenRouter config: https://openrouter.ai/docs/features/models
    OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "anthropic/claude-3-haiku")
    OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "sk-or-v1-xxx")  # or use .env
    OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
    BATCH_SIZE = int(os.environ.get("EXPANSION_BATCH_SIZE", "16"))

    parser = argparse.ArgumentParser(description="Run prompt expansion pipeline")
    parser.add_argument(
        "--clear-pipeline-cache",
        action="store_true",
        help="Clear cached pipeline config before run (use once after code changes to export/step config)",
    )
    args = parser.parse_args()

    if args.clear_pipeline_cache:
        _clear_pipeline_cache()

    llm = OpenAILLM(
        model=OPENROUTER_MODEL,
        api_key=OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE_URL,
    )

    # Same logic as test pipeline; only output_dir, max_tasks, and pipeline_name differ
    pipeline = create_pipeline(
        llm=llm,
        data_dir=str(DEFAULT_DATA_DIR),
        output_dir=str(EXPANDED_OUTPUT_DIR),
        num_variations_per_seed=9,
        seed=42,
        batch_size=BATCH_SIZE,
        max_tasks=None,  # Full run, no limit
        pipeline_name="prompt-expansion",
    )
    pipeline.run(use_cache=False)
