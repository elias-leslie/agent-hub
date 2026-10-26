import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  createAutomationProfile,
  fetchAutomationPolicy,
  fetchAutomationProfiles,
  fetchAutomationRuns,
  runAutomationProfile,
  updateAutomationPolicy,
  updateAutomationProfile,
} from './automations'

function success(body: unknown = {}) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('central Automations API contract', () => {
  it('sends profile revisions and schedule values to canonical routes', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => success())
    vi.stubGlobal('fetch', fetchMock)

    await createAutomationProfile({
      project_id: 'agent-hub',
      subject_id: 'example:one',
      workflow_key: 'agent-hub.example_job',
      label: 'Daily check',
      schedule_type: 'every',
      schedule_value: '3600000',
      schedule_timezone: 'UTC',
      config: {
        payload_type: 'agent_turn',
        payload_message: 'Check status',
        delivery: 'none',
      },
      enabled: true,
    })
    await updateAutomationProfile('profile-1', {
      expected_revision: 4,
      enabled: false,
    })
    await fetchAutomationProfiles('agent-hub', 50, 100)

    const createCall = fetchMock.mock.calls[0]
    expect(createCall[0]).toBe('/api/automations/profiles')
    expect(createCall[1].method).toBe('POST')
    expect(JSON.parse(createCall[1].body)).toMatchObject({
      schedule_type: 'every',
      schedule_value: '3600000',
      config: { payload_message: 'Check status' },
    })
    expect(fetchMock.mock.calls[1][0]).toBe(
      '/api/automations/profiles/profile-1',
    )
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({
      expected_revision: 4,
      enabled: false,
    })
    expect(fetchMock.mock.calls[2][0]).toBe(
      '/api/automations/profiles?limit=50&offset=100&project_id=agent-hub',
    )
  })

  it('uses project policy revisions and sends a JSON body for manual runs', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => success())
    vi.stubGlobal('fetch', fetchMock)

    await fetchAutomationPolicy('agent-hub')
    await updateAutomationPolicy('agent-hub', {
      expected_revision: 2,
      enabled: true,
      config: { daily_limit: 5, allowed_hours: [9, 10] },
    })
    await runAutomationProfile('profile-1')
    await fetchAutomationRuns({ profileId: 'profile-1', limit: 20, offset: 0 })

    expect(fetchMock.mock.calls[0][0]).toBe(
      '/api/automations/projects/agent-hub/policy',
    )
    expect(fetchMock.mock.calls[1][1].method).toBe('PUT')
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({
      expected_revision: 2,
      enabled: true,
      config: { daily_limit: 5, allowed_hours: [9, 10] },
    })
    expect(fetchMock.mock.calls[2][0]).toBe(
      '/api/automations/profiles/profile-1/run',
    )
    expect(fetchMock.mock.calls[2][1]).toMatchObject({
      method: 'POST',
      body: '{}',
    })
    expect(fetchMock.mock.calls[3][0]).toBe(
      '/api/automations/runs?limit=20&offset=0&profile_id=profile-1',
    )
  })
})
