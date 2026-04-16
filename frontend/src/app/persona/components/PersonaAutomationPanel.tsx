"use client";

import { useEffect, useMemo, useState } from "react";
import { formatDistanceToNowStrict } from "date-fns";
import {
  CalendarClock,
  ChevronDown,
  Pencil,
  PauseCircle,
  PlayCircle,
  Rocket,
  Trash2,
} from "lucide-react";

import { cn } from "@/lib/utils";
import type { PreviewProjectOption } from "@/types/agent-preview";
import type { PersonaAutomation } from "@/lib/api/persona-operator";

interface PersonaAutomationPanelProps {
  selectedProject: PreviewProjectOption | null;
  jobs: PersonaAutomation[];
  loading: boolean;
  error: string | null;
  saving: boolean;
  triggeringJobId: string | null;
  onSave: (
    jobId: string | null,
    payload: {
      name: string;
      schedule_type: "at" | "every" | "cron";
      schedule_value: string;
      payload_message: string;
    },
  ) => Promise<void>;
  onToggle: (job: PersonaAutomation) => Promise<void>;
  onDelete: (jobId: string) => Promise<void>;
  onTrigger: (job: PersonaAutomation) => Promise<void>;
}

function buildDefaultMessage(project: PreviewProjectOption | null, detail: string) {
  return [
    `Project: ${project?.id ?? "agent-hub"}`,
    project?.rootPath ? `Working dir: ${project.rootPath}` : null,
    detail,
    "Use only core tools: read, write, edit, bash.",
    "Post concise status back into the persona workspace timeline.",
  ]
    .filter(Boolean)
    .join("\n\n");
}

function automationDetail(message: string): string {
  return message
    .split(/\n\s*\n/)
    .map((chunk) => chunk.trim())
    .find((chunk) => !chunk.startsWith("Project:") && !chunk.startsWith("Working dir:") && !chunk.startsWith("Use only core tools:") && !chunk.startsWith("Post concise status"))
    || message;
}

export function PersonaAutomationPanel({
  selectedProject,
  jobs,
  loading,
  error,
  saving,
  triggeringJobId,
  onSave,
  onToggle,
  onDelete,
  onTrigger,
}: PersonaAutomationPanelProps) {
  const [composerOpen, setComposerOpen] = useState(false);
  const [editingJobId, setEditingJobId] = useState<string | null>(null);
  const [name, setName] = useState("Daily operator check");
  const [scheduleType, setScheduleType] = useState<"every" | "cron" | "at">("every");
  const [everyMinutes, setEveryMinutes] = useState("60");
  const [cronValue, setCronValue] = useState("0 14 * * *");
  const [atValue, setAtValue] = useState("");
  const [detail, setDetail] = useState("Check active work, summarize blockers, and call out the next best move.");

  const editingJob = useMemo(
    () => jobs.find((job) => job.id === editingJobId) ?? null,
    [editingJobId, jobs],
  );

  useEffect(() => {
    if (!editingJob) {
      return;
    }
    setComposerOpen(true);
    setName(editingJob.name);
    setScheduleType(editingJob.schedule_type);
    if (editingJob.schedule_type === "every") {
      setEveryMinutes(String(Math.max(1, Math.round(Number(editingJob.schedule_value) / 60000))));
    }
    if (editingJob.schedule_type === "cron") {
      setCronValue(editingJob.schedule_value);
    }
    if (editingJob.schedule_type === "at") {
      const value = new Date(editingJob.schedule_value);
      setAtValue(Number.isNaN(value.getTime()) ? "" : value.toISOString().slice(0, 16));
    }
    setDetail(automationDetail(editingJob.payload_message));
  }, [editingJob]);

  const scheduleValue = useMemo(() => {
    if (scheduleType === "every") {
      const minutes = Math.max(1, parseInt(everyMinutes || "60", 10));
      return String(minutes * 60 * 1000);
    }
    if (scheduleType === "cron") {
      return cronValue.trim();
    }
    return atValue ? new Date(atValue).toISOString() : "";
  }, [atValue, cronValue, everyMinutes, scheduleType]);

  const resetComposer = () => {
    setEditingJobId(null);
    setName("Daily operator check");
    setScheduleType("every");
    setEveryMinutes("60");
    setCronValue("0 14 * * *");
    setAtValue("");
    setDetail("Check active work, summarize blockers, and call out the next best move.");
  };

  const save = async () => {
    await onSave(editingJobId, {
      name,
      schedule_type: scheduleType,
      schedule_value: scheduleValue,
      payload_message: buildDefaultMessage(selectedProject, detail),
    });
    resetComposer();
    setComposerOpen(false);
  };

  return (
    <section
      data-testid="persona-automation-panel"
      className="rounded-[28px] border border-slate-800/70 bg-slate-900/80 p-4"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
            <CalendarClock className="h-3.5 w-3.5 text-emerald-300" />
            Automations
          </div>
          <h3 className="mt-2 text-lg font-semibold text-slate-50">
            Keep recurring checks available, not sprawling.
          </h3>
        </div>
        <div className="flex items-center gap-2">
          <div className="rounded-full border border-slate-700 bg-slate-950/70 px-2.5 py-1 text-xs text-slate-300">
            {jobs.length} jobs
          </div>
          <button
            type="button"
            onClick={() => {
              resetComposer();
              setComposerOpen((current) => !current || jobs.length === 0);
            }}
            className="rounded-full border border-slate-700 bg-slate-950/70 px-3 py-1 text-xs font-medium text-slate-200 transition hover:border-slate-600 hover:bg-slate-900"
          >
            {composerOpen ? "Hide editor" : "New automation"}
          </button>
        </div>
      </div>

      <div className="mt-4 rounded-[24px] border border-slate-800/70 bg-slate-950/70">
        <button
          type="button"
          onClick={() => setComposerOpen((current) => !current)}
          className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
        >
          <div>
            <div className="text-sm font-medium text-slate-100">
              {editingJobId ? "Edit automation" : "New automation"}
            </div>
            <div className="mt-1 text-xs text-slate-500">
              {editingJobId ? "Adjust schedule or prompt without leaving /persona." : "Create only when needed. Keep chat surface clear."}
            </div>
          </div>
          <ChevronDown className={cn("h-4 w-4 text-slate-500 transition-transform", !composerOpen && "-rotate-90")} />
        </button>

        {composerOpen ? (
          <div className="space-y-2 border-t border-slate-800/70 p-3">
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none"
              placeholder="Automation name"
            />
            <div className="grid gap-2 md:grid-cols-3">
              <select
                value={scheduleType}
                onChange={(event) => setScheduleType(event.target.value as "every" | "cron" | "at")}
                className="rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none"
              >
                <option value="every">Every N minutes</option>
                <option value="cron">Cron</option>
                <option value="at">Run once</option>
              </select>
              {scheduleType === "every" ? (
                <input
                  value={everyMinutes}
                  onChange={(event) => setEveryMinutes(event.target.value)}
                  className="rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none md:col-span-2"
                  placeholder="60"
                />
              ) : null}
              {scheduleType === "cron" ? (
                <input
                  value={cronValue}
                  onChange={(event) => setCronValue(event.target.value)}
                  className="rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none md:col-span-2"
                  placeholder="0 14 * * *"
                />
              ) : null}
              {scheduleType === "at" ? (
                <input
                  type="datetime-local"
                  value={atValue}
                  onChange={(event) => setAtValue(event.target.value)}
                  className="rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none md:col-span-2"
                />
              ) : null}
            </div>
            <textarea
              value={detail}
              onChange={(event) => setDetail(event.target.value)}
              rows={3}
              className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none"
              placeholder="What should the scheduled run do?"
            />
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => void save()}
                disabled={saving || !name.trim() || !scheduleValue.trim() || !detail.trim()}
                className="inline-flex items-center justify-center rounded-xl border border-emerald-500/20 bg-emerald-950/20 px-3 py-2 text-sm font-medium text-emerald-200 transition hover:border-emerald-400/30 hover:bg-emerald-950/30 disabled:opacity-60"
              >
                {saving ? "Saving automation…" : editingJobId ? "Save automation" : "Create automation"}
              </button>
              {(editingJobId || name !== "Daily operator check" || detail !== "Check active work, summarize blockers, and call out the next best move.") ? (
                <button
                  type="button"
                  onClick={() => {
                    resetComposer();
                    setComposerOpen(false);
                  }}
                  className="inline-flex items-center justify-center rounded-xl border border-slate-700 bg-slate-950/70 px-3 py-2 text-sm font-medium text-slate-200 transition hover:border-slate-600 hover:bg-slate-900"
                >
                  Cancel
                </button>
              ) : null}
            </div>
          </div>
        ) : null}
      </div>

      {error ? (
        <div className="mt-3 rounded-2xl border border-rose-500/20 bg-rose-950/20 px-3 py-2 text-sm text-rose-200">
          {error}
        </div>
      ) : null}

      <div className="mt-4 max-h-[18rem] space-y-2 overflow-y-auto pr-1">
        {loading && jobs.length === 0 ? (
          <div className="rounded-2xl border border-slate-800/70 bg-slate-950/70 px-3 py-3 text-sm text-slate-400">
            Loading automations…
          </div>
        ) : null}
        {jobs.map((job) => (
          <div key={job.id} className="rounded-2xl border border-slate-800/70 bg-slate-950/70 px-3 py-2.5">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium text-slate-100">{job.name}</span>
                  <span className="rounded-full border border-slate-700 bg-slate-900/70 px-2 py-0.5 text-[11px] text-slate-300">
                    {job.schedule_type}
                  </span>
                  <span className="rounded-full border border-slate-700 bg-slate-900/70 px-2 py-0.5 text-[11px] text-slate-300">
                    {job.enabled ? "enabled" : "paused"}
                  </span>
                </div>
                <p className="mt-2 line-clamp-3 text-sm leading-6 text-slate-300">{automationDetail(job.payload_message)}</p>
                <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-500">
                  <span>
                    {job.next_run_at
                      ? `Next ${formatDistanceToNowStrict(new Date(job.next_run_at), { addSuffix: true })}`
                      : "No next run scheduled"}
                  </span>
                  {job.last_run_at ? (
                    <span>
                      Last {formatDistanceToNowStrict(new Date(job.last_run_at), { addSuffix: true })}
                    </span>
                  ) : null}
                </div>
              </div>
              <div className="flex shrink-0 flex-wrap gap-1.5">
                <button
                  type="button"
                  onClick={() => void onTrigger(job)}
                  disabled={triggeringJobId === job.id}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-emerald-500/20 bg-emerald-950/20 px-2.5 py-1.5 text-xs font-medium text-emerald-200 transition hover:border-emerald-400/30 hover:bg-emerald-950/30 disabled:opacity-60"
                >
                  <Rocket className="h-4 w-4" />
                  {triggeringJobId === job.id ? "Running" : "Run now"}
                </button>
                <button
                  type="button"
                  onClick={() => setEditingJobId(job.id)}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-slate-700 bg-slate-900/80 px-2.5 py-1.5 text-xs font-medium text-slate-200 transition hover:border-slate-600 hover:bg-slate-800"
                >
                  <Pencil className="h-4 w-4" />
                  Edit
                </button>
                <button
                  type="button"
                  onClick={() => void onToggle(job)}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-slate-700 bg-slate-900/80 px-2.5 py-1.5 text-xs font-medium text-slate-200 transition hover:border-slate-600 hover:bg-slate-800"
                >
                  {job.enabled ? <PauseCircle className="h-4 w-4" /> : <PlayCircle className="h-4 w-4" />}
                  {job.enabled ? "Pause" : "Resume"}
                </button>
                <button
                  type="button"
                  onClick={() => void onDelete(job.id)}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-rose-500/20 bg-rose-950/20 px-2.5 py-1.5 text-xs font-medium text-rose-200 transition hover:border-rose-400/30 hover:bg-rose-950/30"
                >
                  <Trash2 className="h-4 w-4" />
                  Delete
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
