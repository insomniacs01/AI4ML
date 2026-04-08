const API_ROOT = import.meta.env.VITE_API_ROOT ?? "/api";

async function request(path, options = {}) {
  const response = await fetch(`${API_ROOT}${path}`, options);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail ?? `Request failed: ${response.status}`);
  }
  return response.json();
}

export const api = {
  health() {
    return request("/health");
  },
  listTasks() {
    return request("/tasks");
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
  }
};
