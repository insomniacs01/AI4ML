import { AppServerRunner } from './app-server-runner.js';

export function createRunner(socket) {
  return new AppServerRunner(socket);
}
