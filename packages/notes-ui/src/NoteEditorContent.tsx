import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { EditMode } from './useNoteEditorState';

interface NoteEditorContentProps {
    mode: EditMode;
    content: string;
    onContentChange: (v: string) => void;
}

export function NoteEditorContent({ mode, content, onContentChange }: NoteEditorContentProps) {
    if (mode === 'edit') {
        return (
            <div className="flex-1 min-h-0 overflow-y-auto">
                <textarea
                    value={content}
                    onChange={e => onContentChange(e.target.value)}
                    placeholder="Write something..."
                    className="w-full h-full px-4 py-3 bg-transparent text-sm text-slate-300 placeholder:text-slate-700 outline-none resize-none font-mono leading-relaxed"
                    spellCheck={false}
                />
            </div>
        );
    }
    return (
        <div className="flex-1 min-h-0 overflow-y-auto">
            <div className="px-4 py-3 text-sm text-slate-300 prose prose-invert prose-sm max-w-none prose-headings:text-slate-200 prose-a:text-[var(--color-phosphor-400,#33f7ff)] prose-code:text-amber-300 prose-code:bg-slate-800 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-slate-950 prose-pre:border prose-pre:border-slate-700/50">
                {content
                    ? <Markdown remarkPlugins={[remarkGfm]}>{content}</Markdown>
                    : <p className="text-slate-600 italic">Nothing here yet.</p>
                }
            </div>
        </div>
    );
}
