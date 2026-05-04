import { useEffect, useState } from 'react'

interface ClientResponse {
  display_name: string
  rate_limit_rpm: number
  rate_limit_tpm: number
  allowed_projects: string[] | null
}

interface ClientUpdateRequest {
  display_name?: string
  rate_limit_rpm?: number
  rate_limit_tpm?: number
  allowed_projects?: string[]
}

interface EditClientModalProps {
  client: ClientResponse
  isOpen: boolean
  onClose: () => void
  onUpdate: (data: ClientUpdateRequest) => void
  isPending: boolean
}

export function EditClientModal({
  client,
  isOpen,
  onClose,
  onUpdate,
  isPending,
}: EditClientModalProps) {
  const [displayName, setDisplayName] = useState('')
  const [rateLimitRpm, setRateLimitRpm] = useState(60)
  const [rateLimitTpm, setRateLimitTpm] = useState(100000)
  const [allowedProjects, setAllowedProjects] = useState('')
  const [allowUnrestricted, setAllowUnrestricted] = useState(true)

  useEffect(() => {
    if (isOpen && client) {
      setDisplayName(client.display_name)
      setRateLimitRpm(client.rate_limit_rpm)
      setRateLimitTpm(client.rate_limit_tpm)
      setAllowUnrestricted(client.allowed_projects === null)
      setAllowedProjects(
        client.allowed_projects ? client.allowed_projects.join(', ') : '',
      )
    }
  }, [isOpen, client])

  function handleUpdate() {
    const updates: ClientUpdateRequest = {}
    if (displayName !== client.display_name) updates.display_name = displayName
    if (rateLimitRpm !== client.rate_limit_rpm)
      updates.rate_limit_rpm = rateLimitRpm
    if (rateLimitTpm !== client.rate_limit_tpm)
      updates.rate_limit_tpm = rateLimitTpm
    if (!allowUnrestricted) {
      const projects = allowedProjects
        .split(',')
        .map((p) => p.trim())
        .filter(Boolean)
      updates.allowed_projects = projects
    }
    onUpdate(updates)
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4 backdrop-blur-sm">
      <div className="panel-surface max-w-lg w-full p-6">
        <div className="mb-5">
          <p className="section-kicker">Client Policy</p>
          <h3 className="section-heading mt-2">Edit Client Settings</h3>
        </div>

        <div className="space-y-4">
          <div>
            <label className="detail-label mb-2 block">Display Name</label>
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              className="control-input"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="detail-label mb-2 block">
                Rate Limit (RPM)
              </label>
              <input
                type="number"
                value={rateLimitRpm}
                onChange={(e) =>
                  setRateLimitRpm(parseInt(e.target.value, 10) || 60)
                }
                min={1}
                max={10000}
                className="control-input"
              />
            </div>
            <div>
              <label className="detail-label mb-2 block">
                Rate Limit (TPM)
              </label>
              <input
                type="number"
                value={rateLimitTpm}
                onChange={(e) =>
                  setRateLimitTpm(parseInt(e.target.value, 10) || 100000)
                }
                min={1000}
                max={10000000}
                className="control-input"
              />
            </div>
          </div>

          <div className="section-card space-y-3">
            <label className="flex items-center gap-2 text-sm text-slate-300">
              <input
                type="checkbox"
                checked={allowUnrestricted}
                onChange={(e) => setAllowUnrestricted(e.target.checked)}
                className="rounded bg-slate-800 border-slate-600 text-amber-500 focus:ring-amber-500"
              />
              Unrestricted (allow all projects)
            </label>
            {!allowUnrestricted && (
              <div>
                <label className="detail-label mb-2 block">
                  Allowed Projects (comma-separated)
                </label>
                <input
                  type="text"
                  value={allowedProjects}
                  onChange={(e) => setAllowedProjects(e.target.value)}
                  placeholder="project-1, project-2, project-3"
                  className="control-input"
                />
                <p className="text-xs text-slate-500 mt-1">
                  Enter project IDs separated by commas. Leave empty to block
                  all projects.
                </p>
              </div>
            )}
          </div>
        </div>

        <div className="flex gap-3 mt-6">
          <button
            onClick={onClose}
            className="button-secondary flex-1 justify-center"
          >
            Cancel
          </button>
          <button
            onClick={handleUpdate}
            disabled={isPending}
            className="button-primary flex-1 justify-center disabled:cursor-not-allowed disabled:border-slate-700 disabled:bg-slate-800 disabled:text-slate-500 disabled:shadow-none"
          >
            {isPending ? 'Saving...' : 'Save Changes'}
          </button>
        </div>
      </div>
    </div>
  )
}
