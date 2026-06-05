import { StickyNote, Zap, Pin } from 'lucide-react';
import clsx from 'clsx';
import type { Note } from './types';

function relativeTime(dateStr: string | null): string {
    if (!dateStr) return '';
    const diff = Date.now() - new Date(dateStr).getTime();
    const mins = Math.floor(diff / 60_000);
    if (mins < 1) return 'now';
    if (mins < 60) return `${mins}m`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h`;
    const days = Math.floor(hrs / 24);
    return `${days}d`;
}

interface NoteItemProps {
    note: Note;
    selected: boolean;
    onClick: () => void;
}

export function NoteItem({ note, selected, onClick }: NoteItemProps) {
    const Icon = note.type === 'prompt' ? Zap : StickyNote;

    return (
        <button
            type="button"
            onClick={onClick}
            className={clsx(
                'w-full text-left px-3 py-2.5 transition-all duration-200 group',
                'border-l-2',
                selected
                    ? 'bg-slate-800/70 border-l-[var(--color-phosphor-500,#00f5ff)] shadow-[inset_0_0_20px_-10px_var(--color-phosphor-500,#00f5ff)]'
                    : 'border-transparent hover:bg-slate-800/40 hover:border-l-slate-600',
            )}
        >
            <div className="flex items-start gap-2 min-w-0">
                <Icon
                    className={clsx(
                        'w-3.5 h-3.5 mt-0.5 flex-shrink-0 transition-colors duration-150',
                        note.type === 'prompt'
                            ? 'text-amber-400/80'
                            : selected
                                ? 'text-[var(--color-phosphor-400,#33f7ff)]/70'
                                : 'text-slate-600 group-hover:text-slate-500',
                    )}
                />
                <div className="flex-1 min-w-0">
                    <div className="flex items-start gap-1.5">
                        <span
                            className={clsx(
                                'text-[11px] leading-snug transition-colors duration-200',
                                selected ? 'text-slate-100 font-medium' : 'text-slate-300 group-hover:text-slate-200',
                            )}
                            style={{ fontFamily: 'var(--font-display, inherit)' }}
                        >
                            {note.title || 'Untitled'}
                        </span>
                        {note.pinned && (
                            <Pin className="w-2.5 h-2.5 text-[var(--color-phosphor-500,#00f5ff)]/60 flex-shrink-0 rotate-45" />
                        )}
                    </div>
                    <div className="flex items-center gap-2 mt-0.5">
                        <span className={clsx(
                            'text-[10px] tabular-nums transition-colors',
                            selected ? 'text-slate-500' : 'text-slate-600',
                        )}>
                            {relativeTime(note.updated_at)}
                        </span>
                        {note.tags.length > 0 && (
                            <span className={clsx(
                                'text-[10px] truncate transition-colors',
                                selected ? 'text-slate-500' : 'text-slate-600',
                            )}>
                                {note.tags.slice(0, 2).join(', ')}
                                {note.tags.length > 2 && ` +${note.tags.length - 2}`}
                            </span>
                        )}
                    </div>
                </div>
            </div>
        </button>
    );
}
