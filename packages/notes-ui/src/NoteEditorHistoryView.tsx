import { History, X, RotateCcw } from 'lucide-react';
import clsx from 'clsx';
import type { NoteVersion } from './types';

interface NoteEditorHistoryViewProps {
    versions: NoteVersion[];
    loadingVersions: boolean;
    versionError: string | null;
    onClose: () => void;
    onRevert: (versionId: string) => void;
}

function relativeTime(dateStr: string | null): string {
    if (!dateStr) return '';
    const diff = Date.now() - new Date(dateStr).getTime();
    const mins = Math.floor(diff / 60_000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    return `${Math.floor(hrs / 24)}d ago`;
}

function VersionItem({ v, onRevert }: { v: NoteVersion; onRevert: (id: string) => void }) {
    return (
        <div className="px-4 py-3 border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors group">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <span className="text-xs text-slate-300 font-medium">v{v.version}</span>
                    <span className="text-[10px] text-slate-600">{relativeTime(v.created_at)}</span>
                    <span className={clsx(
                        'text-[10px] px-1.5 py-0.5 rounded border',
                        v.change_source === 'format_accept' ? 'text-amber-400/70 border-amber-500/20 bg-amber-500/5' :
                        v.change_source === 'revert' ? 'text-[var(--color-phosphor-400,#33f7ff)]/70 border-[var(--color-phosphor-500,#00f5ff)]/20 bg-[var(--color-phosphor-500,#00f5ff)]/5' :
                        'text-slate-500 border-slate-700/50 bg-slate-800/30',
                    )}>
                        {v.change_source.replace('_', ' ')}
                    </span>
                </div>
                <button type="button" onClick={() => onRevert(v.id)}
                    className="opacity-0 group-hover:opacity-100 inline-flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium text-[var(--color-phosphor-400,#33f7ff)] border border-[var(--color-phosphor-500,#00f5ff)]/20 hover:bg-[var(--color-phosphor-500,#00f5ff)]/10 transition-all">
                    <RotateCcw className="w-2.5 h-2.5" /> Revert
                </button>
            </div>
            <p className="text-[11px] text-slate-400 mt-1 truncate">{v.title || 'Untitled'}</p>
            <p className="text-[10px] text-slate-600 mt-0.5 line-clamp-2">{v.content.substring(0, 150)}</p>
        </div>
    );
}

export function NoteEditorHistoryView({
    versions,
    loadingVersions,
    versionError,
    onClose,
    onRevert,
}: NoteEditorHistoryViewProps) {
    return (
        <div className="flex flex-col h-full min-w-0 bg-slate-900">
            <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-700/50">
                <div className="flex items-center gap-2">
                    <History className="w-3.5 h-3.5 text-[var(--color-phosphor-400,#33f7ff)]" />
                    <span className="text-xs font-medium text-slate-300">Version History</span>
                    <span className="text-[10px] text-slate-500">({versions.length})</span>
                </div>
                <button type="button" onClick={onClose} className="p-1 text-slate-500 hover:text-slate-300 rounded transition-colors">
                    <X className="w-3.5 h-3.5" />
                </button>
            </div>
            <div className="flex-1 overflow-y-auto">
                {loadingVersions && <div className="px-4 py-6 text-center text-xs text-slate-600">Loading...</div>}
                {!loadingVersions && versionError && (
                    <div className="px-4 py-6 text-center text-xs text-rose-400/80">
                        Unable to load versions
                    </div>
                )}
                {!loadingVersions && !versionError && versions.length === 0 && (
                    <div className="px-4 py-6 text-center text-xs text-slate-600">No versions yet</div>
                )}
                {!loadingVersions && versions.map(v => <VersionItem key={v.id} v={v} onRevert={onRevert} />)}
            </div>
        </div>
    );
}
