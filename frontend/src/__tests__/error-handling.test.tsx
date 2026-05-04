import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import {
  type AppError,
  createAppError,
  ToastProvider,
  useToast,
} from '@/components/error'

// Test error
const _testError: AppError = {
  id: 'test-error-1',
  type: 'rate_limit',
  severity: 'warning',
  title: 'Rate Limit Reached',
  message: "You've exceeded the rate limit. Please wait before retrying.",
  details: 'Error code: 429\nRetry-After: 30',
  timestamp: new Date(),
  retryable: true,
  modelSpecific: true,
  suggestedActions: [
    { id: 'wait', label: 'Wait & Retry', action: 'retry', primary: true },
    { id: 'switch', label: 'Try Different Model', action: 'switch_model' },
  ],
}

describe('createAppError', () => {
  it('creates error with correct type configuration', () => {
    const error = createAppError('rate_limit', 'Rate limit exceeded')
    expect(error.type).toBe('rate_limit')
    expect(error.severity).toBe('warning')
    expect(error.title).toBe('Rate Limit Reached')
    expect(error.retryable).toBe(true)
    expect(error.modelSpecific).toBe(true)
  })

  it('includes custom message and details', () => {
    const error = createAppError('provider_down', 'Service unavailable', '503')
    expect(error.message).toBe('Service unavailable')
    expect(error.details).toBe('503')
  })

  it('generates unique IDs', () => {
    const error1 = createAppError('network', 'Connection failed')
    const error2 = createAppError('network', 'Connection failed')
    expect(error1.id).not.toBe(error2.id)
  })
})

// Toast tests require the provider wrapper
function ToastTestComponent() {
  const { addToast, removeToast: _removeToast, toasts } = useToast()

  return (
    <div>
      <button onClick={() => addToast({ type: 'success', title: 'Success!' })}>
        Add Success Toast
      </button>
      <button
        onClick={() =>
          addToast({
            type: 'error',
            title: 'Error!',
            message: 'Something went wrong',
          })
        }
      >
        Add Error Toast
      </button>
      <div data-testid="toast-count">{toasts.length}</div>
    </div>
  )
}

describe('Toast System', () => {
  it('renders toasts from context', () => {
    render(
      <ToastProvider>
        <ToastTestComponent />
      </ToastProvider>,
    )

    fireEvent.click(screen.getByText('Add Success Toast'))
    expect(screen.getByText('Success!')).toBeInTheDocument()
  })

  it('shows toast message', () => {
    render(
      <ToastProvider>
        <ToastTestComponent />
      </ToastProvider>,
    )

    fireEvent.click(screen.getByText('Add Error Toast'))
    expect(screen.getByText('Error!')).toBeInTheDocument()
    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
  })

  it('limits number of toasts', () => {
    render(
      <ToastProvider maxToasts={2}>
        <ToastTestComponent />
      </ToastProvider>,
    )

    fireEvent.click(screen.getByText('Add Success Toast'))
    fireEvent.click(screen.getByText('Add Success Toast'))
    fireEvent.click(screen.getByText('Add Success Toast'))

    expect(screen.getByTestId('toast-count').textContent).toBe('2')
  })
})
