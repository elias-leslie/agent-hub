export interface Note {
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

export interface NoteListResponse {
    items: Note[];
    total: number;
}

export interface TagListResponse {
    tags: string[];
}

export interface CreateNoteData {
    title: string;
    content?: string;
    project_scope?: string;
    type?: 'note' | 'prompt';
    tags?: string[];
    pinned?: boolean;
    metadata?: Record<string, unknown>;
}

export interface UpdateNoteData {
    title?: string;
    content?: string;
    project_scope?: string;
    type?: 'note' | 'prompt';
    tags?: string[];
    pinned?: boolean;
    metadata?: Record<string, unknown>;
}

export interface NotesConfig {
    apiPrefix: string;
    projectScope: string;
    onInject?: (content: string) => void;
}

export interface NotesCapabilities {
    title_generation: boolean;
    formatting: boolean;
    prompt_refinement: boolean;
}

export interface NotesScopeOption {
    value: string;
    label: string;
    known: boolean;
}

export interface FormatProposal {
    id: string;
    note_id: string;
    status: 'pending' | 'complete' | 'failed' | 'accepted' | 'discarded';
    original_title: string;
    original_content: string;
    proposed_title: string | null;
    proposed_content: string | null;
    error_message: string | null;
    created_at: string | null;
    completed_at: string | null;
}

export interface NoteVersion {
    id: string;
    note_id: string;
    version: number;
    title: string;
    content: string;
    tags: string[];
    change_source: string;
    created_at: string | null;
}
