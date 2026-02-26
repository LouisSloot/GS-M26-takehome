"""LoadSeedsFromCSV GeneratorStep for the prompt expansion pipeline."""

import json
import random
from pathlib import Path
from typing import TYPE_CHECKING

from distilabel.steps.base import GeneratorStep

from expansion_pipeline.config import DEFAULT_DATA_DIR
from expansion_pipeline.seed_utils import load_all_seeds, sample_axes

if TYPE_CHECKING:
    from distilabel.typing import GeneratorStepOutput


class LoadSeedsFromCSV(GeneratorStep):
    """
    GeneratorStep that loads seed prompts from CSVs and emits expansion tasks.

    For each seed, creates exactly `num_variations_per_seed` tasks, each with
    1-3 randomly sampled axes according to the configured distributions.
    """

    data_dir: Path | str = DEFAULT_DATA_DIR
    num_variations_per_seed: int = 9
    seed: int | None = None
    max_tasks: int | None = None  # If set, truncate to this many tasks (for testing)

    @property
    def outputs(self) -> list[str]:
        return ["seed_prompt", "category", "label", "axes"]

    def process(self, offset: int = 0) -> "GeneratorStepOutput":
        if self.seed is not None:
            random.seed(self.seed)

        data_dir = Path(self.data_dir) if isinstance(self.data_dir, str) else self.data_dir
        seeds = load_all_seeds(data_dir)
        if not seeds:
            yield ([], True)
            return

        # Build expansion tasks: for each seed, create num_variations_per_seed rows
        tasks = []
        for s in seeds:
            for _ in range(self.num_variations_per_seed):
                axes = sample_axes()
                tasks.append({
                    "seed_prompt": s["seed_prompt"],
                    "category": s["category"],
                    "label": s["label"],
                    "axes": json.dumps(axes),
                })

        # Optionally shuffle for batch diversity
        random.shuffle(tasks)

        # Apply max_tasks cap (for testing / proof-of-concept)
        if self.max_tasks is not None:
            tasks = tasks[: self.max_tasks]

        # Apply offset (for resuming)
        tasks = tasks[offset:]

        batch_size = self.batch_size
        num_tasks = len(tasks)

        for i in range(0, num_tasks, batch_size):
            batch = tasks[i : i + batch_size]
            is_last = (i + batch_size) >= num_tasks
            yield (batch, is_last)
