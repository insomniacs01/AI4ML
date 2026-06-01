from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import quote

from backend.app.models.task import (
    HumanInteractionRequestStatus,
    TaskAgentEventRecord,
    TaskAgentMessageRecord,
    TaskAgentRuntimeRecord,
    TaskHumanRequestRecord,
    TaskRecord,
    TokenUsageReport,
    WorkflowStage,
    WorkflowStageStatus,
    normalize_workflow_stage,
)
from backend.app.services.task_store_payloads import TaskPayloadMapper


def _coerce_non_negative_int(value: Any) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return 0
    return max(result, 0)



class TaskTokenRepository(TaskPayloadMapper):
    def __init__(self, http) -> None:
        self.http = http

    def _request_json(self, **kwargs):
        return self.http.request_json(**kwargs)

    def upsert_run_summary(
        self,
        task: TaskRecord,
        summary: RunSummary,
        *,
        access_token: str,
        status: str = "completed",
        notes: str | None = None,
    ) -> None:
        output_dir = summary.output_dir
        existing = self._request_json(
            path=(
                "task_runs"
                f"?select=id&team_id=eq.{quote(task.team_id, safe='')}"
                f"&task_id=eq.{quote(task.id, safe='')}"
                f"&output_dir=eq.{quote(output_dir, safe='')}"
                "&limit=1"
            ),
            access_token=access_token,
        )
        body = {
            "team_id": task.team_id,
            "task_id": task.id,
            "status": status,
            "output_dir": output_dir,
            "best_model": summary.best_model,
            "metric_name": summary.metric_name,
            "metric_value": summary.metric_value,
            "leaderboard": summary.leaderboard,
            "token_usage": summary.token_usage.model_dump() if summary.token_usage else None,
            "notes": notes,
            "finished_at": task.updated_at.isoformat(),
        }
        if isinstance(existing, list) and existing:
            self._request_json(
                path=f"task_runs?id=eq.{quote(str(existing[0]['id']), safe='')}",
                access_token=access_token,
                method="PATCH",
                body=body,
            )
            return
        self._request_json(path="task_runs", access_token=access_token, method="POST", body=body)

    def upsert_run_attempt(
        self,
        task: TaskRecord,
        *,
        output_dir: str,
        access_token: str,
        status: str,
        token_usage: TokenUsageReport | None = None,
        notes: str | None = None,
    ) -> None:
        existing = self._request_json(
            path=(
                "task_runs"
                f"?select=id&team_id=eq.{quote(task.team_id, safe='')}"
                f"&task_id=eq.{quote(task.id, safe='')}"
                f"&output_dir=eq.{quote(output_dir, safe='')}"
                "&limit=1"
            ),
            access_token=access_token,
        )
        body = {
            "team_id": task.team_id,
            "task_id": task.id,
            "status": status,
            "output_dir": output_dir,
            "token_usage": token_usage.model_dump() if token_usage else None,
            "notes": notes,
            "finished_at": task.updated_at.isoformat(),
        }
        if isinstance(existing, list) and existing:
            self._request_json(
                path=f"task_runs?id=eq.{quote(str(existing[0]['id']), safe='')}",
                access_token=access_token,
                method="PATCH",
                body=body,
            )
            return
        self._request_json(path="task_runs", access_token=access_token, method="POST", body=body)

    def upsert_token_ledger(
        self,
        *,
        team_id: str,
        task_id: str,
        phase: str,
        source_key: str,
        usage: TokenUsageReport | None,
        access_token: str,
        user_id: str | None = None,
        connector_id: str | None = None,
        connector_display_name: str | None = None,
        model_name: str | None = None,
        stage_key: str | None = None,
        calculation_method: str | None = None,
    ) -> None:
        if usage is None:
            return

        existing = self._request_json(
            path=(
                "token_ledgers"
                f"?select=id,total_tokens&team_id=eq.{quote(team_id, safe='')}"
                f"&task_id=eq.{quote(task_id, safe='')}"
                f"&phase=eq.{quote(phase, safe='')}"
                f"&source_key=eq.{quote(source_key, safe='')}"
                "&limit=1"
            ),
            access_token=access_token,
        )
        previous_total = 0
        if isinstance(existing, list) and existing:
            previous_total = _coerce_non_negative_int(existing[0].get("total_tokens"))

        body = {
            "team_id": team_id,
            "task_id": task_id,
            "user_id": user_id,
            "connector_id": connector_id,
            "connector_display_name": connector_display_name,
            "phase": phase,
            "stage_key": stage_key,
            "source_key": source_key,
            "model_name": model_name,
            "calculation_method": calculation_method,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
            "raw_usage": usage.model_dump(),
        }
        self._request_json(
            path="token_ledgers?on_conflict=team_id,task_id,phase,source_key",
            access_token=access_token,
            method="POST",
            body=body,
            prefer="resolution=merge-duplicates,return=representation",
        )

        delta = usage.total_tokens - previous_total
        if user_id and delta != 0:
            self._adjust_member_token_usage(
                team_id=team_id,
                user_id=user_id,
                token_delta=delta,
                access_token=access_token,
            )

    def _adjust_member_token_usage(self, *, team_id: str, user_id: str, token_delta: int, access_token: str) -> None:
        self._request_json(
            path="rpc/adjust_member_token_usage",
            access_token=access_token,
            method="POST",
            body={
                "target_team_id": team_id,
                "target_user_id": user_id,
                "token_delta": token_delta,
            },
            expect_json=False,
        )
