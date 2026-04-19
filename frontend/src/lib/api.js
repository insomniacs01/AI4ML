const API_ROOT = import.meta.env.VITE_API_ROOT ?? "/api";
const API_TOKEN_KEY = "ai4ml_access_token";

export function hasAuthToken() {
  return Boolean(window.localStorage.getItem(API_TOKEN_KEY));
}

function getAuthHeaders() {
  const token = window.localStorage.getItem(API_TOKEN_KEY);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request(path, options = {}) {
  const mergedHeaders = {
    ...(options.headers ?? {}),
    ...getAuthHeaders()
  };
  const response = await fetch(`${API_ROOT}${path}`, {
    ...options,
    headers: mergedHeaders
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail ?? `Request failed: ${response.status}`);
  }
  return response.json();
}

export const api = {
  logout() {
    window.localStorage.removeItem(API_TOKEN_KEY);
  },
  health() {
    return request("/health");
  },
  listTasks() {
    return request("/tasks");
  },
  getTask(taskId) {
    return request(`/tasks/${taskId}`);
  },
  me() {
    return request("/users/me");
  },
  createTask(payload) {
    return request("/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
  },
  uploadDataset(taskId, file) {
    const formData = new FormData();
    formData.append("file", file);
    return request(`/tasks/${taskId}/dataset`, {
      method: "POST",
      body: formData
    });
  },
  runTask(taskId, timeLimit = 20) {
    return request(`/tasks/${taskId}/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ time_limit: timeLimit })
    });
  },
  register(payload) {
    return request("/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
  },
  async login(payload) {
    const result = await request("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    window.localStorage.setItem(API_TOKEN_KEY, result.access_token);
    return result;
  },
  listUsers() {
    return request("/users");
  },
  updateUserRole(userId, role) {
    return request(`/users/${userId}/role`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role })
    });
  },
  updateUserQuota(userId, apiTokenQuota) {
    return request(`/users/${userId}/quota`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_token_quota: apiTokenQuota })
    });
  }
};
