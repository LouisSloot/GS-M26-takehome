"""ExportExpandedStep: Write expanded prompts to CSV files and track distribution stats."""

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List

from distilabel.steps.base import Step, StepInput

from expansion_pipeline.config import EXPANDED_OUTPUT_DIR, STATS_FILENAME

if TYPE_CHECKING:
    from distilabel.typing import StepOutput


class ExportExpandedStep(Step):
    """
    Step that writes expanded prompts to data/train_data/raw_seeds/expanded_all/<category>/<label>_prompts.csv
    and tracks distribution stats to expansion_stats.json.
    """

    output_dir: Path | str = EXPANDED_OUTPUT_DIR
    stats_filename: str = STATS_FILENAME
    total_tasks: int | None = None  # If set, used for progress logging (N/total)
    input_batch_size: int = 1  # Write every batch; Step default 50 would buffer 25 batches

    @property
    def inputs(self) -> List[str]:
        return ["expanded_prompt", "seed_prompt", "category", "label", "axes"]

    @property
    def outputs(self) -> List[str]:
        return ["expanded_prompt", "seed_prompt", "category", "label", "axes"]

    def load(self) -> None:
        super().load()
        self._file_handles: Dict[str, tuple] = {}  # key -> (file_obj, csv.writer)
        self._last_seed_by_file: Dict[str, str] = {}  # file_key -> last seed_prompt written (for original, 1, 2, 3 order)
        self._stats: Dict[str, Any] = {
            "total": 0,
            "by_category": Counter(),
            "by_label": Counter(),
            "by_category_label": defaultdict(lambda: {"harmful": 0, "unharmful": 0}),
            "by_num_axes": Counter(),
            "axes_used": Counter(),
        }

    def _get_writer(self, category: str, label: str, turn_type: int | None = None) -> csv.writer:
        if turn_type is not None:
            key = f"{category}/{turn_type}_turn/{label}"
        else:
            key = f"{category}/{label}"
        if key not in self._file_handles:
            out_dir = Path(self.output_dir) if isinstance(self.output_dir, str) else self.output_dir
            if turn_type is not None:
                category_dir = out_dir / category / f"{turn_type}_turn"
            else:
                category_dir = out_dir / category
            category_dir.mkdir(parents=True, exist_ok=True)
            filepath = category_dir / f"{label}_prompts.csv"
            f = open(filepath, "w", newline="", encoding="utf-8")
            writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
            self._file_handles[key] = (f, writer)
        return self._file_handles[key][1]

    def unload(self) -> None:
        """Flush and close all CSV file handles so data is written to disk."""
        super().unload()
        for key in list(self._file_handles.keys()):
            f, _ = self._file_handles.pop(key, (None, None))
            if f is not None:
                try:
                    f.flush()
                    f.close()
                except Exception:
                    pass

    def _write_stats(self) -> None:
        out_dir = Path(self.output_dir) if isinstance(self.output_dir, str) else self.output_dir
        stats_path = out_dir / self.stats_filename

        # Convert to JSON-serializable format
        stats_serializable = {
            "total": self._stats["total"],
            "by_category": dict(self._stats["by_category"]),
            "by_label": dict(self._stats["by_label"]),
            "by_category_label": {
                cat: dict(counts)
                for cat, counts in self._stats["by_category_label"].items()
            },
            "by_num_axes": dict(self._stats["by_num_axes"]),
            "axes_used": dict(self._stats["axes_used"]),
        }

        with open(stats_path, "w", encoding="utf-8") as f:
            json.dump(stats_serializable, f, indent=2)

    def _get_expanded_text(self, row: Dict[str, Any]) -> str:
        """Extract expanded prompt, with fallbacks for distilabel metadata / seed."""
        expanded = row.get("expanded_prompt")
        if expanded is not None and isinstance(expanded, list):
            expanded = expanded[0] if expanded else ""
        expanded = str(expanded or "").strip()
        if not expanded:
            meta = row.get("distilabel_metadata") or {}
            raw = meta.get("raw_output_expand")
            expanded = str(raw).strip() if raw else ""
        if not expanded:
            expanded = str(row.get("seed_prompt") or "").strip()
        if not expanded:
            # Last resort: any non-empty string value that looks like a prompt
            for v in row.values():
                if isinstance(v, str) and len(v) > 10 and v.strip():
                    expanded = v.strip()
                    break
        return expanded

    def process(self, inputs: StepInput) -> "StepOutput":
        _warned_empty = False
        for row in inputs:
            expanded = self._get_expanded_text(row)
            if not expanded and not _warned_empty:
                _warned_empty = True
                keys = list(row.keys()) if isinstance(row, dict) else []
                self._logger.warning(
                    f"⚠️ Export received row with empty expanded text. "
                    f"Row keys: {keys}. Check expand step output / distilabel_metadata."
                )
            category = row.get("category", "")
            label = row.get("label", "")
            axes_str = row.get("axes", "[]")
            turn_type = row.get("turn_type")  # Present when structure="eval"
            seed_prompt = str(row.get("seed_prompt") or "").strip()

            # File key for "last seed" tracking (same as _get_writer key)
            if turn_type is not None:
                file_key = f"{category}/{turn_type}_turn/{label}"
            else:
                file_key = f"{category}/{label}"

            writer = self._get_writer(category, label, turn_type)
            # Per-seed order: original, then variation 1, 2, 3 (load step emits in order)
            last_seed = self._last_seed_by_file.get(file_key)
            if seed_prompt and seed_prompt != last_seed:
                writer.writerow([seed_prompt])
                self._last_seed_by_file[file_key] = seed_prompt
            writer.writerow([expanded])

            # Update stats
            self._stats["total"] += 1
            self._stats["by_category"][category] += 1
            self._stats["by_label"][label] += 1
            self._stats["by_category_label"][category][label] += 1

            try:
                axes = json.loads(axes_str) if isinstance(axes_str, str) else axes_str
                self._stats["by_num_axes"][len(axes)] += 1
                for ax in axes:
                    self._stats["axes_used"][ax] += 1
            except (json.JSONDecodeError, TypeError):
                pass

        self._write_stats()

        # Show progress (stdout so it's always visible)
        total = self._stats["total"]
        if self.total_tasks is not None and self.total_tasks > 0:
            pct = 100 * total / self.total_tasks
            print(f"\r  Expanded {total:,}/{self.total_tasks:,} ({pct:.1f}%)", end="", flush=True)
            self._logger.info(
                f"📊 Expanded {total:,}/{self.total_tasks:,} prompts ({pct:.1f}%)"
            )
        else:
            print(f"\r  Expanded {total:,} prompts", end="", flush=True)
            self._logger.info(f"📊 Expanded {total:,} prompts")

        yield inputs
