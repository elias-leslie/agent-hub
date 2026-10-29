import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { MarkdownContent } from '../../../packages/chat-ui/src/components/MarkdownContent'

function html(content: string) {
  const { container } = render(<MarkdownContent content={content} />)
  return container.querySelector('.markdown-content') as HTMLElement
}

describe('MarkdownContent line breaks', () => {
  it('keeps a single newline as a line break', () => {
    const root = html('a\nb')
    expect(root.querySelectorAll('p')).toHaveLength(1)
    expect(root.querySelectorAll('br')).toHaveLength(1)
    expect(root.querySelector('p')?.innerHTML).toBe('a<br>\nb')
  })

  it('keeps one number per line', () => {
    const root = html(
      Array.from({ length: 60 }, (_, i) => String(i + 1)).join('\n'),
    )
    expect(root.querySelectorAll('br')).toHaveLength(59)
  })

  it('still splits blank-line-separated text into paragraphs', () => {
    const root = html('a\n\nb')
    expect(root.querySelectorAll('p')).toHaveLength(2)
    expect(root.querySelectorAll('br')).toHaveLength(0)
  })

  it('leaves fenced code untouched', () => {
    const root = html('intro\n\n```sh\nls\npwd\n```')
    expect(root.querySelectorAll('br')).toHaveLength(0)
    expect(root.querySelector('pre code')?.textContent).toBe('ls\npwd')
  })

  it('keeps lists and tables as lists and tables, and inline text in an item', () => {
    const root = html(
      '- one\n- two\n\n| h1 | h2 |\n| --- | --- |\n| x | y |\n\nline1\nline2',
    )
    expect(root.querySelectorAll('li')).toHaveLength(2)
    expect(root.querySelectorAll('table')).toHaveLength(1)
    expect(root.querySelectorAll('br')).toHaveLength(1)
  })

  it('keeps bold text with a line break inside', () => {
    const root = html('**bold**\nnext `code`')
    expect(root.querySelector('strong')?.textContent).toBe('bold')
    expect(root.querySelectorAll('br')).toHaveLength(1)
    expect(root.querySelector('code')?.textContent).toBe('code')
  })
})
