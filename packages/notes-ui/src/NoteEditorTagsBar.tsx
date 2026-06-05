import { X } from 'lucide-react';

interface NoteEditorTagsBarProps {
    tags: string[];
    tagInput: string;
    onTagInputChange: (v: string) => void;
    onTagKeyDown: (e: React.KeyboardEvent<HTMLInputElement>) => void;
    onRemoveTag: (tag: string) => void;
}

export function NoteEditorTagsBar({ tags, tagInput, onTagInputChange, onTagKeyDown, onRemoveTag }: NoteEditorTagsBarProps) {
    return (
        <div className="flex items-center gap-1.5 px-4 py-2 border-b border-slate-800/50 overflow-x-auto scrollbar-none">
            {tags.map(tag => (
                <span key={tag} className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-800 text-slate-400 border border-slate-700/50 flex-shrink-0">
                    {tag}
                    <button type="button" onClick={() => onRemoveTag(tag)} className="hover:text-slate-200 transition-colors">
                        <X className="w-2.5 h-2.5" />
                    </button>
                </span>
            ))}
            <input
                value={tagInput}
                onChange={e => onTagInputChange(e.target.value)}
                onKeyDown={onTagKeyDown}
                placeholder={tags.length === 0 ? 'add tags...' : '+'}
                className="bg-transparent text-[10px] text-slate-500 placeholder:text-slate-700 outline-none min-w-[40px] flex-shrink-0"
            />
        </div>
    );
}
