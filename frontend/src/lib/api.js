const API_ROOT = import.meta.env.VITE_API_ROOT;
const GET_CACHE_TTL_MS = 30_000;
const getCache = new Map();
const inFlightGets = new Map();

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

function clonePayload(payload) {
  return payload;
}

function getCacheKey(path, accessToken, teamId) {
  return `${teamId ?? ""}|${accessToken ? accessToken.slice(-16) : ""}|${path}`;
}

function requireTeamScopedPath(path, context = {}) {
  const teamId = context?.teamId;
  if (!teamId) return path;
  return `/teams/${encodeURIComponent(teamId)}${path}`;
}

function clearApiCache() {
  getCache.clear();
  inFlightGets.clear();
}

async function request(path, options = {}) {
  const { accessToken, teamId, headers, noCache = false, ...fetchOptions } = options;
  const method = String(fetchOptions.method ?? "GET").toUpperCase();
  const canCache = method === "GET" && !noCache;
  const cacheKey = canCache ? getCacheKey(path, accessToken, teamId) : "";

  if (canCache) {
    const cached = getCache.get(cacheKey);
    if (cached && Date.now() - cached.cachedAt < GET_CACHE_TTL_MS) {
      return clonePayload(cached.payload);
    }
    const pending = inFlightGets.get(cacheKey);
    if (pending) return clonePayload(await pending);
  }

  if (method !== "GET") {
    clearApiCache();
  }

  const requestPromise = fetch(`${API_ROOT}${path}`, {
    ...fetchOptions,
    headers: buildHeaders(accessToken, teamId, headers),
  }).catch((error) => {
    if (error instanceof TypeError && error.message === "Failed to fetch") {
      throw new Error(`接口 ${path} 未能连接到后端。请确认 8000 后端服务正在运行，或刷新页面后重试。`);
    }
    throw error;
  }).then(async (response) => {
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      if (typeof payload.detail === "string" && payload.detail) {
        throw new Error(payload.detail);
      }
      throw new Error(`接口 ${path} 返回 HTTP ${response.status}，但响应体没有 detail 字段。`);
    }

    const payload = await response.json();
    if (canCache) getCache.set(cacheKey, { cachedAt: Date.now(), payload });
    return payload;
  }).finally(() => {
    if (canCache) inFlightGets.delete(cacheKey);
  });

  if (canCache) inFlightGets.set(cacheKey, requestPromise);
  return clonePayload(await requestPromise);
}

async function requestBlob(path, options = {}) {
  const { accessToken, teamId, headers, ...fetchOptions } = options;
  const response = await fetch(`${API_ROOT}${path}`, {
    ...fetchOptions,
    headers: buildHeaders(accessToken, teamId, headers),
  }).catch((error) => {
    if (error instanceof TypeError && error.message === "Failed to fetch") {
      throw new Error(`接口 ${path} 未能连接到后端。请确认 8000 后端服务正在运行，或刷新页面后重试。`);
    }
    throw error;
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    if (typeof payload.detail === "string" && payload.detail) {
      throw new Error(payload.detail);
    }
    throw new Error(`接口 ${path} 返回 HTTP ${response.status}，但响应体没有 detail 字段。`);
  }

  const disposition = response.headers.get("content-disposition") ?? "";
  const filenameMatch = disposition.match(/filename="?([^"]+)"?/i);
  return {
    blob: await response.blob(),
    filename: filenameMatch?.[1] ?? "artifact",
  };
}

export const api = {
  health(context = {}) {
    return request("/health", context);
  },
  usageSummary(context = {}) {
    return request(requireTeamScopedPath("/usage", context), context);
  },
  listConnectors(context = {}) {
    return request(requireTeamScopedPath("/connectors", context), context);
  },
  createConnector(payload, context = {}) {
    return request(requireTeamScopedPath("/connectors", context), {
      ...context,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  updateConnector(connectorId, payload, context = {}) {
    return request(requireTeamScopedPath(`/connectors/${connectorId}`, context), {
      ...context,
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  healthCheckConnectors(context = {}) {
    return request(requireTeamScopedPath("/connectors/health-check", context), {
      ...context,
      method: "POST",
    });
  },
  testConnector(connectorId, context = {}) {
    return request(requireTeamScopedPath(`/connectors/${connectorId}/test`, context), {
      ...context,
      method: "POST",
    });
  },
  activateConnector(connectorId, context = {}) {
    return request(requireTeamScopedPath(`/connectors/${connectorId}/activate`, context), {
      ...context,
      method: "POST",
    });
  },
  deactivateConnector(connectorId, context = {}) {
    return request(requireTeamScopedPath(`/connectors/${connectorId}/deactivate`, context), {
      ...context,
      method: "POST",
    });
  },
  deleteConnector(connectorId, context = {}) {
    return request(requireTeamScopedPath(`/connectors/${connectorId}`, context), {
      ...context,
      method: "DELETE",
    });
  },
  teamSettings(context = {}) {
    return request(requireTeamScopedPath("/settings", context), context);
  },
  updateTeamSettings(payload, context = {}) {
    return request(requireTeamScopedPath("/settings", context), {
      ...context,
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  transferTeamOwnership(payload, context = {}) {
    return request(requireTeamScopedPath("/owner/transfer", context), {
      ...context,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  teamMembers(context = {}) {
    return request(requireTeamScopedPath("/members", context), context);
  },
  prepareTeamInvite(payload = {}, context = {}) {
    return request(requireTeamScopedPath("/members/invite", context), {
      ...context,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  updateTeamMemberRole(memberId, payload, context = {}) {
    return request(requireTeamScopedPath(`/members/${memberId}/role`, context), {
      ...context,
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  updateTeamMemberStatus(memberId, payload, context = {}) {
    return request(requireTeamScopedPath(`/members/${memberId}/status`, context), {
      ...context,
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  teamQuotas(context = {}) {
    return request(requireTeamScopedPath("/quotas", context), context);
  },
  adjustTeamQuota(memberId, payload, context = {}) {
    return request(requireTeamScopedPath(`/quotas/${memberId}/adjust`, context), {
      ...context,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  adjustTeamQuotaScope(payload, context = {}) {
    return request(requireTeamScopedPath("/quotas/adjust", context), {
      ...context,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  teamRouting(context = {}) {
    return request(requireTeamScopedPath("/routing", context), context);
  },
  saveTeamRouting(payload, context = {}) {
    return request(requireTeamScopedPath("/routing", context), {
      ...context,
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  teamAssets(assetType, filters = {}, context = {}) {
    let resolvedFilters = filters;
    let resolvedContext = context;
    if (filters?.accessToken || filters?.teamId) {
      resolvedFilters = {};
      resolvedContext = filters;
    }
    const params = new URLSearchParams();
    if (assetType) params.set("asset_type", assetType);
    Object.entries(resolvedFilters ?? {}).forEach(([key, value]) => {
      if (value) params.set(key, value);
    });
    const query = params.toString() ? `?${params.toString()}` : "";
    return request(requireTeamScopedPath(`/assets${query}`, resolvedContext), resolvedContext);
  },
  createTeamAsset(payload, context = {}) {
    return request(requireTeamScopedPath("/assets", context), {
      ...context,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  reviewTeamAsset(assetId, payload, context = {}) {
    return request(requireTeamScopedPath(`/assets/${assetId}/review`, context), {
      ...context,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  publishTeamAsset(assetId, payload = {}, context = {}) {
    return request(requireTeamScopedPath(`/assets/${assetId}/publish`, context), {
      ...context,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  forkTeamAsset(assetId, payload = {}, context = {}) {
    return request(requireTeamScopedPath(`/assets/${assetId}/fork`, context), {
      ...context,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  teamAuditLogs(context = {}) {
    return request(requireTeamScopedPath("/audit-logs", context), context);
  },
  teamTokenLedgers(filters = {}, context = {}) {
    let resolvedFilters = filters;
    let resolvedContext = context;
    if (filters?.accessToken || filters?.teamId) {
      resolvedFilters = {};
      resolvedContext = filters;
    }
    const params = new URLSearchParams();
    Object.entries(resolvedFilters ?? {}).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") params.set(key, value);
    });
    const query = params.toString() ? `?${params.toString()}` : "";
    return request(requireTeamScopedPath(`/token-ledgers${query}`, resolvedContext), resolvedContext);
  },
  listTasks(context = {}) {
    return request(requireTeamScopedPath("/tasks", context), context);
  },
  createTask(payload, context = {}) {
    return request(requireTeamScopedPath("/tasks", context), {
      ...context,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  updateTaskWorkflowConfig(taskId, payload, context = {}) {
    return request(requireTeamScopedPath(`/tasks/${taskId}/workflow-config`, context), {
      ...context,
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  updateTaskSemantics(taskId, payload, context = {}) {
    return request(requireTeamScopedPath(`/tasks/${taskId}/semantic-analysis`, context), {
      ...context,
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  uploadDataset(taskId, file, context = {}, options = {}) {
    const formData = new FormData();
    formData.append("file", file);
    const params = new URLSearchParams();
    params.set("auto_run", options.autoRun === false ? "false" : "true");
    params.set("time_limit", String(options.timeLimit ?? 20));
    return request(requireTeamScopedPath(`/tasks/${taskId}/dataset?${params.toString()}`, context), {
      ...context,
      method: "POST",
      body: formData,
    });
  },
  analyzeTask(taskId, context = {}) {
    return request(requireTeamScopedPath(`/tasks/${taskId}/analyze`, context), {
      ...context,
      method: "POST",
    });
  },
  taskAIConversations(taskId, context = {}) {
    return request(requireTeamScopedPath(`/tasks/${taskId}/ai-conversations`, context), context);
  },
  taskHumanCollaboration(taskId, context = {}) {
    return request(requireTeamScopedPath(`/tasks/${taskId}/human-collaboration`, context), context);
  },
  taskAgentCollaboration(taskId, context = {}) {
    return request(requireTeamScopedPath(`/tasks/${taskId}/agent-collaboration`, context), context);
  },
  createTaskHumanRequest(taskId, payload, context = {}) {
    return request(requireTeamScopedPath(`/tasks/${taskId}/human-requests`, context), {
      ...context,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  getTaskTokenUsage(taskId, context = {}) {
    return request(requireTeamScopedPath(`/tasks/${taskId}/token-usage`, context), context);
  },
  taskRunProgress(taskId, context = {}) {
    return request(requireTeamScopedPath(`/tasks/${taskId}/run-progress`, context), {
      ...context,
      noCache: true,
    });
  },
  taskModelReport(taskId, context = {}) {
    return request(requireTeamScopedPath(`/tasks/${taskId}/report`, context), context);
  },
  taskPredictionDemo(taskId, payload, context = {}) {
    return request(requireTeamScopedPath(`/tasks/${taskId}/prediction-demo`, context), {
      ...context,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  decideTaskHumanRequest(taskId, requestId, payload, context = {}) {
    return request(requireTeamScopedPath(`/tasks/${taskId}/human-requests/${requestId}/decision`, context), {
      ...context,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  resumeTask(taskId, context = {}) {
    return request(requireTeamScopedPath(`/tasks/${taskId}/resume`, context), {
      ...context,
      method: "POST",
    });
  },
  taskInteractiveChat(taskId, payload, context = {}) {
    return request(requireTeamScopedPath(`/tasks/${taskId}/chat`, context), {
      ...context,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  taskCodeWorkspace(taskId, context = {}) {
    return request(requireTeamScopedPath(`/tasks/${taskId}/code-workspace`, context), context);
  },
  taskCodeArtifact(taskId, artifactPath, context = {}) {
    const query = new URLSearchParams({ path: artifactPath }).toString();
    return request(requireTeamScopedPath(`/tasks/${taskId}/code-workspace/file?${query}`, context), context);
  },
  downloadTaskCodeArtifact(taskId, artifactPath, context = {}) {
    const query = new URLSearchParams({ path: artifactPath }).toString();
    return requestBlob(requireTeamScopedPath(`/tasks/${taskId}/code-workspace/download?${query}`, context), context);
  },
  updateTaskCodeArtifact(taskId, payload, context = {}) {
    return request(requireTeamScopedPath(`/tasks/${taskId}/code-workspace/file`, context), {
      ...context,
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  rerunTaskCodeArtifact(taskId, payload, context = {}) {
    return request(requireTeamScopedPath(`/tasks/${taskId}/code-workspace/rerun`, context), {
      ...context,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  runTask(taskId, timeLimit = 20, context = {}) {
    return request(requireTeamScopedPath(`/tasks/${taskId}/run`, context), {
      ...context,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ time_limit: timeLimit }),
    });
  },
  deleteTask(taskId, context = {}) {
    return request(requireTeamScopedPath(`/tasks/${taskId}`, context), {
      ...context,
      method: "DELETE",
    });
  },
};

