import logging
import os
import re
import sys
from ast import parse as parse_python
from pathlib import Path

from ..prompts import BashCoderPrompt, PythonCoderPrompt
from .base_agent import BaseAgent
from .utils import init_llm

logger = logging.getLogger(__name__)


def _build_local_windows_python_runner(manager) -> str:
    node_dir = Path(manager.get_iteration_folder(manager.current_node))
    python_executable = Path(sys.executable)
    lines = [
        "$ErrorActionPreference = 'Stop'",
        f'Set-Location "{node_dir}"',
        f'& "{python_executable}" "generated_code.py"',
    ]
    return "\n".join(lines) + "\n"


def _python_code_completion_issue(code: str) -> str | None:
    stripped = (code or "").strip()
    if not stripped:
        return "generated code is empty"

    lowered = stripped.lower()
    if stripped.startswith("```") or "```" in stripped:
        return "response still contains markdown fences instead of a raw python script"
    if stripped.startswith("#!/bin/bash") or stripped.startswith("#!/usr/bin/env bash"):
        return "python candidate still starts with a shell script header"
    if re.search(r"^\s*(pip|python|conda|mamba)\s+install\b", lowered, re.MULTILINE):
        return "python candidate still contains shell package installation commands"

    try:
        parse_python(stripped)
    except SyntaxError as exc:
        return f"{exc.msg} near line {exc.lineno}"

    if (
        "def main(" in stripped
        and 'if __name__ == "__main__":' not in stripped
        and "if __name__ == '__main__':" not in stripped
    ):
        return "defines main() but never calls it from a __main__ entrypoint"

    if "validation_score" not in lowered and "validation score" not in lowered and "metric_value" not in lowered:
        return "missing any visible validation score output or summary artifact"

    return None


def _truncate_for_prompt(text: str, max_chars: int = 12000) -> str:
    stripped = (text or "").strip()
    if len(stripped) <= max_chars:
        return stripped
    return stripped[:max_chars] + "\n...[truncated]..."


def _build_python_repair_prompt(issue: str, generated_code: str, response: str, retry_count: int) -> str:
    if retry_count < 3:
        strategy = (
            "Repair the current script instead of rewriting a verbose new draft. "
            "Keep the script compact and complete."
        )
    else:
        strategy = (
            "Rewrite the script from scratch as a SHORTER minimal solution so it cannot be truncated again. "
            "Keep the implementation concise and stay within the libraries already required by the task."
        )

    return (
        "Your previous reply did not produce a valid executable Python script.\n"
        f"Detected issue: {issue}.\n"
        f"{strategy}\n\n"
        "Hard requirements:\n"
        "- Return exactly one COMPLETE script inside a single ```python``` code block.\n"
        "- Do not include any bash, shell, PowerShell, or pip install blocks.\n"
        "- Start from the first line and include the final line. Do not truncate the ending.\n"
        "- Keep the code compact.\n"
        "- Use only files that actually exist in the input folder.\n"
        '- Include a runnable `if __name__ == "__main__":` entrypoint.\n'
        "- Persist or print the final validation score.\n\n"
        "Current extracted Python candidate:\n"
        f"```python\n{_truncate_for_prompt(generated_code)}\n```\n\n"
        "Previous raw assistant reply:\n"
        f"```text\n{_truncate_for_prompt(str(response))}\n```\n"
    )


class CoderAgent(BaseAgent):
    """
    Execute the code and give analysis.

    Agent Input:

    Agent Output:
    """

    def __init__(self, config, manager, language, coding_mode, llm_config, prompt_template):
        super().__init__(config=config, manager=manager)
        assert language in ["bash", "python"]
        assert coding_mode in ["reader", "coder"]
        self.language = language
        self.coding_mode = coding_mode

        self.coder_llm_config = llm_config
        self.coder_prompt_template = prompt_template

        prompt_mapping = {
            "bash": {"reader": None, "coder": BashCoderPrompt},
            "python": {"reader": None, "coder": PythonCoderPrompt},
        }

        self.coder_prompt = prompt_mapping[language][coding_mode](
            llm_config=self.coder_llm_config,
            manager=self.manager,
            template=self.coder_prompt_template,
        )

        if self.coder_llm_config.multi_turn:
            self.coder_llm = init_llm(
                llm_config=self.coder_llm_config,
                agent_name=f"{self.language}_{self.coding_mode}",
                multi_turn=self.coder_llm_config.multi_turn,
            )

    def __call__(self):
        self.manager.log_agent_start("CoderAgent: starting to build and send code-generation prompt to the LLM.")

        if self.coding_mode == "coder" and self.language == "bash" and os.name == "nt":
            prompt = "Local PowerShell execution wrapper for generated Python code on Windows."
            generated_code = _build_local_windows_python_runner(self.manager)
            self.manager.save_and_log_states(
                content=prompt, save_name="bash_coder_prompt.txt", per_iteration=True, add_uuid=False
            )
            self.manager.save_and_log_states(
                content=generated_code, save_name="bash_coder_response.txt", per_iteration=True, add_uuid=False
            )
            self.manager.save_and_log_states(
                content=generated_code,
                save_name="extracted_bash_script.sh",
                per_iteration=True,
                add_uuid=False,
            )
            self.manager.log_agent_end(
                "CoderAgent: local PowerShell execution wrapper generated for the Python script."
            )
            return generated_code

        # Build prompt for evaluating execution results
        prompt = self.coder_prompt.build()

        if not self.coder_llm_config.multi_turn:
            self.coder_llm = init_llm(
                llm_config=self.coder_llm_config,
                agent_name=f"{self.language}_{self.coding_mode}",
                multi_turn=self.coder_llm_config.multi_turn,
            )

        response = self.coder_llm.assistant_chat(prompt)

        generated_code = self.coder_prompt.parse(response)

        if self.language == "python":
            completion_issue = _python_code_completion_issue(generated_code)
            retry_count = 0
            while completion_issue is not None and retry_count < 4:
                retry_count += 1
                retry_prompt = _build_python_repair_prompt(
                    issue=completion_issue,
                    generated_code=generated_code,
                    response=str(response),
                    retry_count=retry_count,
                )
                self.manager.save_and_log_states(
                    content=retry_prompt,
                    save_name=f"python_coder_retry_request_{retry_count}.txt",
                    per_iteration=True,
                    add_uuid=False,
                )
                response = self.coder_llm.assistant_chat(retry_prompt)
                self.manager.save_and_log_states(
                    content=response,
                    save_name=f"python_coder_retry_response_{retry_count}.txt",
                    per_iteration=True,
                    add_uuid=False,
                )
                generated_code = self.coder_prompt.parse(response)
                completion_issue = _python_code_completion_issue(generated_code)
            if completion_issue is not None:
                logger.warning(
                    "LLM-generated Python code remained invalid after retries. "
                    f"Final detected issue: {completion_issue}"
                )

        self.manager.log_agent_end("CoderAgent: code-generation prompt handled and code parsed from response.")

        return generated_code
