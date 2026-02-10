import { useState } from "react";
import { Lightbulb, Plus, X } from "lucide-react";
import type { StickyNote } from "./types";
import { Section } from "./section";

interface StickyNotesSectionProps {
  stickyNotes: StickyNote[];
  onAddNote: (content: string) => void;
  onRemoveNote: (id: string) => void;
  isExpanded: boolean;
  onToggle: () => void;
}

export function StickyNotesSection({
  stickyNotes,
  onAddNote,
  onRemoveNote,
  isExpanded,
  onToggle,
}: StickyNotesSectionProps) {
  const [newNote, setNewNote] = useState("");

  const handleAddNote = () => {
    if (newNote.trim()) {
      onAddNote(newNote.trim());
      setNewNote("");
    }
  };

  return (
    <Section
      title="Sticky Notes"
      icon={<Lightbulb className="h-4 w-4" />}
      badge={stickyNotes.length}
      isExpanded={isExpanded}
      onToggle={onToggle}
      testId="context-section-notes"
    >
      <div className="space-y-2">
        <div className="flex gap-2">
          <input
            type="text"
            value={newNote}
            onChange={(e) => setNewNote(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleAddNote()}
            placeholder="Add a note..."
            className="flex-1 px-2 py-1 text-xs rounded border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800"
          />
          <button
            onClick={handleAddNote}
            disabled={!newNote.trim()}
            className="p-1 rounded bg-blue-500 text-white hover:bg-blue-600 disabled:opacity-50"
          >
            <Plus className="h-4 w-4" />
          </button>
        </div>

        {stickyNotes.map((note) => (
          <div
            key={note.id}
            className="flex items-start gap-2 p-2 rounded bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800"
          >
            <Lightbulb className="h-3 w-3 text-amber-500 mt-0.5 flex-shrink-0" />
            <p className="flex-1 text-xs text-amber-800 dark:text-amber-200">
              {note.content}
            </p>
            <button
              onClick={() => onRemoveNote(note.id)}
              className="p-0.5 rounded hover:bg-amber-200 dark:hover:bg-amber-800"
            >
              <X className="h-3 w-3 text-amber-600 dark:text-amber-400" />
            </button>
          </div>
        ))}
      </div>
    </Section>
  );
}
