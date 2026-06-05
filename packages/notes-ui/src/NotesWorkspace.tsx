'use client';

import { NotesPanel } from './NotesPanel';
import { NotesProvider, useNotesContext } from './NotesProvider';

interface NotesWorkspaceProps {
    apiPrefix: string;
    projectScope: string;
}

function NotesWorkspaceShell() {
    const { projectScope, getScopeLabel } = useNotesContext();
    const scopeLabel = getScopeLabel(projectScope || 'global');

    return (
        <div className="relative flex h-screen flex-col overflow-hidden bg-[#05030b]">
            <div
                className="pointer-events-none absolute inset-0"
                style={{
                    background:
                        'radial-gradient(ellipse 80% 60% at 50% 0%, rgba(44,16,84,0.72) 0%, transparent 72%)',
                    opacity: 0.85,
                }}
            />
            <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(180deg,rgba(8,6,18,0.1),rgba(8,6,18,0.9))]" />

            <div className="relative z-10 flex items-center justify-between gap-3 px-4 py-3">
                <span className="rounded-full border border-slate-700/70 bg-slate-950/70 px-3 py-1 text-[10px] uppercase tracking-[0.18em] text-slate-300">
                    Notes
                </span>
                <span className="rounded-full border border-slate-700/70 bg-slate-950/70 px-3 py-1 text-[10px] uppercase tracking-[0.18em] text-slate-400">
                    project: {scopeLabel}
                </span>
            </div>

            <div className="relative z-10 flex-1 px-4 pb-4">
                <div className="h-full overflow-hidden rounded-[1.75rem] border border-slate-800/80 bg-[#0b0615]/80 shadow-[0_28px_80px_rgba(3,6,18,0.45)] backdrop-blur">
                    <NotesPanel />
                </div>
            </div>
        </div>
    );
}

export function NotesWorkspace({ apiPrefix, projectScope }: NotesWorkspaceProps) {
    return (
        <NotesProvider apiPrefix={apiPrefix} projectScope={projectScope || 'global'}>
            <NotesWorkspaceShell />
        </NotesProvider>
    );
}
