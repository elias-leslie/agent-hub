import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import AgentLoginsPage from '@/app/access-control/logins/page'
import {
  type AgentLogin,
  addAccountLogin,
  editAgentLogin,
  fetchAgentLogins,
  removeAgentLogin,
  replaceAgentLogin,
} from '@/lib/api/lab-credentials'

vi.mock('@/lib/api/lab-credentials', () => ({
  addAccountLogin: vi.fn(),
  editAgentLogin: vi.fn(),
  fetchAgentLogins: vi.fn(),
  removeAgentLogin: vi.fn(),
  replaceAgentLogin: vi.fn(),
}))

function login(overrides: Partial<AgentLogin>): AgentLogin {
  const target = overrides.target ?? 'site'
  const actor = overrides.actor ?? 'default'
  return {
    reference: `secret://lab/${target}/${actor}`,
    target,
    actor,
    kind: 'synthetic',
    expires_at: null,
    expired: false,
    fields: ['password'],
    login_url: null,
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-10-02T00:00:00Z',
    undecodable: false,
    ...overrides,
  }
}

const LOGINS = [
  login({
    target: 'hackerone',
    kind: 'account',
    fields: ['login_url', 'password', 'totp_secret', 'username'],
    login_url: 'https://hackerone.com/users/sign_in',
    updated_at: '2026-10-05T00:00:00Z',
  }),
  login({
    target: 'neri-local',
    actor: 'viewer',
    fields: ['password', 'session_cookie'],
  }),
  login({
    target: 'neri-local',
    actor: 'old',
    expires_at: '2026-10-03T00:00:00Z',
    expired: true,
  }),
  login({
    target: 'zeta',
    actor: 'broken',
    kind: null,
    fields: [],
    undecodable: true,
  }),
]

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <AgentLoginsPage />
    </QueryClientProvider>,
  )
}

function siteOrder() {
  return screen
    .getAllByRole('row')
    .slice(1)
    .map((row) => within(row).getAllByRole('cell')[0].textContent)
}

describe('AgentLoginsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(fetchAgentLogins).mockResolvedValue(LOGINS)
    vi.mocked(addAccountLogin).mockResolvedValue()
    vi.mocked(editAgentLogin).mockResolvedValue()
    vi.mocked(replaceAgentLogin).mockResolvedValue()
    vi.mocked(removeAgentLogin).mockResolvedValue()
  })

  it('lists field names, type, login URL and status without any value', async () => {
    renderPage()
    const row = (await screen.findByText('hackerone')).closest(
      'tr',
    ) as HTMLElement
    expect(within(row).getByText('Real login')).toBeInTheDocument()
    expect(within(row).getByText('password, 2FA, username')).toBeInTheDocument()
    expect(
      within(row).getByRole('link', { name: 'hackerone.com' }),
    ).toHaveAttribute('href', 'https://hackerone.com/users/sign_in')
    expect(within(row).getByText('No expiry')).toBeInTheDocument()
    expect(screen.getByText(/^Expired /)).toBeInTheDocument()
  })

  it('shows an unreadable login as such, warns, and keeps the rest of the list', async () => {
    renderPage()
    const row = (await screen.findByText('zeta')).closest('tr') as HTMLElement
    expect(within(row).getByText("Can't be read")).toBeInTheDocument()
    expect(within(row).getByText('Unreadable')).toBeInTheDocument()
    expect(
      within(row).queryByRole('button', { name: /^Edit/ }),
    ).not.toBeInTheDocument()
    expect(
      within(row).getByRole('button', { name: 'Remove zeta / broken' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent(
      "1 login can't be read",
    )
    expect(screen.getByText('hackerone')).toBeInTheDocument()
  })

  it('gives loading, empty and failed their own states', async () => {
    vi.mocked(fetchAgentLogins).mockReturnValue(new Promise(() => {}))
    const loading = renderPage()
    expect(
      screen.getByRole('status', { name: 'Loading logins' }),
    ).toBeInTheDocument()
    loading.unmount()

    vi.mocked(fetchAgentLogins).mockResolvedValue([])
    const empty = renderPage()
    expect(await screen.findByText('No agent logins yet')).toBeInTheDocument()
    expect(
      screen.queryByText('Could not load agent logins.'),
    ).not.toBeInTheDocument()
    empty.unmount()

    vi.mocked(fetchAgentLogins).mockRejectedValue(
      new Error('Owner access required'),
    )
    renderPage()
    expect(
      await screen.findByText('Could not load agent logins.'),
    ).toBeInTheDocument()
    expect(screen.getByText('Owner access required')).toBeInTheDocument()
    expect(screen.queryByText('No agent logins yet')).not.toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Try again' }),
    ).toBeInTheDocument()
  })

  it('sorts by a column and reverses on a second click', async () => {
    renderPage()
    await screen.findByText('hackerone')
    expect(siteOrder()).toEqual([
      'hackerone',
      'neri-local',
      'neri-local',
      'zeta',
    ])

    fireEvent.click(screen.getByRole('button', { name: 'Site' }))
    expect(siteOrder()).toEqual([
      'zeta',
      'neri-local',
      'neri-local',
      'hackerone',
    ])

    fireEvent.click(screen.getByRole('button', { name: 'Updated' }))
    expect(siteOrder().at(-1)).toBe('hackerone')
    fireEvent.click(screen.getByRole('button', { name: 'Updated' }))
    expect(siteOrder()[0]).toBe('hackerone')
  })

  it('filters by text and type, hides expired, and clears the filters', async () => {
    renderPage()
    await screen.findByText('hackerone')

    fireEvent.change(screen.getByLabelText('Search'), {
      target: { value: 'session_cookie' },
    })
    expect(siteOrder()).toEqual(['neri-local'])
    expect(screen.getByText('Showing 1 of 4')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Search'), { target: { value: '' } })

    fireEvent.change(screen.getByLabelText('Type'), {
      target: { value: 'account' },
    })
    expect(siteOrder()).toEqual(['hackerone'])
    fireEvent.change(screen.getByLabelText('Type'), {
      target: { value: 'unreadable' },
    })
    expect(siteOrder()).toEqual(['zeta'])
    fireEvent.change(screen.getByLabelText('Type'), {
      target: { value: 'all' },
    })

    fireEvent.click(screen.getByLabelText('Show expired'))
    expect(siteOrder()).toHaveLength(3)
    expect(screen.queryByText(/^Expired /)).not.toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Search'), {
      target: { value: 'nothing-like-this' },
    })
    expect(
      screen.getByText('No logins match these filters.'),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(siteOrder()).toHaveLength(4)
  })

  it('adds an account with masked inputs and sends the values once', async () => {
    renderPage()
    await screen.findByText('hackerone')
    fireEvent.click(screen.getByRole('button', { name: 'Add login' }))
    const form = screen.getByRole('form', { name: 'Add a login' })

    for (const label of ['Password', /2FA secret/]) {
      const input = within(form).getByLabelText(label)
      expect(input).toHaveAttribute('type', 'password')
      expect(input).toHaveAttribute('autocomplete', 'off')
    }
    expect(
      within(form).queryByRole('button', { name: /show|reveal/i }),
    ).not.toBeInTheDocument()
    expect(
      within(form).getByRole('button', { name: 'Add login' }),
    ).toBeDisabled()

    fireEvent.change(within(form).getByLabelText('Site'), {
      target: { value: 'hackerone2' },
    })
    fireEvent.change(within(form).getByLabelText('Username'), {
      target: { value: 'elias' },
    })
    fireEvent.change(within(form).getByLabelText('Password'), {
      target: { value: 'pw-value' },
    })
    fireEvent.change(within(form).getByLabelText('Login URL'), {
      target: { value: 'https://hackerone.com/login' },
    })
    fireEvent.click(within(form).getByRole('button', { name: 'Add login' }))

    await waitFor(() => expect(addAccountLogin).toHaveBeenCalled())
    expect(vi.mocked(addAccountLogin).mock.calls[0][0]).toEqual({
      target: 'hackerone2',
      actor: 'default',
      username: 'elias',
      password: 'pw-value',
      login_url: 'https://hackerone.com/login',
    })
    await waitFor(() =>
      expect(screen.queryByRole('form')).not.toBeInTheDocument(),
    )
  })

  it('shows the server reason when adding fails and keeps the form', async () => {
    vi.mocked(addAccountLogin).mockRejectedValue(
      new Error('Lab credential reference already exists or is ambiguous'),
    )
    renderPage()
    await screen.findByText('hackerone')
    fireEvent.click(screen.getByRole('button', { name: 'Add login' }))
    const form = screen.getByRole('form', { name: 'Add a login' })
    for (const [label, value] of [
      ['Site', 'hackerone'],
      ['Username', 'u'],
      ['Password', 'p'],
      ['Login URL', 'https://hackerone.com/login'],
    ] as const) {
      fireEvent.change(within(form).getByLabelText(label), {
        target: { value },
      })
    }
    fireEvent.click(within(form).getByRole('button', { name: 'Add login' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('already exists')
    expect(
      screen.getByRole('form', { name: 'Add a login' }),
    ).toBeInTheDocument()
  })

  it('edits only what changed: blank secrets keep, a 2FA removal is sent', async () => {
    renderPage()
    const row = (await screen.findByText('hackerone')).closest(
      'tr',
    ) as HTMLElement
    fireEvent.click(
      within(row).getByRole('button', { name: 'Edit hackerone / default' }),
    )
    const form = screen.getByRole('form', { name: 'Edit hackerone / default' })

    expect(within(form).getByLabelText('Password')).toHaveValue('')
    fireEvent.change(within(form).getByLabelText('Username'), {
      target: { value: 'new-name' },
    })
    fireEvent.click(within(form).getByLabelText('Remove this field'))
    fireEvent.click(within(form).getByRole('button', { name: 'Save changes' }))

    await waitFor(() => expect(editAgentLogin).toHaveBeenCalled())
    expect(vi.mocked(editAgentLogin).mock.calls[0]).toEqual([
      'hackerone',
      'default',
      { set: { username: 'new-name' }, remove: ['totp_secret'] },
    ])
  })

  it('needs the password again to move to another site but not within the same one', async () => {
    renderPage()
    const row = (await screen.findByText('hackerone')).closest(
      'tr',
    ) as HTMLElement
    fireEvent.click(
      within(row).getByRole('button', { name: 'Edit hackerone / default' }),
    )
    const form = screen.getByRole('form', { name: 'Edit hackerone / default' })
    const save = within(form).getByRole('button', { name: 'Save changes' })

    expect(
      within(form).getByText('Changing the site needs the password again.'),
    ).toBeInTheDocument()
    fireEvent.change(within(form).getByLabelText('Login URL'), {
      target: { value: 'https://elsewhere.example/login' },
    })
    expect(save).toBeDisabled()
    fireEvent.change(within(form).getByLabelText('Password'), {
      target: { value: 'again' },
    })
    expect(save).toBeEnabled()
    fireEvent.change(within(form).getByLabelText('Password'), {
      target: { value: '' },
    })
    fireEvent.change(within(form).getByLabelText('Login URL'), {
      target: { value: 'https://hackerone.com/other' },
    })
    expect(save).toBeEnabled()
  })

  it('removes a login only after a confirm', async () => {
    renderPage()
    const row = (await screen.findByText('zeta')).closest('tr') as HTMLElement
    fireEvent.click(
      within(row).getByRole('button', { name: 'Remove zeta / broken' }),
    )
    expect(removeAgentLogin).not.toHaveBeenCalled()
    fireEvent.click(within(row).getByRole('button', { name: 'Keep' }))
    expect(
      within(row).getByRole('button', { name: 'Remove zeta / broken' }),
    ).toBeInTheDocument()

    fireEvent.click(
      within(row).getByRole('button', { name: 'Remove zeta / broken' }),
    )
    fireEvent.click(
      within(row).getByRole('button', { name: 'Confirm remove zeta / broken' }),
    )
    await waitFor(() =>
      expect(removeAgentLogin).toHaveBeenCalledWith('zeta', 'broken'),
    )
  })

  it('replaces a whole synthetic bundle, asking for every field again', async () => {
    renderPage()
    await screen.findByText('hackerone')
    const viewer = screen
      .getAllByRole('row')
      .find((r) => r.textContent?.includes('viewer')) as HTMLElement
    fireEvent.click(
      within(viewer).getByRole('button', {
        name: 'Replace neri-local / viewer',
      }),
    )
    const form = screen.getByRole('form', {
      name: 'Replace neri-local / viewer',
    })
    const save = within(form).getByRole('button', { name: 'Replace login' })
    expect(save).toBeDisabled()
    fireEvent.change(within(form).getByLabelText('password'), {
      target: { value: 'a' },
    })
    fireEvent.change(within(form).getByLabelText('session_cookie'), {
      target: { value: 'b' },
    })
    fireEvent.click(save)
    await waitFor(() => expect(replaceAgentLogin).toHaveBeenCalled())
    expect(vi.mocked(replaceAgentLogin).mock.calls[0]).toEqual([
      'neri-local',
      'viewer',
      { values: { password: 'a', session_cookie: 'b' } },
    ])
  })
})
