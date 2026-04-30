import logging
from importlib.util import find_spec
from typing import List

from ..prompts import ToolSelectorPrompt
from ..tools_registry import registry
from .base_agent import BaseAgent
from .utils import init_llm

logger = logging.getLogger(__name__)


TOOL_RUNTIME_REQUIREMENTS = {
    "machine learning": ("sklearn", "pandas"),
    "autogluon.tabular": ("autogluon.tabular",),
    "autogluon.multimodal": ("autogluon.multimodal",),
    "autogluon.timeseries": ("autogluon.timeseries",),
    "wav2vec2": ("transformers",),
}


def _module_available(module_name: str) -> bool:
    try:
        return find_spec(module_name) is not None
    except ModuleNotFoundError:
        return False


def _tool_supported_locally(tool_name: str) -> bool:
    requirements = TOOL_RUNTIME_REQUIREMENTS.get(tool_name)
    if not requirements:
        return True
    return all(_module_available(module_name) for module_name in requirements)


def _supported_tool_names() -> List[str]:
    return [tool_name for tool_name in registry.tools.keys() if _tool_supported_locally(tool_name)]


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

    def __call__(self) -> List[str]:
        self.manager.log_agent_start("ToolSelectorAgent: choosing and ranking ML libraries for the task.")
        supported_tools = _supported_tool_names()
        if not supported_tools:
            raise RuntimeError("No locally supported tools are available for selection in the current runtime.")
        self.manager.supported_tool_names = supported_tools

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
        unsupported_tools = [tool for tool in tools if tool not in supported_tools]
        if unsupported_tools:
            raise RuntimeError(
                "Tool selector chose tools that are unavailable in the current runtime: "
                + ", ".join(unsupported_tools)
            )
        # Select only top #tools required
        if len(tools) > self.manager.config.initial_root_children:
            tools = tools[: self.manager.config.initial_root_children]

        tools_str = ", ".join(tools)
        self.manager.log_agent_end(f"ToolSelectorAgent: selected tools in priority order: {tools_str}")

        return tools
