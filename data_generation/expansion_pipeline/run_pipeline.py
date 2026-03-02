"""Run the prompt expansion pipeline: LoadSeeds -> Expand -> Export."""

import argparse
import os
import shutil
import sys
from pathlib import Path

from distilabel.pipeline import Pipeline

from expansion_pipeline.config import DEFAULT_DATA_DIR, EXPANDED_OUTPUT_DIR
from expansion_pipeline.export_expanded import ExportExpandedStep
from expansion_pipeline.load_seeds import LoadSeedsFromCSV
from expansion_pipeline.prompt_expansion import PromptExpansionTask
from expansion_pipeline.seed_utils import load_all_seeds, load_all_seeds_from_eval_dir
from dotenv import load_dotenv
load_dotenv()


def create_pipeline(
    llm,
    data_dir: Path | str = DEFAULT_DATA_DIR,
    output_dir: Path | str = EXPANDED_OUTPUT_DIR,
    structure: str = "flat",
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
        data_dir: Path to seed prompts (flat: seed_prompts/generated, eval: test_data_outputs)
        output_dir: Path for expanded output
        structure: "flat" for train seeds, "eval" for eval seeds (category/n_turn/label)
        num_variations_per_seed: Number of variations per seed (default 9)
        seed: Random seed for reproducibility (or None)
        batch_size: Batch size for loading and expansion
    """
    # Use str() so distilabel's YAML cache can serialize/deserialize paths safely
    data_dir_str = str(data_dir)
    output_dir_str = str(output_dir)

    # Compute total tasks for progress logging
    data_path = Path(data_dir) if isinstance(data_dir, str) else data_dir
    seeds = load_all_seeds_from_eval_dir(data_path) if structure == "eval" else load_all_seeds(data_path)
    total_tasks = len(seeds) * num_variations_per_seed if seeds else 0
    if max_tasks is not None:
        total_tasks = min(total_tasks, max_tasks)

    with Pipeline(name=pipeline_name) as pipeline:
        load_seeds = LoadSeedsFromCSV(
            name="load_seeds",
            data_dir=data_dir_str,
            structure=structure,
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

    return pipeline, total_tasks, len(seeds) if seeds else 0


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
        "--data-dir",
        type=Path,
        default=None,
        help="Input directory (default: seed_prompts/generated for flat, test_data_outputs for eval)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory (default: seed_prompts/expanded_all for flat, test_data_outputs/expanded for eval)",
    )
    parser.add_argument(
        "--structure",
        choices=("flat", "eval"),
        default="flat",
        help="flat = train seeds {category}/{label}.csv; eval = {category}/{n}_turn/{label}.csv",
    )
    parser.add_argument(
        "--num-variations",
        type=int,
        default=9,
        help="Variations per seed (default: 9)",
    )
    parser.add_argument(
        "--max-tasks",
        type=int,
        default=None,
        help="Limit tasks (for testing)",
    )
    parser.add_argument(
        "--clear-pipeline-cache",
        action="store_true",
        help="Clear cached pipeline config before run (use once after code changes to export/step config)",
    )
    args = parser.parse_args()

    if args.clear_pipeline_cache:
        _clear_pipeline_cache()

    # Default paths by structure
    if args.structure == "eval":
        # Project root (expansion_pipeline -> data_generation -> project root)
        repo_root = Path(__file__).resolve().parent.parent.parent
        default_data = repo_root / "test_data_outputs" / "raw_seeds"  # seeds live here
        default_output = repo_root / "test_data_outputs" / "expanded"
    else:
        default_data = DEFAULT_DATA_DIR
        default_output = EXPANDED_OUTPUT_DIR

    data_dir = args.data_dir if args.data_dir is not None else default_data
    output_dir = args.output_dir if args.output_dir is not None else default_output

    llm = OpenAILLM(
        model=OPENROUTER_MODEL,
        api_key=OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE_URL,
    )

    pipeline, total_tasks, num_seeds = create_pipeline(
        llm=llm,
        data_dir=str(data_dir),
        output_dir=str(output_dir),
        structure=args.structure,
        num_variations_per_seed=args.num_variations,
        seed=42,
        batch_size=BATCH_SIZE,
        max_tasks=args.max_tasks,
        pipeline_name="prompt-expansion-eval" if args.structure == "eval" else "prompt-expansion",
    )

    print(f"Expansion pipeline: {num_seeds:,} seeds × {args.num_variations} variations = {total_tasks:,} tasks")
    print(f"Input:  {data_dir}")
    print(f"Output: {output_dir}")
    if total_tasks == 0:
        print("No tasks to run. Check that input dir has structure: {category}/1_turn,2_turn,3_turn/{harmful,unharmful}_prompts.csv")
        sys.exit(1)
    print("Running...")
    pipeline.run(use_cache=False)
    print()  # newline after \r progress
    print("Done.")
