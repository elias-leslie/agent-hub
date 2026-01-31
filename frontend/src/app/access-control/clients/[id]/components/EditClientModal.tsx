import { useState, useEffect } from "react";

interface ClientResponse {
  display_name: string;
  rate_limit_rpm: number;
  rate_limit_tpm: number;
  allowed_projects: string[] | null;
}

interface ClientUpdateRequest {
  display_name?: string;
  rate_limit_rpm?: number;
  rate_limit_tpm?: number;
  allowed_projects?: string[];
}

interface EditClientModalProps {
  client: ClientResponse;
  isOpen: boolean;
  onClose: () => void;
  onUpdate: (data: ClientUpdateRequest) => void;
  isPending: boolean;
}

export function EditClientModal({ client, isOpen, onClose, onUpdate, isPending }: EditClientModalProps) {
  const [displayName, setDisplayName] = useState("");
  const [rateLimitRpm, setRateLimitRpm] = useState(60);
  const [rateLimitTpm, setRateLimitTpm] = useState(100000);
  const [allowedProjects, setAllowedProjects] = useState("");
  const [allowUnrestricted, setAllowUnrestricted] = useState(true);

  useEffect(() => {
    if (isOpen && client) {
      setDisplayName(client.display_name);
      setRateLimitRpm(client.rate_limit_rpm);
      setRateLimitTpm(client.rate_limit_tpm);
      setAllowUnrestricted(client.allowed_projects === null);
      setAllowedProjects(client.allowed_projects ? client.allowed_projects.join(", ") : "");
    }
  }, [isOpen, client]);

  function handleUpdate() {
    const updates: ClientUpdateRequest = {};
    if (displayName !== client.display_name) updates.display_name = displayName;
    if (rateLimitRpm !== client.rate_limit_rpm) updates.rate_limit_rpm = rateLimitRpm;
    if (rateLimitTpm !== client.rate_limit_tpm) updates.rate_limit_tpm = rateLimitTpm;
    if (!allowUnrestricted) {
      const projects = allowedProjects.split(",").map((p) => p.trim()).filter(Boolean);
      updates.allowed_projects = projects;
    }
    onUpdate(updates);
  }

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 max-w-lg w-full mx-4">
        <h3 className="text-lg font-semibold text-slate-100 mb-4">Edit Client Settings</h3>

        <div className="space-y-4">
          <div>
            <label className="block text-sm text-slate-400 mb-1">Display Name</label>
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              className="w-full px-4 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-100 focus:outline-none focus:border-blue-500"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm text-slate-400 mb-1">Rate Limit (RPM)</label>
              <input
                type="number"
                value={rateLimitRpm}
                onChange={(e) => setRateLimitRpm(parseInt(e.target.value) || 60)}
                min={1}
                max={10000}
                className="w-full px-4 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-100 focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm text-slate-400 mb-1">Rate Limit (TPM)</label>
              <input
                type="number"
                value={rateLimitTpm}
                onChange={(e) => setRateLimitTpm(parseInt(e.target.value) || 100000)}
                min={1000}
                max={10000000}
                className="w-full px-4 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-100 focus:outline-none focus:border-blue-500"
              />
            </div>
          </div>

          <div>
            <label className="flex items-center gap-2 text-sm text-slate-400 mb-2">
              <input
                type="checkbox"
                checked={allowUnrestricted}
                onChange={(e) => setAllowUnrestricted(e.target.checked)}
                className="rounded bg-slate-800 border-slate-600 text-blue-500 focus:ring-blue-500"
              />
              Unrestricted (allow all projects)
            </label>
            {!allowUnrestricted && (
              <div>
                <label className="block text-sm text-slate-400 mb-1">
                  Allowed Projects (comma-separated)
                </label>
                <input
                  type="text"
                  value={allowedProjects}
                  onChange={(e) => setAllowedProjects(e.target.value)}
                  placeholder="project-1, project-2, project-3"
                  className="w-full px-4 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-blue-500"
                />
                <p className="text-xs text-slate-500 mt-1">
                  Enter project IDs separated by commas. Leave empty to block all projects.
                </p>
              </div>
            )}
          </div>
        </div>

        <div className="flex gap-3 mt-6">
          <button
            onClick={onClose}
            className="flex-1 py-2 px-4 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-100 text-sm transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleUpdate}
            disabled={isPending}
            className="flex-1 py-2 px-4 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm transition-colors disabled:opacity-50"
          >
            {isPending ? "Saving..." : "Save Changes"}
          </button>
        </div>
      </div>
    </div>
  );
}
