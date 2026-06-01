const ansiPattern =
  /[\u001b\u009b][[\]()#;?]*(?:(?:(?:[a-zA-Z\d]*(?:;[a-zA-Z\d]*)*)?\u0007)|(?:(?:\d{1,4}(?:;\d{0,4})*)?[\dA-PR-TZcf-nq-uy=><~]))/g;
const controlPattern = /[\u0000-\u0008\u000b-\u001a\u001c-\u001f\u007f]/g;

export function cleanOutput(text = '') {
  return String(text)
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n')
    .replace(ansiPattern, '')
    .replace(controlPattern, '')
    .replace(/\n{3,}/g, '\n\n');
}

export function createLucidePlaceholder(name) {
  const icon = document.createElement('i');
  icon.setAttribute('data-lucide', name);
  return icon;
}

export function refreshIcons() {
  if (window.lucide) {
    window.requestAnimationFrame(() => window.lucide.createIcons());
  }
}

export function refreshIconsNow() {
  if (window.lucide) {
    window.lucide.createIcons();
  }
}

export function formatTime(value) {
  if (!value) {
    return '--';
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '--';
  }

  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  }).format(date);
}

export function formatDuration(milliseconds) {
  const totalSeconds = Math.max(0, Math.round((milliseconds || 0) / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;

  if (minutes > 0) {
    return `${minutes}m ${seconds}s`;
  }

  return `${seconds}s`;
}

export function normalizeChangeKind(kind) {
  if (typeof kind === 'string') {
    return kind;
  }
  if (kind && typeof kind.type === 'string') {
    return kind.type;
  }
  return 'modify';
}

export function toolIcon(tool) {
  if (tool === 'command') {
    return 'square-terminal';
  }
  if (tool === 'file_change') {
    return 'file-pen';
  }
  if (tool === 'web_search') {
    return 'search';
  }
  if (tool === 'collab_agent') {
    return 'users';
  }
  return 'wrench';
}
