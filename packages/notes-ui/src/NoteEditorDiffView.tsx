import { Check, XCircle, Wand2 } from 'lucide-react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { FormatProposal } from './types';

interface NoteEditorDiffViewProps {
    proposal: FormatProposal;
    currentTitle: string;
    currentContent: string;
    onAccept: () => void;
    onDiscard: () => void;
}

export function NoteEditorDiffView({ proposal, currentTitle, currentContent, onAccept, onDiscard }: NoteEditorDiffViewProps) {
    const titleChanged = !!proposal.proposed_title && proposal.proposed_title !== currentTitle;
    const contentChanged = proposal.proposed_content !== currentContent;

    return (
        <div className="flex flex-col h-full min-w-0 bg-slate-900">
            <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-700/50">
                <div className="flex items-center gap-2">
                    <Wand2 className="w-3.5 h-3.5 text-amber-400" />
                    <span className="text-xs font-medium text-slate-300">Proposed Changes</span>
                </div>
                <div className="flex items-center gap-1.5">
                    <button type="button" onClick={onAccept}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/25 transition-colors">
                        <Check className="w-3 h-3" /> Accept
                    </button>
                    <button type="button" onClick={onDiscard}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium bg-slate-800 text-slate-400 border border-slate-700 hover:text-slate-300 transition-colors">
                        <XCircle className="w-3 h-3" /> Discard
                    </button>
                </div>
            </div>
            {titleChanged && (
                <div className="px-4 py-2 border-b border-slate-800/50">
                    <span className="text-[10px] text-slate-500 uppercase tracking-wider">Title</span>
                    <div className="flex gap-3 mt-1">
                        <div className="flex-1 min-w-0">
                            <span className="text-[10px] text-rose-400/70 block mb-0.5">Current</span>
                            <span className="text-sm text-slate-400 line-through">{currentTitle || 'Untitled'}</span>
                        </div>
                        <div className="flex-1 min-w-0">
                            <span className="text-[10px] text-emerald-400/70 block mb-0.5">Proposed</span>
                            <span className="text-sm text-slate-200 font-medium">{proposal.proposed_title}</span>
                        </div>
                    </div>
                </div>
            )}
            <div className="flex flex-1 min-h-0 overflow-hidden">
                <div className="flex-1 min-w-0 border-r border-slate-800/50 overflow-y-auto">
                    <div className="px-3 py-1.5 border-b border-slate-800/30 sticky top-0 bg-slate-900">
                        <span className="text-[10px] text-rose-400/70 uppercase tracking-wider">Current</span>
                    </div>
                    {contentChanged
                        ? <div className="px-3 py-2 text-xs text-slate-400 font-mono leading-relaxed whitespace-pre-wrap">{currentContent || '(empty)'}</div>
                        : <div className="px-3 py-4 text-center text-[11px] text-slate-600">Content unchanged</div>
                    }
                </div>
                <div className="flex-1 min-w-0 overflow-y-auto">
                    <div className="px-3 py-1.5 border-b border-slate-800/30 sticky top-0 bg-slate-900">
                        <span className="text-[10px] text-emerald-400/70 uppercase tracking-wider">Proposed</span>
                    </div>
                    {contentChanged
                        ? (
                            <div className="px-3 py-2 text-sm text-slate-300 prose prose-invert prose-sm max-w-none prose-headings:text-slate-200 prose-code:text-amber-300 prose-code:bg-slate-800 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-slate-950 prose-pre:border prose-pre:border-slate-700/50">
                                <Markdown remarkPlugins={[remarkGfm]}>{proposal.proposed_content ?? ''}</Markdown>
                            </div>
                        )
                        : <div className="px-3 py-4 text-center text-[11px] text-slate-600">Content unchanged</div>
                    }
                </div>
            </div>
        </div>
    );
}
