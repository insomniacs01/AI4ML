import logging
import re
from pathlib import Path

from ..prompts import BashCoderPrompt, PythonCoderPrompt
from .base_agent import BaseAgent
from .utils import init_llm

logger = logging.getLogger(__name__)


def _extract_task_field(task_description: str, field_name: str, default: str) -> str:
    pattern = rf"{re.escape(field_name)}:\s*(.+)"
    match = re.search(pattern, task_description)
    if match:
        return match.group(1).strip()
    return default


def _build_local_machine_learning_python(manager) -> str:
    node_dir = Path(manager.get_iteration_folder(manager.current_node))
    output_dir = Path(manager.get_per_iteration_output_folder(manager.current_node))
    train_path = Path(manager.input_data_folder) / "train.csv"
    label_column = _extract_task_field(manager.task_description, "Label column", "label")
    problem_type = _extract_task_field(manager.task_description, "Problem type", "classification").lower()

    lines = [
        '"""Deterministic sklearn baseline generated for local MLZero validation."""',
        "from __future__ import annotations",
        "",
        "import time",
        "from pathlib import Path",
        "",
        "import joblib",
        "import pandas as pd",
        "from sklearn.compose import ColumnTransformer",
        "from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor",
        "from sklearn.impute import SimpleImputer",
        "from sklearn.metrics import accuracy_score, mean_squared_error",
        "from sklearn.model_selection import train_test_split",
        "from sklearn.pipeline import Pipeline",
        "from sklearn.preprocessing import OneHotEncoder, StandardScaler",
        "",
        f'TRAIN_PATH = Path(r"{train_path}")',
        f'OUTPUT_DIR = Path(r"{output_dir}")',
        f'LABEL_COLUMN = "{label_column}"',
        f'PROBLEM_TYPE = "{problem_type}"',
        "",
        "def build_preprocessor(frame: pd.DataFrame) -> ColumnTransformer:",
        '    numeric_features = frame.select_dtypes(include=["number", "bool"]).columns.tolist()',
        "    categorical_features = [col for col in frame.columns if col not in numeric_features]",
        "    transformers = []",
        "    if numeric_features:",
        "        transformers.append((",
        '            "numeric",',
        "            Pipeline(",
        "                steps=[",
        '                    ("imputer", SimpleImputer(strategy="median")),',
        '                    ("scaler", StandardScaler()),',
        "                ]",
        "            ),",
        "            numeric_features,",
        "        ))",
        "    if categorical_features:",
        "        transformers.append((",
        '            "categorical",',
        "            Pipeline(",
        "                steps=[",
        '                    ("imputer", SimpleImputer(strategy="most_frequent")),',
        '                    ("encoder", OneHotEncoder(handle_unknown="ignore")),',
        "                ]",
        "            ),",
        "            categorical_features,",
        "        ))",
        '    remainder = "drop" if transformers else "passthrough"',
        "    return ColumnTransformer(transformers=transformers, remainder=remainder)",
        "",
        "def main() -> None:",
        "    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)",
        "    data = pd.read_csv(TRAIN_PATH)",
        "    if LABEL_COLUMN not in data.columns:",
        '        raise ValueError(f"Missing label column: {LABEL_COLUMN}")',
        "    data = data.dropna(subset=[LABEL_COLUMN]).copy()",
        "    y = data.pop(LABEL_COLUMN)",
        "    X = data",
        "    stratify = None",
        '    if PROBLEM_TYPE == "classification" and y.nunique() > 1 and y.value_counts().min() > 1:',
        "        stratify = y",
        "    X_train, X_valid, y_train, y_valid = train_test_split(",
        "        X,",
        "        y,",
        "        test_size=0.2,",
        "        random_state=42,",
        "        stratify=stratify,",
        "    )",
        "    preprocessor = build_preprocessor(X_train)",
        '    model = RandomForestClassifier(n_estimators=200, random_state=42) if PROBLEM_TYPE == "classification" else RandomForestRegressor(n_estimators=200, random_state=42)',
        "    pipeline = Pipeline(",
        "        steps=[",
        '            ("preprocessor", preprocessor),',
        '            ("model", model),',
        "        ]",
        "    )",
        "    pipeline.fit(X_train, y_train)",
        "    predictions = pipeline.predict(X_valid)",
        '    if PROBLEM_TYPE == "classification":',
        "        score = accuracy_score(y_valid, predictions)",
        "    else:",
        "        score = mean_squared_error(y_valid, predictions, squared=False)",
        '    model_dir = OUTPUT_DIR / f"model_{int(time.time())}"',
        "    model_dir.mkdir(parents=True, exist_ok=True)",
        '    joblib.dump(pipeline, model_dir / "pipeline.joblib")',
        "    results = X_valid.copy()",
        "    results[LABEL_COLUMN] = predictions",
        '    results.to_csv(OUTPUT_DIR / "results.csv", index=True)',
        '    print(f"validation_score={score:.6f}")',
        '    print(f"Validation score: {score:.6f}")',
        "",
        'if __name__ == "__main__":',
        "    main()",
    ]
    return "\n".join(lines) + "\n"


def _build_local_machine_learning_bash(manager) -> str:
    node_dir = Path(manager.get_iteration_folder(manager.current_node))
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        f'cd "{node_dir}"',
        "python generated_code.py",
    ]
    return "\n".join(lines) + "\n"


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

        if self.coding_mode == "coder" and self.manager.selected_tool == "machine learning":
            if self.language == "python":
                prompt = "Local deterministic machine learning baseline generator."
                generated_code = _build_local_machine_learning_python(self.manager)
                self.manager.save_and_log_states(
                    content=prompt, save_name="python_coder_prompt.txt", per_iteration=True, add_uuid=False
                )
                self.manager.save_and_log_states(
                    content=generated_code, save_name="python_coder_response.txt", per_iteration=True, add_uuid=False
                )
                self.manager.save_and_log_states(
                    content=generated_code, save_name="python_code.py", per_iteration=True, add_uuid=False
                )
            else:
                prompt = "Local deterministic bash runner for machine learning baseline."
                generated_code = _build_local_machine_learning_bash(self.manager)
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

            self.manager.log_agent_end("CoderAgent: local deterministic code generated without LLM.")
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

        self.manager.log_agent_end("CoderAgent: code-generation prompt handled and code parsed from response.")

        return generated_code
