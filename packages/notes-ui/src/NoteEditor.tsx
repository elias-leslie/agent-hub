import { useEffect } from 'react';
import { useNotesContext } from './NotesProvider';
import { PromptActions } from './PromptActions';
import { useNoteEditorState } from './useNoteEditorState';
import { useFormatProposal } from './useFormatProposal';
import { useVersionHistory } from './useVersionHistory';
import { NoteEditorHeader } from './NoteEditorHeader';
import { NoteEditorTagsBar } from './NoteEditorTagsBar';
import { NoteEditorContent } from './NoteEditorContent';
import { NoteEditorDiffView } from './NoteEditorDiffView';
import { NoteEditorHistoryView } from './NoteEditorHistoryView';
import type { Note } from './types';

interface NoteEditorProps {
    note: Note;
    onDeleted: () => void;
}

export function NoteEditor({ note, onDeleted }: NoteEditorProps) {
    const { api, capabilities } = useNotesContext();

    const editor = useNoteEditorState({ note, onDeleted });

    const format = useFormatProposal({
        noteId: note.id,
        api,
        onAccepted: (proposedTitle, proposedContent) => {
            if (proposedTitle) editor.setTitle(proposedTitle);
            if (proposedContent) editor.setContent(proposedContent);
            editor.autoFormatAttemptedRef.current = true;
            editor.setSaveState('saved');
            setTimeout(() => editor.setSaveState('idle'), 1500);
        },
    });

    const history = useVersionHistory({
        noteId: note.id,
        api,
        onReverted: (title, content, tags) => {
            editor.setTitle(title);
            editor.setContent(content);
            editor.setTags(tags);
            editor.setSaveState('saved');
            setTimeout(() => editor.setSaveState('idle'), 1500);
        },
    });

    // Check for existing pending/complete proposal on mount and when note changes
    useEffect(() => {
        format.setFormatState('idle');
        format.setProposal(null);
        format.stopPolling();
        history.setShowHistory(false);
        format.initProposal(note.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [note.id]);

    // Auto-title on load
    useEffect(() => {
        if (!capabilities.title_generation) return;
        const isUntitled = !note.title.trim() || note.title === 'Untitled';
        if (isUntitled && note.content.trim().length >= 50 && !editor.autoFormatAttemptedRef.current) {
            editor.autoFormatAttemptedRef.current = true;
            api.generateTitle(note.content).then(result => {
                if (result.title) {
                    editor.setTitle(result.title);
                    editor.mutateRef.current({ noteId: note.id, data: { title: result.title } });
                }
            }).catch(() => {});
        }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [capabilities.title_generation, note.id]);

    // Flush polling on unmount
    useEffect(() => {
        return () => { format.stopPolling(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    if (format.proposal && format.formatState === 'ready' &&
        (format.proposal.proposed_title || format.proposal.proposed_content)) {
        return (
            <NoteEditorDiffView
                proposal={format.proposal}
                currentTitle={editor.title}
                currentContent={editor.content}
                onAccept={format.acceptProposal}
                onDiscard={format.discardProposal}
            />
        );
    }

    if (history.showHistory) {
        return (
            <NoteEditorHistoryView
                versions={history.versions}
                loadingVersions={history.loadingVersions}
                versionError={history.versionError}
                onClose={() => history.setShowHistory(false)}
                onRevert={history.revertToVersion}
            />
        );
    }

    return (
        <div className="flex flex-col h-full min-w-0 bg-slate-900">
            <NoteEditorHeader
                title={editor.title}
                pinned={editor.pinned}
                mode={editor.mode}
                saveState={editor.saveState}
                formatState={format.formatState}
                canFormat={capabilities.formatting}
                contentLength={editor.content.trim().length}
                confirmDelete={editor.confirmDelete}
                onTitleChange={editor.handleTitleChange}
                onStartFormat={() => format.startFormat(editor.content, editor.title)}
                onToggleHistory={history.toggleHistory}
                onTogglePin={editor.togglePin}
                onSetMode={editor.setMode}
                onDelete={editor.handleDelete}
            />
            <NoteEditorTagsBar
                tags={editor.tags}
                tagInput={editor.tagInput}
                onTagInputChange={editor.setTagInput}
                onTagKeyDown={editor.handleTagKeyDown}
                onRemoveTag={editor.removeTag}
            />
            <NoteEditorContent
                mode={editor.mode}
                content={editor.content}
                onContentChange={editor.handleContentChange}
            />
            {note.type === 'prompt' && (
                <PromptActions
                    content={editor.content}
                    noteId={note.id}
                    onRefineStarted={() => {
                        format.setFormatState('pending');
                        format.startPolling(note.id);
                    }}
                />
            )}
        </div>
    );
}
