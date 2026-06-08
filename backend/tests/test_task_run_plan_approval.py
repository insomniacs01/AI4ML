from __future__ import annotations

import pytest

from backend.app.services.task_codex_plan_approval import (
    CODEX_PLAN_NOT_READY_DETAIL,
    CodexPlanNotReadyError,
    assert_codex_plan_ready_for_approval,
)


def test_rejects_placeholder_codex_plan() -> None:
    with pytest.raises(CodexPlanNotReadyError) as exc_info:
        assert_codex_plan_ready_for_approval(
            "# AI4ML 任务计划\n\nCodex 正在读取数据并生成可确认的建模计划。\n"
        )

    assert str(exc_info.value) == CODEX_PLAN_NOT_READY_DETAIL


def test_accepts_actionable_codex_plan() -> None:
    assert_codex_plan_ready_for_approval(
        """
        # AI4ML 任务计划

        默认假设：以 CO(GT) 作为目标列，任务类型为回归。
        数据处理：读取 CSV，处理 -200 缺失标记，并按时间顺序切分训练集和验证集。
        建模与评估：训练 RandomForestRegressor，使用 RMSE 作为主指标，并输出特征重要性和模型产物。
        """
    )
