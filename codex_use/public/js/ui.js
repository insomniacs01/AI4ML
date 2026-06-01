import { elements, state } from './state.js';

export function setConnectionStatus(label, status) {
  elements.connectionStatus.textContent = label;
  elements.connectionStatus.dataset.status = status;
}

export function setActivity(label, status) {
  elements.activityIndicator.dataset.status = status;
  elements.activityIndicator.querySelector('strong').textContent = label;
}

export function setComposerEnabled(enabled) {
  if (elements.dataPathInput) {
    elements.dataPathInput.disabled = !enabled;
  }
  if (elements.taskDescriptionInput) {
    elements.taskDescriptionInput.disabled = !enabled;
  }
  if (elements.startTaskButton) {
    elements.startTaskButton.disabled = !enabled;
  }
  if (elements.selectFileButton) {
    elements.selectFileButton.disabled = !enabled;
  }
  if (elements.selectFolderButton) {
    elements.selectFolderButton.disabled = !enabled;
  }
}

export function updateHeartbeat(isoTime) {
  const now = Date.now();
  const heartbeatAt = Date.parse(isoTime);
  const latency = Number.isNaN(heartbeatAt) ? null : Math.max(0, now - heartbeatAt);
  state.lastHeartbeatAt = now;
  elements.latencyValue.textContent = latency === null ? '--' : `${latency} ms`;
}

export function resizeComposer() {
  if (!elements.taskDescriptionInput) {
    return;
  }

  elements.taskDescriptionInput.style.height = 'auto';
  elements.taskDescriptionInput.style.height = `${Math.min(elements.taskDescriptionInput.scrollHeight, 180)}px`;
}

export function scrollConversationToBottom() {
  elements.conversation.scrollTop = elements.conversation.scrollHeight;
}
