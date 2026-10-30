import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { MobileHeader } from '@/components/layout/mobile-header'

describe('MobileHeader', () => {
  it('names the menu button for assistive technology', () => {
    const onMenuClick = vi.fn()
    render(<MobileHeader onMenuClick={onMenuClick} />)

    const button = screen.getByRole('button', {
      name: 'Open navigation menu',
    })
    expect(button).toHaveAttribute('type', 'button')
    fireEvent.click(button)
    expect(onMenuClick).toHaveBeenCalledOnce()
  })

  it('stacks above the fixed page backdrop so pages cannot dim it', () => {
    render(<MobileHeader onMenuClick={vi.fn()} />)
    expect(screen.getByRole('banner')).toHaveClass('relative', 'z-10')
  })
})
