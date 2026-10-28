import { act, renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import {
  MAX_COMPARED_MODELS,
  useModelComparison,
} from '@/components/models/use-model-comparison'
import type { ModelOption } from '@/hooks/use-models-catalog'

function model(id: string, provider = 'claude'): ModelOption {
  return { id, name: id, provider } as ModelOption
}

describe('useModelComparison', () => {
  it('opens the comparison only when asked, with the selected models', () => {
    const { result } = renderHook(() => useModelComparison())

    act(() => result.current.toggleModel(model('claude-opus-5-5')))
    act(() => result.current.toggleModel(model('gemini-3.8-flash', 'gemini')))
    expect(result.current.isOpen).toBe(false)

    act(() => result.current.open())
    expect(result.current.isOpen).toBe(true)
    expect(result.current.selectedModels.map((m) => m.id)).toEqual([
      'claude-opus-5-5',
      'gemini-3.8-flash',
    ])
  })

  it('keeps the selection when the panel closes', () => {
    const { result } = renderHook(() => useModelComparison())
    act(() => result.current.toggleModel(model('claude-opus-5-5')))
    act(() => result.current.open())
    act(() => result.current.close())

    expect(result.current.isOpen).toBe(false)
    expect(result.current.isSelected('claude-opus-5-5')).toBe(true)
  })

  it('closes when the last model is removed and caps the selection', () => {
    const { result } = renderHook(() => useModelComparison())
    for (const id of ['a', 'b', 'c', 'd']) {
      act(() => result.current.toggleModel(model(id)))
    }
    expect(result.current.selectedModels).toHaveLength(MAX_COMPARED_MODELS)

    act(() => result.current.open())
    for (const id of ['a', 'b', 'c']) {
      act(() => result.current.removeModel(id))
    }
    expect(result.current.isOpen).toBe(false)

    act(() => result.current.toggleModel(model('e')))
    expect(result.current.isOpen).toBe(false)
  })
})
