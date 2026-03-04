"""Export2TurnStep: Write generated 2-turn conversations to JSONL (OpenAI format with category)."""

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List

from distilabel.steps.base import Step, StepInput

from response_generation.config import (
    STATS_FILENAME,
    TRAIN_FORMATTED_DIR,
    TRAIN_JSONL_FILENAME,
)

if TYPE_CHECKING:
    from distilabel.typing import StepOutput


class Export2TurnStep(Step):
    """
    Step that appends 2-turn conversations to data/train_data/formatted/train.jsonl in OpenAI format.
    Each line: {"messages": [{"role": "user", "content": ...}, {"role": "assistant", "content": ...}], "label": ..., "convo_length": 2, "category": ...}
    """

    output_dir: Path | str = TRAIN_FORMATTED_DIR
    jsonl_filename: str = TRAIN_JSONL_FILENAME
    stats_filename: str = STATS_FILENAME
    total_tasks: int | None = None
    input_batch_size: int = 1

    @property
    def inputs(self) -> List[str]:
        return ["user_prompt", "model_response", "conv_label", "category", "target_response_type"]

    @property
    def outputs(self) -> List[str]:
        return ["user_prompt", "model_response", "conv_label", "category", "target_response_type"]

    def load(self) -> None:
        super().load()
        self._jsonl_handle = None
        self._stats: Dict[str, Any] = {
            "total": 0,
            "by_conv_label": Counter(),
            "by_category": Counter(),
            "by_target_response_type": Counter(),
            "by_category_label": defaultdict(lambda: {"harmful": 0, "unharmful": 0}),
        }

    def _get_jsonl_file(self):
        if self._jsonl_handle is None:
            out_dir = Path(self.output_dir) if isinstance(self.output_dir, str) else self.output_dir
            out_dir.mkdir(parents=True, exist_ok=True)
            filepath = out_dir / self.jsonl_filename
            self._jsonl_handle = open(filepath, "a", encoding="utf-8")
        return self._jsonl_handle

    def unload(self) -> None:
        super().unload()
        if self._jsonl_handle is not None:
            try:
                self._jsonl_handle.flush()
                self._jsonl_handle.close()
            except Exception:
                pass
            self._jsonl_handle = None

    def _write_stats(self) -> None:
        out_dir = Path(self.output_dir) if isinstance(self.output_dir, str) else self.output_dir
        stats_path = out_dir / self.stats_filename
        stats_serializable = {
            "total": self._stats["total"],
            "by_conv_label": dict(self._stats["by_conv_label"]),
            "by_category": dict(self._stats["by_category"]),
            "by_target_response_type": dict(self._stats["by_target_response_type"]),
            "by_category_label": {
                cat: dict(counts) for cat, counts in self._stats["by_category_label"].items()
            },
        }
        with open(stats_path, "w", encoding="utf-8") as f:
            json.dump(stats_serializable, f, indent=2)

    def process(self, inputs: StepInput) -> "StepOutput":
        for row in inputs:
            user_prompt = str(row.get("user_prompt") or "").strip()
            model_response = str(row.get("model_response") or "").strip()
            conv_label = str(row.get("conv_label") or "unharmful").strip()
            category = str(row.get("category") or "")
            target_type = str(row.get("target_response_type") or "")

            # Skip failed generations (empty model_response)
            if not model_response:
                continue

            rec = {
                "messages": [
                    {"role": "user", "content": user_prompt},
                    {"role": "assistant", "content": model_response},
                ],
                "label": conv_label,
                "convo_length": 2,
                "category": category,
            }
            f = self._get_jsonl_file()
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

            self._stats["total"] += 1
            self._stats["by_conv_label"][conv_label] += 1
            self._stats["by_category"][category] += 1
            self._stats["by_target_response_type"][target_type] += 1
            self._stats["by_category_label"][category][conv_label] += 1

        self._write_stats()

        total = self._stats["total"]
        if self.total_tasks is not None and self.total_tasks > 0:
            pct = 100 * total / self.total_tasks
            self._logger.info(f"📊 Exported {total:,}/{self.total_tasks:,} 2-turn conversations ({pct:.1f}%)")
        else:
            self._logger.info(f"📊 Exported {total:,} 2-turn conversations")

        yield inputs
