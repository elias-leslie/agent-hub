import * as react_jsx_runtime from 'react/jsx-runtime';
import { ReactNode } from 'react';

interface Note {
    id: string;
    project_scope: string;
    type: 'note' | 'prompt';
    title: string;
    content: string;
    tags: string[];
    pinned: boolean;
    metadata: Record<string, unknown>;
    created_at: string | null;
    updated_at: string | null;
}
interface NoteListResponse {
    items: Note[];
    total: number;
}
interface TagListResponse {
    tags: string[];
}
interface CreateNoteData {
    title: string;
    content?: string;
    project_scope?: string;
    type?: 'note' | 'prompt';
    tags?: string[];
    pinned?: boolean;
    metadata?: Record<string, unknown>;
}
interface UpdateNoteData {
    title?: string;
    content?: string;
    project_scope?: string;
    type?: 'note' | 'prompt';
    tags?: string[];
    pinned?: boolean;
    metadata?: Record<string, unknown>;
}
interface NotesConfig {
    apiPrefix: string;
    projectScope: string;
    onInject?: (content: string) => void;
}
interface NotesCapabilities {
    title_generation: boolean;
    formatting: boolean;
    prompt_refinement: boolean;
}
interface NotesScopeOption {
    value: string;
    label: string;
    known: boolean;
}

interface NotesProviderProps extends NotesConfig {
    children: ReactNode;
}
declare function NotesProvider({ apiPrefix, projectScope, onInject, children }: NotesProviderProps): react_jsx_runtime.JSX.Element;

declare function NotesButton({ className, popOutUrl }: {
    className?: string;
    popOutUrl?: string;
}): react_jsx_runtime.JSX.Element | null;

interface NotesPanelProps {
    onPopOut?: () => void;
}
declare function NotesPanel({ onPopOut }: NotesPanelProps): react_jsx_runtime.JSX.Element;

interface NotesWorkspaceProps {
    apiPrefix: string;
    projectScope: string;
}
declare function NotesWorkspace({ apiPrefix, projectScope }: NotesWorkspaceProps): react_jsx_runtime.JSX.Element;

export { type CreateNoteData, type Note, type NoteListResponse, NotesButton, type NotesCapabilities, type NotesConfig, NotesPanel, NotesProvider, type NotesScopeOption, NotesWorkspace, type TagListResponse, type UpdateNoteData };
