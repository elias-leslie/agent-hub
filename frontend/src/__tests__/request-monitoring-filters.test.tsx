import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { Filters } from '@/app/monitoring/requests/components/Filters'

function renderFilters() {
  const props = {
    clientFilter: '',
    setClientFilter: vi.fn(),
    agentFilter: '',
    setAgentFilter: vi.fn(),
    toolTypeFilter: undefined,
    setToolTypeFilter: vi.fn(),
    statusFilter: undefined,
    setStatusFilter: vi.fn(),
    rejectedOnly: false,
    setRejectedOnly: vi.fn(),
  }
  render(<Filters {...props} />)
  return props
}

describe('Request Monitoring filters', () => {
  it('names every filter control so it can be found by role', () => {
    const props = renderFilters()

    fireEvent.change(screen.getByRole('combobox', { name: 'Tool type' }), {
      target: { value: 'cli' },
    })
    fireEvent.change(screen.getByRole('combobox', { name: 'Status code' }), {
      target: { value: '403' },
    })
    fireEvent.change(screen.getByRole('textbox', { name: 'Client ID' }), {
      target: { value: 'c1' },
    })
    fireEvent.change(screen.getByRole('textbox', { name: 'Agent' }), {
      target: { value: 'coder' },
    })
    fireEvent.click(screen.getByRole('checkbox', { name: 'Rejected only' }))

    expect(props.setToolTypeFilter).toHaveBeenCalledWith('cli')
    expect(props.setStatusFilter).toHaveBeenCalledWith(403)
    expect(props.setClientFilter).toHaveBeenCalledWith('c1')
    expect(props.setAgentFilter).toHaveBeenCalledWith('coder')
    expect(props.setRejectedOnly).toHaveBeenCalledWith(true)
  })
})
