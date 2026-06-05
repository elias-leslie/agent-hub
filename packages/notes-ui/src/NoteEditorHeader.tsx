import { Pin, PinOff, Eye, Pencil, Trash2, Wand2, Loader2, History } from 'lucide-react';
import clsx from 'clsx';
import type { EditMode, SaveState } from './useNoteEditorState';
import type { FormatState } from './useFormatProposal';

interface NoteEditorHeaderProps {
    title: string;
    pinned: boolean;
    mode: EditMode;
    saveState: SaveState;
    formatState: FormatState;
    canFormat: boolean;
    contentLength: number;
    confirmDelete: boolean;
    onTitleChange: (val: string) => void;
    onStartFormat: () => void;
    onToggleHistory: () => void;
    onTogglePin: () => void;
    onSetMode: (m: EditMode) => void;
    onDelete: () => void;
}

export function NoteEditorHeader({
    title, pinned, mode, saveState, formatState, contentLength,
    canFormat,
    confirmDelete, onTitleChange, onStartFormat, onToggleHistory,
    onTogglePin, onSetMode, onDelete,
}: NoteEditorHeaderProps) {
    return (
        <div className="flex items-center gap-3 px-4 py-2.5 border-b border-slate-700/50">
            <input
                value={title}
                onChange={e => onTitleChange(e.target.value)}
                placeholder="Untitled"
                className="flex-1 bg-transparent text-slate-100 text-sm font-semibold placeholder:text-slate-600 outline-none min-w-0"
                style={{ fontFamily: 'var(--font-display, inherit)' }}
            />
            <div className="flex items-center gap-0.5 flex-shrink-0">
                {formatState === 'pending' && (
                    <span className="text-[10px] text-amber-400/80 tabular-nums mr-1.5 animate-pulse">formatting...</span>
                )}
                {formatState === 'failed' && (
                    <span className="text-[10px] text-rose-400/70 tabular-nums mr-1.5">format failed</span>
                )}
                {formatState !== 'pending' && saveState !== 'idle' && (
                    <span className={clsx(
                        'text-[10px] tabular-nums mr-1.5 transition-colors',
                        saveState === 'saving' ? 'text-slate-500' : 'text-emerald-400/80',
                    )}>
                        {saveState === 'saving' ? 'saving...' : 'saved'}
                    </span>
                )}
                {canFormat && (
                    <button type="button" onClick={onStartFormat}
                        disabled={formatState === 'pending' || contentLength < 50}
                        className={clsx(
                            'p-1.5 rounded-md transition-all duration-150',
                            formatState === 'pending' ? 'text-amber-400' :
                            'text-slate-500 hover:text-amber-400 hover:bg-slate-800 disabled:opacity-30 disabled:cursor-not-allowed',
                        )}
                        title="Format note (title + content cleanup)">
                        {formatState === 'pending' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Wand2 className="w-3.5 h-3.5" />}
                    </button>
                )}
                <button type="button" onClick={onToggleHistory}
                    className="p-1.5 rounded-md transition-all duration-150 text-slate-500 hover:text-[var(--color-phosphor-400,#33f7ff)] hover:bg-slate-800"
                    title="Version history">
                    <History className="w-3.5 h-3.5" />
                </button>
                <button type="button" onClick={onTogglePin}
                    className={clsx(
                        'p-1.5 rounded-md transition-all duration-150',
                        pinned ? 'text-[var(--color-phosphor-400,#33f7ff)] bg-[var(--color-phosphor-500,#00f5ff)]/10' : 'text-slate-500 hover:text-slate-300 hover:bg-slate-800',
                    )}
                    title={pinned ? 'Unpin' : 'Pin'}>
                    {pinned ? <Pin className="w-3.5 h-3.5 rotate-45" /> : <PinOff className="w-3.5 h-3.5" />}
                </button>
                <div className="flex items-center bg-slate-800 rounded-md border border-slate-700/60 ml-0.5">
                    <button type="button" onClick={() => onSetMode('edit')}
                        className={clsx('p-1.5 rounded-l-md transition-all duration-150', mode === 'edit' ? 'text-slate-100 bg-slate-700' : 'text-slate-500 hover:text-slate-300')}
                        title="Edit"><Pencil className="w-3 h-3" /></button>
                    <button type="button" onClick={() => onSetMode('preview')}
                        className={clsx('p-1.5 rounded-r-md transition-all duration-150', mode === 'preview' ? 'text-slate-100 bg-slate-700' : 'text-slate-500 hover:text-slate-300')}
                        title="Preview"><Eye className="w-3 h-3" /></button>
                </div>
                <button type="button" onClick={onDelete}
                    className={clsx('p-1.5 rounded-md transition-all duration-150 ml-0.5', confirmDelete ? 'text-rose-400 bg-rose-500/10 hover:text-rose-300' : 'text-slate-500 hover:text-slate-300 hover:bg-slate-800')}
                    title={confirmDelete ? 'Click again to confirm' : 'Delete'}>
                    <Trash2 className="w-3.5 h-3.5" />
                </button>
            </div>
        </div>
    );
}
