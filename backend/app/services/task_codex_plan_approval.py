from __future__ import annotations


CODEX_PLAN_NOT_READY_DETAIL = "Codex plan is not ready for approval"

PLACEHOLDER_CODEX_PLAN_PHRASES = (
    "codex 正在读取数据并生成可确认的建模计划",
    "正在读取数据并生成可确认的建模计划",
    "正在生成可确认的建模计划",
)
ACTIONABLE_CODEX_PLAN_MARKERS = (
    "目标",
    "任务类型",
    "默认假设",
    "数据",
    "训练",
    "建模",
    "模型",
    "验证",
    "评估",
    "指标",
    "特征",
    "产物",
    "target",
    "metric",
    "train",
    "model",
    "validation",
    "rmse",
    "feature",
)


class CodexPlanNotReadyError(RuntimeError):
    pass


def assert_codex_plan_ready_for_approval(plan_text: str) -> None:
    if not codex_plan_ready_for_approval(plan_text):
        raise CodexPlanNotReadyError(CODEX_PLAN_NOT_READY_DETAIL)


def codex_plan_ready_for_approval(plan_text: str) -> bool:
    text = plan_text.strip()
    if not text:
        return False
    normalized = " ".join(text.lower().split())
    if any(phrase in normalized for phrase in PLACEHOLDER_CODEX_PLAN_PHRASES):
        return False

    content_lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    content_text = " ".join(content_lines).lower()
    marker_count = sum(1 for marker in ACTIONABLE_CODEX_PLAN_MARKERS if marker in content_text)
    if marker_count < 2:
        return False
    if len(content_text) < 80 and marker_count < 4:
        return False
    return True
