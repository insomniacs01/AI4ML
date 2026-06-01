import { describe, expect, it } from 'vitest'
import { pickActiveTask, pickBlockingRuntimeTask } from './taskRecords'

function task(taskId, status, createdAt = '2026-05-19T00:00:00Z') {
  return {
    task_id: taskId,
    status,
    created_at: createdAt,
    updated_at: createdAt,
  }
}

describe('task record selection', () => {
  it('does not classify paused or human-waiting tasks as runtime blockers', () => {
    const tasks = [
      task('paused-task', 'paused_for_review'),
      task('waiting-task', 'waiting_human'),
    ]

    expect(pickBlockingRuntimeTask(tasks)).toBeNull()
  })

  it('keeps paused tasks visible to the workspace when nothing is running', () => {
    const selected = pickActiveTask([
      task('completed-task', 'completed'),
      task('paused-task', 'paused_for_review'),
    ])

    expect(selected.task_id).toBe('paused-task')
  })

  it('prefers a running task over a paused task for workspace display', () => {
    const selected = pickActiveTask([
      task('paused-task', 'paused_for_review', '2026-05-20T00:00:00Z'),
      task('running-task', 'running', '2026-05-19T00:00:00Z'),
    ])

    expect(selected.task_id).toBe('running-task')
  })
})
