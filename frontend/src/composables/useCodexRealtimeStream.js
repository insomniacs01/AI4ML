import {
  applyCodexRealtimeEvent,
  codexWebSocketUrl,
  resetCodexRealtimeState,
  seedCodexRealtimeFromSnapshot,
} from '@/utils/codexRealtime'

export function createCodexRealtimeStream({
  state,
  getSessionId,
  getTaskId = () => '',
  getSnapshotCodex = () => null,
  isFinished = () => false,
  onMessage = () => {},
  onError = () => {},
}) {
  let socket = null
  let connectedSessionId = ''

  function connect() {
    if (isFinished()) {
      close()
      return
    }

    const sessionId = getSessionId() || ''
    if (!sessionId) {
      close()
      return
    }
    if (socket && connectedSessionId === sessionId) return

    close()
    connectedSessionId = sessionId
    const realtimeState = unwrapState(state)
    resetCodexRealtimeState(realtimeState)
    realtimeState.status = 'connecting'

    try {
      socket = new WebSocket(codexWebSocketUrl(sessionId, { taskId: getTaskId() }))
    } catch (err) {
      realtimeState.status = 'error'
      onError(err)
      return
    }

    socket.addEventListener('message', (event) => {
      try {
        const payload = JSON.parse(event.data)
        applyCodexRealtimeEvent(unwrapState(state), payload)
        onMessage(payload)
      } catch {
        // Ignore malformed socket frames.
      }
    })
    socket.addEventListener('open', () => {
      unwrapState(state).status = 'connected'
    })
    socket.addEventListener('close', () => {
      const currentState = unwrapState(state)
      if (!currentState.events.length) {
        seedCodexRealtimeFromSnapshot(currentState, getSnapshotCodex())
      }
      currentState.status = currentState.events.length ? 'snapshot' : 'closed'
      socket = null
      connectedSessionId = ''
    })
    socket.addEventListener('error', () => {
      unwrapState(state).status = 'error'
    })
  }

  function close() {
    if (socket) socket.close()
    socket = null
    connectedSessionId = ''
  }

  return { connect, close }
}

function unwrapState(state) {
  return state && typeof state === 'object' && 'value' in state ? state.value : state
}
