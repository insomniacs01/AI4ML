from __future__ import annotations

from backend.app.models.task import RunSummary, TaskRecord, TokenUsageReport


class TaskStoreRunMixin:
    def upsert_run_summary(
        self,
        task: TaskRecord,
        summary: RunSummary,
        *,
        access_token: str,
        status: str = "completed",
        notes: str | None = None,
    ) -> None:
        self.token_repository.upsert_run_summary(
            task,
            summary,
            access_token=access_token,
            status=status,
            notes=notes,
        )

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
        self.token_repository.upsert_run_attempt(
            task,
            output_dir=output_dir,
            access_token=access_token,
            status=status,
            token_usage=token_usage,
            notes=notes,
        )

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
        self.token_repository.upsert_token_ledger(
            team_id=team_id,
            task_id=task_id,
            phase=phase,
            source_key=source_key,
            usage=usage,
            access_token=access_token,
            user_id=user_id,
            connector_id=connector_id,
            connector_display_name=connector_display_name,
            model_name=model_name,
            stage_key=stage_key,
            calculation_method=calculation_method,
        )

    def _adjust_member_token_usage(self, *, team_id: str, user_id: str, token_delta: int, access_token: str) -> None:
        self.token_repository._adjust_member_token_usage(  # noqa: SLF001
            team_id=team_id,
            user_id=user_id,
            token_delta=token_delta,
            access_token=access_token,
        )
