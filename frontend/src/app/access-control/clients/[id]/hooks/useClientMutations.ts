import { useMutation, useQueryClient } from '@tanstack/react-query'
import { buildApiUrl, fetchApi } from '@/lib/api-config'

interface ClientUpdateRequest {
  display_name?: string
  rate_limit_rpm?: number
  rate_limit_tpm?: number
  allowed_projects?: string[]
}

export function useClientMutations(clientId: string) {
  const queryClient = useQueryClient()

  const suspendMutation = useMutation({
    mutationFn: async (reason: string) => {
      const response = await fetchApi(
        buildApiUrl(`/access-control/clients/${clientId}/suspend`),
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ reason }),
        },
      )
      if (!response.ok) throw new Error('Failed to suspend client')
      return response.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['access-control-client', clientId],
      })
    },
  })

  const activateMutation = useMutation({
    mutationFn: async () => {
      const response = await fetchApi(
        buildApiUrl(`/access-control/clients/${clientId}/activate`),
        {
          method: 'POST',
        },
      )
      if (!response.ok) throw new Error('Failed to activate client')
      return response.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['access-control-client', clientId],
      })
    },
  })

  const blockMutation = useMutation({
    mutationFn: async (reason: string) => {
      const response = await fetchApi(
        buildApiUrl(`/access-control/clients/${clientId}/block`),
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ reason }),
        },
      )
      if (!response.ok) throw new Error('Failed to block client')
      return response.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['access-control-client', clientId],
      })
    },
  })

  const updateMutation = useMutation({
    mutationFn: async (data: ClientUpdateRequest) => {
      const response = await fetchApi(
        buildApiUrl(`/access-control/clients/${clientId}`),
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data),
        },
      )
      if (!response.ok) throw new Error('Failed to update client')
      return response.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['access-control-client', clientId],
      })
    },
  })

  return {
    suspendMutation,
    activateMutation,
    blockMutation,
    updateMutation,
  }
}
