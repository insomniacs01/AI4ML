from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class TaskStatus(str, Enum):
    draft = "draft"
    uploaded = "uploaded"
    planning = "planning"
    running = "running"
    paused_for_review = "paused_for_review"
    waiting_human = "waiting_human"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    published = "published"


class TokenUsageReport(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    sessions: list[dict[str, Any]] = Field(default_factory=list)
    conversations: list[dict[str, Any]] = Field(default_factory=list)


class RunSummary(BaseModel):
    best_model: str
    metric_name: str
    metric_value: float
    validation_score: Optional[float] = None
    leaderboard: list[dict[str, Any]] = Field(default_factory=list)
    output_dir: str
    token_usage: Optional[TokenUsageReport] = None


class RunAttempt(BaseModel):
    output_dir: str
    token_usage: Optional[TokenUsageReport] = None
    diagnosis: Optional[str] = None
    diagnosis_detail: Optional[str] = None
    error_artifact_path: Optional[str] = None


class TaskRunProgressArtifactSummary(BaseModel):
    has_run_summary: bool = False
    has_leaderboard: bool = False
    has_token_usage: bool = False
    has_generated_code: bool = False
    has_overview: bool = False
    run_summary_path: Optional[str] = None
    leaderboard_path: Optional[str] = None
    token_usage_path: Optional[str] = None
    generated_code_path: Optional[str] = None
    overview_path: Optional[str] = None
    error_log_path: Optional[str] = None
    error_log_name: Optional[str] = None
    best_model: Optional[str] = None
    metric_name: Optional[str] = None
    metric_value: Optional[float] = None
    validation_score: Optional[float] = None
    candidate_model_count: Optional[int] = None


class TaskRunProgressEvent(BaseModel):
    time: Optional[datetime] = None
    stage: Optional["WorkflowStage"] = None
    event_type: str
    message: str
    source: Optional[str] = None


class TaskRunProgressLeaderboardRow(BaseModel):
    model: str
    validation_score: Optional[float] = None
    fit_time: Optional[float] = None
    pred_time: Optional[float] = None
    rank: Optional[int] = None


class TaskRunProgressTrainingMetric(BaseModel):
    time: Optional[datetime] = None
    model: Optional[str] = None
    epoch: Optional[int] = None
    total_epochs: Optional[int] = None
    iteration: Optional[int] = None
    total_iterations: Optional[int] = None
    train_loss: Optional[float] = None
    validation_loss: Optional[float] = None
    validation_score: Optional[float] = None
    metric_name: Optional[str] = None
    source: Optional[str] = None


class TaskRunProgressInsight(BaseModel):
    time: Optional[datetime] = None
    stage: Optional["WorkflowStage"] = None
    event_type: str
    headline: str
    detail: str = ""
    evidence: Optional[str] = None
    source: Optional[str] = None
    severity: Literal["info", "success", "warning", "danger"] = "info"


class TaskRunProgressResponse(BaseModel):
    task: "TaskRecord"
    output_dir: Optional[str] = None
    status: Literal["not_started", "running", "repairing", "blocked", "stale", "completed", "failed", "unknown"] = "unknown"
    progress_percent: int = 0
    current_stage: Optional["WorkflowStage"] = None
    current_activity: str = ""
    observer_status: Optional[str] = None
    observer_detail: Optional[str] = None
    observer_stage: Optional["WorkflowStage"] = None
    last_log_at: Optional[datetime] = None
    seconds_since_last_update: Optional[float] = None
    stale: bool = False
    stale_reason: Optional[str] = None
    repaired: bool = False
    repair_action: Optional[str] = None
    artifacts: TaskRunProgressArtifactSummary = Field(default_factory=TaskRunProgressArtifactSummary)
    latest_log_lines: list[str] = Field(default_factory=list)
    events: list[TaskRunProgressEvent] = Field(default_factory=list)
    insights: list[TaskRunProgressInsight] = Field(default_factory=list)
    leaderboard: list[TaskRunProgressLeaderboardRow] = Field(default_factory=list)
    training_metrics: list[TaskRunProgressTrainingMetric] = Field(default_factory=list)
    current_model: Optional[str] = None
    completed_model_count: Optional[int] = None
    total_model_count: Optional[int] = None
    current_iteration: Optional[int] = None
    total_iterations: Optional[int] = None
    current_epoch: Optional[int] = None
    total_epochs: Optional[int] = None
    current_model_started_at: Optional[datetime] = None
    current_model_elapsed_seconds: Optional[float] = None
    current_model_time_budget_seconds: Optional[float] = None
    latest_train_loss: Optional[float] = None
    latest_validation_loss: Optional[float] = None
    latest_validation_score: Optional[float] = None
    telemetry_note: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    codex_raw_progress: Optional[dict[str, Any]] = None
    codex_raw_steps: list[dict[str, Any]] = Field(default_factory=list)
    codex_workspace_path: Optional[str] = None


class TaskStepSummaryRecord(BaseModel):
    id: str
    name: str
    node: str
    title: str
    agent_role: str
    status: str = "pending"
    message: str = ""
    summary: str = ""
    duration_s: Optional[float] = None
    artifacts: list[str] = Field(default_factory=list)
    updated_at: Optional[datetime] = None


class TaskRuntimeSnapshotResponse(BaseModel):
    task: "TaskRecord"
    task_run: dict[str, Any] = Field(default_factory=dict)


class DatasetColumnProfile(BaseModel):
    name: str
    inferred_type: Literal["integer", "number", "datetime", "text", "empty", "mixed"]
    non_empty_count: int
    missing_count: int
    missing_ratio: float
    sample_values: list[str] = Field(default_factory=list)


class DatasetProfile(BaseModel):
    filename: Optional[str] = None
    path: Optional[str] = None
    row_count: int = 0
    column_count: int = 0
    columns: list[DatasetColumnProfile] = Field(default_factory=list)
    preview_rows: list[dict[str, str]] = Field(default_factory=list)
    target_column: Optional[str] = None
    generated_at: datetime


class DatasetUploadSummary(BaseModel):
    filename: str
    size_bytes: int
    content_type: Optional[str] = None
    profile: DatasetProfile


class FeatureImportanceEntry(BaseModel):
    feature: str
    importance: float
    source: Optional[str] = None


class TaskModelReportResponse(BaseModel):
    task_id: str
    task_name: str
    generated_at: datetime
    dataset_profile: Optional[DatasetProfile] = None
    feature_importance: list[FeatureImportanceEntry] = Field(default_factory=list)
    result_summary: list[str] = Field(default_factory=list)
    data_quality_notes: list[str] = Field(default_factory=list)
    relationship_notes: list[str] = Field(default_factory=list)
    limitation_notes: list[str] = Field(default_factory=list)
    overview: dict[str, Any] = Field(default_factory=dict)
    artifact_paths: list[str] = Field(default_factory=list)
    report_markdown: str = ""


class TaskPredictionDemoRequest(BaseModel):
    features: dict[str, Any]


class TaskPredictionDemoResponse(BaseModel):
    task_id: str
    supported: bool
    detail: str
    prediction: Optional[Any] = None
    command_hint: Optional[str] = None


class WorkflowStage(str, Enum):
    requirement_analysis = "requirement_analysis"
    data_analysis = "data_analysis"
    feature_engineering = "feature_engineering"
    model_selection = "model_selection"
    training_validation = "training_validation"
    report_generation = "report_generation"
    request_review = "request_review"
    code_generation = "code_generation"
    execution_validation = "execution_validation"
    report_review = "report_review"


PRIMARY_WORKFLOW_STAGES: tuple[WorkflowStage, ...] = (
    WorkflowStage.requirement_analysis,
    WorkflowStage.data_analysis,
    WorkflowStage.feature_engineering,
    WorkflowStage.model_selection,
    WorkflowStage.training_validation,
    WorkflowStage.report_generation,
)

LEGACY_WORKFLOW_STAGE_MAP: dict[str, WorkflowStage] = {
    WorkflowStage.request_review.value: WorkflowStage.requirement_analysis,
    WorkflowStage.code_generation.value: WorkflowStage.feature_engineering,
    WorkflowStage.execution_validation.value: WorkflowStage.training_validation,
    WorkflowStage.report_review.value: WorkflowStage.report_generation,
}


def normalize_workflow_stage(value: WorkflowStage | str) -> WorkflowStage:
    if isinstance(value, WorkflowStage):
        if value in PRIMARY_WORKFLOW_STAGES:
            return value
        mapped = LEGACY_WORKFLOW_STAGE_MAP.get(value.value)
        return mapped if mapped is not None else value
    normalized = str(value).strip()
    if normalized in LEGACY_WORKFLOW_STAGE_MAP:
        return LEGACY_WORKFLOW_STAGE_MAP[normalized]
    return WorkflowStage(normalized)


class WorkflowStageStatus(str, Enum):
    pending = "pending"
    running = "running"
    waiting_human = "waiting_human"
    completed = "completed"
    failed = "failed"


class HumanInteractionRequestStatus(str, Enum):
    pending = "pending"
    open = "open"
    confirmed = "confirmed"
    modified = "modified"
    rejected = "rejected"
    reassigned = "reassigned"
    expired = "expired"
    skipped = "skipped"
    resolved = "resolved"


class HumanInteractionDecisionAction(str, Enum):
    approve = "approve"
    revise = "revise"
    block = "block"
    reject = "reject"
    reassign = "reassign"
    skip = "skip"


class InteractionTriggerMode(str, Enum):
    before_run = "before_run"
    in_run = "in_run"


class InteractionAssigneeType(str, Enum):
    member = "member"
    role = "role"
    candidate_pool = "candidate_pool"


class TaskStageRoutingOverrideInput(BaseModel):
    stage: WorkflowStage
    connector_id: Optional[str] = Field(default=None, max_length=64)
    model_name: Optional[str] = Field(default=None, max_length=200)


class TaskStageRoutingRecord(BaseModel):
    stage: WorkflowStage
    connector_id: Optional[str] = None
    connector_display_name: Optional[str] = None
    model_name: Optional[str] = None
    selection_source: Optional[str] = None


class TaskInteractionPolicyInput(BaseModel):
    policy_id: Optional[str] = Field(default=None, max_length=120)
    enabled: bool = True
    stage: WorkflowStage
    trigger_mode: InteractionTriggerMode = InteractionTriggerMode.before_run
    assignee_type: InteractionAssigneeType = InteractionAssigneeType.member
    assignee_value: str = Field(min_length=1, max_length=200)
    request_type: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=4000)
    suggested_action: Optional[str] = Field(default=None, max_length=4000)
    timeout_minutes: Optional[int] = Field(default=None, ge=5, le=10080)
    artifact_paths: list[str] = Field(default_factory=list)


class TaskInteractionPolicyRecord(BaseModel):
    policy_id: str
    enabled: bool = True
    stage: WorkflowStage
    trigger_mode: InteractionTriggerMode = InteractionTriggerMode.before_run
    assignee_type: InteractionAssigneeType = InteractionAssigneeType.member
    assignee_value: str
    request_type: str
    title: str
    summary: str
    suggested_action: Optional[str] = None
    timeout_minutes: Optional[int] = None
    artifact_paths: list[str] = Field(default_factory=list)


class TaskCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=500)
    label_column: Optional[str] = Field(default=None, min_length=1, max_length=80)
    problem_type: Optional[Literal["classification", "regression"]] = None
    structured_requirements: Optional[dict[str, Any]] = None
    stage_routing: list[TaskStageRoutingOverrideInput] = Field(default_factory=list)
    interaction_policies: list[TaskInteractionPolicyInput] = Field(default_factory=list)


class TaskWorkflowConfigUpdateRequest(BaseModel):
    stage_routing: list[TaskStageRoutingOverrideInput] = Field(default_factory=list)
    interaction_policies: list[TaskInteractionPolicyInput] = Field(default_factory=list)


class TaskSemanticUpdateRequest(BaseModel):
    label_column: str = Field(min_length=1, max_length=120)
    problem_type: Literal["classification", "regression"]
    metric_name: str = Field(min_length=1, max_length=120)
    correction_note: Optional[str] = Field(default=None, max_length=4000)


class TaskRunRequest(BaseModel):
    time_limit: Optional[int] = Field(default=None, ge=5, le=300)
    rerun_from_stage: Optional[WorkflowStage] = None
    force_full_run: bool = False
    resume_after_human: bool = False
    resume_interrupted: bool = False
    regenerate_plan: bool = False
    improvement_decision: Optional[Literal["continue_improvement", "stop_and_report"]] = None
    plan_text: Optional[str] = Field(default=None, max_length=200000)


class TaskInteractiveChatRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=12000)


class WorkflowStageRecord(BaseModel):
    id: str
    team_id: str
    task_id: str
    stage: WorkflowStage | str
    status: WorkflowStageStatus
    selected_connector_id: Optional[str] = None
    model_name: Optional[str] = None
    selection_source: Optional[str] = None
    summary: Optional[str] = None
    artifact_refs: Optional[Any] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    log_excerpt: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class TaskHumanRequestRecord(BaseModel):
    id: str
    team_id: str
    task_id: str
    stage: WorkflowStage | str
    status: HumanInteractionRequestStatus = HumanInteractionRequestStatus.pending
    requested_by: Optional[str] = None
    assigned_to: Optional[str] = None
    assignee_type: Optional[InteractionAssigneeType] = None
    assignee_value: Optional[str] = None
    timeout_at: Optional[datetime] = None
    version_id: Optional[str] = None
    payload: Optional[dict[str, Any]] = None
    decision: Optional[dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime


class TaskHumanRequestCreateRequest(BaseModel):
    stage: WorkflowStage
    request_type: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=4000)
    suggested_action: Optional[str] = Field(default=None, max_length=4000)
    artifact_paths: list[str] = Field(default_factory=list)
    assigned_to: Optional[str] = Field(default=None, max_length=64)
    assignee_type: Optional[InteractionAssigneeType] = None
    assignee_value: Optional[str] = Field(default=None, max_length=200)
    timeout_minutes: Optional[int] = Field(default=None, ge=5, le=10080)
    details: Optional[dict[str, Any]] = None


class TaskHumanRequestDecisionRequest(BaseModel):
    action: HumanInteractionDecisionAction
    decision_summary: str = Field(min_length=1, max_length=4000)
    artifact_paths: list[str] = Field(default_factory=list)
    resume_task: bool = True
    reassign_assignee_type: Optional[InteractionAssigneeType] = None
    reassign_assignee_value: Optional[str] = Field(default=None, max_length=200)
    reassign_assigned_to: Optional[str] = Field(default=None, max_length=64)
    reassign_timeout_minutes: Optional[int] = Field(default=None, ge=5, le=10080)
    details: Optional[dict[str, Any]] = None


class TaskHumanDecisionHistoryEntry(BaseModel):
    request_id: Optional[str] = None
    stage: Optional[str] = None
    action: Optional[str] = None
    title: Optional[str] = None
    request_type: Optional[str] = None
    request_summary: Optional[str] = None
    suggested_action: Optional[str] = None
    decision_summary: Optional[str] = None
    artifact_paths: list[str] = Field(default_factory=list)
    decision_details: Optional[dict[str, Any]] = None
    resume_task: Optional[bool] = None
    requires_rerun: Optional[bool] = None
    reassign_assignee_type: Optional[str] = None
    reassign_assignee_value: Optional[str] = None
    reassign_assigned_to: Optional[str] = None
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TaskHumanGuidancePreview(BaseModel):
    has_guidance: bool = False
    decision_count: int = 0
    targets: list[str] = Field(default_factory=list)
    prompt_guidance_lines: list[str] = Field(default_factory=list)
    description_appendix: str = ""
    human_instruction_file: str = ""
    chat_context_block: str = ""
    initial_instruction_note: str = ""


class TaskRecord(BaseModel):
    id: str
    team_id: str
    created_by: str
    creator_user_id: str | None = None
    name: str
    description: str
    workflow_id: str | None = None
    label_column: Optional[str] = None
    problem_type: Optional[Literal["classification", "regression"]] = None
    status: TaskStatus = TaskStatus.draft
    dataset_filename: Optional[str] = None
    dataset_path: Optional[str] = None
    dataset_profile: Optional[DatasetProfile] = None
    notes: Optional[str] = None
    analysis_token_usage: Optional[TokenUsageReport] = None
    last_run: Optional[RunSummary] = None
    last_run_attempt: Optional[RunAttempt] = None
    executor_type: Optional[Literal["codex"]] = "codex"
    codex_workspace_path: Optional[str] = None
    codex_session_id: Optional[str] = None
    codex_thread_id: Optional[str] = None
    codex_status: Optional[str] = None
    codex_started_at: Optional[datetime] = None
    codex_finished_at: Optional[datetime] = None
    routing_policy_id: Optional[str] = None
    routing_source: Optional[str] = None
    structured_requirements: Optional[dict[str, Any]] = None
    stage_routing: list[TaskStageRoutingRecord] = Field(default_factory=list)
    interaction_policies: list[TaskInteractionPolicyRecord] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @field_validator("executor_type", mode="before")
    @classmethod
    def normalize_executor_type(cls, value: object) -> str:
        return "codex"


class TaskListResponse(BaseModel):
    items: list[TaskRecord]


class TaskHumanCollaborationResponse(BaseModel):
    task: TaskRecord
    stages: list[WorkflowStageRecord] = Field(default_factory=list)
    requests: list[TaskHumanRequestRecord] = Field(default_factory=list)
    my_requests: list[TaskHumanRequestRecord] = Field(default_factory=list)
    decision_history: list[TaskHumanDecisionHistoryEntry] = Field(default_factory=list)
    next_run_guidance: TaskHumanGuidancePreview = Field(default_factory=TaskHumanGuidancePreview)
    open_request_count: int = 0
    my_open_request_count: int = 0
    can_resume: bool = False


class TaskAgentRecord(BaseModel):
    id: str
    stage: WorkflowStage | str
    name: str
    role: str
    short_role: str
    status: WorkflowStageStatus
    progress: int = 0
    current_task: str
    model_name: Optional[str] = None
    connector_id: Optional[str] = None
    selection_source: Optional[str] = None
    artifact_refs: list[str] = Field(default_factory=list)
    artifact_count: int = 0
    last_action_at: Optional[datetime] = None
    runtime_id: Optional[str] = None
    runtime_source: Literal["persistent_agent_runtime", "stage_record_projection"] = "stage_record_projection"
    worker_id: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    log_excerpt: Optional[str] = None
    x: int = 0
    y: int = 0


class TaskAgentRuntimeRecord(BaseModel):
    id: str
    team_id: str
    task_id: str
    agent_id: str
    stage: WorkflowStage | str
    name: str
    role: str
    short_role: str
    status: WorkflowStageStatus
    progress: int = 0
    current_task: str
    selected_connector_id: Optional[str] = None
    model_name: Optional[str] = None
    selection_source: Optional[str] = None
    artifact_refs: Optional[Any] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    log_excerpt: Optional[str] = None
    worker_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class TaskAgentEventRecord(BaseModel):
    id: str
    team_id: Optional[str] = None
    task_id: Optional[str] = None
    agent_id: str
    stage: WorkflowStage | str
    kind: Literal["agent", "stage", "human_request"]
    status: str
    text: str
    time: Optional[datetime] = None
    artifact_refs: list[str] = Field(default_factory=list)


class TaskAgentMessageRecord(BaseModel):
    id: str
    team_id: Optional[str] = None
    task_id: Optional[str] = None
    from_agent_id: str
    to_agent_id: Optional[str] = None
    stage: WorkflowStage | str
    message_type: Literal[
        "coordination",
        "handoff",
        "acknowledgement",
        "blocker",
        "human_review",
        "result",
    ] = "coordination"
    status: str = "sent"
    content: str
    payload: Optional[dict[str, Any]] = None
    artifact_refs: list[str] = Field(default_factory=list)
    correlation_id: Optional[str] = None
    time: Optional[datetime] = None


class TaskAgentCollaborationResponse(BaseModel):
    task: TaskRecord
    runtime_mode: Literal["persistent_agent_runtime", "stage_agent_orchestrator"] = "stage_agent_orchestrator"
    stages: list[WorkflowStageRecord] = Field(default_factory=list)
    requests: list[TaskHumanRequestRecord] = Field(default_factory=list)
    agents: list[TaskAgentRecord] = Field(default_factory=list)
    events: list[TaskAgentEventRecord] = Field(default_factory=list)
    messages: list[TaskAgentMessageRecord] = Field(default_factory=list)


class TaskTokenUsageSummaryItem(BaseModel):
    task_id: str
    task_name: str
    status: TaskStatus
    dataset_filename: Optional[str] = None
    metric_name: Optional[str] = None
    metric_value: Optional[float] = None
    analysis_token_usage: Optional[TokenUsageReport] = None
    run_token_usage: Optional[TokenUsageReport] = None
    combined_token_usage: TokenUsageReport
    updated_at: datetime


class TeamTokenUsageResponse(BaseModel):
    team_id: str
    task_count: int
    tasks_with_analysis_usage: int
    tasks_with_run_usage: int
    analysis_totals: TokenUsageReport
    run_totals: TokenUsageReport
    combined_totals: TokenUsageReport
    items: list[TaskTokenUsageSummaryItem]


class TaskAIConversationEntry(BaseModel):
    id: str
    phase: Literal["analysis", "codex"]
    stage: str
    title: str
    origin: Literal["ai_model", "local_runtime", "unknown"]
    node: Optional[str] = None
    prompt: str
    response: str
    prompt_path: Optional[str] = None
    response_path: Optional[str] = None
    created_at: Optional[datetime] = None


class TaskInteractiveChatMessage(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    origin: Literal["user", "ai_model", "local_runtime"] = "user"
    content: str
    status: Literal["ok", "error"] = "ok"
    model_name: Optional[str] = None
    composed_prompt: Optional[str] = None
    token_usage: Optional[TokenUsageReport] = None
    created_at: Optional[datetime] = None


class TaskAIInternalStateEntry(BaseModel):
    id: str
    phase: Literal["analysis", "codex"]
    title: str
    category: Literal["decision", "error", "log", "retrieval", "code", "summary", "metric", "artifact", "other"]
    description: Optional[str] = None
    node: Optional[str] = None
    path: str
    content: str
    created_at: Optional[datetime] = None


class TaskAIConversationResponse(BaseModel):
    task_id: str
    task_name: str
    run_output_dir: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    items: list[TaskAIConversationEntry] = Field(default_factory=list)
    interactive_messages: list[TaskInteractiveChatMessage] = Field(default_factory=list)
    internal_states: list[TaskAIInternalStateEntry] = Field(default_factory=list)


class TaskInteractiveChatResponse(BaseModel):
    task: TaskRecord
    conversation: TaskAIConversationResponse


class TaskCodeArtifactEntry(BaseModel):
    path: str
    name: str
    display_name: str
    purpose: str
    editing_guidance: str
    category: Literal["code", "state", "result", "log", "other"]
    group: Literal["generation", "result", "log", "context", "other"]
    artifact_kind: str = "other_text"
    stage: Optional[str] = None
    node: Optional[str] = None
    is_core: bool = False
    recommended_order: int = 999
    language: str
    size_bytes: int
    editable: bool
    updated_at: Optional[datetime] = None


class TaskCodeWorkspaceResponse(BaseModel):
    task_id: str
    task_name: str
    run_output_dir: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    items: list[TaskCodeArtifactEntry] = Field(default_factory=list)


class TaskCodeArtifactVersionRecord(BaseModel):
    version_id: str
    path: str
    saved_at: datetime
    size_bytes: int
    previous_sha256: Optional[str] = None
    sha256: str


class TaskCodeArtifactContentResponse(BaseModel):
    task_id: str
    task_name: str
    run_output_dir: str
    artifact: TaskCodeArtifactEntry
    content: str
    version_id: Optional[str] = None
    version_history: list[TaskCodeArtifactVersionRecord] = Field(default_factory=list)


class TaskCodeArtifactUpdateRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4000)
    content: str


class TaskCodeArtifactRerunRequest(BaseModel):
    path: Optional[str] = Field(default=None, min_length=1, max_length=4000)
    time_limit_seconds: int = Field(default=300, ge=5, le=1800)


class TaskCodeArtifactRerunResponse(BaseModel):
    task_id: str
    task_name: str
    run_output_dir: str
    path: str
    success: bool
    exit_code: int
    detail: str
    stdout_path: str
    stderr_path: str
    version_id: Optional[str] = None
    started_at: datetime
    finished_at: datetime


class TaskDeleteResponse(BaseModel):
    deleted: bool
    task_id: str
