import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ExecutionPermissionEditor } from './ExecutionPermissionEditor'

const permission = {
  project_id: 'agent-hub',
  permission_tier: 'full' as const,
  auto_exec_enabled: true,
  execution_start_hour: 0,
  execution_end_hour: 24,
  root_path: null,
  updated_at: '2026-09-23T00:00:00Z',
  created_at: '2026-09-23T00:00:00Z',
}

describe('ExecutionPermissionEditor', () => {
  it('submits auto execution and hours through its central policy control', () => {
    const onSave = vi.fn()
    render(
      <ExecutionPermissionEditor
        permission={permission}
        saving={false}
        onSave={onSave}
      />,
    )
    fireEvent.click(
      screen.getByRole('checkbox', { name: 'Allow automated execution' }),
    )
    fireEvent.change(screen.getByLabelText('Start hour'), {
      target: { value: '9' },
    })
    fireEvent.change(screen.getByLabelText('End hour'), {
      target: { value: '17' },
    })
    fireEvent.click(
      screen.getByRole('button', { name: 'Save execution permission' }),
    )
    expect(onSave).toHaveBeenCalledWith({
      auto_exec_enabled: false,
      execution_start_hour: 9,
      execution_end_hour: 17,
    })
  })

  it('keeps tier read only in Automations', () => {
    render(
      <ExecutionPermissionEditor
        permission={permission}
        saving={false}
        onSave={vi.fn()}
      />,
    )
    expect(screen.getByText('full')).toBeInTheDocument()
    expect(
      screen.queryByRole('combobox', { name: 'Tier' }),
    ).not.toBeInTheDocument()
  })

  it('keeps execution controls unavailable when the access tier is off', () => {
    render(
      <ExecutionPermissionEditor
        permission={{ ...permission, permission_tier: 'off' }}
        saving={false}
        onSave={vi.fn()}
      />,
    )
    expect(
      screen.getByRole('checkbox', { name: 'Allow automated execution' }),
    ).toBeDisabled()
    expect(
      screen.getByRole('link', { name: 'Access Control' }),
    ).toHaveAttribute('href', '/access-control/permissions')
  })
})
