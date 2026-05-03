from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    draft = "draft"
    uploaded = "uploaded"
    planning = "planning"
    running = "running"
    paused_for_review = "paused_for_review"
    waiting_human = "waiting_human"
    completed = "completed"
    failed = "failed"
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
    leaderboard: list[dict[str, Any]] = Field(default_factory=list)
    output_dir: str
    token_usage: Optional[TokenUsageReport] = None


class RunAttempt(BaseModel):
    output_dir: str
    token_usage: Optional[TokenUsageReport] = None


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
    limitation_notes: list[str] = Field(default_factory=list)
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
    fallback_connector_id: Optional[str] = None
    fallback_connector_display_name: Optional[str] = None
    fallback_model_name: Optional[str] = None
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


class TokenUsageResponse(BaseModel):
    task_id: str
    run_output_dir: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    source: str
    updated_at: datetime


class TaskCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=500)
    label_column: Optional[str] = Field(default=None, min_length=1, max_length=80)
    problem_type: Optional[Literal["classification", "regression"]] = None
    stage_routing: list[TaskStageRoutingOverrideInput] = Field(default_factory=list)
    interaction_policies: list[TaskInteractionPolicyInput] = Field(default_factory=list)


class TaskWorkflowConfigUpdateRequest(BaseModel):
    stage_routing: list[TaskStageRoutingOverrideInput] = Field(default_factory=list)
    interaction_policies: list[TaskInteractionPolicyInput] = Field(default_factory=list)


class TaskRunRequest(BaseModel):
    time_limit: int = Field(default=20, ge=5, le=300)
    rerun_from_stage: Optional[WorkflowStage] = None
    force_full_run: bool = False


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
    name: str
    description: str
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
    structured_requirements: Optional[dict[str, Any]] = None
    stage_routing: list[TaskStageRoutingRecord] = Field(default_factory=list)
    interaction_policies: list[TaskInteractionPolicyRecord] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class TaskListResponse(BaseModel):
    items: list[TaskRecord]


class TaskHumanCollaborationResponse(BaseModel):
    task: TaskRecord
    stages: list[WorkflowStageRecord] = Field(default_factory=list)
    requests: list[TaskHumanRequestRecord] = Field(default_factory=list)
    decision_history: list[TaskHumanDecisionHistoryEntry] = Field(default_factory=list)
    next_run_guidance: TaskHumanGuidancePreview = Field(default_factory=TaskHumanGuidancePreview)
    open_request_count: int = 0
    can_resume: bool = False


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


class TokenUsageResponse(BaseModel):
    task_id: str
    run_output_dir: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    source: str
    updated_at: datetime


class TaskAIConversationEntry(BaseModel):
    id: str
    phase: Literal["analysis", "mlzero"]
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
    phase: Literal["analysis", "mlzero"]
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
