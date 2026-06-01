from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backend.app.core.config import Settings
from backend.app.models.task import TaskRecord
from backend.app.services.codex_common import CodexBackendError


class CodexBackendClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def start_task(self, task: TaskRecord, *, token_budget: int | None = None) -> dict[str, Any]:
        if not task.dataset_path:
            raise CodexBackendError("dataset has not been uploaded")
        selected_plan = selected_plan_from_task(task)
        payload = {
            "taskId": task.id,
            "teamId": task.team_id,
            "dataPath": task.dataset_path,
            "description": task_description(task),
            "sessionId": None,
            "threadId": task.codex_thread_id,
            "approvedPlanText": selected_plan.get("plan_text") if selected_plan else None,
            "approvedPlanId": selected_plan.get("plan_id") if selected_plan else None,
            "approvedPlanName": selected_plan.get("plan_name") if selected_plan else None,
        }
        _apply_token_budget(payload, token_budget)
        return self.post_json("/api/ai4ml/tasks/start", payload)

    def approve_plan(self, task: TaskRecord, *, plan_text: str, token_budget: int | None = None) -> dict[str, Any]:
        if not plan_text.strip():
            raise CodexBackendError("Codex plan is empty; cannot approve execution.")
        payload = {
            "taskId": task.id,
            "teamId": task.team_id,
            "sessionId": task.codex_session_id,
            "threadId": task.codex_thread_id,
            "workspacePath": task.codex_workspace_path,
            "planText": plan_text,
        }
        _apply_token_budget(payload, token_budget)
        return self.post_json("/api/ai4ml/tasks/approve-plan", payload)

    def regenerate_plan(self, task: TaskRecord, *, token_budget: int | None = None) -> dict[str, Any]:
        payload = {
            "taskId": task.id,
            "teamId": task.team_id,
            "sessionId": task.codex_session_id,
            "threadId": task.codex_thread_id,
            "workspacePath": task.codex_workspace_path,
        }
        _apply_token_budget(payload, token_budget)
        return self.post_json("/api/ai4ml/tasks/regenerate-plan", payload)

    def interrupt_task(self, task: TaskRecord, *, reason: str | None = None) -> dict[str, Any]:
        return self.post_json(
            "/api/ai4ml/tasks/interrupt",
            {
                "taskId": task.id,
                "teamId": task.team_id,
                "sessionId": task.codex_session_id,
                "threadId": task.codex_thread_id,
                "reason": reason,
            },
        )

    def resume_task(self, task: TaskRecord, *, token_budget: int | None = None) -> dict[str, Any]:
        if not task.codex_workspace_path:
            raise CodexBackendError("Codex workspace is missing; cannot resume interrupted task.")
        payload = {
            "taskId": task.id,
            "teamId": task.team_id,
            "sessionId": task.codex_session_id,
            "threadId": task.codex_thread_id,
            "workspacePath": task.codex_workspace_path,
        }
        _apply_token_budget(payload, token_budget)
        return self.post_json("/api/ai4ml/tasks/resume", payload)

    def task_status(self, task: TaskRecord) -> dict[str, Any]:
        return self.post_json(
            "/api/ai4ml/tasks/status",
            {
                "taskId": task.id,
                "teamId": task.team_id,
                "sessionId": task.codex_session_id,
                "threadId": task.codex_thread_id,
                "workspacePath": task.codex_workspace_path,
            },
        )

    def fetch_latest_artifacts(self) -> dict[str, Any]:
        return self.get_json("/api/latest-workspace")

    def reload_config(self) -> dict[str, Any]:
        return self.post_json("/api/ai4ml/config/reload", {})

    def post_json(self, route: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            self._url(route),
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        return self._request_json(request)

    def get_json(self, route: str) -> dict[str, Any]:
        request = Request(self._url(route), method="GET")
        return self._request_json(request)

    def _request_json(self, request: Request) -> dict[str, Any]:
        try:
            with urlopen(request, timeout=self._settings.codex_request_timeout_seconds) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise CodexBackendError(f"Codex backend returned HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise CodexBackendError(f"Codex backend is not reachable: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise CodexBackendError("Codex backend returned non-JSON response.") from exc
        return payload if isinstance(payload, dict) else {"value": payload}

    def _url(self, route: str) -> str:
        return f"{self._settings.codex_backend_url.rstrip('/')}{route}"


def task_description(task: TaskRecord) -> str:
    parts = [task.description.strip()]
    if task.label_column:
        parts.append(f"目标列：{task.label_column}")
    if task.problem_type:
        parts.append(f"任务类型：{task.problem_type}")
    return "\n".join(part for part in parts if part)


def selected_plan_from_task(task: TaskRecord) -> dict[str, Any] | None:
    structured = task.structured_requirements if isinstance(task.structured_requirements, dict) else {}
    selected_plan = structured.get("selected_plan")
    if not isinstance(selected_plan, dict):
        return None
    plan_text = selected_plan.get("plan_text")
    if not isinstance(plan_text, str) or not plan_text.strip():
        return None
    return {
        **selected_plan,
        "plan_text": plan_text.strip(),
    }


def _apply_token_budget(payload: dict[str, Any], token_budget: int | None) -> None:
    if token_budget is None:
        return
    payload["tokenBudget"] = max(0, int(token_budget))
