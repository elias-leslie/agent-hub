import { render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { SidebarNav } from '@/components/layout/sidebar-nav'

const AGENT_SECTION_LINKS = [
  ['Agents', '/agents'],
  ['Models', '/models'],
  ['Prompts', '/prompts'],
  ['Memory', '/memory'],
  ['Agent context', '/runtime-context'],
] as const

function agentsGroup() {
  return screen.getByRole('group', { name: 'Agents' })
}

describe('SidebarNav', () => {
  it('groups the agent pages under one Agents section', () => {
    render(<SidebarNav isCollapsed={false} pathname="/dashboard" />)

    const group = agentsGroup()
    const links = within(group).getAllByRole('link')
    expect(links.map((link) => link.getAttribute('href'))).toEqual(
      AGENT_SECTION_LINKS.map(([, href]) => href),
    )
    for (const [label] of AGENT_SECTION_LINKS) {
      expect(
        within(group).getByText(label, { selector: 'p.truncate' }),
      ).toBeInTheDocument()
    }

    for (const href of ['/chat', '/dashboard', '/admin', '/access-control']) {
      const link = screen
        .getAllByRole('link')
        .find((candidate) => candidate.getAttribute('href') === href)
      expect(link).toBeDefined()
      expect(group).not.toContainElement(link ?? null)
    }
  })

  it.each([
    ['/admin', '/admin'],
    ['/agents/persona', '/agents'],
    ['/memory', '/memory'],
    ['/runtime-context', '/runtime-context'],
    ['/models/claude-opus', '/models'],
  ])('marks %s active on %s only', (pathname, activeHref) => {
    render(<SidebarNav isCollapsed={false} pathname={pathname} />)

    const active = screen
      .getAllByRole('link')
      .filter((link) => link.getAttribute('data-active') === 'true')
    expect(active.map((link) => link.getAttribute('href'))).toEqual([
      activeHref,
    ])
    expect(active[0]).toHaveAttribute('aria-current', 'page')
  })

  it('keeps the section and link names usable when collapsed', () => {
    render(<SidebarNav isCollapsed={true} pathname="/memory" />)

    const group = agentsGroup()
    const memory = within(group).getByRole('link', { name: 'Memory' })
    expect(memory).toHaveAttribute('title', 'Memory')
    expect(memory).toHaveAttribute('data-active', 'true')
    expect(
      within(group).getByRole('link', { name: 'Agent context' }),
    ).toHaveAttribute('href', '/runtime-context')
    expect(screen.queryByText('Semantic store')).not.toBeInTheDocument()
  })

  describe('active link visibility', () => {
    afterEach(() => vi.restoreAllMocks())

    it('scrolls the active link into view and follows route changes', () => {
      const scrolled: (string | null)[] = []
      vi.spyOn(Element.prototype, 'scrollIntoView').mockImplementation(
        function (this: Element, options?: boolean | ScrollIntoViewOptions) {
          expect(options).toEqual({ block: 'nearest' })
          scrolled.push(this.getAttribute('href'))
        },
      )

      const { rerender } = render(
        <SidebarNav isCollapsed={false} pathname="/runtime-context" />,
      )
      expect(scrolled).toEqual(['/runtime-context'])

      rerender(<SidebarNav isCollapsed={false} pathname="/access-control" />)
      expect(scrolled).toEqual(['/runtime-context', '/access-control'])
    })
  })
})
