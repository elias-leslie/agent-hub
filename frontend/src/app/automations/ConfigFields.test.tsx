import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ConfigFields } from './ConfigFields'

describe('automation typed settings', () => {
  it('edits nullable numeric limits and allowed UTC hours', () => {
    const onChange = vi.fn()
    const schema = {
      properties: {
        daily_limit: {
          title: 'Daily limit',
          anyOf: [
            { type: 'integer' as const, minimum: 1 },
            { type: 'null' as const },
          ],
        },
        allowed_hours: {
          anyOf: [{ type: 'array' as const }, { type: 'null' as const }],
        },
      },
    }
    const { rerender } = render(
      <ConfigFields
        schema={schema}
        value={{}}
        onChange={onChange}
        idPrefix="policy"
      />,
    )

    fireEvent.change(screen.getByLabelText('Daily limit'), {
      target: { value: '5' },
    })
    expect(onChange).toHaveBeenLastCalledWith({ daily_limit: 5 })

    fireEvent.click(screen.getByLabelText('All hours'))
    expect(onChange).toHaveBeenLastCalledWith({ allowed_hours: [] })

    rerender(
      <ConfigFields
        schema={schema}
        value={{ allowed_hours: [] }}
        onChange={onChange}
        idPrefix="policy"
      />,
    )
    fireEvent.click(screen.getByLabelText('09:00'))
    expect(onChange).toHaveBeenLastCalledWith({ allowed_hours: [9] })
  })

  it('requires an explicit choice for required enum values', () => {
    render(
      <ConfigFields
        schema={{
          properties: { delivery: { type: 'string', enum: ['none', 'push'] } },
          required: ['delivery'],
        }}
        value={{}}
        onChange={vi.fn()}
        idPrefix="profile"
      />,
    )
    const select = screen.getByLabelText('delivery') as HTMLSelectElement
    expect(select.required).toBe(true)
    expect(select.value).toBe('')
  })
})
