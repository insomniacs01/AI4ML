import { describe, expect, it } from 'vitest'
import {
  buildTokenComparison,
  buildTokenObservability,
  chartPolylinePoints,
  comparisonChartPolylinePoints,
  normalizeTokenUsage,
} from './taskDetail'

describe('task detail chart helpers', () => {
  it('uses one value scale for actual and predicted comparison lines', () => {
    const points = comparisonChartPolylinePoints([
      { actual: 0, predicted: 100 },
      { actual: 10, predicted: 110 },
    ])

    expect(points.actual).toBe('0.0,76.0 100.0,70.7')
    expect(points.predicted).toBe('0.0,23.3 100.0,18.0')
  })

  it('does not draw comparison lines without two complete real points', () => {
    expect(comparisonChartPolylinePoints([{ actual: 1, predicted: 2 }])).toEqual({})
    expect(comparisonChartPolylinePoints([
      { actual: 1, predicted: 2 },
      { actual: 3 },
    ])).toEqual({})
  })

  it('keeps single-series polyline generation for existing callers', () => {
    expect(chartPolylinePoints([
      { value: 10 },
      { value: 20 },
    ], 'value')).toBe('0.0,76.0 100.0,18.0')
  })
})

describe('task detail token helpers', () => {
  it('normalizes nested token usage into one frontend shape', () => {
    expect(normalizeTokenUsage({
      total: {
        total_input_tokens: 120,
        total_output_tokens: 30,
        cached_input_tokens: 40,
        reasoning_output_tokens: 10,
      },
    })).toEqual(expect.objectContaining({
      input_tokens: 120,
      output_tokens: 30,
      cached_input_tokens: 40,
      reasoning_output_tokens: 10,
      total_tokens: 150,
    }))
  })

  it('compares token usage only against real comparable peer tasks', () => {
    const comparison = buildTokenComparison(
      { total_tokens: 120 },
      [
        { id: 'current', dataset_filename: 'train.csv', llm_usage: { total_tokens: 999 } },
        { id: 'same-data', dataset_filename: 'train.csv', llm_usage: { total_tokens: 100 } },
        { id: 'same-type', task_type: 'classification', llm_usage: { total_tokens: 80 } },
        { id: 'different', dataset_filename: 'other.csv', task_type: 'regression', llm_usage: { total_tokens: 50 } },
        { id: 'empty-usage', dataset_filename: 'train.csv', llm_usage: { total_tokens: 0 } },
      ],
      { id: 'current', dataset_filename: 'train.csv', task_type: 'classification' },
    )

    expect(comparison).toEqual({
      available: true,
      text: '当前 120，历史同类均值 90，高于均值。',
      current: 120,
      average: 90,
      sample_count: 2,
    })
  })

  it('compares peer token usage when task records use task_id identifiers', () => {
    const comparison = buildTokenComparison(
      { total_tokens: 120 },
      [
        { task_id: 'current', dataset_filename: 'train.csv', llm_usage: { total_tokens: 999 } },
        { task_id: 'peer', dataset_filename: 'train.csv', llm_usage: { total_tokens: 80 } },
      ],
      { task_id: 'current', dataset_filename: 'train.csv' },
    )

    expect(comparison).toEqual({
      available: true,
      text: '当前 120，历史同类均值 80，高于均值。',
      current: 120,
      average: 80,
      sample_count: 1,
    })
  })

  it('reports unavailable comparison without current or peer token records', () => {
    expect(buildTokenComparison(null, [], { id: 'current' })).toEqual({
      available: false,
      text: '暂无可比较的历史同类任务 token 记录。',
    })
  })

  it('builds observability totals and cost reasons from strategy limits', () => {
    const comparison = { available: false, text: 'none' }
    const observability = buildTokenObservability({
      usage: {
        total_tokens: 100,
        input_tokens: 80,
        output_tokens: 20,
        cached_input_tokens: 30,
        reasoning_output_tokens: 5,
      },
      limits: {
        allow_subagents: true,
        candidate_model_count: 4,
        max_auto_improvement_rounds: 2,
        report_depth: 'detailed',
      },
      threadId: 'thread-1',
      comparison,
    })

    expect(observability).toEqual(expect.objectContaining({
      totalTokens: 100,
      inputTokens: 80,
      outputTokens: 20,
      cachedInputTokens: 30,
      uncachedInputTokens: 50,
      reasoningOutputTokens: 5,
      comparison,
    }))
    expect(observability.reasons).toEqual([
      '策略允许 subagents，会增加独立上下文、工具调用和汇总成本。',
      '候选模型数量较多，模型比较和结果解释会增加消耗。',
      '允许多轮自动改进，失败诊断和重试会增加消耗。',
      '报告深度为 detailed，最终报告和诊断说明会更长。',
      'Codex thread 会累计历史上下文，新轮恢复会读取已有计划和产物。',
    ])
  })
})
