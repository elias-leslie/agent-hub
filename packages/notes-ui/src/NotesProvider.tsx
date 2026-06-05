import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { createNotesApi } from './api';
import type { NotesCapabilities, NotesConfig, NotesScopeOption } from './types';

interface NotesContextValue extends NotesConfig {
    api: ReturnType<typeof createNotesApi>;
    canInject: boolean;
    capabilities: NotesCapabilities;
    scopeOptions: NotesScopeOption[];
    getScopeLabel: (scope: string) => string;
}

const NotesContext = createContext<NotesContextValue | null>(null);

const DEFAULT_CAPABILITIES: NotesCapabilities = {
    title_generation: true,
    formatting: true,
    prompt_refinement: true,
};

export function useNotesContext(): NotesContextValue {
    const ctx = useContext(NotesContext);
    if (!ctx) throw new Error('useNotesContext must be used within NotesProvider');
    return ctx;
}

interface NotesProviderProps extends NotesConfig {
    children: ReactNode;
}

export function NotesProvider({ apiPrefix, projectScope, onInject, children }: NotesProviderProps) {
    const [capabilities, setCapabilities] = useState(DEFAULT_CAPABILITIES);
    const [scopeOptions, setScopeOptions] = useState<NotesScopeOption[]>([]);
    const api = useMemo(() => createNotesApi(apiPrefix), [apiPrefix]);

    useEffect(() => {
        let cancelled = false;
        api.capabilities()
            .then(next => {
                if (!cancelled) setCapabilities(next);
            })
            .catch(() => {
                if (!cancelled) setCapabilities(DEFAULT_CAPABILITIES);
            });
        return () => {
            cancelled = true;
        };
    }, [api]);

    useEffect(() => {
        let cancelled = false;
        api.scopes()
            .then(next => {
                if (!cancelled) setScopeOptions(next);
            })
            .catch(() => {
                if (!cancelled) setScopeOptions([]);
            });
        return () => {
            cancelled = true;
        };
    }, [api]);

    const value = useMemo<NotesContextValue>(() => ({
        apiPrefix,
        projectScope,
        onInject,
        canInject: typeof onInject === 'function',
        api,
        capabilities,
        scopeOptions,
        getScopeLabel: (scope: string) => {
            const option = scopeOptions.find(candidate => candidate.value === scope);
            return option?.label ?? scope;
        },
    }), [apiPrefix, api, capabilities, projectScope, onInject, scopeOptions]);

    return <NotesContext.Provider value={value}>{children}</NotesContext.Provider>;
}
