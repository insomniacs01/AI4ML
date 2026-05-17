import logging
from typing import Any, Dict, List

from autogluon.assistant.tools_registry.indexing import TutorialIndexer

from ..prompts import RetrieverPrompt
from ..tools_registry import TutorialInfo
from .base_agent import BaseAgent
from .mcp_web_search import search_with_mcp
from .utils import init_llm

logger = logging.getLogger(__name__)


class RetrieverAgent(BaseAgent):
    """
    Agent for coarse retriever of relevant tutorials using LLM-generated search queries.
    Agent Input: Task context, data info, user prompt, selected tool
    Agent Output: List of retrieved tutorial candidates for further reranking
    """

    def __init__(self, config, manager, llm_config, prompt_template):
        super().__init__(config=config, manager=manager)
        self.retriever_llm_config = llm_config
        self.retriever_prompt_template = prompt_template

        # Initialize retriever prompt
        self.retriever_prompt = RetrieverPrompt(
            llm_config=self.retriever_llm_config,
            manager=self.manager,
            template=self.retriever_prompt_template,
        )

        # Initialize tutorial indexer
        self.indexer = TutorialIndexer()
        self._initialize_indexer()

        if self.retriever_llm_config.multi_turn:
            self.retriever_llm = init_llm(
                llm_config=self.retriever_llm_config,
                agent_name="retriever",
                multi_turn=self.retriever_llm_config.multi_turn,
            )

    def _initialize_indexer(self):
        """Initialize the tutorial indexer, building indices if necessary."""
        try:
            loaded_successfully = self.indexer.load_indices()
            if not loaded_successfully:
                logger.info("Building tutorial indices...")
                self.indexer.build_indices()
                self.indexer.save_indices()
                logger.info("Tutorial indices built and saved successfully.")
        except Exception as e:
            logger.error(f"Error initializing tutorial indexer: {e}")
            raise

    def __call__(self) -> List[TutorialInfo]:
        """Retrieve relevant tutorials using LLM-generated search queries."""
        self.manager.log_agent_start("RetrieverAgent: generating search query and retrieving tutorials.")

        prompt = self.retriever_prompt.build()

        if not self.retriever_llm_config.multi_turn:
            self.retriever_llm = init_llm(
                llm_config=self.retriever_llm_config,
                agent_name="retriever",
                multi_turn=self.retriever_llm_config.multi_turn,
            )

        response = self.retriever_llm.assistant_chat(prompt)
        search_query = self.retriever_prompt.parse(response)

        mcp_results = self._search_mcp_web(search_query)
        if mcp_results:
            retrieved_tutorials = self._convert_mcp_results_to_tutorial_info(mcp_results)
            self.manager.save_and_log_states(
                content=self._format_mcp_results(mcp_results, search_query),
                save_name="tutorial_retriever_results.txt",
                per_iteration=True,
                add_uuid=False,
            )
            self.manager.log_agent_end(
                f"RetrieverAgent: retrieved {len(retrieved_tutorials)} MCP web results using query: '{search_query}'"
            )
            return retrieved_tutorials

        results = self.indexer.search(
            query=search_query,
            tool_name=self.manager.selected_tool,
            condensed=self.config.condense_tutorials,
            top_k=self.config.num_tutorial_retrievals,
        )

        retrieved_tutorials = self._convert_to_tutorial_info(results)

        self.manager.save_and_log_states(
            content=self._format_retriever_results(results, search_query),
            save_name="tutorial_retriever_results.txt",
            per_iteration=True,
            add_uuid=False,
        )

        self.manager.log_agent_end(
            f"RetrieverAgent: retrieved {len(retrieved_tutorials)} tutorial candidates using query: '{search_query}'"
        )

        return retrieved_tutorials

    def _search_mcp_web(self, search_query: str) -> List[Dict[str, Any]]:
        if not bool(self.config.get("mcp_web_search_enabled", False)):
            return []
        server_url = str(self.config.get("mcp_web_search_server_url", "") or "").strip()
        if not server_url:
            logger.warning("MCP web search is enabled but mcp_web_search_server_url is empty.")
            return []
        tool_name = str(self.config.get("mcp_web_search_tool_name", "") or "").strip() or None
        timeout_seconds = float(self.config.get("mcp_web_search_timeout_seconds", 20) or 20)
        top_k = int(self.config.get("mcp_web_search_top_k", self.config.num_tutorial_retrievals) or self.config.num_tutorial_retrievals)
        try:
            return search_with_mcp(
                server_url=server_url,
                query=search_query,
                tool_name=tool_name,
                top_k=top_k,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("MCP web search failed, falling back to local tutorial index: %s", exc)
            return []

    def _convert_mcp_results_to_tutorial_info(self, search_results: List[Dict[str, Any]]) -> List[TutorialInfo]:
        tutorials = []
        for index, result in enumerate(search_results):
            title = str(result.get("title") or f"Web search result {index + 1}").strip()
            url = str(result.get("url") or "").strip()
            snippet = str(result.get("snippet") or "").strip()
            content = str(result.get("content") or snippet or "").strip()
            if not content:
                continue
            markdown = self._format_mcp_tutorial_content(title=title, url=url, snippet=snippet, content=content)
            tutorials.append(
                TutorialInfo(
                    path=f"mcp-web://{url or index + 1}",
                    title=title,
                    summary=snippet or content[:400],
                    score=float(result.get("score", 1.0) or 1.0),
                    content=markdown,
                )
            )
        return tutorials

    def _format_mcp_tutorial_content(self, *, title: str, url: str, snippet: str, content: str) -> str:
        lines = [
            f"# {title}",
            "Summary: Web search result retrieved through MCP.",
        ]
        if url:
            lines.append(f"Source: {url}")
        if snippet:
            lines.extend(["", "## Snippet", snippet])
        lines.extend(["", "## Retrieved Content", content])
        return "\n".join(lines)

    def _convert_to_tutorial_info(self, search_results: List[Dict[str, Any]]) -> List[TutorialInfo]:
        """Convert search results to TutorialInfo objects."""
        tutorials = []

        for index, result in enumerate(search_results):
            file_path = result.get("file_path")
            content = result.get("content")
            score = result.get("score")
            if not isinstance(file_path, str) or not file_path.strip():
                raise RuntimeError(f"Retriever result {index + 1} is missing a non-empty file_path.")
            if not isinstance(content, str) or not content.strip():
                raise RuntimeError(f"Retriever result {index + 1} for {file_path} is missing tutorial content.")
            if not isinstance(score, (int, float)):
                raise RuntimeError(f"Retriever result {index + 1} for {file_path} is missing a numeric score.")

            title = self._extract_title_from_content(content, file_path)
            summary = self._extract_summary_from_content(content)

            tutorial = TutorialInfo(
                path=file_path,
                title=title,
                summary=summary,
                score=score,
                content=content,
            )

            tutorials.append(tutorial)

        return tutorials

    def _format_mcp_results(self, results: List[Dict[str, Any]], search_query: str) -> str:
        formatted = f"Search Query: {search_query}\n"
        formatted += "=" * 50 + "\n"
        if not results:
            formatted += "No MCP web results retrieved.\n"
            return formatted
        formatted += f"Retrieved {len(results)} MCP Web Results:\n\n"
        for i, result in enumerate(results, 1):
            formatted += f"{i}. Title: {result.get('title', 'Unknown')}\n"
            if result.get("url"):
                formatted += f"   URL: {result.get('url')}\n"
            if result.get("snippet"):
                formatted += f"   Snippet: {str(result.get('snippet'))[:300]}\n"
            formatted += "-" * 30 + "\n"
        return formatted

    def _extract_title_from_content(self, content: str, file_path: str) -> str:
        """Extract title from content, similar to existing get_all_tutorials logic."""
        lines = content.split("\n")
        title = next(
            (line.lstrip("#").strip() for line in lines if line.strip().startswith("#")),
            "",
        )
        if not title:
            raise RuntimeError(f"Tutorial content at {file_path} is missing a markdown title.")
        return title

    def _extract_summary_from_content(self, content: str) -> str:
        """Extract summary from content, similar to existing get_all_tutorials logic."""
        lines = content.split("\n")
        return next(
            (line.replace("Summary:", "").strip() for line in lines if line.strip().startswith("Summary:")),
            "",
        )

    def _format_retriever_results(self, results: List[Dict[str, Any]], search_query: str) -> str:
        """Format retriever results for logging."""
        formatted = f"Search Query: {search_query}\n"
        formatted += "=" * 50 + "\n"

        if not results:
            formatted += "No tutorials retrieved.\n"
            return formatted

        formatted += f"Retrieved {len(results)} Tutorial Results:\n\n"

        for i, result in enumerate(results, 1):
            formatted += f"{i}. File: {result.get('file_path', 'Unknown')}\n"
            formatted += f"   Score: {result.get('score', 0.0):.4f}\n"
            content = result.get("content", "")
            if content:
                # Extract title for better readability
                title = self._extract_title_from_content(content, result.get("file_path", ""))
                if title:
                    formatted += f"   Title: {title}\n"
                preview = content[:200] + "..." if len(content) > 200 else content
                formatted += f"   Content Preview: {preview}\n"
            formatted += "-" * 30 + "\n"

        return formatted

    def cleanup(self):
        """Clean up resources."""
        if hasattr(self, "indexer"):
            self.indexer.cleanup()

    def __del__(self):
        """Destructor to ensure cleanup."""
        self.cleanup()
