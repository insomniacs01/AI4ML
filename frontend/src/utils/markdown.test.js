import { describe, expect, it } from 'vitest'
import { renderMarkdown } from './markdown'

describe('markdown rendering', () => {
  it('preserves pipe-delimited text that is not a complete markdown table', () => {
    expect(renderMarkdown('| Y1 | Y2 |')).toBe('<p>| Y1 | Y2 |</p>')
  })

  it('renders markdown tables only when a separator row is present', () => {
    expect(renderMarkdown('| Metric | Score |\n| --- | --- |\n| RMSE | 0.42 |')).toBe([
      '<div class="markdown-table-wrap"><table>',
      '<thead><tr>',
      '<th>Metric</th>',
      '<th>Score</th>',
      '</tr></thead>',
      '<tbody>',
      '<tr><td>RMSE</td><td>0.42</td></tr>',
      '</tbody></table></div>',
    ].join(''))
  })
})
