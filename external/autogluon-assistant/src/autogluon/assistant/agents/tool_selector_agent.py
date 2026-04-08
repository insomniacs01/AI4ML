import logging
from typing import List, Union

from ..prompts import ToolSelectorPrompt
from ..tools_registry import registry
from .base_agent import BaseAgent
from .utils import init_llm

logger = logging.getLogger(__name__)


def infer_tools_from_task(task_description: str, data_prompt: str) -> List[str]:
    available_tools = list(registry.tools.keys())
    normalized = f"{task_description}\n{data_prompt}".lower()

    def ordered(candidates: List[str]) -> List[str]:
        return [tool for tool in candidates if tool in available_tools]

    if any(keyword in normalized for keyword in ("forecast", "time series", "timeseries")):
        return ordered(["autogluon.timeseries", "machine learning", "autogluon.tabular"])

    if any(keyword in normalized for keyword in ("audio", "speech", "wav")):
        return ordered(["wav2vec2", "autogluon.multimodal", "machine learning"])

    if any(keyword in normalized for keyword in ("image", "vision", "multimodal", "text")):
        return ordered(["autogluon.multimodal", "machine learning", "autogluon.tabular"])

    if any(keyword in normalized for keyword in ("classification", "regression", "label column", ".csv")):
        return ordered(["machine learning", "autogluon.tabular", "autogluon.multimodal"])

    return ordered(["machine learning", "autogluon.tabular", "autogluon.multimodal"])


class ToolSelectorAgent(BaseAgent):
    """
    Select and rank the most appropriate tools based on data description and task requirements.

    Agent Input:
    - data_prompt: Text string containing data prompt
    - description: Description of the task/data from previous analysis

    Agent Output:
    - List[str]: Prioritized list of tool names
    - str: Selected tool name (for backward compatibility)
    """

    def __init__(self, config, manager, llm_config, prompt_template):
        super().__init__(config=config, manager=manager)

        self.tool_selector_llm_config = llm_config
        self.tool_selector_prompt_template = prompt_template

        self.tool_selector_prompt = ToolSelectorPrompt(
            llm_config=self.tool_selector_llm_config,
            manager=self.manager,
            template=self.tool_selector_prompt_template,
        )

        if self.tool_selector_llm_config.multi_turn:
            self.tool_selector_llm = init_llm(
                llm_config=self.tool_selector_llm_config,
                agent_name="tool_selector",
                multi_turn=self.tool_selector_llm_config.multi_turn,
            )

    def __call__(self) -> Union[List[str], str]:
        self.manager.log_agent_start("ToolSelectorAgent: choosing and ranking ML libraries for the task.")

        heuristic_tools = infer_tools_from_task(
            task_description=self.manager.task_description,
            data_prompt=self.manager.data_prompt,
        )
        if heuristic_tools:
            logger.info(f"Using local heuristic tool ranking: {', '.join(heuristic_tools)}")
            synthetic_response = "EXPLANATION: Local heuristic selected tools based on task description and data type.\n\nRANKED_LIBRARIES:\n"
            synthetic_response += "\n".join(
                f"{index}. {tool}" for index, tool in enumerate(heuristic_tools, start=1)
            )
            tools = self.tool_selector_prompt.parse(synthetic_response)
            if len(tools) > self.manager.config.initial_root_children:
                tools = tools[: self.manager.config.initial_root_children]
            tools_str = ", ".join(tools)
            self.manager.log_agent_end(f"ToolSelectorAgent: selected tools in priority order: {tools_str}")
            return tools

        # Build prompt for tool selection
        prompt = self.tool_selector_prompt.build()

        if not self.tool_selector_llm_config.multi_turn:
            self.tool_selector_llm = init_llm(
                llm_config=self.tool_selector_llm_config,
                agent_name="tool_selector",
                multi_turn=self.tool_selector_llm_config.multi_turn,
            )

        response = self.tool_selector_llm.assistant_chat(prompt)

        tools = self.tool_selector_prompt.parse(response)
        # Select only top #tools required
        if len(tools) > self.manager.config.initial_root_children:
            tools = tools[: self.manager.config.initial_root_children]

        tools_str = ", ".join(tools)
        self.manager.log_agent_end(f"ToolSelectorAgent: selected tools in priority order: {tools_str}")

        return tools
