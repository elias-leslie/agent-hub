import { useState, useEffect, useCallback, useRef } from 'react';
import { createPortal } from 'react-dom';
import { StickyNote } from 'lucide-react';
import clsx from 'clsx';
import { useNotesContext } from './NotesProvider';
import { NotesPanel } from './NotesPanel';

const POPUP_FEATURES = 'width=700,height=800,menubar=no,toolbar=no,location=no,status=no';

export function NotesButton({ className, popOutUrl = '/notes' }: { className?: string; popOutUrl?: string }) {
    const { api } = useNotesContext();
    const [open, setOpen] = useState(false);
    const [available, setAvailable] = useState(true);
    const buttonRef = useRef<HTMLButtonElement>(null);
    const panelRef = useRef<HTMLDivElement>(null);
    const [panelStyle, setPanelStyle] = useState<React.CSSProperties>({});

    useEffect(() => {
        api.list({ limit: 1 })
            .then(() => setAvailable(true))
            .catch(() => setAvailable(false));
    }, [api]);

    // Position the portal panel relative to the button, adapting to its screen quadrant
    useEffect(() => {
        if (!open || !buttonRef.current) return;
        const rect = buttonRef.current.getBoundingClientRect();
        const vw = window.innerWidth;
        const vh = window.innerHeight;
        const GAP = 8;
        const PANEL_W = 700;
        const style: React.CSSProperties = { width: PANEL_W, zIndex: 9999 };

        // Vertical: open downward if button is in top half, upward if bottom half
        if (rect.top < vh / 2) {
            style.top = rect.bottom + GAP;
            style.height = `calc(100vh - ${rect.bottom + GAP + 16}px)`;
        } else {
            style.bottom = vh - rect.top + GAP;
            style.height = `calc(100vh - ${vh - rect.top + GAP + 16}px)`;
        }
        style.maxHeight = 900;

        // Horizontal: open leftward if button is on the right, rightward if on the left
        const leftOffset = rect.left < vw / 2 ? Math.max(rect.left, GAP) : null;
        if (leftOffset !== null) {
            style.left = leftOffset;
        } else {
            style.right = Math.max(vw - rect.right, GAP);
        }

        // Clamp panel width if it would overflow viewport
        if (leftOffset !== null && leftOffset + PANEL_W > vw - GAP) {
            style.width = vw - leftOffset - GAP;
        }

        setPanelStyle(style);
    }, [open]);

    // Close on click outside
    useEffect(() => {
        if (!open) return;
        const handler = (e: MouseEvent) => {
            const target = e.target as HTMLElement;
            if (
                buttonRef.current?.contains(target) ||
                panelRef.current?.contains(target)
            ) return;
            setOpen(false);
        };
        const timer = setTimeout(() => document.addEventListener('mousedown', handler), 0);
        return () => { clearTimeout(timer); document.removeEventListener('mousedown', handler); };
    }, [open]);

    // Close on Escape
    useEffect(() => {
        if (!open) return;
        const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
        window.addEventListener('keydown', handler);
        return () => window.removeEventListener('keydown', handler);
    }, [open]);

    const toggle = useCallback(() => setOpen(v => !v), []);

    const handlePopOut = useCallback(() => {
        window.open(popOutUrl, 'summitflow-notes', POPUP_FEATURES);
        setOpen(false);
    }, [popOutUrl]);

    if (!available) return null;

    return (
        <>
            {/* Icon button */}
            <button
                ref={buttonRef}
                type="button"
                onClick={toggle}
                className={clsx(
                    'relative p-2 rounded-lg transition-all duration-200',
                    'text-slate-400 hover:text-[var(--color-phosphor-400,#33f7ff)] hover:bg-slate-800/50',
                    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-phosphor-500,#00f5ff)]/40',
                    'active:bg-slate-800',
                    open && 'text-[var(--color-phosphor-400,#33f7ff)] bg-slate-800/50',
                    className,
                )}
                aria-label="Notes"
                aria-expanded={open}
                title="Notes"
            >
                <StickyNote className="w-4 h-4" />
                {open && (
                    <span className="absolute bottom-0 left-1/2 -translate-x-1/2 w-1 h-1 rounded-full bg-[var(--color-phosphor-500,#00f5ff)]" />
                )}
            </button>

            {/* Portal-mounted pop-down panel */}
            {open && createPortal(
                <div
                    ref={panelRef}
                    className={clsx(
                        'fixed flex flex-col bg-slate-900',
                        'border border-slate-700/70 rounded-lg',
                        'shadow-2xl shadow-black/60',
                        'overflow-hidden',
                    )}
                    style={{
                        ...panelStyle,
                        backgroundColor: '#0f172a',
                        borderColor: 'rgba(51, 65, 85, 0.7)',
                        boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.55)',
                    }}
                >
                    {/* Phosphor glow line */}
                    <div className="h-px w-full flex-shrink-0" style={{
                        background: 'linear-gradient(90deg, transparent 0%, var(--color-phosphor-500, #00f5ff) 30%, var(--color-phosphor-400, #33f7ff) 50%, var(--color-phosphor-500, #00f5ff) 70%, transparent 100%)',
                        opacity: 0.35,
                    }} />

                    <NotesPanel onPopOut={handlePopOut} />
                </div>,
                document.body,
            )}
        </>
    );
}
