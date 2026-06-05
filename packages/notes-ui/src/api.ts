import type {
    Note,
    NoteListResponse,
    CreateNoteData,
    UpdateNoteData,
    TagListResponse,
    FormatProposal,
    NoteVersion,
    NotesCapabilities,
    NotesScopeOption,
} from './types';

function buildQuery(params: Record<string, string | string[] | number | boolean | null | undefined>): string {
    const parts: string[] = [];
    for (const [key, value] of Object.entries(params)) {
        if (value === null || value === undefined) continue;
        if (Array.isArray(value)) {
            for (const v of value) parts.push(`${key}=${encodeURIComponent(v)}`);
        } else {
            parts.push(`${key}=${encodeURIComponent(String(value))}`);
        }
    }
    return parts.length ? `?${parts.join('&')}` : '';
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
    const res = await fetch(url, options);
    if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Request failed: ${res.status}`);
    }
    return res.json();
}

export function createNotesApi(apiPrefix: string) {
    const base = `${apiPrefix}/notes`;

    return {
        list(options?: {
            project_scope?: string;
            type?: string;
            tag?: string[];
            search?: string;
            pinned?: boolean;
            limit?: number;
            offset?: number;
        }): Promise<NoteListResponse> {
            const query = buildQuery(options ?? {});
            return request<NoteListResponse>(`${base}${query}`);
        },

        get(noteId: string): Promise<Note> {
            return request<Note>(`${base}/${noteId}`);
        },

        create(data: CreateNoteData): Promise<Note> {
            return request<Note>(base, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
            });
        },

        update(noteId: string, data: UpdateNoteData): Promise<Note> {
            return request<Note>(`${base}/${noteId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
            });
        },

        delete(noteId: string): Promise<{ deleted: boolean; id: string }> {
            return request<{ deleted: boolean; id: string }>(`${base}/${noteId}`, {
                method: 'DELETE',
            });
        },

        tags(projectScope?: string): Promise<TagListResponse> {
            const query = projectScope
                ? `?project_scope=${encodeURIComponent(projectScope)}`
                : '';
            return request<TagListResponse>(`${base}/tags${query}`);
        },

        capabilities(): Promise<NotesCapabilities> {
            return request<NotesCapabilities>(`${base}/capabilities`);
        },

        scopes(): Promise<NotesScopeOption[]> {
            return request<NotesScopeOption[]>(`${base}/scopes`);
        },

        generateTitle(content: string): Promise<{ title: string }> {
            return request<{ title: string }>(`${base}/generate-title`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content }),
            });
        },

        startFormat(noteId: string, content: string, currentTitle?: string): Promise<FormatProposal> {
            return request<FormatProposal>(`${base}/format`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ note_id: noteId, content, current_title: currentTitle ?? '' }),
            });
        },

        getFormatProposal(noteId: string): Promise<FormatProposal | null> {
            return fetch(`${base}/${noteId}/format-proposal`).then(res => {
                if (!res.ok) return null;
                return res.json().then((d: FormatProposal | null) => d);
            });
        },

        refinePrompt(noteId: string, currentContent: string, instruction: string): Promise<FormatProposal> {
            return request<FormatProposal>(`${base}/refine-prompt`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ note_id: noteId, current_content: currentContent, instruction }),
            });
        },

        resolveProposal(proposalId: string, action: 'accept' | 'discard'): Promise<{ resolved: boolean }> {
            return request<{ resolved: boolean }>(`${base}/format-proposals/${proposalId}/resolve`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action }),
            });
        },

        listVersions(noteId: string): Promise<NoteVersion[]> {
            return request<NoteVersion[]>(`${base}/${noteId}/versions`);
        },

        revertToVersion(noteId: string, versionId: string): Promise<Note> {
            return request<Note>(`${base}/${noteId}/revert/${versionId}`, { method: 'POST' });
        },
    };
}
