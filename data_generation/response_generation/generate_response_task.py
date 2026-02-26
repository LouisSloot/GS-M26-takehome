"""GenerateResponseTask: LLM generates model response given user prompt and target behavior."""

from typing import Any, Dict, List, Union

from distilabel.steps.tasks.base import Task
from distilabel.typing import ChatType

from response_generation.config import (
    RESPONSE_TO_CONV_LABEL,
    SYSTEM_PROMPTS,
)


class GenerateResponseTask(Task):
    """
    Task that generates a model response to a user prompt.
    Uses a system prompt chosen by target_response_type (compliance, overrefusal, harmful).
    Input: user_prompt, target_response_type, category, prompt_label
    Output: model_response, conv_label, plus pass-through of input columns
    """

    @property
    def inputs(self) -> List[str]:
        return ["user_prompt", "target_response_type", "category", "prompt_label"]

    def format_input(self, input: Dict[str, Any]) -> ChatType:
        system_content = SYSTEM_PROMPTS.get(
            input["target_response_type"],
            SYSTEM_PROMPTS["compliance"],
        )
        user_content = input["user_prompt"]
        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]

    @property
    def outputs(self) -> List[str]:
        return ["model_response", "conv_label"]

    def format_output(
        self,
        output: Union[str, None],
        input: Union[Dict[str, Any], None] = None,
    ) -> Dict[str, Any]:
        response_text = (output or "").strip() if output else ""
        target_type = input["target_response_type"] if input else "compliance"
        conv_label = RESPONSE_TO_CONV_LABEL.get(target_type, "unharmful")
        return {
            "model_response": response_text,
            "conv_label": conv_label,
        }
