import logging
from typing import List

from ..prompts import RerankerPrompt
from ..tools_registry import TutorialInfo
from .base_agent import BaseAgent
from .utils import init_llm

logger = logging.getLogger(__name__)


class RerankerAgent(BaseAgent):
    """
    Agent for reranking and selecting the most relevant tutorials from retrieved candidates.
    Agent Input: Task context, data info, user prompt, error info, retrieved tutorials
    Agent Output: Formatted tutorial prompt with selected relevant tutorials
    """

    def __init__(self, config, manager, llm_config, prompt_template):
        super().__init__(config=config, manager=manager)
        self.reranker_llm_config = llm_config
        self.reranker_prompt_template = prompt_template
        self.reranker_prompt = RerankerPrompt(
            llm_config=self.reranker_llm_config,
            manager=self.manager,
            template=self.reranker_prompt_template,
        )

        if self.reranker_llm_config.multi_turn:
            self.reranker_llm = init_llm(
                llm_config=self.reranker_llm_config,
                agent_name="reranker",
                multi_turn=self.reranker_llm_config.multi_turn,
            )

    def __call__(self):
        """Select and rerank relevant tutorials from retrieved candidates."""
        self.manager.log_agent_start("RerankerAgent: reranking and selecting top tutorials from retrieved candidates.")
        tutorials = self.manager.current_node.tutorial_retrieval or []
        if not tutorials:
            self.manager.log_agent_end("RerankerAgent: no retrieved tutorials were available to rerank.")
            return ""

        prompt = self.reranker_prompt.build()
        if not prompt.strip():
            raise ValueError("Reranker prompt is empty even though tutorial candidates are available.")

        if not self.reranker_llm_config.multi_turn:
            self.reranker_llm = init_llm(
                llm_config=self.reranker_llm_config,
                agent_name="reranker",
                multi_turn=self.reranker_llm_config.multi_turn,
            )

        response = self.reranker_llm.assistant_chat(prompt)
        selected_tutorials = self.reranker_prompt.parse(response)

        # Generate tutorial prompt using selected tutorials
        tutorial_prompt = self._generate_tutorial_prompt(selected_tutorials)

        # Save reranking results for debugging
        self.manager.save_and_log_states(
            content=self._format_reranking_results(selected_tutorials),
            save_name="tutorial_reranking_results.txt",
            per_iteration=True,
            add_uuid=False,
        )

        self.manager.log_agent_end(
            f"RerankerAgent: selected {len(selected_tutorials)} tutorials and formatted prompt."
        )
        return tutorial_prompt

    def _format_tutorial_content(
        self,
        tutorial: TutorialInfo,
        max_length: int,
    ) -> str:
        """Format a single tutorial's content with truncation if needed."""
        if tutorial.content:
            content = tutorial.content
        else:
            with open(tutorial.path, "r", encoding="utf-8") as f:
                content = f.read()

        if len(content) > max_length:
            content = content[:max_length] + "\n...(truncated)"

        formatted = f"""### {tutorial.title}
{content}
"""
        return formatted

    def _generate_tutorial_prompt(self, selected_tutorials: List[TutorialInfo]) -> str:
        """Generate formatted tutorial prompt from selected tutorials."""
        if not selected_tutorials:
            raise ValueError("Reranker selected no tutorials while tutorial candidates were available.")

        # Get max tutorial length from config if available
        max_tutorial_length = self.config.max_tutorial_length

        # Format selected tutorials
        formatted_tutorials = []
        for tutorial in selected_tutorials:
            per_tutorial_max_length = max_tutorial_length // len(selected_tutorials)
            formatted = self._format_tutorial_content(tutorial, per_tutorial_max_length)
            formatted_tutorials.append(formatted)

        if not formatted_tutorials:
            raise RuntimeError("Reranker selected tutorials but no tutorial content could be formatted.")

        return "\n\n".join(formatted_tutorials)

    def _format_reranking_results(self, selected_tutorials: List[TutorialInfo]) -> str:
        """Format reranking results for logging."""
        if not selected_tutorials:
            return "No tutorials selected after reranking."

        formatted = "Selected Tutorials After Reranking:\n"
        formatted += "=" * 50 + "\n"

        for i, tutorial in enumerate(selected_tutorials, 1):
            formatted += f"\n{i}. Title: {tutorial.title}\n"
            formatted += f"   Path: {getattr(tutorial, 'path', 'Unknown')}\n"
            if tutorial.score:
                formatted += f"   Retrieval Score: {tutorial.score:.4f}\n"
            if tutorial.content:
                preview = tutorial.content[:200] + "..." if len(tutorial.content) > 200 else tutorial.content
                formatted += f"   Content Preview: {preview}\n"
            formatted += "-" * 30 + "\n"

        return formatted
