import { useState, useRef, useEffect, useCallback } from 'react';
import { useUpdateNote, useDeleteNote } from './useNotes';
import type { Note } from './types';

export type SaveState = 'idle' | 'saving' | 'saved';
export type EditMode = 'edit' | 'preview';

interface UseNoteEditorStateOptions {
    note: Note;
    onDeleted: () => void;
}

export interface NoteEditorState {
    pinned: boolean;
    title: string;
    setTitle: (v: string) => void;
    content: string;
    setContent: (v: string) => void;
    tags: string[];
    setTags: (v: string[]) => void;
    tagInput: string;
    setTagInput: (v: string) => void;
    mode: EditMode;
    setMode: (v: EditMode) => void;
    saveState: SaveState;
    setSaveState: (v: SaveState) => void;
    confirmDelete: boolean;
    autoFormatAttemptedRef: React.MutableRefObject<boolean>;
    mutateRef: React.MutableRefObject<ReturnType<typeof useUpdateNote>['mutate']>;
    save: (updates: { title?: string; content?: string; tags?: string[]; pinned?: boolean }) => void;
    handleTitleChange: (val: string) => void;
    handleContentChange: (val: string) => void;
    handleTagKeyDown: (e: React.KeyboardEvent<HTMLInputElement>) => void;
    removeTag: (tag: string) => void;
    togglePin: () => void;
    handleDelete: () => void;
}

export function useNoteEditorState({ note, onDeleted }: UseNoteEditorStateOptions): NoteEditorState {
    const [pinned, setPinned] = useState(note.pinned);
    const [title, setTitle] = useState(note.title);
    const [content, setContent] = useState(note.content);
    const [tags, setTags] = useState<string[]>(note.tags);
    const [tagInput, setTagInput] = useState('');
    const [mode, setMode] = useState<EditMode>('edit');
    const [saveState, setSaveState] = useState<SaveState>('idle');
    const [confirmDelete, setConfirmDelete] = useState(false);

    const autoFormatAttemptedRef = useRef(false);
    const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const pendingRef = useRef<{ noteId: string; data: Record<string, unknown> } | null>(null);

    const updateNote = useUpdateNote();
    const deleteNote = useDeleteNote();
    const mutateRef = useRef(updateNote.mutate);
    mutateRef.current = updateNote.mutate;

    // Reset state on note switch
    const prevIdRef = useRef(note.id);
    useEffect(() => {
        if (prevIdRef.current === note.id) return;
        if (debounceRef.current) { clearTimeout(debounceRef.current); debounceRef.current = null; }
        if (pendingRef.current) { mutateRef.current(pendingRef.current); pendingRef.current = null; }
        prevIdRef.current = note.id;
        setPinned(note.pinned);
        setTitle(note.title);
        setContent(note.content);
        setTags(note.tags);
        setTagInput('');
        setSaveState('idle');
        setConfirmDelete(false);
        autoFormatAttemptedRef.current = false;
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [note.id]);

    // Flush pending save on unmount
    useEffect(() => {
        return () => {
            if (debounceRef.current) clearTimeout(debounceRef.current);
            if (pendingRef.current) mutateRef.current(pendingRef.current);
        };
    }, []);

    const save = useCallback((updates: { title?: string; content?: string; tags?: string[]; pinned?: boolean }) => {
        if (debounceRef.current) clearTimeout(debounceRef.current);
        const payload = { noteId: note.id, data: updates };
        pendingRef.current = payload;
        debounceRef.current = setTimeout(() => {
            pendingRef.current = null;
            setSaveState('saving');
            mutateRef.current(payload, {
                onSuccess: () => { setSaveState('saved'); setTimeout(() => setSaveState('idle'), 1500); },
                onError: () => setSaveState('idle'),
            });
        }, 500);
    }, [note.id]);

    const handleTitleChange = (val: string) => {
        setTitle(val);
        save({ title: val });
        if (val.trim()) autoFormatAttemptedRef.current = true;
    };

    const handleContentChange = (val: string) => {
        setContent(val);
        save({ content: val });
    };

    const handleTagKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
        if ((e.key === 'Enter' || e.key === ',') && tagInput.trim()) {
            e.preventDefault();
            const tag = tagInput.trim().replace(/,/g, '');
            if (tag && !tags.includes(tag)) {
                const next = [...tags, tag];
                setTags(next);
                save({ tags: next });
            }
            setTagInput('');
        }
        if (e.key === 'Backspace' && !tagInput && tags.length > 0) {
            const next = tags.slice(0, -1);
            setTags(next);
            save({ tags: next });
        }
    };

    const removeTag = (tag: string) => {
        const next = tags.filter(t => t !== tag);
        setTags(next);
        save({ tags: next });
    };

    const togglePin = () => {
        const next = !pinned;
        setPinned(next);
        save({ pinned: next });
    };

    const handleDelete = () => {
        if (!confirmDelete) {
            setConfirmDelete(true);
            setTimeout(() => setConfirmDelete(false), 3000);
            return;
        }
        deleteNote.mutate(note.id, { onSuccess: onDeleted });
    };

    return {
        pinned,
        title, setTitle, content, setContent, tags, setTags,
        tagInput, setTagInput, mode, setMode,
        saveState, setSaveState, confirmDelete,
        autoFormatAttemptedRef, mutateRef,
        save, handleTitleChange, handleContentChange,
        handleTagKeyDown, removeTag, togglePin, handleDelete,
    };
}
