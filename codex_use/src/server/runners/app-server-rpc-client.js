
export class AppServerRpcClient {
  call(method, params = {}, timeoutMs = 60000) {
    const id = this.nextRequestId++;
    const payload = { method, id, params };

    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.pendingRequests.delete(id);
        reject(new Error(`${method} timed out after ${timeoutMs}ms.`));
      }, timeoutMs);

      this.pendingRequests.set(id, {
        resolve,
        reject,
        timeout
      });

      try {
        this.writeJson(payload);
      } catch (error) {
        clearTimeout(timeout);
        this.pendingRequests.delete(id);
        reject(error);
      }
    });
  }

  async notify(method, params = {}) {
    this.writeJson({ method, params });
  }

  respond(id, result) {
    this.writeJson({ id, result });
  }

  writeJson(payload) {
    if (!this.currentProcess || !this.currentProcess.stdin || this.currentProcess.stdin.destroyed) {
      throw new Error('Codex app-server is not running.');
    }

    this.currentProcess.stdin.write(`${JSON.stringify(payload)}\n`, 'utf8');
  }

  rejectPendingRequests(error) {
    for (const [, pending] of this.pendingRequests) {
      clearTimeout(pending.timeout);
      pending.reject(error);
    }

    this.pendingRequests.clear();
  }

  handleStdout(chunk) {
    this.stdoutBuffer += chunk.toString();
    const lines = this.stdoutBuffer.split(/\r?\n/);
    this.stdoutBuffer = lines.pop() || '';

    for (const line of lines) {
      this.handleJsonLine(line);
    }
  }

  handleStderr(chunk) {
    this.stderrBuffer += chunk.toString();
    const lines = this.stderrBuffer.split(/\r?\n/);
    this.stderrBuffer = lines.pop() || '';

    for (const line of lines) {
      if (line.trim()) {
        this.send({
          type: 'raw',
          stream: 'stderr',
          data: line
        });
      }
    }
  }

  handleJsonLine(line) {
    const trimmedLine = line.trim();

    if (!trimmedLine) {
      return;
    }

    let message;
    try {
      message = JSON.parse(trimmedLine);
    } catch {
      this.send({
        type: 'raw',
        stream: 'stdout',
        data: line
      });
      return;
    }

    if (typeof message.id === 'number' && typeof message.method !== 'string') {
      this.handleResponse(message);
      return;
    }

    if (typeof message.id === 'number' && typeof message.method === 'string') {
      this.handleRequest(message);
      return;
    }

    if (typeof message.method === 'string') {
      this.handleNotification(message.method, message.params || {});
    }
  }

  handleResponse(message) {
    const pending = this.pendingRequests.get(message.id);

    if (!pending) {
      return;
    }

    clearTimeout(pending.timeout);
    this.pendingRequests.delete(message.id);

    if (message.error) {
      pending.reject(new Error(message.error.message || JSON.stringify(message.error)));
      return;
    }

    pending.resolve(message.result);
  }

  handleRequest(message) {
    if (
      message.method === 'item/commandExecution/requestApproval' ||
      message.method === 'item/fileChange/requestApproval'
    ) {
      this.respond(message.id, {
        decision: 'accept'
      });
      return;
    }

    this.send({
      type: 'event',
      event: {
        method: message.method,
        params: message.params || {}
      }
    });
    this.respond(message.id, {});
  }
}
