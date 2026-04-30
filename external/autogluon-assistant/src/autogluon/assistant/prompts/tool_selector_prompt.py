import logging
import json
import re
from typing import Dict, List, Union

from ..tools_registry import registry
from .base_prompt import BasePrompt

logger = logging.getLogger(__name__)


def _format_tools_info(tools_info: Dict) -> str:
    """
    Format tools information for the prompt.

    Args:
        tools_info: Dictionary containing tool information

    Returns:
        str: Formatted string of tool information
    """
    formatted_info = ""
    for tool_name, info in tools_info.items():
        formatted_info += f"Library Name: {tool_name}\n"
        formatted_info += f"Version: v{info['version']}\n"
        formatted_info += f"Description: {info['description']}\n"
        formatted_info += "\n\n"
    return formatted_info


class ToolSelectorPrompt(BasePrompt):
    """Handles prompts for tool selection"""

    @classmethod
    def meta_instructions(cls) -> str:
        """
        Returns specific instructions for meta-prompting the Tool Selector template.
        """
        return """
The ToolSelectorPrompt selects the most appropriate machine learning library for a given task based on data characteristics and requirements.

Considerations for rewriting this template:
1. Focus on clear criteria for matching libraries to specific data types and task requirements
2. Include evaluation of library strengths and limitations for the particular use case
3. Consider computational efficiency requirements based on data size and available resources
4. Emphasize specific features of libraries that are most relevant to the task domain
5. Ensure the output format clearly identifies the selected tool with detailed justification
"""

    def default_template(self) -> str:
        """Default template for tool selection"""
        return """
You are a data science expert tasked with selecting and ranking the most appropriate ML libraries for a specific task.

### Task Description:
{task_description}

### Data Information:
{data_prompt}

### Available ML Libraries:
{tools_info}

Return JSON only with exactly these keys:
{
  "ranked_libraries": ["<best library>", "<second choice>", "<third choice>"],
  "explanation": "<brief explanation>"
}

Requirements:
1. `ranked_libraries` must be a JSON array of exact library names copied from the available libraries list.
2. Put the best choice first.
3. Include at least 3 libraries if 3 or more are available.
4. Keep `explanation` under 80 words.
5. Do not use markdown, code fences, or any extra keys.
"""

    def _build(self, **kwargs) -> str:
        """Build a prompt for the LLM to select appropriate library.

        Args:
            **kwargs: Additional keyword arguments to customize the prompt building process
        """

        supported_tool_names = getattr(self.manager, "supported_tool_names", None)
        if isinstance(supported_tool_names, list) and supported_tool_names:
            tools_info = {tool_name: registry.tools[tool_name] for tool_name in supported_tool_names}
        else:
            tools_info = dict(registry.tools)

        if not tools_info:
            raise ValueError("No tools are available to present to the tool selector prompt.")

        additional_vars = {"tools_info": _format_tools_info(tools_info)}
        prompt = self.render(additional_vars)

        self.manager.save_and_log_states(
            content=prompt, save_name="tool_selector_prompt.txt", per_iteration=False, add_uuid=False
        )

        return prompt

    def parse(self, response: str) -> Union[List[str], str]:
        """
        Parse the library selection response from LLM.

        Args:
            response: The raw response from the LLM

        Returns:
            Union[List[str], str]: Either a prioritized list of tools or a single tool name
        """
        response = response.strip()
        cleaned = response
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)

        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if not match:
                self._log_results(response, "", "")
                raise ValueError("Tool selector response is not valid JSON.")
            try:
                payload = json.loads(match.group(0))
            except json.JSONDecodeError as exc:
                self._log_results(response, "", "")
                raise ValueError("Tool selector response JSON could not be parsed.") from exc

        if not isinstance(payload, dict):
            self._log_results(response, "", "")
            raise ValueError("Tool selector response JSON must be an object.")

        explanation = str(payload.get("explanation", "")).strip()
        if not explanation:
            self._log_results(response, "", "")
            raise ValueError("Tool selector response is missing a non-empty explanation.")

        ranked_payload = payload.get("ranked_libraries")
        if not isinstance(ranked_payload, list):
            self._log_results(response, "", explanation)
            raise ValueError("Tool selector response is missing a ranked_libraries array.")

        prioritized_tools = []
        for item in ranked_payload:
            if not isinstance(item, str):
                continue
            stripped = item.strip()
            if stripped:
                prioritized_tools.append(stripped)
        if not prioritized_tools:
            self._log_results(response, "", explanation)
            raise ValueError("Tool selector response ranked_libraries array is empty.")

        available_tools = set(registry.tools.keys())
        validated_tools = []
        invalid_tools = []
        seen_tools = set()

        for tool in prioritized_tools:
            if tool not in available_tools:
                invalid_tools.append(tool)
                continue
            if tool in seen_tools:
                continue
            seen_tools.add(tool)
            validated_tools.append(tool)

        if invalid_tools:
            self._log_results(response, "", explanation)
            raise ValueError("Tool selector returned unknown library names: " + ", ".join(invalid_tools))

        if not validated_tools:
            self._log_results(response, "", explanation)
            raise ValueError("Failed to extract any valid ranked tools from the LLM response.")

        tools_str = ", ".join(validated_tools)
        self._log_results(response, tools_str, explanation)
        return validated_tools

    def _log_results(self, response: str, selected_tool: str, explanation: str):
        """Log the parsing results."""
        self.manager.save_and_log_states(
            content=response, save_name="tool_selector_response.txt", per_iteration=False, add_uuid=False
        )
        self.manager.save_and_log_states(
            content=selected_tool, save_name="selected_tool.txt", per_iteration=False, add_uuid=False
        )
        self.manager.save_and_log_states(
            content=explanation, save_name="tool_selector_explanation.txt", per_iteration=False, add_uuid=False
        )
