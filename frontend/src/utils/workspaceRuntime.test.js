import { describe, expect, it } from 'vitest'
import { workspaceRealtimeUpdate } from './workspaceRuntime'

describe('workspace runtime realtime updates', () => {
  it('turns task completion events into completed task and run patches', () => {
    const update = workspaceRealtimeUpdate({
      payload: { type: 'task_completed' },
      activeTask: { task_id: 'task-1', status: 'running' },
      taskRun: { progress_status: 'running', codex: { status: 'running' } },
      realtimeStatus: 'running',
    })

    expect(update).toEqual({
      taskPatch: { status: 'completed', codex_status: 'completed' },
      taskRun: {
        progress_percent: 100,
        progress_status: 'completed',
        codex: { status: 'completed' },
      },
      persist: true,
      refreshSnapshot: true,
    })
  })

  it('marks generated plans as waiting for approval without inventing a percent', () => {
    const update = workspaceRealtimeUpdate({
      payload: { type: 'plan_generation_completed' },
      activeTask: { task_id: 'task-1', status: 'running' },
      taskRun: { codex: { progress: { percent: 0 } } },
      realtimeStatus: 'running',
    })

    expect(update.taskPatch).toEqual({ status: 'paused_for_review', codex_status: 'waiting_plan_approval' })
    expect(update.taskRun).toEqual({
      progress_status: 'waiting_plan_approval',
      codex: {
        progress: {
          percent: 0,
          status: 'waiting_plan_approval',
          current_step: 'waiting_plan_approval',
        },
        status: 'waiting_plan_approval',
      },
    })
    expect(update.taskRun.progress_percent).toBeUndefined()
  })

  it('pauses and blocks the workspace when quota is exhausted', () => {
    const update = workspaceRealtimeUpdate({
      payload: { type: 'quota_exhausted', reason: '额度不足' },
      activeTask: { task_id: 'task-1', status: 'running', notes: 'old note' },
      taskRun: { current_activity: 'running', codex: { status: 'running' } },
      realtimeStatus: 'running',
    })

    expect(update).toEqual({
      taskPatch: {
        status: 'paused_for_review',
        codex_status: 'interrupted',
        notes: '额度不足',
      },
      taskRun: {
        current_activity: '额度不足',
        progress_status: 'blocked',
        codex: { status: 'interrupted' },
      },
      persist: true,
      closeStream: true,
      refreshSnapshot: true,
    })
  })

  it('marks resume-like events as running task patches', () => {
    const update = workspaceRealtimeUpdate({
      payload: { type: 'turn_started' },
      activeTask: { task_id: 'task-1', status: 'paused_for_review' },
      realtimeStatus: 'running',
    })

    expect(update).toEqual({
      taskPatch: { status: 'running', codex_status: 'running' },
      persist: true,
    })
  })

  it('ignores replayed events and non-completion events after a task is finished', () => {
    expect(workspaceRealtimeUpdate({
      payload: { type: 'activity', message: '旧事件' },
      activeTask: { task_id: 'task-1', status: 'running' },
      realtimeStatus: 'replaying',
    })).toBeNull()

    expect(workspaceRealtimeUpdate({
      payload: { type: 'activity', message: '迟到事件' },
      activeTask: { task_id: 'task-1', status: 'completed' },
      realtimeStatus: 'running',
      finished: true,
    })).toBeNull()
  })
})
