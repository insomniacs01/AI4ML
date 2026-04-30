const API_ROOT = import.meta.env.VITE_API_ROOT;

if (typeof API_ROOT !== "string" || !API_ROOT.trim()) {
  throw new Error("VITE_API_ROOT 未配置，请先在 frontend/.env.local 中设置后端 API 根路径。");
}

function buildHeaders(accessToken, teamId, headers) {
  const nextHeaders = headers instanceof Headers || headers ? new Headers(headers) : new Headers();
  if (accessToken) {
    nextHeaders.set("Authorization", `Bearer ${accessToken}`);
  }
  if (teamId) {
    nextHeaders.set("X-Team-Id", teamId);
  }
  return nextHeaders;
}

async function request(path, options = {}) {
  const { accessToken, teamId, headers, ...fetchOptions } = options;
  const response = await fetch(`${API_ROOT}${path}`, {
    ...fetchOptions,
    headers: buildHeaders(accessToken, teamId, headers),
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    if (typeof payload.detail === "string" && payload.detail) {
      throw new Error(payload.detail);
    }
    throw new Error(`接口 ${path} 返回 HTTP ${response.status}，但响应体没有 detail 字段。`);
  }

  return response.json();
}

export const api = {
  health(context = {}) {
    return request("/health", context);
  },
  usageSummary(context = {}) {
    return request("/usage", context);
  },
  listConnectors(context = {}) {
    return request("/connectors", context);
  },
  createConnector(payload, context = {}) {
    return request("/connectors", {
      ...context,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  testConnector(connectorId, context = {}) {
    return request(`/connectors/${connectorId}/test`, {
      ...context,
      method: "POST",
    });
  },
  activateConnector(connectorId, context = {}) {
    return request(`/connectors/${connectorId}/activate`, {
      ...context,
      method: "POST",
    });
  },
  teamMembers(context = {}) {
    return request("/team/members", context);
  },
  prepareTeamInvite(payload = {}, context = {}) {
    return request("/team/members/invite", {
      ...context,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  updateTeamMemberRole(memberId, payload, context = {}) {
    return request(`/team/members/${memberId}/role`, {
      ...context,
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  updateTeamMemberStatus(memberId, payload, context = {}) {
    return request(`/team/members/${memberId}/status`, {
      ...context,
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  teamQuotas(context = {}) {
    return request("/team/quotas", context);
  },
  adjustTeamQuota(memberId, payload, context = {}) {
    return request(`/team/quotas/${memberId}/adjust`, {
      ...context,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  teamRouting(context = {}) {
    return request("/team/routing", context);
  },
  saveTeamRouting(payload, context = {}) {
    return request("/team/routing", {
      ...context,
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  teamAssets(assetType, context = {}) {
    const query = assetType ? `?asset_type=${encodeURIComponent(assetType)}` : "";
    return request(`/team/assets${query}`, context);
  },
  createTeamAsset(payload, context = {}) {
    return request("/team/assets", {
      ...context,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  reviewTeamAsset(assetId, payload, context = {}) {
    return request(`/team/assets/${assetId}/review`, {
      ...context,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  teamAuditLogs(context = {}) {
    return request("/team/audit-logs", context);
  },
  listTasks(context = {}) {
    return request("/tasks", context);
  },
  createTask(payload, context = {}) {
    return request("/tasks", {
      ...context,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  updateTaskWorkflowConfig(taskId, payload, context = {}) {
    return request(`/tasks/${taskId}/workflow-config`, {
      ...context,
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  uploadDataset(taskId, file, context = {}) {
    const formData = new FormData();
    formData.append("file", file);
    return request(`/tasks/${taskId}/dataset`, {
      ...context,
      method: "POST",
      body: formData,
    });
  },
  analyzeTask(taskId, context = {}) {
    return request(`/tasks/${taskId}/analyze`, {
      ...context,
      method: "POST",
    });
  },
  taskAIConversations(taskId, context = {}) {
    return request(`/tasks/${taskId}/ai-conversations`, context);
  },
  taskHumanCollaboration(taskId, context = {}) {
    return request(`/tasks/${taskId}/human-collaboration`, context);
  },
  createTaskHumanRequest(taskId, payload, context = {}) {
    return request(`/tasks/${taskId}/human-requests`, {
      ...context,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  getTaskTokenUsage(taskId) {
    return request(`/tasks/${taskId}/token-usage`);
  },
  decideTaskHumanRequest(taskId, requestId, payload, context = {}) {
    return request(`/tasks/${taskId}/human-requests/${requestId}/decision`, {
      ...context,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  resumeTask(taskId, context = {}) {
    return request(`/tasks/${taskId}/resume`, {
      ...context,
      method: "POST",
    });
  },
  taskInteractiveChat(taskId, payload, context = {}) {
    return request(`/tasks/${taskId}/chat`, {
      ...context,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  taskCodeWorkspace(taskId, context = {}) {
    return request(`/tasks/${taskId}/code-workspace`, context);
  },
  taskCodeArtifact(taskId, artifactPath, context = {}) {
    const query = new URLSearchParams({ path: artifactPath }).toString();
    return request(`/tasks/${taskId}/code-workspace/file?${query}`, context);
  },
  updateTaskCodeArtifact(taskId, payload, context = {}) {
    return request(`/tasks/${taskId}/code-workspace/file`, {
      ...context,
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  runTask(taskId, timeLimit = 20, context = {}) {
    return request(`/tasks/${taskId}/run`, {
      ...context,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ time_limit: timeLimit }),
    });
  },
  deleteTask(taskId, context = {}) {
    return request(`/tasks/${taskId}`, {
      ...context,
      method: "DELETE",
    });
  },
};
