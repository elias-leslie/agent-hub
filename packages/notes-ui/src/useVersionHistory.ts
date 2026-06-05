import { useState, useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { NoteVersion } from './types';

interface UseVersionHistoryOptions {
    noteId: string;
    api: {
        listVersions: (noteId: string) => Promise<NoteVersion[]>;
        revertToVersion: (noteId: string, versionId: string) => Promise<{ title: string; content: string; tags: string[] }>;
    };
    onReverted: (title: string, content: string, tags: string[]) => void;
}

export interface VersionHistoryState {
    showHistory: boolean;
    versions: NoteVersion[];
    loadingVersions: boolean;
    versionError: string | null;
    toggleHistory: () => void;
    revertToVersion: (versionId: string) => Promise<void>;
    setShowHistory: (v: boolean) => void;
}

export function useVersionHistory({ noteId, api, onReverted }: UseVersionHistoryOptions): VersionHistoryState {
    const queryClient = useQueryClient();
    const [showHistory, setShowHistory] = useState(false);
    const [versions, setVersions] = useState<NoteVersion[]>([]);
    const [loadingVersions, setLoadingVersions] = useState(false);
    const [versionError, setVersionError] = useState<string | null>(null);

    const loadVersions = useCallback(async () => {
        setLoadingVersions(true);
        setVersionError(null);
        try {
            const v = await api.listVersions(noteId);
            setVersions(v);
        } catch (err) {
            setVersions([]);
            setVersionError(err instanceof Error ? err.message : 'Failed to load version history');
        } finally {
            setLoadingVersions(false);
        }
    }, [api, noteId]);

    const toggleHistory = useCallback(() => {
        if (!showHistory) void loadVersions();
        setShowHistory(v => !v);
    }, [showHistory, loadVersions]);

    const revertToVersion = useCallback(async (versionId: string) => {
        try {
            const reverted = await api.revertToVersion(noteId, versionId);
            await Promise.all([
                queryClient.invalidateQueries({ queryKey: ['notes'] }),
                queryClient.invalidateQueries({ queryKey: ['notes-tags'] }),
            ]);
            onReverted(reverted.title, reverted.content, reverted.tags);
            setShowHistory(false);
        } catch (err) {
            console.warn('Revert failed:', err);
        }
    }, [api, noteId, onReverted, queryClient]);

    return { showHistory, versions, loadingVersions, versionError, toggleHistory, revertToVersion, setShowHistory };
}
