import { useState, useCallback, useRef } from 'react';
import { Copy, Check, Syringe, SendHorizontal, Loader2 } from 'lucide-react';
import clsx from 'clsx';
import { useNotesContext } from './NotesProvider';

interface PromptActionsProps {
    content: string;
    noteId: string;
    onRefineStarted?: () => void;
}

export function PromptActions({ content, noteId, onRefineStarted }: PromptActionsProps) {
    const { canInject, onInject, api, capabilities } = useNotesContext();
    const [copied, setCopied] = useState(false);
    const [instruction, setInstruction] = useState('');
    const [refining, setRefining] = useState(false);
    const inputRef = useRef<HTMLInputElement>(null);

    const handleCopy = useCallback(async () => {
        try {
            await navigator.clipboard.writeText(content);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        } catch { /* clipboard API may fail in non-secure context */ }
    }, [content]);

    const handleInject = useCallback(() => {
        onInject?.(content);
    }, [content, onInject]);

    const handleRefine = useCallback(async () => {
        if (!instruction.trim()) return;
        setRefining(true);
        try {
            await api.refinePrompt(noteId, content, instruction.trim());
            setInstruction('');
            onRefineStarted?.();
        } catch (err) {
            console.warn('Refine request failed:', err);
        } finally {
            setRefining(false);
        }
    }, [api, noteId, content, instruction, onRefineStarted]);

    const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleRefine();
        }
    }, [handleRefine]);

    return (
        <div className="border-t border-slate-700/60 bg-slate-950/60">
            {/* Refinement input */}
            {capabilities.prompt_refinement && (
                <div className="flex items-center gap-2 px-3 py-2">
                    <input
                        ref={inputRef}
                        value={instruction}
                        onChange={e => setInstruction(e.target.value)}
                        onKeyDown={handleKeyDown}
                        placeholder="Refine this prompt... (e.g. &quot;make it focus on error handling&quot;)"
                        disabled={refining}
                        className={clsx(
                            'flex-1 bg-slate-800/50 border border-slate-700/50 rounded-md px-3 py-1.5',
                            'text-xs text-slate-300 placeholder:text-slate-600',
                            'outline-none focus:border-[var(--color-phosphor-500,#00f5ff)]/40 focus:ring-1 focus:ring-[var(--color-phosphor-500,#00f5ff)]/15',
                            'transition-all',
                            refining && 'opacity-50',
                        )}
                    />
                    <button
                        type="button"
                        onClick={handleRefine}
                        disabled={refining || !instruction.trim()}
                        className={clsx(
                            'p-1.5 rounded-md transition-all duration-150',
                            refining ? 'text-amber-400' :
                            instruction.trim()
                                ? 'text-[var(--color-phosphor-400,#33f7ff)] hover:bg-[var(--color-phosphor-500,#00f5ff)]/10'
                                : 'text-slate-600 cursor-not-allowed',
                        )}
                        title="Send refinement"
                    >
                        {refining ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <SendHorizontal className="w-3.5 h-3.5" />}
                    </button>
                </div>
            )}

            {/* Action buttons */}
            <div className="flex items-center gap-2 px-3 pb-2.5">
                <button
                    type="button"
                    onClick={handleCopy}
                    className={clsx(
                        'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all duration-200 border',
                        copied
                            ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-400'
                            : 'border-slate-600 bg-slate-800/60 text-slate-300 hover:border-slate-500 hover:text-slate-100 hover:bg-slate-800',
                    )}
                >
                    {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
                    {copied ? 'Copied' : 'Copy'}
                </button>

                {canInject && (
                    <button
                        type="button"
                        onClick={handleInject}
                        className={clsx(
                            'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all duration-200',
                            'border border-[var(--color-phosphor-500,#00f5ff)]/30',
                            'bg-[var(--color-phosphor-500,#00f5ff)]/10 text-[var(--color-phosphor-400,#33f7ff)]',
                            'hover:bg-[var(--color-phosphor-500,#00f5ff)]/20 hover:border-[var(--color-phosphor-500,#00f5ff)]/50',
                        )}
                    >
                        <Syringe className="w-3 h-3" />
                        Inject
                    </button>
                )}
            </div>
        </div>
    );
}
