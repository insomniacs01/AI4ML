"""
Python code generation prompt.

This module provides the PythonCoderPrompt class for generating Python code
based on task description, data structure, and other context.
"""

import logging
from typing import Dict, Optional, Tuple

from ..utils import get_cpu_count, get_gpu_count
from .base_prompt import BasePrompt
from .utils import extract_code

logger = logging.getLogger(__name__)


class PythonCoderPrompt(BasePrompt):
    """Handles prompts for Python code generation"""

    @classmethod
    def meta_instructions(cls) -> str:
        """
        Returns specific instructions for meta-prompting the Python coder template.
        """
        return """
This prompt generates executable Python code for the specified task. Make sure to PRESERVE the variables in the original template.
"""

    def default_template(self) -> str:
        return """
As an AutoML Agent, you will be given a folder containing data and description files. Generate one COMPLETE Python script using {selected_tool}. Keep it concise, fully executable, and aligned with the files that actually exist in the input folder.

ONLY save files to the working directory: {per_iteration_output_folder}.

Requirements:
- Use train.csv as the primary dataset. If test.csv is missing, do NOT assume it exists; use a validation approach that works with the selected library and report a validation score.
- If test.csv exists, predict the full test set without dropping rows and preserve original row order and indices.
- If the task description or user instruction specifies a label/target column, use that exact column as the target. Never silently replace it with the last CSV column.
- Remove training samples without valid labels from training data only, unless explicitly instructed otherwise.
- Remove unnecessary index columns such as 'Unnamed: 0' when appropriate.
- Do not stop at a single baseline when labeled training data is available. Compare multiple candidate models and persist a ranked leaderboard of the candidates you actually evaluated.
- For tabular classification and regression in this project runtime, use autogluon.tabular and fix its configuration directly instead of switching to sklearn or another library.
- Follow any runtime-verified AutoGluon dependency and model-family constraints provided in the task description or user instruction. Restrict fit() hyperparameters to the verified supported families and do not assume torch, lightgbm, xgboost, catboost, tabicl, or tabm are installed unless they are explicitly verified.
- Do not use AutoGluon presets or portfolios that depend on optional extras unless those dependencies are explicitly verified. In particular, do not use extreme, extreme_quality, best, best_quality, high, high_quality, good, good_quality, or any zeroshot/tabarena/foundation-model portfolio when the runtime guidance forbids them.
- Do not add a secondary sklearn implementation path. If an autogluon.tabular attempt fails, correct the AutoGluon hyperparameters, preset choice, API usage, or data handling and keep the solution in autogluon.tabular.
- For large tabular datasets, bound tree model sizes, for example RF/XT n_estimators around 30-80, and drop obvious file/path/provenance identifier columns such as Source_File when they are not the prediction target.
- Do not manually log-transform, scale, or otherwise transform the target column unless you also inverse-transform predictions and compute metric_value on the original target scale. Prefer leaving the target on its original scale.
- Do not pass a fit(time_limit=...) value to AutoGluon unless the user explicitly asks for one; let training finish instead of cutting it short.
- In AutoGluon 1.4, use predictor.model_best or the first leaderboard row to identify the best model. Do not call predictor.get_model_best().
- Before saving leaderboard.json or leaderboard.csv, normalize AutoGluon leaderboard() output to the canonical artifact schema. Each saved row must include exact fields model and validation_score, and should include fit_time and pred_time when available.
- Do not persist raw AutoGluon field names such as score_val or pred_time_val in the final saved leaderboard artifact; rename them to validation_score and pred_time first. If you include rank, derive it yourself from the sorted row order.
- AutoGluon does not accept the generic problem_type value 'classification'. Infer the label cardinality first and pass problem_type='binary' for 2 classes or problem_type='multiclass' for more than 2 classes.
- If a model is trained, save it in a timestamped folder under {per_iteration_output_folder}.
- Save prediction results to {per_iteration_output_folder}. If there is no test set, save validation artifacts instead.
- Print the final validation score clearly when labeled training data is available, and persist any summary artifacts needed by downstream evaluation.
- Save a machine-readable run summary to {per_iteration_output_folder}/run_summary.json with at least: metric_name, metric_value, validation_score, best_model, tool, candidate_model_count, target_column, and problem_type.
- Save the compared candidates to {per_iteration_output_folder}/leaderboard.json or {per_iteration_output_folder}/leaderboard.csv. Each row should include exact fields model and validation_score, plus fit_time and pred_time when available.
- If the task metric is naturally lower-is-better (for example RMSE), still persist a higher-is-better validation_score for search and comparison, while also saving the raw metric in run_summary.json.
- Add only brief comments when they genuinely help readability.
- Wrap the runnable entrypoint with: if __name__ == "__main__":
- Do not use try/except blocks unless you explicitly re-raise the exception.
- Do not include bash, shell, PowerShell, or pip install commands anywhere in the Python response.
- Return one Python script only. Do not prepend a shell setup block before the Python code.
- Return the FULL script from the first line to the final line. Do not omit the ending.

{tool_prompt}

{code_improvement_prompt}

{validation_prompt}

### Task Description
{task_description}

### Data Structure
{data_prompt}

### User Instruction
{user_input_truncate_end_2048}

### Previous Errors
These errors were encountered across different implementation approaches and may not be directly related to your current implementation. Use them as reference material to identify potential pitfalls and avoid similar mistakes in your implementation.
{all_previous_error_analyses}

### Tutorials for Reference
{tutorial_prompt}
"""

    def get_format_instruction(self) -> str:
        """Get the format instruction to append to the prompt."""
        return (
            "Please format your response with exactly one ```python``` code block containing the full script. "
            "Do not include any ```bash``` or shell code blocks."
        )

    def _build(self, **kwargs) -> str:
        """Build a prompt for the LLM to generate Python code.

        Args:
            **kwargs: Additional keyword arguments to customize the prompt building process
        """
        assert self.manager.time_step >= 0, "run manager.step(user_input) before retrieving the prompt"

        # Generate best code prompt and validation prompt
        code_improvement_prompt = self._generate_code_improvement_prompt()
        validation_prompt = self._generate_validation_prompt()

        # Render the prompt using the variable provider with additional variables
        additional_vars = {
            "code_improvement_prompt": code_improvement_prompt,  # Dynamically generated
            "validation_prompt": validation_prompt,  # Dynamically generated
        }

        prompt = self.render(additional_vars)

        # TODO: Remove hardcoding. And add this safeguard for other prompts.
        if len(prompt) > 80000:
            logger.warning(f"Coder's prompt too long: {len(prompt)}. Truncated.")
            self.manager.save_and_log_states(
                content=prompt,
                save_name="python_coder_prompt_before_truncation.txt",
                per_iteration=True,
                add_uuid=False,
            )
            prompt = self._truncate_output_end(
                output=prompt,
                max_length=80000,
            )

        self.manager.save_and_log_states(
            content=prompt, save_name="python_coder_prompt.txt", per_iteration=True, add_uuid=False
        )

        return prompt

    def _generate_validation_prompt(self) -> str:
        """Generate the validation section of the prompt."""
        if self.manager.config.continuous_improvement:
            return """6. Validation (only when there is labeled training data):
   - If there is training and but no validation data is given, hold out a validation dataset (10 percent of the data) at the start, train only on the remaining data.
   - At the end compute and print the final evaluation metric score on the validation set.
   - Use a try-except block for the validation step - if validation fails, it's acceptable to continue.
"""
        else:
            return ""

    def _generate_system_resources_prompt(self) -> str:
        """Generate information about available system resources."""
        return f"""### System Resources
Available CPUs: {get_cpu_count()}
Available GPUs: {get_gpu_count()}
Please optimize your code to efficiently utilize the available hardware resources. 
"""

    def _generate_code_improvement_prompt(self) -> str:
        """Generate prompt section about best/successful previous code."""
        if self.manager.time_step == 0:
            return ""  # No previous code on first iteration

        if self.manager.code_to_improve:
            code_improvement_prompt = f"""### Previous Code to Improve
```python
{self.manager.code_to_improve}
```
Please prioritize model architecture improvements and training optimization to enhance performance. Feature engineering may also be applied but with lower priority.
"""
        elif self.manager.code_to_debug:
            code_improvement_prompt = f"""### Previous Code to Debug
```python
{self.manager.code_to_debug}
```
Please fix the errors in the code above. Make minimal changes necessary to fix the issues.
"""
        else:
            code_improvement_prompt = ""

        if self.manager.config.optimize_system_resources:
            code_improvement_prompt += self._generate_system_resources_prompt()

        return code_improvement_prompt

    def parse(self, response: Dict) -> Tuple[str, Optional[str]]:
        """Parse the LLM's response to generated python code"""

        python_code = extract_code(response=response, language="python")

        self.manager.save_and_log_states(
            content=response, save_name="python_coder_response.txt", per_iteration=True, add_uuid=False
        )
        self.manager.save_and_log_states(
            content=python_code, save_name="python_code.py", per_iteration=True, add_uuid=False
        )

        return python_code
