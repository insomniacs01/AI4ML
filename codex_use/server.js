import express from 'express';
import http from 'node:http';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';
import { WebSocketServer } from 'ws';

import { host, port } from './src/server/config.js';
import { getLatestAi4mlWorkspaceArtifacts, listAi4mlDataPaths } from './src/server/ai4ml-artifacts.js';
import { selectNativeDataPath } from './src/server/native-data-dialog.js';
import { WebSessionManager } from './src/server/web-session-manager.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const server = http.createServer(app);
const wss = new WebSocketServer({ server, path: '/terminal' });
const sessionManager = new WebSessionManager();

app.use(express.json({ limit: '1mb' }));

app.use((request, response, next) => {
  if (
    request.path === '/' ||
    request.path.endsWith('.html') ||
    request.path.endsWith('.js') ||
    request.path.endsWith('.css')
  ) {
    response.setHeader('Cache-Control', 'no-store, max-age=0');
  }

  next();
});

app.use(express.static(path.join(__dirname, 'public'), {
  etag: false,
  lastModified: false
}));

app.get('/favicon.ico', (_request, response) => {
  response.status(204).end();
});

app.get('/api/data-paths', async (_request, response) => {
  try {
    response.json(await listAi4mlDataPaths());
  } catch (error) {
    response.status(500).json({
      error: error.message
    });
  }
});

app.get('/api/select-data-path', async (request, response) => {
  try {
    const mode = request.query.mode === 'directory' ? 'directory' : 'file';
    response.json(await selectNativeDataPath(mode));
  } catch (error) {
    response.status(500).json({
      error: error.message
    });
  }
});

app.get('/api/latest-workspace', async (_request, response) => {
  try {
    response.json(await getLatestAi4mlWorkspaceArtifacts());
  } catch (error) {
    response.status(500).json({
      error: error.message
    });
  }
});

app.post('/api/ai4ml/tasks/start', async (request, response) => {
  try {
    response.json(await sessionManager.startAi4mlTask(request.body || {}, request.body?.sessionId));
  } catch (error) {
    response.status(400).json({
      error: error.message
    });
  }
});

app.post('/api/ai4ml/tasks/approve-plan', async (request, response) => {
  try {
    response.json(await sessionManager.approveAi4mlPlan(request.body || {}, request.body?.sessionId));
  } catch (error) {
    response.status(400).json({
      error: error.message
    });
  }
});

app.post('/api/ai4ml/tasks/regenerate-plan', async (request, response) => {
  try {
    response.json(await sessionManager.regenerateAi4mlPlan(request.body || {}, request.body?.sessionId));
  } catch (error) {
    response.status(400).json({
      error: error.message
    });
  }
});

app.post('/api/ai4ml/tasks/interrupt', async (request, response) => {
  try {
    response.json(await sessionManager.interruptAi4mlTask(request.body?.sessionId, {
      reason: request.body?.reason
    }));
  } catch (error) {
    response.status(400).json({
      error: error.message
    });
  }
});

app.post('/api/ai4ml/tasks/resume', async (request, response) => {
  try {
    response.json(await sessionManager.resumeAi4mlTask(request.body || {}, request.body?.sessionId));
  } catch (error) {
    response.status(400).json({
      error: error.message
    });
  }
});

app.post('/api/ai4ml/tasks/status', async (request, response) => {
  try {
    response.json(await sessionManager.getAi4mlTaskStatus(request.body || {}, request.body?.sessionId));
  } catch (error) {
    response.status(400).json({
      error: error.message
    });
  }
});

app.post('/api/ai4ml/config/reload', async (_request, response) => {
  try {
    response.json(sessionManager.reloadCodexConfig());
  } catch (error) {
    response.status(500).json({
      error: error.message
    });
  }
});

app.use('/vendor/lucide', express.static(path.join(__dirname, 'node_modules', 'lucide', 'dist', 'umd')));
app.use('/vendor/marked', express.static(path.join(__dirname, 'node_modules', 'marked', 'lib')));
app.use('/vendor/dompurify', express.static(path.join(__dirname, 'node_modules', 'dompurify', 'dist')));

wss.on('connection', async (socket, request) => {
  try {
    const url = new URL(request.url || '/terminal', `http://${request.headers.host || `${host}:${port}`}`);
    const requestedSessionId = url.searchParams.get('sessionId') || undefined;
    const requestedTaskId = url.searchParams.get('taskId') || undefined;
    const session = await sessionManager.getOrCreateSession(requestedSessionId, { taskId: requestedTaskId });
    session.attach(socket, { taskId: requestedTaskId });
  } catch (error) {
    socket.send(JSON.stringify({
      type: 'error',
      message: `Failed to attach Codex session: ${error.message}`
    }));
    socket.close();
  }
});

server.listen(port, host, () => {
  console.log(`Codex web console: http://${host}:${port}`);
});
