import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { AppShell } from '@/components/layout/app-shell'

vi.mock('next/navigation', () => ({
  usePathname: () => '/dashboard',
  useRouter: () => ({ push: vi.fn() }),
}))
vi.mock('@/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api')>()),
  fetchStatus: vi.fn().mockResolvedValue({ status: 'healthy' }),
}))

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={new QueryClient()}>
    {children}
  </QueryClientProvider>
)

describe('AppShell phone sidebar', () => {
  it('keeps the closed sidebar out of the tab order and shows it when opened', () => {
    const { container } = render(<AppShell>page</AppShell>, { wrapper })
    const aside = container.querySelector('aside')
    expect(aside).toHaveClass('max-lg:invisible', '-translate-x-full')
    fireEvent.click(
      screen.getByRole('button', { name: 'Open navigation menu' }),
    )
    expect(aside).not.toHaveClass('max-lg:invisible')
    expect(aside).toHaveClass('translate-x-0')
  })
})
