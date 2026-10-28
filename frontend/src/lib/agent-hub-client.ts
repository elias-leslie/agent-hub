import { createClient } from '@agent-hub/sdk'
import { buildInternalHeaders, getApiBaseUrl } from '@/lib/api-config'

/**
 * The dashboard's one Agent Hub client. It sends the same identity headers as `fetchApi` (read on every request,
 * so they follow the browser or server context) to the same-origin base URL.
 */
export const agentHubClient = createClient({
  baseUrl: getApiBaseUrl(),
  headers: buildInternalHeaders,
})
