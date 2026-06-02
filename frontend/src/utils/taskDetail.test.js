import { describe, expect, it } from 'vitest'
import { chartPolylinePoints, comparisonChartPolylinePoints } from './taskDetail'

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
