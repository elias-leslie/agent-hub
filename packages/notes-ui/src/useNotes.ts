import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNotesContext } from './NotesProvider';
import type { CreateNoteData, UpdateNoteData } from './types';

const NOTES_KEY = 'notes';
const TAGS_KEY = 'notes-tags';

export function useNotesList(options?: {
    project_scope?: string;
    type?: string;
    tag?: string[];
    search?: string;
    pinned?: boolean;
    limit?: number;
    offset?: number;
}) {
    const { api } = useNotesContext();
    return useQuery({
        queryKey: [NOTES_KEY, 'list', options],
        queryFn: () => api.list(options),
        staleTime: 5_000,
    });
}

export function useNote(noteId: string | null) {
    const { api } = useNotesContext();
    return useQuery({
        queryKey: [NOTES_KEY, 'detail', noteId],
        queryFn: () => api.get(noteId!),
        enabled: !!noteId,
    });
}

export function useCreateNote() {
    const { api } = useNotesContext();
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (data: CreateNoteData) => api.create(data),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: [NOTES_KEY] });
            qc.invalidateQueries({ queryKey: [TAGS_KEY] });
        },
    });
}

export function useUpdateNote() {
    const { api } = useNotesContext();
    const qc = useQueryClient();
    return useMutation({
        mutationFn: ({ noteId, data }: { noteId: string; data: UpdateNoteData }) =>
            api.update(noteId, data),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: [NOTES_KEY] });
            qc.invalidateQueries({ queryKey: [TAGS_KEY] });
        },
    });
}

export function useDeleteNote() {
    const { api } = useNotesContext();
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (noteId: string) => api.delete(noteId),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: [NOTES_KEY] });
            qc.invalidateQueries({ queryKey: [TAGS_KEY] });
        },
    });
}

export function useNoteTags(projectScope?: string) {
    const { api } = useNotesContext();
    return useQuery({
        queryKey: [TAGS_KEY, projectScope],
        queryFn: () => api.tags(projectScope),
        staleTime: 10_000,
    });
}
