import logging
import sys

from rich.progress import (
    Progress,
    TextColumn,
)

from ..prompts import ExecuterPrompt
from ..rich_logging import show_progress_bar
from .base_agent import BaseAgent
from .utils import init_llm

logger = logging.getLogger(__name__)


def execute_code(code, language, timeout):
    """
    Execute code with real-time output streaming and timeout and show a linear timeout progress bar..
    Args:
        code (str): The code to execute (Python code or bash script)
        language (str): The language to execute ("python" or "bash")
        timeout (float): Maximum execution time in seconds before terminating the process.
    Returns:
        tuple: (success: bool, stdout: str, stderr: str)
    """
    import select
    import subprocess
    import time
    from collections import deque
    import os

    try:
        timeout_seconds = None
        try:
            parsed_timeout = float(timeout) if timeout is not None else 0
        except (TypeError, ValueError):
            parsed_timeout = 0
        if parsed_timeout > 0:
            timeout_seconds = parsed_timeout

        # Set up the command based on language
        env = os.environ.copy()
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.setdefault("PYTHONUTF8", "1")

        if language.lower() == "python":
            python_executable = env.get("AI4ML_PYTHON_EXECUTABLE") or sys.executable
            cmd = [python_executable, "-c", code]
        elif language.lower() == "bash":
            if os.name == "nt":
                cmd = ["powershell", "-NoProfile", "-Command", code]
            else:
                cmd = ["bash", "-c", code]
        else:
            raise ValueError(f"Unsupported language: {language}. Use 'python' or 'bash'.")

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
        )

        if process.stdout is None or process.stderr is None:
            process.kill()
            raise RuntimeError("Subprocess did not expose stdout/stderr pipes.")

        if os.name == "nt" or timeout_seconds is None:
            import threading

            stdout_chunks, stderr_chunks = [], []
            recent_stdout_lines = deque(maxlen=100)
            recent_stderr_lines = deque(maxlen=100)

            def stream_reader(stream, chunks, recent_lines):
                for line in iter(stream.readline, ""):
                    if line in recent_lines:
                        continue
                    recent_lines.append(line)
                    chunks.append(line)
                    logger.detail(line.rstrip())

            stdout_thread = threading.Thread(
                target=stream_reader,
                args=(process.stdout, stdout_chunks, recent_stdout_lines),
                daemon=True,
            )
            stderr_thread = threading.Thread(
                target=stream_reader,
                args=(process.stderr, stderr_chunks, recent_stderr_lines),
                daemon=True,
            )
            stdout_thread.start()
            stderr_thread.start()

            try:
                process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout_chunks.append(f"\nProcess reached time limit after {timeout_seconds} seconds.\n")
                logger.info(f"\nProcess reached time limit after {timeout_seconds} seconds.\n")
            finally:
                stdout_thread.join(timeout=5)
                stderr_thread.join(timeout=5)
            return process.returncode == 0, "".join(stdout_chunks), "".join(stderr_chunks)

        stdout_chunks, stderr_chunks = [], []

        # Track last 100 unique lines for deduplication (separate for stdout and stderr)
        recent_stdout_lines = deque(maxlen=100)
        recent_stderr_lines = deque(maxlen=100)

        # Set up tracking of both output streams
        streams = [process.stdout, process.stderr]

        # Track start time for timeout
        start_time = time.time()

        with Progress(
            TextColumn(f"[bold cyan]Executing {language}:"),
            TextColumn("[bold green]{task.completed:.1f}s[/bold green] [dim](time limit: {task.total:.0f}s)[/dim]"),
            refresh_per_second=2,
            transient=False,
            disable=not show_progress_bar(),
        ) as progress_context:

            task = progress_context.add_task("", total=timeout_seconds)

            while streams:
                # Calculate remaining time
                elapsed_time = time.time() - start_time
                progress_context.update(task, completed=elapsed_time)
                remaining_time = max(0, timeout_seconds - elapsed_time)

                # Check if we've exceeded timeout
                if remaining_time <= 0:
                    process.terminate()
                    time.sleep(3)  # Give it a moment to terminate gracefully
                    if process.poll() is None:  # If still running
                        process.kill()  # Force kill
                    stdout_chunks.append(f"\nProcess reached time limit after {timeout_seconds} seconds.\n")
                    logger.info(f"\nProcess reached time limit after {timeout_seconds} seconds.\n")
                    break

                # Wait for output on either stream with timeout
                # select.select returns empty lists if the timeout elapses
                readable, _, _ = select.select(streams, [], [], min(1, remaining_time))

                # If nothing was read but process is still running, continue the loop
                if not readable and process.poll() is None:
                    continue

                # If nothing was read and process exited, exit loop
                if not readable and process.poll() is not None:
                    break

                for stream in readable:
                    line = stream.readline()
                    if not line:  # EOF
                        streams.remove(stream)
                        continue

                    # Handle stdout
                    if stream == process.stdout:
                        # Skip duplicate lines (exact match with any of the last 100 stdout lines)
                        if line in recent_stdout_lines:
                            continue
                        recent_stdout_lines.append(line)
                        stdout_chunks.append(line)
                        logger.detail(line.rstrip())
                    # Handle stderr
                    else:
                        # Skip duplicate lines (exact match with any of the last 100 stderr lines)
                        if line in recent_stderr_lines:
                            continue
                        recent_stderr_lines.append(line)
                        stderr_chunks.append(line)
                        logger.detail(line.rstrip())

            elapsed_time = time.time() - start_time
            progress_context.update(task, completed=elapsed_time)

        # Wait for process to complete (should already be done, but just in case)
        if process.poll() is None:
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                stderr_chunks.append("Process forcibly terminated after timeout\n")

        success = process.returncode == 0
        return success, "".join(stdout_chunks), "".join(stderr_chunks)

    except Exception as e:
        raise RuntimeError(f"ExecuterAgent failed to launch or monitor {language} code: {e}") from e


class ExecuterAgent(BaseAgent):
    """
    Execute the code and give analysis.

    Agent Input:

    Agent Output:
    """

    def __init__(
        self,
        config,
        manager,
        language,
        timeout,
        executer_llm_config,
        executer_prompt_template,
        require_validation_score=True,
    ):
        super().__init__(config=config, manager=manager)
        assert language in ["bash", "python"]

        self.timeout = timeout
        self.language = language
        self.executer_llm_config = executer_llm_config
        self.require_validation_score = require_validation_score

        if executer_prompt_template is not None:
            self.executer_prompt_template = executer_prompt_template
        elif self.executer_llm_config.template is not None:
            self.executer_prompt_template = self.executer_llm_config.template
        else:
            self.executer_prompt_template = None

        if self.executer_llm_config.multi_turn:
            self.executer_llm = init_llm(
                llm_config=self.executer_llm_config,
                agent_name=f"{language}_executer",
                multi_turn=self.executer_llm_config.multi_turn,
            )

        self.executer_prompt = ExecuterPrompt(
            llm_config=self.executer_llm_config, manager=manager, template=self.executer_prompt_template
        )

    def __call__(self, code_to_execute, code_to_analyze=None, execution_task=None, execution_data=None):

        self.manager.log_agent_start("ExecuterAgent: executing code and collecting stdout/stderr for evaluation.")

        if code_to_analyze is None:
            code_to_analyze = code_to_execute

        success, stdout, stderr = execute_code(code=code_to_execute, language=self.language, timeout=self.timeout)

        self.manager.save_and_log_states(content=stdout, save_name="stdout.txt", per_iteration=True, add_uuid=True)
        self.manager.save_and_log_states(content=stderr, save_name="stderr.txt", per_iteration=True, add_uuid=True)
        self.manager.save_and_log_states(content=stdout, save_name="stdout.orig.txt", per_iteration=True, add_uuid=True)
        self.manager.save_and_log_states(content=stderr, save_name="stderr.orig.txt", per_iteration=True, add_uuid=True)

        if not self.executer_llm_config.multi_turn:
            self.executer_llm = init_llm(
                llm_config=self.executer_llm_config,
                agent_name=f"{self.language}_executer",
                multi_turn=self.executer_llm_config.multi_turn,
            )

        # Build prompt for evaluating execution results
        prompt = self.executer_prompt.build(
            stdout=stdout,
            stderr=stderr,
            code_to_analyze=code_to_analyze,
            execution_task=execution_task,
            execution_data=execution_data,
        )

        # Query the LLM
        response = self.executer_llm.assistant_chat(prompt)

        # Parse the LLM response to extract decision, error summary, and validation score
        decision, error_summary, validation_score = self.executer_prompt.parse(
            response,
            require_validation_score=self.require_validation_score,
        )

        # Log the decision, error summary, and validation score
        logger.brief(f"Planner decision: {decision}")
        if error_summary:
            logger.info(f"Error summary: {error_summary}")
        if validation_score is not None:
            logger.info(f"Validation score: {validation_score}")

        self.manager.log_agent_end("ExecuterAgent: execution finished; planner decision logged.")

        return decision, error_summary, validation_score, prompt, stderr, stdout

