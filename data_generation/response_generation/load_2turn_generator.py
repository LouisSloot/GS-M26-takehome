"""Load2TurnTasks: GeneratorStep that emits 2-turn response generation tasks."""

import random
from pathlib import Path
from typing import TYPE_CHECKING

from distilabel.steps.base import GeneratorStep

from response_generation.config import SEED_PROMPTS_DIR
from response_generation.load_tasks import generate_tasks

if TYPE_CHECKING:
    from distilabel.typing import GeneratorStepOutput


class Load2TurnTasks(GeneratorStep):
    """
    GeneratorStep that loads prompts from seed_prompts and emits 2-turn tasks.
    Each task has user_prompt, category, prompt_label, target_response_type.
    """

    seed_dir: Path | str = SEED_PROMPTS_DIR
    num_tasks: int | None = None  # If None, use one task per prompt
    seed: int | None = 42

    @property
    def outputs(self) -> list[str]:
        return ["user_prompt", "target_response_type", "category", "prompt_label"]

    def process(self, offset: int = 0) -> "GeneratorStepOutput":
        if self.seed is not None:
            random.seed(self.seed)

        seed_dir = Path(self.seed_dir) if isinstance(self.seed_dir, str) else self.seed_dir
        task_iter = generate_tasks(
            seed_dir=seed_dir,
            num_tasks=self.num_tasks,
            seed=self.seed,
            shuffle=True,
        )
        tasks = list(task_iter)
        if not tasks:
            yield ([], True)
            return

        tasks = tasks[offset:]
        batch_size = self.batch_size
        num_tasks = len(tasks)

        for i in range(0, num_tasks, batch_size):
            batch = tasks[i : i + batch_size]
            is_last = (i + batch_size) >= num_tasks
            yield (batch, is_last)
