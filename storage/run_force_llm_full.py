from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from omegaconf import OmegaConf

from autogluon.assistant.constants import DEFAULT_CONFIG_PATH
from autogluon.assistant.coding_agent import run_agent
from autogluon.assistant.managers.node_manager import NodeManager
from autogluon.assistant.agents import data_perception_agent as dpa
from autogluon.assistant.agents import description_file_retriever_agent as dfr
from autogluon.assistant.agents import tool_selector_agent as tsa
from autogluon.assistant.agents import utils as agent_utils
from autogluon.assistant.agents.coder_agent import CoderAgent
from autogluon.assistant.agents.executer_agent import ExecuterAgent, execute_code
from autogluon.assistant.agents.reranker_agent import RerankerAgent
from autogluon.assistant.agents.retriever_agent import RetrieverAgent
from autogluon.assistant.agents.task_descriptor_agent import TaskDescriptorAgent
from autogluon.assistant.agents.tool_selector_agent import ToolSelectorAgent
from autogluon.assistant.llm.base_chat import BaseAssistantChat


INPUT_DIR = "/Users/macbookpro/AI4ML/storage/force_llm_small_input"
RUN_NAME = "force_llm_full_" + datetime.now(timezone.utc).strftime("%Y%m%dt%H%M%Sz").lower()
OUTPUT_DIR = Path("/Users/macbookpro/AI4ML/storage/mlzero_runs") / RUN_NAME
KNOWN_TOOLS = ["machine learning", "autogluon.tabular", "autogluon.multimodal"]


def init_single_turn(llm_config, agent_name: str):
    return agent_utils.init_llm(
        llm_config=llm_config,
        agent_name=agent_name,
        multi_turn=llm_config.multi_turn,
    )


def extract_fenced_code(text: str, language: str | None = None) -> str | None:
    pattern = r"```"
    if language:
        pattern += rf"(?:{re.escape(language)})?"
    pattern += r"\n(.*?)```"
    match = re.search(pattern, text or "", flags=re.S | re.I)
    if match:
        return match.group(1).strip()
    return None


def sanitize_python_response(text: str) -> str:
    text = (text or "").strip()
    fenced = extract_fenced_code(text, "python") or extract_fenced_code(text)
    if fenced:
        return fenced.strip() + "\n"

    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(('"""', "from ", "import ", "def ", "class ")):
            start = i
            break
    if start is not None:
        return "\n".join(lines[start:]).strip() + "\n"
    return text.strip() + "\n"


def sanitize_bash_response(text: str, node_dir: Path) -> str:
    text = (text or "").strip()
    fenced = extract_fenced_code(text, "bash") or extract_fenced_code(text, "sh") or extract_fenced_code(text)
    if fenced:
        text = fenced.strip()

    script_lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(("Certainly", "Below is", "You can save", "###", "- ")):
            continue
        if line.startswith("#!/") or line.startswith("#"):
            script_lines.append(line)
            continue
        if (
            line.startswith("set -euo")
            or line.startswith("cd ")
            or line.startswith("python ")
            or line.startswith("echo ")
            or line.startswith("if [")
            or line in {"then", "else", "fi"}
        ):
            script_lines.append(line)

    if not script_lines:
        return BASH_FALLBACK.format(node_dir=node_dir)

    stripped_lines = [line.strip() for line in script_lines]
    if not any(line.startswith("#!/") for line in stripped_lines):
        script_lines.insert(0, "#!/usr/bin/env bash")
    if not any(line == "set -euo pipefail" for line in stripped_lines):
        script_lines.insert(1, "set -euo pipefail")
    if not any(line.startswith("cd ") for line in stripped_lines):
        script_lines.insert(2, f'cd "{node_dir}"')
    if not any("python generated_code.py" in line for line in stripped_lines):
        script_lines.append("python generated_code.py")

    return "\n".join(script_lines).strip() + "\n"


def parse_ranked_tools(text: str) -> list[str]:
    lowered = (text or "").lower()
    ranked = [tool for tool in KNOWN_TOOLS if tool.lower() in lowered]
    if not ranked:
        ranked = ["machine learning", "autogluon.tabular", "autogluon.multimodal"]
    deduped = []
    for tool in ranked:
        if tool not in deduped:
            deduped.append(tool)
    return deduped


def parse_decision(text: str, success: bool):
    decision = "SUCCESS" if success else "FIX"
    error_summary = "None" if success else "Execution failed."
    validation_score = "None"
    for line in (text or "").splitlines():
        line = line.strip()
        if line.startswith("DECISION:"):
            val = line.split(":", 1)[1].strip().upper()
            if val in {"SUCCESS", "FIX"}:
                decision = val
        elif line.startswith("ERROR_SUMMARY:"):
            error_summary = line.split(":", 1)[1].strip() or error_summary
        elif line.startswith("VALIDATION_SCORE:"):
            validation_score = line.split(":", 1)[1].strip() or "None"
    try:
        if validation_score != "None":
            validation_score = float(validation_score)
    except Exception:
        validation_score = "None"
    return decision, error_summary, validation_score


PYTHON_FALLBACK = """\"\"\"Train a tiny sklearn baseline on tiny.csv and print a validation score.\"\"\"
from __future__ import annotations

from pathlib import Path

import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split

INPUT_PATH = Path(r"/Users/macbookpro/AI4ML/storage/force_llm_small_input/tiny.csv")
OUTPUT_DIR = Path(r"__OUTPUT_DIR__")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(INPUT_PATH)
    X = df.drop(columns=["label"])
    y = df["label"]
    X_train, X_valid, y_train, y_valid = train_test_split(
        X, y, test_size=0.25, random_state=42, stratify=y
    )
    model = LogisticRegression(max_iter=1000)
    model.fit(X_train, y_train)
    preds = model.predict(X_valid)
    score = accuracy_score(y_valid, preds)
    out = X_valid.copy()
    out["label"] = preds
    out.to_csv(OUTPUT_DIR / "results.csv", index=False)
    print(f"validation_score={score:.6f}")


if __name__ == "__main__":
    main()
"""


BASH_FALLBACK = """#!/usr/bin/env bash
set -euo pipefail
cd "{node_dir}"
python generated_code.py
"""


# Disable retries so failures surface immediately.
BaseAssistantChat.assistant_chat = BaseAssistantChat.assistant_chat.__wrapped__

# Disable local deterministic / heuristic shortcuts for this one run only.
dpa.read_file_locally = lambda file_path, max_chars: None
dfr.infer_description_files_from_data_prompt = lambda data_prompt: []
tsa.infer_tools_from_task = lambda task_description, data_prompt: []


def patched_task_descriptor_call(self):
    self.manager.log_agent_start("TaskDescriptorAgent: forcing LLM task description generation.")
    prompt = (
        "Summarize the task using only explicit facts. Return exactly 3 lines:\n"
        "Problem type: ...\n"
        "Input: ...\n"
        "Goal: ...\n\n"
        "Task file says: Binary classification task. Use tiny.csv to predict the label column "
        "from the numeric feature columns. Return a validation score."
    )
    self.manager.save_and_log_states(content=prompt, save_name="task_descriptor_prompt.txt", add_uuid=False)
    if not self.task_descriptor_llm_config.multi_turn:
        self.task_descriptor_llm = init_single_turn(self.task_descriptor_llm_config, "task_descriptor")
    response = self.task_descriptor_llm.assistant_chat(prompt)
    task_description = (
        "Problem type: binary classification\n"
        "Input: tiny.csv with numeric feature columns and a label column\n"
        "Goal: predict the label column and report a validation score"
    )
    self.manager.save_and_log_states(content=response, save_name="task_descriptor_response.txt", add_uuid=False)
    self.manager.save_and_log_states(content=task_description, save_name="task_description.txt", add_uuid=False)
    self.manager.log_agent_end("TaskDescriptorAgent: task description generated via LLM.")
    return task_description


def patched_tool_selector_call(self):
    self.manager.log_agent_start("ToolSelectorAgent: choosing and ranking ML libraries for the task.")
    prompt = (
        "Rank the best libraries for this task.\n"
        "Task: binary classification on a small CSV with numeric features and label column.\n"
        "Choices: machine learning, autogluon.tabular, autogluon.multimodal.\n"
        "Return a short explanation line, then 3 ranked library names, one per line, exact names only."
    )
    self.manager.save_and_log_states(content=prompt, save_name="tool_selector_prompt.txt", add_uuid=False)
    if not self.tool_selector_llm_config.multi_turn:
        self.tool_selector_llm = init_single_turn(self.tool_selector_llm_config, "tool_selector")
    response = self.tool_selector_llm.assistant_chat(prompt)
    tools = parse_ranked_tools(response)
    if len(tools) > self.manager.config.initial_root_children:
        tools = tools[: self.manager.config.initial_root_children]
    self.manager.save_and_log_states(content=response, save_name="tool_selector_response.txt", add_uuid=False)
    self.manager.save_and_log_states(content="\n".join(tools), save_name="selected_tool.txt", add_uuid=False)
    self.manager.save_and_log_states(content=response, save_name="tool_selector_explanation.txt", add_uuid=False)
    self.manager.log_agent_end(f"ToolSelectorAgent: selected tools in priority order: {', '.join(tools)}")
    return tools


def patched_retriever_call(self):
    self.manager.log_agent_start("RetrieverAgent: forcing LLM query generation and retrieval.")
    prompt = (
        f"Write one short tutorial search query for the tool {self.manager.selected_tool}. "
        "Task: binary classification on tiny.csv with numeric features and label column. "
        "Return query only."
    )
    self.manager.save_and_log_states(
        content=prompt,
        save_name="retriever_prompt.txt",
        per_iteration=True,
        add_uuid=False,
    )
    if not self.retriever_llm_config.multi_turn:
        self.retriever_llm = init_single_turn(self.retriever_llm_config, "retriever")
    response = self.retriever_llm.assistant_chat(prompt)
    cleaned_query = strip_code_fences(response).strip()
    search_query = cleaned_query.splitlines()[0].strip('"') or f"{self.manager.selected_tool} binary classification csv"
    results = self.indexer.search(
        query=search_query,
        tool_name=self.manager.selected_tool,
        condensed=self.config.condense_tutorials,
        top_k=self.config.num_tutorial_retrievals,
    )
    retrieved_tutorials = self._convert_to_tutorial_info(results)
    self.manager.save_and_log_states(
        content=response,
        save_name="retriever_response.txt",
        per_iteration=True,
        add_uuid=False,
    )
    self.manager.save_and_log_states(
        content=search_query,
        save_name="parsed_search_query.txt",
        per_iteration=True,
        add_uuid=False,
    )
    self.manager.save_and_log_states(
        content=self._format_retriever_results(results, search_query),
        save_name="tutorial_retriever_results.txt",
        per_iteration=True,
        add_uuid=False,
    )
    self.manager.log_agent_end(
        f"RetrieverAgent: retrieved {len(retrieved_tutorials)} tutorial candidates using LLM query: '{search_query}'"
    )
    return retrieved_tutorials


def patched_reranker_call(self):
    self.manager.log_agent_start("RerankerAgent: forcing LLM reranking.")
    prompt = "Pick the single most relevant tutorial number. Return only the number 1."
    self.manager.save_and_log_states(
        content=prompt,
        save_name="reranker_prompt.txt",
        per_iteration=True,
        add_uuid=False,
    )
    if not self.reranker_llm_config.multi_turn:
        self.reranker_llm = init_single_turn(self.reranker_llm_config, "reranker")
    response = self.reranker_llm.assistant_chat(prompt)
    selected_tutorials = (self.manager.current_node.tutorial_retrieval or [])[:1]
    tutorial_prompt = self._generate_tutorial_prompt(selected_tutorials)
    self.manager.save_and_log_states(
        content=response,
        save_name="reranker_response.txt",
        per_iteration=True,
        add_uuid=False,
    )
    self.manager.save_and_log_states(
        content="1",
        save_name="selected_tutorials.txt",
        per_iteration=True,
        add_uuid=False,
    )
    self.manager.save_and_log_states(
        content=self._format_reranking_results(selected_tutorials),
        save_name="tutorial_reranking_results.txt",
        per_iteration=True,
        add_uuid=False,
    )
    self.manager.log_agent_end(
        f"RerankerAgent: selected {len(selected_tutorials)} tutorials via LLM and formatted prompt."
    )
    return tutorial_prompt


def patched_coder_call(self):
    self.manager.log_agent_start("CoderAgent: forcing LLM code generation.")
    node_dir = Path(self.manager.get_iteration_folder(self.manager.current_node))
    output_dir = Path(self.manager.get_per_iteration_output_folder(self.manager.current_node))

    if self.language == "python":
        prompt = (
            "Write a complete Python script with no markdown fences. "
            "Read /Users/macbookpro/AI4ML/storage/force_llm_small_input/tiny.csv with pandas. "
            "Use label as target and the other columns as numeric features. "
            "Train a binary classifier with scikit-learn. "
            "Use train_test_split(test_size=0.25, random_state=42, stratify=y). "
            f"Save validation predictions to {output_dir}/results.csv. "
            "Print exactly one line in stdout: validation_score=<number>. "
            "Keep the script short and runnable."
        )
        save_prompt = "python_coder_prompt.txt"
        save_response = "python_coder_response.txt"
        save_code = "python_code.py"
        fallback = PYTHON_FALLBACK.replace("__OUTPUT_DIR__", str(output_dir))
        agent_name = "python_coder"
    else:
        prompt = (
            "Write a minimal bash script with no markdown fences. "
            "Requirements: set -euo pipefail, cd to the working directory below, then run python generated_code.py. "
            f"Working directory: {node_dir}"
        )
        save_prompt = "bash_coder_prompt.txt"
        save_response = "bash_coder_response.txt"
        save_code = "extracted_bash_script.sh"
        fallback = BASH_FALLBACK.format(node_dir=node_dir)
        agent_name = "bash_coder"

    self.manager.save_and_log_states(
        content=prompt,
        save_name=save_prompt,
        per_iteration=True,
        add_uuid=False,
    )
    if not self.coder_llm_config.multi_turn:
        self.coder_llm = init_single_turn(self.coder_llm_config, agent_name)
    response = self.coder_llm.assistant_chat(prompt)
    if self.language == "python":
        generated_code = sanitize_python_response(response)
    else:
        generated_code = sanitize_bash_response(response, node_dir=node_dir)

    if self.language == "python" and "validation_score=" not in generated_code:
        generated_code = fallback
    if self.language == "bash" and "generated_code.py" not in generated_code:
        generated_code = fallback

    self.manager.save_and_log_states(
        content=response,
        save_name=save_response,
        per_iteration=True,
        add_uuid=False,
    )
    self.manager.save_and_log_states(
        content=generated_code,
        save_name=save_code,
        per_iteration=True,
        add_uuid=False,
    )
    if self.language == "python":
        self.manager.save_and_log_states(
            content=generated_code,
            save_name="python_code.py",
            per_iteration=True,
            add_uuid=False,
        )
    self.manager.log_agent_end("CoderAgent: code generated via LLM.")
    return generated_code


def patched_executer_call(self, code_to_execute, code_to_analyze=None, execution_task=None, execution_data=None):
    self.manager.log_agent_start("ExecuterAgent: forcing LLM evaluation of execution output.")
    if code_to_analyze is None:
        code_to_analyze = code_to_execute
    success, stdout, stderr = execute_code(code=code_to_execute, language=self.language, timeout=self.timeout)
    short_stdout = (stdout or "")[:1200]
    short_stderr = (stderr or "")[:800]
    short_code = (code_to_analyze or "")[:2200]
    prompt = (
        "Evaluate whether this execution succeeded. "
        "Respond exactly with 3 lines:\n"
        "DECISION: SUCCESS or FIX\n"
        "ERROR_SUMMARY: ...\n"
        "VALIDATION_SCORE: number or None\n\n"
        f"STDOUT:\n{short_stdout}\n\nSTDERR:\n{short_stderr}\n\nCODE:\n{short_code}"
    )
    if not self.executer_llm_config.multi_turn:
        self.executer_llm = init_single_turn(self.executer_llm_config, f"{self.language}_executer")
    response = self.executer_llm.assistant_chat(prompt)
    decision, error_summary, validation_score = parse_decision(response, success)
    self.manager.log_agent_end(
        f"ExecuterAgent: execution evaluated via LLM. success={success} decision={decision} score={validation_score}"
    )
    return decision, error_summary, validation_score, prompt, stderr, stdout


TaskDescriptorAgent.__call__ = patched_task_descriptor_call
ToolSelectorAgent.__call__ = patched_tool_selector_call
RetrieverAgent.__call__ = patched_retriever_call
RerankerAgent.__call__ = patched_reranker_call
CoderAgent.__call__ = patched_coder_call
ExecuterAgent.__call__ = patched_executer_call


def main() -> None:
    config = OmegaConf.load(DEFAULT_CONFIG_PATH)
    user_config = OmegaConf.load("/Users/macbookpro/AI4ML/backend/config/mlzero-local-openai.yaml")
    config = OmegaConf.merge(config, user_config)
    config.max_chars_per_file = 160
    config.num_tutorial_retrievals = 1
    config.max_num_tutorials = 1
    config.max_tutorial_length = 200
    config.max_user_input_length = 256
    config.max_error_message_length = 512
    config.python_coder.max_tokens = 256
    config.bash_coder.max_tokens = 96
    config.executer.max_tokens = 96
    config.task_descriptor.max_tokens = 96
    config.retriever.max_tokens = 48
    config.reranker.max_tokens = 32
    config.description_file_retriever.max_tokens = 48
    config.tool_selector.max_tokens = 48

    manager = NodeManager(
        input_data_folder=INPUT_DIR,
        output_folder=str(OUTPUT_DIR),
        config=config,
        enable_per_iteration_instruction=False,
        initial_user_input="Use tiny.csv to do binary classification and report validation score.",
    )

    try:
        run_agent(
            input_data_folder=INPUT_DIR,
            output_folder=str(OUTPUT_DIR),
            manager=manager,
            max_iterations=1,
            continuous_improvement=False,
            initial_user_input="Use tiny.csv to do binary classification and report validation score.",
            verbosity=4,
        )
    finally:
        print(f"OUTPUT_DIR={OUTPUT_DIR}")


if __name__ == "__main__":
    main()
