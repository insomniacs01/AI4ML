export function predictionValueFromPayload(payload, { targetName = '', requiredFeatures = [] } = {}) {
  if (payload === null || payload === undefined) return null
  if (typeof payload !== 'object') return { value: payload }

  const prediction = payload.prediction
  if (prediction && typeof prediction === 'object') {
    if (Object.prototype.hasOwnProperty.call(prediction, 'label')) return { value: prediction.label }
    if (Object.prototype.hasOwnProperty.call(prediction, 'value')) return { value: prediction.value }
    if (Object.prototype.hasOwnProperty.call(prediction, 'prediction')) return { value: prediction.prediction }
    if (prediction.result && typeof prediction.result === 'object') {
      const result = prediction.result
      const knownKeys = ['predicted_value', 'prediction', 'predicted', 'label', targetName]
      const key = knownKeys.find((item) => item && Object.prototype.hasOwnProperty.call(result, item))
      if (key) return { value: result[key] }
      const candidate = Object.entries(result).find(([name]) => !requiredFeatures.includes(name))
      if (candidate) return { label: candidate[0], value: candidate[1] }
    }
  }

  const directKeys = ['predicted_value', 'prediction', 'predicted', 'label', 'value']
  const directKey = directKeys.find((key) => Object.prototype.hasOwnProperty.call(payload, key))
  if (directKey) return { value: payload[directKey] }
  return null
}

export function chartPolylinePoints(rows, field) {
  if (!Array.isArray(rows) || rows.length < 2) return ''
  const values = rows.map((item) => Number(item[field])).filter((value) => Number.isFinite(value))
  if (values.length < 2) return ''
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  return values.slice(0, 12).map((value, index) => {
    const x = values.length === 1 ? 0 : (index / (values.length - 1)) * 100
    const y = 76 - ((value - min) / span) * 58
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
}

export function demoRowsFromDelivery(data) {
  if (Array.isArray(data?.sample_rows) && data.sample_rows.length) return data.sample_rows
  const features = data?.input_schema?.features || data?.required_features || []
  const dtypes = data?.input_schema?.dtypes || {}
  const row = {}
  features.forEach((name) => {
    const dtype = String(dtypes[name] || '').toLowerCase()
    row[name] = dtype.includes('int') || dtype.includes('float') || dtype.includes('double') || dtype.includes('number') ? 0 : ''
  })
  return [row]
}

export function hasObjectContent(value) {
  return value && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length > 0
}
