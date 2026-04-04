"use client";

import Link from "next/link";
import {
  Activity,
  ArrowRight,
  Bot,
  BrainCircuit,
  DatabaseZap,
  LayoutDashboard,
  Radar,
  ShieldCheck,
  Sparkles,
  TerminalSquare,
  Zap,
} from "lucide-react";

import { ThemeSelector } from "@/components/theme-selector";

const FEATURE_CARDS = [
  {
    icon: LayoutDashboard,
    title: "Operator dashboard",
    copy: "Track sessions, failure pressure, benchmark regressions, and routing health from one control plane.",
  },
  {
    icon: DatabaseZap,
    title: "Persistent memory",
    copy: "Store mandates, guardrails, and searchable references in PostgreSQL with progressive context injection.",
  },
  {
    icon: BrainCircuit,
    title: "Persona orchestration",
    copy: "Run a named persona with heartbeat automation, self-improvement loops, and specialist delegation.",
  },
];

const QUICKSTART_STEPS = [
  {
    label: "1. Install",
    detail: "Clone the repo, copy `.env.example`, then choose either the Docker stack or the native services.",
    command: "cp .env.example .env.local && pnpm install",
  },
  {
    label: "2. Boot",
    detail: "Run the backend, worker, and frontend on the default public ports `8003` and `3003`.",
    command: "rebuild.sh agent-hub",
  },
  {
    label: "3. Use it",
    detail: "Open the dashboard, inspect the persona workspace, then start issuing completions or reviewing sessions.",
    command: "open http://localhost:3003",
  },
];

const SURFACE_PILLS = [
  "Multi-provider completions",
  "PostgreSQL + pgvector memory",
  "Persona heartbeat + self-honing",
  "Session and benchmark observability",
];

export default function HomePage() {
  return (
    <div className="relative min-h-screen overflow-hidden">
      <div className="pointer-events-none absolute inset-0 bg-grid-pattern opacity-50" />

      <header className="relative z-10 mx-auto flex w-full max-w-7xl items-center justify-between gap-4 px-5 py-5 lg:px-8">
        <Link href="/" className="flex items-center gap-3">
          <div className="rounded-2xl border border-amber-400/20 bg-gradient-to-br from-amber-500 to-orange-600 p-3 shadow-[0_24px_48px_-30px_rgba(245,158,11,0.7)]">
            <Zap className="h-5 w-5 text-white" />
          </div>
          <div>
            <p className="text-sm font-semibold text-slate-100">Agent Hub</p>
            <p className="text-[11px] uppercase tracking-[0.24em] text-slate-500">
              Self-Hosted Control Plane
            </p>
          </div>
        </Link>

        <div className="flex items-center gap-3">
          <div className="hidden sm:block">
            <ThemeSelector compact />
          </div>
          <Link href="/dashboard" className="button-secondary">
            <LayoutDashboard className="h-4 w-4" />
            Open App
          </Link>
        </div>
      </header>

      <main className="relative z-10 mx-auto flex w-full max-w-7xl flex-col gap-8 px-5 pb-14 lg:px-8 lg:pb-20">
        <section className="grid gap-8 pt-4 xl:grid-cols-[1.08fr_0.92fr] xl:items-center xl:pt-10">
          <div className="animate-fade-up">
            <p className="section-kicker">Public Release Candidate</p>
            <h1 className="mt-4 max-w-4xl text-4xl font-semibold tracking-tight text-slate-50 sm:text-5xl lg:text-6xl">
              Run, observe, and improve multi-provider agents from one place.
            </h1>
            <p className="mt-5 max-w-2xl text-base leading-7 text-slate-400 sm:text-lg">
              Agent Hub is a self-hosted control plane for completions, memory,
              persona routing, and operational review. It is built for teams that
              want real agent infrastructure, not a thin demo chat shell.
            </p>

            <div className="mt-6 flex flex-wrap gap-3">
              <Link href="/dashboard" className="button-primary">
                <Activity className="h-4 w-4" />
                Open Dashboard
              </Link>
              <Link href="/persona" className="button-secondary">
                <Bot className="h-4 w-4" />
                Persona Workspace
              </Link>
              <Link href="/sessions" className="button-secondary">
                <TerminalSquare className="h-4 w-4" />
                Session History
              </Link>
            </div>

            <div className="mt-6 flex flex-wrap gap-2">
              {SURFACE_PILLS.map((pill) => (
                <span
                  key={pill}
                  className="rounded-full border border-slate-700/70 bg-slate-900/70 px-3 py-1 text-xs font-medium text-slate-300"
                >
                  {pill}
                </span>
              ))}
            </div>
          </div>

          <div className="panel-surface animate-fade-up p-5 lg:p-6">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="section-kicker">Live Surfaces</p>
                <h2 className="section-heading mt-2">The product at a glance</h2>
              </div>
              <div className="rounded-full border border-emerald-500/20 bg-emerald-500/10 px-3 py-1 text-xs font-semibold text-emerald-300">
                Dashboard online
              </div>
            </div>

            <div className="mt-5 grid gap-4">
              <div className="rounded-3xl border border-slate-800/80 bg-slate-950/70 p-4 shadow-[0_24px_70px_-48px_rgba(0,0,0,0.9)]">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-slate-100">Arena + Dashboard</p>
                    <p className="mt-1 text-xs text-slate-500">
                      Reliability, token pressure, and regression signals.
                    </p>
                  </div>
                  <Radar className="h-5 w-5 text-amber-400" />
                </div>
                <div className="mt-4 grid gap-3 sm:grid-cols-3">
                  <div className="rounded-2xl border border-slate-800 bg-slate-900/80 p-3">
                    <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">Active agents</p>
                    <p className="mt-2 text-2xl font-semibold text-slate-100">12</p>
                  </div>
                  <div className="rounded-2xl border border-slate-800 bg-slate-900/80 p-3">
                    <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">Reliability</p>
                    <p className="mt-2 text-2xl font-semibold text-emerald-400">94.1%</p>
                  </div>
                  <div className="rounded-2xl border border-slate-800 bg-slate-900/80 p-3">
                    <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">Open regressions</p>
                    <p className="mt-2 text-2xl font-semibold text-amber-300">3</p>
                  </div>
                </div>
              </div>

              <div className="grid gap-4 lg:grid-cols-[0.95fr_1.05fr]">
                <div className="rounded-3xl border border-slate-800/80 bg-slate-950/70 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-semibold text-slate-100">Persona loop</p>
                      <p className="mt-1 text-xs text-slate-500">
                        Heartbeat automation, self-honing, and workspace state.
                      </p>
                    </div>
                    <Sparkles className="h-5 w-5 text-violet-400" />
                  </div>
                  <div className="mt-4 space-y-3">
                    <div className="rounded-2xl border border-slate-800 bg-slate-900/75 px-3 py-3">
                      <p className="text-xs font-medium text-slate-400">Status</p>
                      <p className="mt-1 text-sm font-semibold text-slate-100">Working with live memory injection</p>
                    </div>
                    <div className="rounded-2xl border border-slate-800 bg-slate-900/75 px-3 py-3">
                      <p className="text-xs font-medium text-slate-400">Current focus</p>
                      <p className="mt-1 text-sm text-slate-300">Reduce benchmark regressions and tighten recovery behavior.</p>
                    </div>
                  </div>
                </div>

                <div className="rounded-3xl border border-slate-800/80 bg-slate-950/70 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-semibold text-slate-100">Memory + policy</p>
                      <p className="mt-1 text-xs text-slate-500">
                        Durable instructions, searchable references, and citation pressure.
                      </p>
                    </div>
                    <ShieldCheck className="h-5 w-5 text-cyan-400" />
                  </div>
                  <div className="mt-4 grid gap-3 sm:grid-cols-2">
                    <div className="rounded-2xl border border-slate-800 bg-slate-900/75 p-3">
                      <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">Mandates</p>
                      <p className="mt-2 text-sm text-slate-300">Always-on workflow rules with progressive injection.</p>
                    </div>
                    <div className="rounded-2xl border border-slate-800 bg-slate-900/75 p-3">
                      <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">References</p>
                      <p className="mt-2 text-sm text-slate-300">Searchable project knowledge with audience targeting.</p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="grid gap-4 lg:grid-cols-3">
          {FEATURE_CARDS.map(({ icon: Icon, title, copy }, index) => (
            <article
              key={title}
              className={`section-card animate-fade-up stagger-${index + 1} card-hover-lift`}
            >
              <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-amber-400/15 bg-slate-900/80 text-amber-300">
                <Icon className="h-5 w-5" />
              </div>
              <h2 className="mt-4 text-lg font-semibold text-slate-100">{title}</h2>
              <p className="mt-2 text-sm leading-6 text-slate-400">{copy}</p>
            </article>
          ))}
        </section>

        <section className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
          <div className="section-card">
            <p className="section-kicker">Why It Exists</p>
            <h2 className="mt-3 text-2xl font-semibold tracking-tight text-slate-100">
              Most agent stacks fail when the operational layer starts to matter.
            </h2>
            <p className="mt-3 text-sm leading-6 text-slate-400">
              Agent Hub is opinionated about the missing pieces: persistent
              memory, observable sessions, persona-level automation, and
              benchmark feedback that tells you when the system is drifting.
            </p>
            <div className="mt-5 grid gap-3">
              <div className="rounded-2xl border border-slate-800/80 bg-slate-950/70 px-4 py-4">
                <p className="text-sm font-semibold text-slate-100">One completion surface</p>
                <p className="mt-1 text-sm text-slate-400">Claude, Gemini, OpenAI, and OpenRouter through one API and one dashboard.</p>
              </div>
              <div className="rounded-2xl border border-slate-800/80 bg-slate-950/70 px-4 py-4">
                <p className="text-sm font-semibold text-slate-100">One memory model</p>
                <p className="mt-1 text-sm text-slate-400">Mandates, guardrails, and references live in the same system instead of scattered prompt files.</p>
              </div>
              <div className="rounded-2xl border border-slate-800/80 bg-slate-950/70 px-4 py-4">
                <p className="text-sm font-semibold text-slate-100">One operator loop</p>
                <p className="mt-1 text-sm text-slate-400">Sessions, benchmarks, and self-improvement signals share the same operational truth.</p>
              </div>
            </div>
          </div>

          <div className="section-card">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="section-kicker">Time To Value</p>
                <h2 className="mt-3 text-2xl font-semibold tracking-tight text-slate-100">
                  Go from clone to useful in three moves.
                </h2>
              </div>
              <Link href="/dashboard" className="button-secondary">
                Inspect live UI
                <ArrowRight className="h-4 w-4" />
              </Link>
            </div>

            <div className="mt-5 grid gap-4">
              {QUICKSTART_STEPS.map((step) => (
                <div key={step.label} className="rounded-2xl border border-slate-800/80 bg-slate-950/70 px-4 py-4">
                  <p className="text-sm font-semibold text-slate-100">{step.label}</p>
                  <p className="mt-1 text-sm leading-6 text-slate-400">{step.detail}</p>
                  <code className="mt-3 block overflow-x-auto rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-300">
                    {step.command}
                  </code>
                </div>
              ))}
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
