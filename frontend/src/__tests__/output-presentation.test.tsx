import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { CodeBlock } from '@/components/output'

// Mock clipboard API
const mockClipboard = {
  writeText: vi.fn().mockResolvedValue(undefined),
}
Object.assign(navigator, { clipboard: mockClipboard })

describe('CodeBlock', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders code content', () => {
    const { container } = render(<CodeBlock code="const x = 1;" />)
    // Code might be split by syntax highlighting spans, check container has the text
    expect(container.textContent).toContain('const')
    expect(container.textContent).toContain('x')
    expect(container.textContent).toContain('1')
  })

  it('detects TypeScript language', () => {
    render(
      <CodeBlock code="import { foo } from 'bar';\nconst x: string = 'test';" />,
    )
    expect(screen.getByText('TypeScript')).toBeInTheDocument()
  })

  it('detects Python language', () => {
    render(<CodeBlock code="def hello():\n    print('world')" />)
    expect(screen.getByText('Python')).toBeInTheDocument()
  })

  it('detects Bash language', () => {
    render(<CodeBlock code="$ npm install\n$ npm run dev" />)
    expect(screen.getByText('Bash')).toBeInTheDocument()
  })

  it('detects JSON language', () => {
    render(<CodeBlock code='{"name": "test", "value": 123}' />)
    expect(screen.getByText('JSON')).toBeInTheDocument()
  })

  it('detects SQL language', () => {
    render(<CodeBlock code="SELECT * FROM users WHERE id = 1" />)
    expect(screen.getByText('SQL')).toBeInTheDocument()
  })

  it('uses provided language over detection', () => {
    render(<CodeBlock code="some code" language="rust" />)
    expect(screen.getByText('Rust')).toBeInTheDocument()
  })

  it('displays filename when provided', () => {
    render(<CodeBlock code="const x = 1;" filename="test.ts" />)
    expect(screen.getByText('test.ts')).toBeInTheDocument()
  })

  it('shows line numbers by default', () => {
    const { container } = render(<CodeBlock code="line 1\nline 2\nline 3" />)
    // Line numbers container exists when showLineNumbers is true (default)
    const lineNumberContainer = container.querySelector('.select-none')
    expect(lineNumberContainer).toBeInTheDocument()
  })

  it('hides line numbers when showLineNumbers is false', () => {
    const { container } = render(
      <CodeBlock code="line 1\nline 2" showLineNumbers={false} />,
    )
    const lineNumberDiv = container.querySelector('.select-none.text-right')
    expect(lineNumberDiv).toBeNull()
  })

  it('copies code to clipboard when copy button clicked', async () => {
    render(<CodeBlock code="const x = 1;" />)

    const copyButton = screen.getByTitle('Copy code')
    fireEvent.click(copyButton)

    await waitFor(() => {
      expect(mockClipboard.writeText).toHaveBeenCalledWith('const x = 1;')
    })
  })

  it('shows Copied feedback after copying', async () => {
    render(<CodeBlock code="const x = 1;" />)

    const copyButton = screen.getByTitle('Copy code')
    fireEvent.click(copyButton)

    await waitFor(() => {
      expect(screen.getByText('Copied')).toBeInTheDocument()
    })
  })

  it('renders terminal dots in header', () => {
    const { container } = render(<CodeBlock code="test" />)
    const dots = container.querySelectorAll('.rounded-full')
    expect(dots.length).toBe(3)
  })
})
