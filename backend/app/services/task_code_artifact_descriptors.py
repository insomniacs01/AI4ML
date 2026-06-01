from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


TEXT_ARTIFACT_SUFFIXES = {
    ".py": "python",
    ".txt": "text",
    ".md": "markdown",
    ".json": "json",
    ".csv": "csv",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".log": "log",
    ".sh": "shell",
    ".ps1": "powershell",
    ".bat": "batch",
    ".sql": "sql",
}
TEXT_ARTIFACT_FILENAMES = {"stdout": "log", "stderr": "log"}
EDITABLE_LANGUAGES = {"python", "shell", "powershell", "batch", "sql"}
GROUP_ORDER = {"generation": 0, "result": 1, "log": 2, "context": 3, "other": 4}


@dataclass(frozen=True)
class ArtifactDescriptor:
    category: str
    group: str
    artifact_kind: str
    display_name: str
    purpose: str
    editing_guidance: str
    stage: str | None = None
    is_core: bool = False
    sort_priority: int = 999


def _d(
    category: str,
    group: str,
    kind: str,
    name: str,
    purpose: str,
    guidance: str,
    stage: str | None = None,
    is_core: bool = False,
    priority: int = 999,
) -> ArtifactDescriptor:
    return ArtifactDescriptor(category, group, kind, name, purpose, guidance, stage, is_core, priority)


FINAL_MODELING = _d(
    "code", "generation", "final_modeling", "训练源码",
    "这是 Codex 最终用于训练、验证和导出模型结果的 Python 源码。",
    "建议优先编辑这个文件来调整训练逻辑。保存后只会写回本次运行目录，不会自动重跑。",
    "final_code", True, 0,
)
PREDICT_ENTRYPOINT = _d(
    "code", "generation", "predict_entrypoint", "预测入口源码",
    "这是 Codex 生成的预测入口，前端预测演示会围绕它调用真实模型。",
    "适合修改预测入参解析和输出格式；如果要调整训练逻辑，请优先查看训练源码。",
    "prediction", True, 1,
)
RUNTIME_CONFIG = _d(
    "other", "context", "runtime_config", "运行时配置快照",
    "这里保存了这次运行使用的配置快照，方便追溯当时的参数和模型设置。",
    "这是运行配置快照，通常用于理解上下文，不建议直接在这里改。",
    "context", False, 200,
)

EXACT_NAME_DESCRIPTORS = {
    "final_modeling.py": FINAL_MODELING,
    "predict.py": PREDICT_ENTRYPOINT,
    "generated_code.py": _d(
        "code", "generation", "generated_code", "最终执行代码",
        "这是当前节点最终真正执行的 Python 代码，最接近你想要直接修改的 AI 产物。",
        "建议优先编辑这个文件。保存后只会写回本次运行目录，不会自动重跑。",
        "final_code", True, 0,
    ),
    "python_code.py": _d(
        "code", "generation", "python_draft", "Python 草稿代码",
        "这是 Python coder 阶段整理出的代码草稿，通常是最终执行代码的上游版本。",
        "适合对照 AI 的中间稿；如果要改最终行为，记得同时核对 generated_code.py。",
        "python_draft", True, 1,
    ),
    "execution_script.sh": _d(
        "code", "generation", "execution_script", "执行脚本",
        "这是把当前节点代码真正跑起来的 shell 脚本，用来组织命令行参数和运行入口。",
        "通常只有运行入口、命令参数或环境问题需要排查时才需要修改它。",
        "execution", True, 2,
    ),
    "extracted_bash_script.sh": _d(
        "code", "generation", "bash_draft", "提取出的 Bash 草稿",
        "这是从 AI 回复里抽取出的 shell 脚本草稿，属于执行脚本生成过程中的中间态。",
        "更适合拿来理解 AI 生成了什么命令；真正执行时请优先看 execution_script.sh。",
        "execution", False, 40,
    ),
    "token_usage.json": _d(
        "result", "result", "token_usage", "Token 用量记录",
        "这里记录了这次运行中 AI 会话的 token 消耗情况。",
        "这是统计结果文件，默认只读。",
        "usage", True, 6,
    ),
    "runtime-config.yaml": RUNTIME_CONFIG,
    "codex-config.toml": RUNTIME_CONFIG,
}

RUN_SUMMARY = _d(
    "result", "result", "run_summary", "运行摘要",
    "这是这次运行的总体结果摘要，适合先快速判断 AI 代码有没有跑通以及结果如何。",
    "这是结果快照，默认只读，建议作为概览查看而不是修改入口。",
    "summary", True, 3,
)
NODE_SUMMARY = _d(
    "result", "result", "node_output_summary", "节点输出摘要",
    "这是某个节点输出目录里的结果摘要，反映该节点自己的运行结果。",
    "这是节点结果快照，适合查看，不建议作为编辑入口。",
    "summary", False, 60,
)
LEADERBOARD = _d(
    "result", "result", "leaderboard", "候选结果对比",
    "这里记录的是候选方案、分数或结构化结果，适合用来比较这次运行产出了什么。",
    "这是结果文件，默认只读，更适合查看和对比而不是手工改写。",
    "result_compare", True, 4,
)
PREDICTIONS = _d(
    "result", "result", "predictions", "预测结果表",
    "这里保存了这次运行导出的预测结果或验证结果，方便你核对输出。",
    "这是运行结果，不建议把它当成代码修改入口。",
    "predictions", True, 5,
)
NODE_PREDICTIONS = _d(
    "result", "result", "node_predictions", "节点预测结果",
    "这是某个节点输出目录里的预测结果文件，用来核对该节点产出的表格结果。",
    "这是节点结果文件，适合查看，不建议作为编辑入口。",
    "predictions", False, 61,
)
INPUT_DATASET = _d(
    "other", "context", "input_dataset", "输入数据副本",
    "这是本次运行使用的数据集副本，便于追溯 AI 代码当时面对的数据输入。",
    "这是输入快照，不建议在代码工作区里改数据本身。",
    "context", False, 201,
)
INPUT_CONTEXT = _d(
    "other", "context", "input_context", "输入说明文件",
    "这是本次运行用到的输入说明或附加描述，帮助 AI 理解任务背景。",
    "这是输入上下文文件，适合查看，不建议作为代码编辑入口。",
    "context", False, 202,
)
PROCESS_STREAM = _d(
    "log", "log", "process_stream", "标准输出/错误输出",
    "这里保存的是运行过程中的标准输出或标准错误内容，适合直接看报错和执行痕迹。",
    "这是运行输出流，默认只读，主要用来排查错误。",
    "logs", False, 301,
)
NODE_SCORE = _d(
    "result", "result", "node_score", "节点分数记录",
    "这里记录了某个节点的候选排序分或最佳运行摘要，适合快速判断这个节点在同次运行中的排序表现。",
    "这是结果记录文件，主要用于查看和比对。",
    "score", False, 62,
)
GENERIC_STATE = _d(
    "state", "generation", "generic_state", "过程状态文件",
    "这是运行过程中的中间状态文件，通常用来追踪 AI 在某个阶段产生了什么内容。",
    "这是过程追踪文件，适合理解流程，不建议作为主要代码修改入口。",
    "state", False, 90,
)
OTHER_CODE = _d(
    "code", "other", "other_code", "其他代码文件",
    "这是最新运行目录里的代码文件，但当前还没有命中特定用途规则。",
    "修改前请先确认它是不是当前真正会被执行的入口文件。",
    "other", False, 400,
)
OTHER_TEXT = _d(
    "other", "other", "other_text", "其他文本工件",
    "这是最新运行目录里的文本工件，暂时没有命中特定说明规则。",
    "更适合查看，不建议在不了解上下文时直接修改。",
    "other", False, 401,
)
OTHER_ARTIFACT = _d(
    "other", "other", "other_text", "其他工件",
    "这是最新运行目录里的工件，当前没有识别出更明确的用途。",
    "建议先查看路径和上下文，再决定是否需要操作它。",
    "other", False, 999,
)

LEADERBOARD_NAMES = {"run_summary.json", "leaderboard.csv", "leaderboard.json"}
PREDICTION_NAMES = {"validation_predictions.csv", "results.csv"}
PROCESS_STREAM_NAMES = {"stdout", "stderr"}
PROCESS_STREAM_PREFIXES = ("stdout_", "stderr_")
CODE_SUFFIXES = (".py", ".sh", ".ps1", ".bat", ".sql")
TEXT_SUFFIXES = (".json", ".csv", ".yaml", ".yml", ".md", ".txt")


def _runtime_log(display_name: str) -> ArtifactDescriptor:
    return _d(
        "log", "log", "runtime_log", display_name,
        "这是运行过程中的总日志或分级日志，用来排查流程执行情况。",
        "日志文件默认只读，主要用于定位问题，不建议修改。",
        "logs", False, 300,
    )


LOG_DESCRIPTORS = {
    "logs.txt": _runtime_log("总日志"),
    "detail_logs.txt": _runtime_log("详细日志"),
    "info_logs.txt": _runtime_log("信息日志"),
    "debugging_logs.txt": _runtime_log("调试日志"),
}

GENERATION_STATE_PREFIX_DESCRIPTORS = (
    (("python_coder_prompt",), _d(
        "state", "generation", "python_coder_prompt", "写代码 Prompt",
        "这是发给写代码模型的提示词，能直接看到 AI 当时是基于什么要求写代码的。",
        "更适合理解生成过程；如果你要改最终代码，优先看 generated_code.py。",
        "python_coder", True, 20,
    )),
    (("python_coder_response",), _d(
        "state", "generation", "python_coder_response", "写代码 AI 回复",
        "这是写代码模型返回的原始文本，方便对照 AI 原话和最终落地代码之间的差别。",
        "更适合审阅 AI 的原始回答；真正执行的代码仍以 generated_code.py 为准。",
        "python_coder", True, 21,
    )),
    (("python_coder_retry_request",), _d(
        "state", "generation", "python_coder_retry_request", "代码重试请求",
        "这是系统要求 AI 重写代码时发出的补充请求，用来解释为什么会再次生成代码。",
        "这是过程追踪文件，适合理解重试原因，不是最终代码入口。",
        "python_coder_retry", False, 22,
    )),
    (("python_coder_retry_response",), _d(
        "state", "generation", "python_coder_retry_response", "代码重试回复",
        "这是 AI 针对重试请求给出的回复，适合用来对比修复前后发生了什么变化。",
        "这是过程追踪文件，适合理解重试结果，不是最终代码入口。",
        "python_coder_retry", False, 23,
    )),
    (("bash_coder_prompt",), _d(
        "state", "generation", "bash_coder_prompt", "执行脚本 Prompt",
        "这是发给脚本生成阶段的提示词，用来生成或整理执行命令。",
        "这是脚本生成过程文件，更适合理解 AI 怎样组织运行命令。",
        "bash_coder", False, 24,
    )),
    (("bash_coder_response",), _d(
        "state", "generation", "bash_coder_response", "执行脚本 AI 回复",
        "这是脚本生成阶段 AI 的原始回复，通常对应 execution_script.sh 的上游内容。",
        "建议把它当成过程说明来看；真正运行的脚本优先看 execution_script.sh。",
        "bash_coder", False, 25,
    )),
    (("executer_prompt",), _d(
        "state", "generation", "executer_prompt", "执行阶段 Prompt",
        "这是执行/审查阶段发给 AI 的提示词，通常会携带运行结果或报错信息。",
        "这是过程文件，适合拿来理解系统为什么做出下一步判断。",
        "executor", False, 26,
    )),
    (("executer_response",), _d(
        "state", "generation", "executer_response", "执行阶段 AI 回复",
        "这是执行/审查阶段 AI 的回复，反映它如何理解运行结果或错误。",
        "这是过程文件，主要用于理解 AI 的判断，不是最终代码入口。",
        "executor", False, 27,
    )),
    (("decision_",), _d(
        "state", "generation", "decision", "决策记录",
        "这是节点内部的决策说明，帮助你理解系统为什么选择当前这条生成或修复路径。",
        "这是过程说明文件，适合查看，不建议作为代码编辑入口。",
        "decision", False, 29,
    )),
)
ERROR_ANALYSIS_PREFIXES = ("error_analyzer_prompt", "error_analyzer_response", "error_summary")
ERROR_ANALYSIS_NAMES = {"error_analysis.txt"}
ERROR_ANALYSIS = _d(
    "state", "generation", "error_analysis", "错误分析",
    "这里记录了失败分析阶段的提示词、AI 回复或错误总结，用来解释为什么代码没跑通。",
    "这是排错过程文件，适合查看问题来源，不建议作为最终代码入口。",
    "repair", False, 28,
)
TASK_SETUP_NAMES = {
    "description_files.txt",
    "description_file_retriever_prompt.txt",
    "description_file_retriever_response.txt",
    "task_description.txt",
    "task_descriptor_prompt.txt",
    "task_descriptor_response.txt",
    "selected_tool.txt",
    "tool_selector_prompt.txt",
    "tool_selector_response.txt",
    "tool_selector_explanation.txt",
}
TASK_SETUP = _d(
    "state", "generation", "task_setup", "任务理解过程",
    "这里记录的是任务描述、工具选择和前置理解过程，帮助解释 AI 为什么会走到后面的代码生成步骤。",
    "这是任务理解阶段文件，更适合看 AI 的思路，不建议直接当作代码入口。",
    "task_setup", False, 30,
)
READER_STAGE_NAMES = {"chat_prompt.txt", "chat_response.txt", "user_message.txt"}
READER_STAGE = _d(
    "state", "generation", "reader_stage", "前置读取阶段",
    "这是前置读取/解释阶段留下的文本或代码，用来说明系统怎样理解输入数据和任务。",
    "这是过程文件，主要用于理解上下文和前置读取逻辑。",
    "reader", False, 31,
)
RETRIEVAL_PREFIXES = ("tutorial_", "retriever_", "reranker_")
RETRIEVAL_NAMES = {"parsed_search_query.txt", "selected_tutorials.txt"}
RETRIEVAL_STAGE = _d(
    "state", "generation", "retrieval_stage", "检索与教程选择",
    "这里记录的是教程检索、重排和上下文拼装过程，帮助解释 AI 写代码时参考了哪些材料。",
    "这是检索过程文件，更适合排查 AI 参考了什么内容。",
    "retrieval", False, 32,
)


def detect_artifact_language(path: Path) -> str | None:
    filename_language = TEXT_ARTIFACT_FILENAMES.get(path.name.lower())
    if filename_language is not None:
        return filename_language
    return TEXT_ARTIFACT_SUFFIXES.get(path.suffix.lower())


def is_editable_artifact(descriptor: ArtifactDescriptor, language: str) -> bool:
    return language in EDITABLE_LANGUAGES and descriptor.category == "code"


def describe_artifact(relative_path: str, filename: str) -> ArtifactDescriptor:
    lowered_path = relative_path.lower()
    lowered_name = filename.lower()
    in_output_dir = "/output/" in f"/{lowered_path}"

    descriptor = _direct_descriptor(lowered_path, lowered_name, in_output_dir)
    if descriptor is not None:
        return descriptor

    descriptor = _generation_state_descriptor(lowered_name)
    if descriptor is not None:
        return descriptor

    if "/states/" in f"/{lowered_path}" or lowered_path.startswith("states/"):
        return GENERIC_STATE
    if lowered_name.endswith(CODE_SUFFIXES):
        return OTHER_CODE
    if lowered_name.endswith(TEXT_SUFFIXES):
        return OTHER_TEXT
    return OTHER_ARTIFACT


def _direct_descriptor(lowered_path: str, lowered_name: str, in_output_dir: bool) -> ArtifactDescriptor | None:
    descriptor = EXACT_NAME_DESCRIPTORS.get(lowered_name)
    if descriptor is not None:
        return descriptor
    if lowered_name == "summary.txt":
        return NODE_SUMMARY if in_output_dir else RUN_SUMMARY
    if lowered_name in LEADERBOARD_NAMES:
        return LEADERBOARD
    if lowered_name in PREDICTION_NAMES:
        return NODE_PREDICTIONS if in_output_dir else PREDICTIONS
    if lowered_path.startswith("input/"):
        return INPUT_DATASET if lowered_name.endswith(".csv") else INPUT_CONTEXT
    descriptor = LOG_DESCRIPTORS.get(lowered_name)
    if descriptor is not None:
        return descriptor
    if lowered_name in PROCESS_STREAM_NAMES or lowered_name.startswith(PROCESS_STREAM_PREFIXES):
        return PROCESS_STREAM
    if lowered_name.startswith("validation_score_") or lowered_name == "best_run_summary.txt":
        return NODE_SCORE
    return None


def _generation_state_descriptor(lowered_name: str) -> ArtifactDescriptor | None:
    for prefixes, descriptor in GENERATION_STATE_PREFIX_DESCRIPTORS:
        if lowered_name.startswith(prefixes):
            return descriptor
    if lowered_name.startswith(ERROR_ANALYSIS_PREFIXES) or lowered_name in ERROR_ANALYSIS_NAMES:
        return ERROR_ANALYSIS
    if lowered_name in TASK_SETUP_NAMES:
        return TASK_SETUP
    if lowered_name.startswith("python_reader_") or lowered_name in READER_STAGE_NAMES:
        return READER_STAGE
    if lowered_name.startswith(RETRIEVAL_PREFIXES) or lowered_name in RETRIEVAL_NAMES:
        return RETRIEVAL_STAGE
    return None
