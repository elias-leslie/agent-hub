import { useState, useRef, useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { FormatProposal } from './types';

export type FormatState = 'idle' | 'pending' | 'ready' | 'failed';

interface UseFormatProposalOptions {
    noteId: string;
    api: {
        getFormatProposal: (noteId: string) => Promise<FormatProposal | null>;
        startFormat: (noteId: string, content: string, title: string) => Promise<FormatProposal>;
        resolveProposal: (proposalId: string, action: 'accept' | 'discard') => Promise<void>;
    };
    onAccepted: (title: string | null, content: string | null) => void;
}

export interface FormatProposalState {
    formatState: FormatState;
    setFormatState: (v: FormatState) => void;
    proposal: FormatProposal | null;
    setProposal: (v: FormatProposal | null) => void;
    pollRef: React.MutableRefObject<ReturnType<typeof setInterval> | null>;
    startPolling: (noteId: string) => void;
    startFormat: (content: string, title: string) => Promise<void>;
    acceptProposal: () => Promise<void>;
    discardProposal: () => Promise<void>;
    initProposal: (noteId: string) => void;
    stopPolling: () => void;
}

export function useFormatProposal({ noteId, api, onAccepted }: UseFormatProposalOptions): FormatProposalState {
    const queryClient = useQueryClient();
    const [formatState, setFormatState] = useState<FormatState>('idle');
    const [proposal, setProposal] = useState<FormatProposal | null>(null);
    const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

    const stopPolling = useCallback(() => {
        if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    }, []);

    const startPolling = useCallback((id: string) => {
        stopPolling();
        pollRef.current = setInterval(async () => {
            try {
                const p = await api.getFormatProposal(id);
                if (!p || p.status === 'discarded' || p.status === 'accepted') {
                    setFormatState('idle');
                    setProposal(null);
                    stopPolling();
                } else if (p.status === 'complete') {
                    setProposal(p);
                    setFormatState('ready');
                    stopPolling();
                } else if (p.status === 'failed') {
                    setFormatState('failed');
                    setProposal(null);
                    stopPolling();
                }
            } catch {
                // keep polling
            }
        }, 2000);
    }, [api, stopPolling]);

    const initProposal = useCallback((id: string) => {
        api.getFormatProposal(id).then(p => {
            if (!p) return;
            if (p.status === 'complete') {
                setProposal(p);
                setFormatState('ready');
            } else if (p.status === 'pending') {
                setProposal(p);
                setFormatState('pending');
                startPolling(p.note_id);
            }
        }).catch(() => {});
    }, [api, startPolling]);

    const startFormat = useCallback(async (content: string, title: string) => {
        if (content.trim().length < 50) return;
        setFormatState('pending');
        try {
            const p = await api.startFormat(noteId, content, title);
            setProposal(p);
            startPolling(noteId);
        } catch (err) {
            console.warn('Format request failed:', err);
            setFormatState('failed');
        }
    }, [api, noteId, startPolling]);

    const acceptProposal = useCallback(async () => {
        if (!proposal || (!proposal.proposed_title && !proposal.proposed_content)) return;
        try {
            await api.resolveProposal(proposal.id, 'accept');
            await Promise.all([
                queryClient.invalidateQueries({ queryKey: ['notes'] }),
                queryClient.invalidateQueries({ queryKey: ['notes-tags'] }),
            ]);
            onAccepted(proposal.proposed_title, proposal.proposed_content);
            setProposal(null);
            setFormatState('idle');
        } catch (err) {
            console.warn('Accept proposal failed:', err);
        }
    }, [proposal, api, onAccepted, queryClient]);

    const discardProposal = useCallback(async () => {
        if (!proposal) return;
        try { await api.resolveProposal(proposal.id, 'discard'); } catch {}
        setProposal(null);
        setFormatState('idle');
    }, [proposal, api]);

    return {
        formatState, setFormatState,
        proposal, setProposal,
        pollRef, startPolling, stopPolling,
        startFormat, acceptProposal, discardProposal, initProposal,
    };
}
