from __future__ import annotations

from datetime import datetime
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
from backend.app.services.task_token_ledger_writes import (
    TOKEN_LEDGER_UPSERT_PATH,
    build_token_ledger_payload,
    previous_ledger_total,
    token_ledger_lookup_path,
    token_usage_delta,
)
from backend.app.services.task_store_payloads import TaskPayloadMapper


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
            path=token_ledger_lookup_path(team_id, task_id, phase, source_key),
            access_token=access_token,
        )
        previous_total = previous_ledger_total(existing)
        body = build_token_ledger_payload(
            team_id=team_id,
            task_id=task_id,
            phase=phase,
            source_key=source_key,
            usage=usage,
            user_id=user_id,
            connector_id=connector_id,
            connector_display_name=connector_display_name,
            model_name=model_name,
            stage_key=stage_key,
            calculation_method=calculation_method,
        )
        self._request_json(
            path=TOKEN_LEDGER_UPSERT_PATH,
            access_token=access_token,
            method="POST",
            body=body,
            prefer="resolution=merge-duplicates,return=representation",
        )

        delta = token_usage_delta(usage, previous_total)
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
