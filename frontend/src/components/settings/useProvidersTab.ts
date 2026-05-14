'use client'

import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { useCallback, useEffect, useState } from 'react'
import {
  type Credential,
  type CredentialCreate,
  createCredential,
  deleteCredential,
  exchangeOAuthCode,
  fetchCredentials,
  fetchOAuthStatus,
  fetchStatus,
  setPrimaryCredential,
  startOAuthFlow,
  updateCredential,
} from '@/lib/api'
import {
  fetchUserPreferences,
  updateUserPreferences,
} from '@/lib/api/preferences'
import {
  filterVisibleSettingsProviders,
  isOAuthProvider,
  listKnownProviderIds,
} from './constants'
import type {
  ProviderHealthData,
  SaveCredentialOptions,
} from './ProviderCardTypes'

export function useProvidersTab() {
  const queryClient = useQueryClient()
  const knownProviderIds = listKnownProviderIds()
  const oauthProviderIds = knownProviderIds.filter(isOAuthProvider)

  const { data, isLoading } = useQuery({
    queryKey: ['credentials'],
    queryFn: () => fetchCredentials(),
  })
  const oauthStatusQueries = useQueries({
    queries: oauthProviderIds.map((providerId) => ({
      queryKey: ['oauth-status', providerId] as const,
      queryFn: () => fetchOAuthStatus(providerId),
    })),
  })
  const { data: statusData } = useQuery({
    queryKey: ['provider-status'],
    queryFn: () => fetchStatus(),
    refetchInterval: 30_000,
  })
  const { data: prefsData } = useQuery({
    queryKey: ['user-preferences'],
    queryFn: () => fetchUserPreferences(),
  })
  const prefsMut = useMutation({
    mutationFn: (prefs: Parameters<typeof updateUserPreferences>[0]) =>
      updateUserPreferences(prefs),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['user-preferences'] })
      queryClient.invalidateQueries({ queryKey: ['provider-status'] })
    },
  })

  const [editingProvider, setEditingProvider] = useState<string | null>(null)
  const [editingCredentialId, setEditingCredentialId] = useState<number | null>(
    null,
  )
  const [addingProvider, setAddingProvider] = useState<string | null>(null)
  const [confirmingDelete, setConfirmingDelete] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [oauthLoading, setOauthLoading] = useState<string | null>(null)
  const [manualPasteProvider, setManualPasteProvider] = useState<string | null>(
    null,
  )
  const [manualPasteState, setManualPasteState] = useState<string | null>(null)

  const credentialsByProvider: Record<string, Credential[]> = {}
  if (data) {
    for (const cred of data.credentials) {
      if (!credentialsByProvider[cred.provider]) {
        credentialsByProvider[cred.provider] = []
      }
      credentialsByProvider[cred.provider].push(cred)
    }
  }

  const handleOAuthMessage = useCallback(
    (event: MessageEvent) => {
      if (event.data?.type === 'oauth-success') {
        const provider = event.data.provider
        setOauthLoading(null)
        setManualPasteProvider(null)
        setManualPasteState(null)
        queryClient.invalidateQueries({ queryKey: ['credentials'] })
        if (isOAuthProvider(provider)) {
          queryClient.invalidateQueries({
            queryKey: ['oauth-status', provider],
          })
        }
        queryClient.invalidateQueries({ queryKey: ['provider-status'] })
      } else if (event.data?.type === 'oauth-error') {
        setOauthLoading(null)
        setError(event.data.error || 'OAuth authentication failed')
      }
    },
    [queryClient],
  )

  useEffect(() => {
    window.addEventListener('message', handleOAuthMessage)
    return () => window.removeEventListener('message', handleOAuthMessage)
  }, [handleOAuthMessage])

  async function handleOAuthStart(providerId: string) {
    setError(null)
    setOauthLoading(providerId)
    try {
      const result = await startOAuthFlow(providerId)
      setManualPasteProvider(providerId)
      setManualPasteState(result.state)
      const width = 600
      const height = 700
      const left = window.screenX + (window.outerWidth - width) / 2
      const top = window.screenY + (window.outerHeight - height) / 2
      const popup = window.open(
        result.url,
        `oauth-${providerId}`,
        `width=${width},height=${height},left=${left},top=${top},popup=yes`,
      )
      if (!popup) {
        setError(`Popup blocked. Please open this URL manually: ${result.url}`)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to start OAuth flow')
      setOauthLoading(null)
      setManualPasteProvider(null)
      setManualPasteState(null)
    }
  }

  async function handleManualExchange(providerId: string, codeInput: string) {
    if (!manualPasteState) return
    setError(null)
    try {
      const result = await exchangeOAuthCode(
        providerId,
        codeInput,
        manualPasteState,
      )
      if (result.success) {
        setManualPasteProvider(null)
        setManualPasteState(null)
        setOauthLoading(null)
        queryClient.invalidateQueries({ queryKey: ['credentials'] })
        queryClient.invalidateQueries({
          queryKey: ['oauth-status', providerId],
        })
        queryClient.invalidateQueries({ queryKey: ['provider-status'] })
      } else {
        setError(result.error || 'OAuth exchange failed')
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'OAuth exchange failed')
    }
  }

  function resetForm() {
    setEditingProvider(null)
    setEditingCredentialId(null)
    setAddingProvider(null)
    setError(null)
  }

  const createMut = useMutation({
    mutationFn: (d: CredentialCreate) => createCredential(d),
    onSuccess: (_data, vars) => {
      queryClient.invalidateQueries({ queryKey: ['credentials'] })
      if (isOAuthProvider(vars.provider)) {
        queryClient.invalidateQueries({
          queryKey: ['oauth-status', vars.provider],
        })
      }
      queryClient.invalidateQueries({ queryKey: ['provider-status'] })
      resetForm()
    },
    onError: (e: Error) => setError(e.message),
  })

  const updateMut = useMutation({
    mutationFn: ({ id, value }: { id: number; value: string }) =>
      updateCredential(id, value),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['credentials'] })
      queryClient.invalidateQueries({ queryKey: ['provider-status'] })
      resetForm()
    },
    onError: (e: Error) => setError(e.message),
  })

  const deleteMut = useMutation({
    mutationFn: (ids: number[]) =>
      Promise.all(ids.map((id) => deleteCredential(id))),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['credentials'] })
      knownProviderIds.filter(isOAuthProvider).forEach((p) => {
        queryClient.invalidateQueries({ queryKey: ['oauth-status', p] })
      })
      queryClient.invalidateQueries({ queryKey: ['provider-status'] })
      setConfirmingDelete(null)
    },
    onError: (e: Error) => setError(e.message),
  })

  const setPrimaryMut = useMutation({
    mutationFn: (id: number) => setPrimaryCredential(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['credentials'] })
      queryClient.invalidateQueries({ queryKey: ['provider-status'] })
    },
    onError: (e: Error) => setError(e.message),
  })

  function handleSave(
    providerId: string,
    value: string,
    options?: SaveCredentialOptions,
  ) {
    setError(null)

    if (options?.credentialId) {
      updateMut.mutate({ id: options.credentialId, value })
      return
    }

    if (options?.forceCreate) {
      createMut.mutate({
        provider: providerId,
        credential_type: 'api_key',
        value,
      })
      return
    }

    const existing = credentialsByProvider[providerId]?.find(
      (c) => c.credential_type === 'api_key',
    )
    if (existing) {
      updateMut.mutate({ id: existing.id, value })
    } else {
      createMut.mutate({
        provider: providerId,
        credential_type: 'api_key',
        value,
      })
    }
  }

  async function handleSaveMulti(
    providerId: string,
    fields: Record<string, string>,
  ) {
    setError(null)
    const existing = credentialsByProvider[providerId] ?? []
    try {
      for (const [credentialType, value] of Object.entries(fields)) {
        const match = existing.find((c) => c.credential_type === credentialType)
        if (match) {
          await updateCredential(match.id, value)
        } else {
          await createCredential({
            provider: providerId,
            credential_type: credentialType,
            value,
          })
        }
      }
      queryClient.invalidateQueries({ queryKey: ['credentials'] })
      queryClient.invalidateQueries({ queryKey: ['provider-status'] })
      resetForm()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save credentials')
    }
  }

  function getOAuthStatus(providerId: string) {
    const oauthIndex = oauthProviderIds.indexOf(providerId)
    return oauthIndex >= 0 ? oauthStatusQueries[oauthIndex]?.data : undefined
  }

  function getHealthData(providerId: string): ProviderHealthData | undefined {
    if (!statusData) return undefined
    // Status API uses adapter names which may differ from UI provider IDs
    const match = statusData.providers.find((p) => p.name === providerId)
    if (!match) return undefined
    return {
      available: match.available,
      configured: match.configured,
      error: match.error,
      health: match.health,
    }
  }

  const providerIds = filterVisibleSettingsProviders([
    ...knownProviderIds,
    ...Object.keys(credentialsByProvider),
    ...(statusData?.providers.map((p) => p.name) ?? []),
  ])

  function getPreferredAuth(providerId: string): 'oauth' | 'api_key' {
    if (providerId === 'codex')
      return (
        (prefsData?.codex_auth_preference as 'oauth' | 'api_key') ?? 'oauth'
      )
    return 'oauth'
  }

  function handlePreferenceChange(
    providerId: string,
    pref: 'oauth' | 'api_key',
  ) {
    if (providerId === 'codex') {
      prefsMut.mutate({ codex_auth_preference: pref })
    }
  }

  return {
    isLoading,
    providerIds,
    credentialsByProvider,
    editingProvider,
    setEditingProvider,
    editingCredentialId,
    setEditingCredentialId,
    addingProvider,
    setAddingProvider,
    confirmingDelete,
    setConfirmingDelete,
    error,
    oauthLoading,
    manualPasteProvider,
    setManualPasteProvider,
    setManualPasteState,
    setOauthLoading,
    isSaving: createMut.isPending || updateMut.isPending,
    isDeletingAny: deleteMut.isPending,
    resetForm,
    handleSave,
    handleSaveMulti,
    handleOAuthStart,
    handleManualExchange,
    getOAuthStatus,
    getHealthData,
    getPreferredAuth,
    handlePreferenceChange,
    onDelete: (ids: number[]) => deleteMut.mutate(ids),
    onSetPrimaryCredential: (credentialId: number) =>
      setPrimaryMut.mutate(credentialId),
  }
}
