import { useState, useMemo } from 'react';
import { Search, Plus, StickyNote, Zap } from 'lucide-react';
import clsx from 'clsx';
import { useNotesList, useCreateNote, useNoteTags } from './useNotes';
import { useNotesContext } from './NotesProvider';
import { NoteItem } from './NoteItem';
import type { Note } from './types';

interface NotesListProps {
    activeTab: 'note' | 'prompt';
    scopeFilter: string | undefined;
    selectedId: string | null;
    onSelect: (note: Note) => void;
}

export function NotesList({ activeTab, scopeFilter, selectedId, onSelect }: NotesListProps) {
    const { projectScope } = useNotesContext();
    const [search, setSearch] = useState('');
    const [activeTag, setActiveTag] = useState<string | null>(null);

    const listOptions = useMemo(() => ({
        type: activeTab,
        project_scope: scopeFilter,
        search: search || undefined,
        tag: activeTag ? [activeTag] : undefined,
        limit: 100,
    }), [activeTab, scopeFilter, search, activeTag]);

    const { data, isLoading } = useNotesList(listOptions);
    const { data: tagsData } = useNoteTags(scopeFilter);
    const createNote = useCreateNote();

    const handleCreate = () => {
        createNote.mutate(
            {
                title: '',
                type: activeTab,
                project_scope: scopeFilter ?? projectScope ?? 'global',
            },
            {
                onSuccess: (note) => onSelect(note),
            },
        );
    };

    const items = data?.items ?? [];
    const allTags = tagsData?.tags ?? [];

    return (
        <div
            className="flex flex-col h-full border-r border-slate-700/50 bg-slate-950/40"
            style={{
                width: '30%',
                minWidth: 180,
                maxWidth: 280,
                backgroundColor: 'rgba(2, 6, 23, 0.55)',
                borderColor: 'rgba(51, 65, 85, 0.5)',
            }}
        >
            {/* Search */}
            <div className="px-2 pt-2 pb-1.5">
                <div className="relative">
                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3 h-3 text-slate-600 pointer-events-none" />
                    <input
                        value={search}
                        onChange={e => setSearch(e.target.value)}
                        placeholder="Search..."
                        className="w-full pl-8 pr-2 py-1.5 bg-slate-800/60 border border-slate-700/40 rounded-lg text-xs text-slate-300 placeholder:text-slate-600 outline-none focus:border-[var(--color-phosphor-500,#00f5ff)]/40 focus:ring-1 focus:ring-[var(--color-phosphor-500,#00f5ff)]/15 focus:shadow-[0_0_8px_-2px_var(--color-phosphor-500,#00f5ff)] transition-all"
                    />
                </div>
            </div>

            {/* Tag filter bar */}
            {allTags.length > 0 && (
                <div className="flex gap-1 px-2 pb-1.5 overflow-x-auto scrollbar-none">
                    {allTags.map(tag => (
                        <button
                            key={tag}
                            type="button"
                            onClick={() => setActiveTag(activeTag === tag ? null : tag)}
                            className={clsx(
                                'px-1.5 py-0.5 rounded text-[10px] font-medium flex-shrink-0 transition-colors border',
                                activeTag === tag
                                    ? 'bg-[var(--color-phosphor-500,#00f5ff)]/15 text-[var(--color-phosphor-400,#33f7ff)] border-[var(--color-phosphor-500,#00f5ff)]/30'
                                    : 'bg-slate-800/50 text-slate-500 border-slate-700/50 hover:text-slate-400 hover:border-slate-600',
                            )}
                        >
                            {tag}
                        </button>
                    ))}
                </div>
            )}

            {/* List */}
            <div className="flex-1 overflow-y-auto min-h-0">
                {isLoading ? (
                    <div className="px-3 py-6 text-center text-xs text-slate-600">Loading...</div>
                ) : items.length === 0 ? (
                    <div className="px-3 py-8 text-center">
                        {activeTab === 'prompt' ? (
                            <Zap className="w-4 h-4 text-slate-700 mx-auto mb-2" />
                        ) : (
                            <StickyNote className="w-4 h-4 text-slate-700 mx-auto mb-2" />
                        )}
                        <p className="text-[11px] text-slate-600">
                            {search ? 'No matches' : `No ${activeTab}s yet`}
                        </p>
                    </div>
                ) : (
                    items.map(note => (
                        <NoteItem
                            key={note.id}
                            note={note}
                            selected={note.id === selectedId}
                            onClick={() => onSelect(note)}
                        />
                    ))
                )}
            </div>

            {/* New button */}
            <div className="px-2 py-2.5 border-t border-slate-700/40">
                <button
                    type="button"
                    onClick={handleCreate}
                    disabled={createNote.isPending}
                    className={clsx(
                        'w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition-all duration-200',
                        'bg-slate-800/60 border border-slate-700/50 text-slate-400',
                        'hover:border-[var(--color-phosphor-500,#00f5ff)]/30 hover:text-[var(--color-phosphor-400,#33f7ff)] hover:bg-[var(--color-phosphor-500,#00f5ff)]/8 hover:shadow-[0_0_12px_-3px_var(--color-phosphor-500,#00f5ff)]',
                        createNote.isPending && 'opacity-50 cursor-wait',
                    )}
                >
                    <Plus className="w-3.5 h-3.5" />
                    New {activeTab === 'prompt' ? 'Prompt' : 'Note'}
                </button>
            </div>
        </div>
    );
}
