// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'

import { renderMarkdown } from '../src/markdown'

describe('renderMarkdown', () => {
  it('renders headings, lists and gfm tables', () => {
    const html = renderMarkdown('# 标题\n\n- 一\n- 二\n\n| A | B |\n| --- | --- |\n| 1 | 2 |')
    expect(html).toContain('<h1>标题</h1>')
    expect(html).toContain('<li>一</li>')
    expect(html).toContain('<table>')
    expect(html).toContain('<td>1</td>')
  })

  it('highlights fenced code with hljs classes', () => {
    const html = renderMarkdown('```python\nprint("hi")\n```')
    expect(html).toContain('language-python')
    expect(html).toMatch(/hljs-[a-z_]+/)
  })

  it('sanitizes scripts, event handlers and images', () => {
    const html = renderMarkdown('<script>alert(1)</script>\n\n<img src=x onerror="alert(1)">\n\n[点我](javascript:alert(1))')
    expect(html).not.toContain('<script')
    expect(html).not.toContain('<img')
    expect(html).not.toContain('onerror')
    expect(html).not.toContain('javascript:')
  })

  it('keeps safe links and turns single newlines into breaks', () => {
    const html = renderMarkdown('第一行\n第二行\n\n[官网](https://example.edu)')
    expect(html).toContain('<br>')
    expect(html).toContain('href="https://example.edu"')
  })
})
