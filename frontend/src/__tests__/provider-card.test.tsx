import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ProviderInfo } from '@/components/settings/constants'
import { ProviderCard } from '@/components/settings/ProviderCard'
import type { Credential } from '@/lib/api'

const baseCredential: Credential = {
  id: 101,
  provider: 'gemini',
  credential_type: 'api_key',
  value_masked: 'sk-****1234',
  created_at: '2026-03-06T12:00:00Z',
  updated_at: '2026-03-06T12:00:00Z',
}

const oauthProvider: ProviderInfo = {
  id: 'codex',
  name: 'Codex',
  hint: 'ChatGPT subscription OAuth',
  oauth: true,
}

function renderCard(
  overrides: Partial<React.ComponentProps<typeof ProviderCard>> = {},
) {
  return render(
    <ProviderCard
      provider={oauthProvider}
      credentials={[{ ...baseCredential, provider: 'codex' }]}
      oauthStatus={{
        provider: 'codex',
        oauth_status: 'authenticated',
        api_key_status: 'not_configured',
        preferred_auth: 'oauth',
      }}
      healthData={undefined}
      colors={{ dot: 'bg-blue-400', bg: 'border-blue-500/20' }}
      isEditing={false}
      isAdding={false}
      isConfirmDelete={false}
      isSaving={false}
      error={null}
      onEdit={vi.fn()}
      onAdd={vi.fn()}
      onDeleteAll={vi.fn()}
      onSave={vi.fn()}
      onCancel={vi.fn()}
      onConfirmDelete={vi.fn()}
      onCancelDelete={vi.fn()}
      isDeletingThis={false}
      onOAuthStart={vi.fn()}
      onDisconnectOAuth={vi.fn()}
      onEditCredential={vi.fn()}
      onDeleteCredential={vi.fn()}
      onSetPrimaryCredential={vi.fn()}
      {...overrides}
    />,
  )
}

describe('ProviderCard', () => {
  it('confirms OAuth disconnect inline before deleting credentials', () => {
    const onDisconnectOAuth = vi.fn()
    renderCard({
      credentials: [
        {
          ...baseCredential,
          provider: 'codex',
          credential_type: 'oauth_token',
          value_masked: 'oauth-****',
        },
        {
          ...baseCredential,
          id: 202,
          provider: 'codex',
          credential_type: 'refresh_token',
          value_masked: 'refresh-****',
        },
      ],
      onDisconnectOAuth,
    })

    fireEvent.click(screen.getByRole('button', { name: 'Disconnect' }))

    expect(screen.getByText('Disconnect OAuth?')).toBeInTheDocument()
    expect(onDisconnectOAuth).not.toHaveBeenCalled()

    fireEvent.click(
      screen.getByRole('button', { name: 'Confirm disconnect OAuth' }),
    )
    expect(onDisconnectOAuth).toHaveBeenCalledTimes(1)
  })

  it('confirms single credential deletion inline', () => {
    const onDeleteCredential = vi.fn()
    renderCard({ onDeleteCredential })

    fireEvent.click(
      screen.getByRole('button', { name: 'Delete credential sk-****1234' }),
    )

    expect(screen.getByText('Delete key?')).toBeInTheDocument()
    expect(onDeleteCredential).not.toHaveBeenCalled()

    fireEvent.click(
      screen.getByRole('button', {
        name: 'Confirm delete credential sk-****1234',
      }),
    )
    expect(onDeleteCredential).toHaveBeenCalledWith(101)
  })
})
