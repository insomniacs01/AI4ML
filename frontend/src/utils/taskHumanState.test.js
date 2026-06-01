import { describe, expect, it } from 'vitest'
import {
  firstWaitingHumanStep,
  hasPendingHumanConfirmation,
  isHumanWaitingStatus,
} from '@/utils/taskHumanState'

describe('taskHumanState', () => {
  it('detects waiting human statuses from task and Codex runtime state', () => {
    expect(isHumanWaitingStatus('waiting_human')).toBe(true)
    expect(isHumanWaitingStatus('waiting_plan_approval')).toBe(true)
    expect(isHumanWaitingStatus('interrupted')).toBe(false)
    expect(hasPendingHumanConfirmation(
      { status: 'paused_for_review' },
      { codex: { status: 'waiting_plan_approval' } },
    )).toBe(true)
  })

  it('detects normalized waiting steps when the task status is only paused', () => {
    const waiting = { id: 'plan_ready', status: 'waiting_human' }

    expect(firstWaitingHumanStep([{ status: 'completed' }, waiting])).toBe(waiting)
    expect(hasPendingHumanConfirmation(
      { status: 'paused_for_review' },
      null,
      [{ status: 'completed' }, waiting],
    )).toBe(true)
  })

  it('detects open request counts without treating interrupted pauses as human approvals', () => {
    expect(hasPendingHumanConfirmation({ status: 'paused_for_review', open_request_count: 1 })).toBe(true)
    expect(hasPendingHumanConfirmation(
      { status: 'paused_for_review', codex_status: 'interrupted' },
      { codex: { status: 'interrupted' } },
    )).toBe(false)
  })

  it('does not reopen finished tasks from stale waiting steps unless an open request exists', () => {
    expect(hasPendingHumanConfirmation(
      { status: 'completed' },
      null,
      [{ status: 'waiting_human' }],
    )).toBe(false)
    expect(hasPendingHumanConfirmation({ status: 'completed', my_open_request_count: 1 })).toBe(true)
  })
})
