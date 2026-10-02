import DOMPurify from 'dompurify'
import hljs from 'highlight.js/lib/core'
import bash from 'highlight.js/lib/languages/bash'
import cpp from 'highlight.js/lib/languages/cpp'
import css from 'highlight.js/lib/languages/css'
import java from 'highlight.js/lib/languages/java'
import javascript from 'highlight.js/lib/languages/javascript'
import json from 'highlight.js/lib/languages/json'
import python from 'highlight.js/lib/languages/python'
import sql from 'highlight.js/lib/languages/sql'
import typescript from 'highlight.js/lib/languages/typescript'
import xml from 'highlight.js/lib/languages/xml'
import { Marked } from 'marked'
import { markedHighlight } from 'marked-highlight'

for (const [name, definition] of Object.entries({
  bash, cpp, css, java, javascript, json, python, sql, typescript, xml,
})) {
  hljs.registerLanguage(name, definition)
}

function escapeHtml(value: string) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

const marked = new Marked(
  markedHighlight({
    langPrefix: 'hljs language-',
    highlight(code, lang) {
      const language = lang && hljs.getLanguage(lang) ? lang : ''
      if (!language) return escapeHtml(code)
      try { return hljs.highlight(code, { language }).value }
      catch { return escapeHtml(code) }
    },
  }),
)
marked.use({ gfm: true, breaks: true })

/** Render an assistant answer as sanitized Markdown (tables, lists, highlighted code, links). */
export function renderMarkdown(text: string): string {
  const raw = marked.parse(text || '', { async: false }) as string
  return DOMPurify.sanitize(raw, {
    FORBID_TAGS: ['img', 'video', 'audio', 'iframe', 'form', 'input', 'button', 'select', 'textarea', 'style'],
  })
}
