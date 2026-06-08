function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function renderInlineMarkdown(value) {
  return escapeHtml(value)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
}

function renderParagraphText(value) {
  return `<p>${renderInlineMarkdown(value.trim())}</p>`
}

function splitTableRow(line) {
  return line.trim().replace(/^\||\|$/g, '').split('|').map((cell) => cell.trim())
}

function isTableSeparatorCell(cell) {
  return /^:?-{3,}:?$/.test(cell)
}

function isMarkdownTable(lines) {
  if (lines.length < 2) return false
  const header = splitTableRow(lines[0])
  const separator = splitTableRow(lines[1])
  return header.length > 0 && separator.length === header.length && separator.every(isTableSeparatorCell)
}

function renderMarkdownTable(lines) {
  const rows = lines
    .filter((line) => line.trim())
    .map((line) => splitTableRow(line).map((cell) => renderInlineMarkdown(cell)))
  const header = rows[0]
  const body = rows.slice(2)
  return [
    '<div class="markdown-table-wrap"><table>',
    '<thead><tr>',
    ...header.map((cell) => `<th>${cell}</th>`),
    '</tr></thead>',
    '<tbody>',
    ...body.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join('')}</tr>`),
    '</tbody></table></div>',
  ].join('')
}

function flushList(items, ordered) {
  if (!items.length) return ''
  const tag = ordered ? 'ol' : 'ul'
  return `<${tag}>${items.map((item) => `<li>${renderInlineMarkdown(item)}</li>`).join('')}</${tag}>`
}

export function renderMarkdown(markdown) {
  const lines = String(markdown || '').replace(/\r\n/g, '\n').split('\n')
  const html = []
  let paragraph = []
  let listItems = []
  let orderedList = false
  let codeLines = []
  let tableLines = []
  let inCode = false

  const flushParagraph = () => {
    if (!paragraph.length) return
    html.push(renderParagraphText(paragraph.join(' ')))
    paragraph = []
  }
  const flushTable = () => {
    if (!tableLines.length) return
    if (isMarkdownTable(tableLines)) {
      html.push(renderMarkdownTable(tableLines))
    } else {
      html.push(...tableLines.map(renderParagraphText))
    }
    tableLines = []
  }
  const flushCode = () => {
    if (!codeLines.length) return
    html.push(`<pre><code>${escapeHtml(codeLines.join('\n'))}</code></pre>`)
    codeLines = []
  }
  const flushBlocks = () => {
    flushParagraph()
    html.push(flushList(listItems, orderedList))
    listItems = []
    flushTable()
  }

  lines.forEach((line) => {
    if (line.trim().startsWith('```')) {
      if (inCode) {
        inCode = false
        flushCode()
      } else {
        flushBlocks()
        inCode = true
      }
      return
    }
    if (inCode) {
      codeLines.push(line)
      return
    }
    if (/^\s*\|.+\|\s*$/.test(line)) {
      flushParagraph()
      if (listItems.length) {
        html.push(flushList(listItems, orderedList))
        listItems = []
      }
      tableLines.push(line)
      return
    }
    if (!line.trim()) {
      flushBlocks()
      return
    }
    flushTable()
    const heading = line.match(/^(#{1,6})\s+(.+)$/)
    if (heading) {
      flushBlocks()
      const level = Math.min(heading[1].length + 1, 6)
      html.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`)
      return
    }
    const unordered = line.match(/^\s*[-*]\s+(.+)$/)
    const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/)
    if (unordered || ordered) {
      flushParagraph()
      const nextOrdered = Boolean(ordered)
      if (listItems.length && orderedList !== nextOrdered) {
        html.push(flushList(listItems, orderedList))
        listItems = []
      }
      orderedList = nextOrdered
      listItems.push((unordered || ordered)[1])
      return
    }
    if (listItems.length) {
      html.push(flushList(listItems, orderedList))
      listItems = []
    }
    paragraph.push(line.trim())
  })

  if (inCode) flushCode()
  flushBlocks()
  return html.filter(Boolean).join('\n')
}
