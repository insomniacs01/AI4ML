import { marked } from '/vendor/marked/marked.esm.js';
import createDOMPurify from '/vendor/dompurify/purify.es.mjs';

const allowedUriPattern = /^(?:(?:https?|mailto):|[#/]|$)/i;
const purify = createDOMPurify(window);
const renderer = new marked.Renderer();
const defaultLinkRenderer = renderer.link.bind(renderer);

renderer.link = function renderLink(token) {
  const href = typeof token.href === 'string' ? token.href : '';

  if (isLocalFileHref(href)) {
    const label = this.parser.parseInline(token.tokens || []);
    return `<span class="file-reference" title="${escapeHtml(href)}">${label}</span>`;
  }

  return defaultLinkRenderer(token);
};

marked.use({
  async: false,
  breaks: true,
  gfm: true,
  renderer
});

export function renderMarkdown(markdownText) {
  const source = typeof markdownText === 'string' ? markdownText : '';
  const rendered = marked.parse(source);
  return purify.sanitize(rendered, {
    ALLOWED_URI_REGEXP: allowedUriPattern,
    ADD_ATTR: ['target', 'rel']
  });
}

export function renderMarkdownInto(element, markdownText) {
  element.dataset.markdown = markdownText;
  element.innerHTML = renderMarkdown(markdownText);

  for (const link of element.querySelectorAll('a[href]')) {
    const href = link.getAttribute('href') || '';

    if (/^https?:\/\//i.test(href)) {
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
    }
  }
}

function escapeHtml(value) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function isLocalFileHref(href) {
  return /^(?:\/mnt\/[a-z]\/|[A-Za-z]:[\\/])/i.test(href);
}
