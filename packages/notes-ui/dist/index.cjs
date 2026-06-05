"use strict";
"use client";
var __create = Object.create;
var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __getProtoOf = Object.getPrototypeOf;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, { get: all[name], enumerable: true });
};
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toESM = (mod, isNodeMode, target) => (target = mod != null ? __create(__getProtoOf(mod)) : {}, __copyProps(
  // If the importer is in node compatibility mode or this is not an ESM
  // file that has been converted to a CommonJS file using a Babel-
  // compatible transform (i.e. "__esModule" has not been set), then set
  // "default" to the CommonJS "module.exports" for node compatibility.
  isNodeMode || !mod || !mod.__esModule ? __defProp(target, "default", { value: mod, enumerable: true }) : target,
  mod
));
var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

// src/index.ts
var index_exports = {};
__export(index_exports, {
  NotesButton: () => NotesButton,
  NotesPanel: () => NotesPanel,
  NotesProvider: () => NotesProvider,
  NotesWorkspace: () => NotesWorkspace
});
module.exports = __toCommonJS(index_exports);

// src/NotesProvider.tsx
var import_react = require("react");

// src/api.ts
function buildQuery(params) {
  const parts = [];
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === void 0) continue;
    if (Array.isArray(value)) {
      for (const v of value) parts.push(`${key}=${encodeURIComponent(v)}`);
    } else {
      parts.push(`${key}=${encodeURIComponent(String(value))}`);
    }
  }
  return parts.length ? `?${parts.join("&")}` : "";
}
async function request(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed: ${res.status}`);
  }
  return res.json();
}
function createNotesApi(apiPrefix) {
  const base = `${apiPrefix}/notes`;
  return {
    list(options) {
      const query = buildQuery(options ?? {});
      return request(`${base}${query}`);
    },
    get(noteId) {
      return request(`${base}/${noteId}`);
    },
    create(data) {
      return request(base, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data)
      });
    },
    update(noteId, data) {
      return request(`${base}/${noteId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data)
      });
    },
    delete(noteId) {
      return request(`${base}/${noteId}`, {
        method: "DELETE"
      });
    },
    tags(projectScope) {
      const query = projectScope ? `?project_scope=${encodeURIComponent(projectScope)}` : "";
      return request(`${base}/tags${query}`);
    },
    capabilities() {
      return request(`${base}/capabilities`);
    },
    scopes() {
      return request(`${base}/scopes`);
    },
    generateTitle(content) {
      return request(`${base}/generate-title`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content })
      });
    },
    startFormat(noteId, content, currentTitle) {
      return request(`${base}/format`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note_id: noteId, content, current_title: currentTitle ?? "" })
      });
    },
    getFormatProposal(noteId) {
      return fetch(`${base}/${noteId}/format-proposal`).then((res) => {
        if (!res.ok) return null;
        return res.json().then((d) => d);
      });
    },
    refinePrompt(noteId, currentContent, instruction) {
      return request(`${base}/refine-prompt`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note_id: noteId, current_content: currentContent, instruction })
      });
    },
    resolveProposal(proposalId, action) {
      return request(`${base}/format-proposals/${proposalId}/resolve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action })
      });
    },
    listVersions(noteId) {
      return request(`${base}/${noteId}/versions`);
    },
    revertToVersion(noteId, versionId) {
      return request(`${base}/${noteId}/revert/${versionId}`, { method: "POST" });
    }
  };
}

// src/NotesProvider.tsx
var import_jsx_runtime = require("react/jsx-runtime");
var NotesContext = (0, import_react.createContext)(null);
var DEFAULT_CAPABILITIES = {
  title_generation: true,
  formatting: true,
  prompt_refinement: true
};
function useNotesContext() {
  const ctx = (0, import_react.useContext)(NotesContext);
  if (!ctx) throw new Error("useNotesContext must be used within NotesProvider");
  return ctx;
}
function NotesProvider({ apiPrefix, projectScope, onInject, children }) {
  const [capabilities, setCapabilities] = (0, import_react.useState)(DEFAULT_CAPABILITIES);
  const [scopeOptions, setScopeOptions] = (0, import_react.useState)([]);
  const api = (0, import_react.useMemo)(() => createNotesApi(apiPrefix), [apiPrefix]);
  (0, import_react.useEffect)(() => {
    let cancelled = false;
    api.capabilities().then((next) => {
      if (!cancelled) setCapabilities(next);
    }).catch(() => {
      if (!cancelled) setCapabilities(DEFAULT_CAPABILITIES);
    });
    return () => {
      cancelled = true;
    };
  }, [api]);
  (0, import_react.useEffect)(() => {
    let cancelled = false;
    api.scopes().then((next) => {
      if (!cancelled) setScopeOptions(next);
    }).catch(() => {
      if (!cancelled) setScopeOptions([]);
    });
    return () => {
      cancelled = true;
    };
  }, [api]);
  const value = (0, import_react.useMemo)(() => ({
    apiPrefix,
    projectScope,
    onInject,
    canInject: typeof onInject === "function",
    api,
    capabilities,
    scopeOptions,
    getScopeLabel: (scope) => {
      const option = scopeOptions.find((candidate) => candidate.value === scope);
      return option?.label ?? scope;
    }
  }), [apiPrefix, api, capabilities, projectScope, onInject, scopeOptions]);
  return /* @__PURE__ */ (0, import_jsx_runtime.jsx)(NotesContext.Provider, { value, children });
}

// src/NotesButton.tsx
var import_react9 = require("react");
var import_react_dom = require("react-dom");
var import_lucide_react9 = require("lucide-react");
var import_clsx7 = __toESM(require("clsx"), 1);

// src/NotesPanel.tsx
var import_react8 = require("react");
var import_lucide_react8 = require("lucide-react");
var import_clsx6 = __toESM(require("clsx"), 1);

// src/NotesList.tsx
var import_react2 = require("react");
var import_lucide_react2 = require("lucide-react");
var import_clsx2 = __toESM(require("clsx"), 1);

// src/useNotes.ts
var import_react_query = require("@tanstack/react-query");
var NOTES_KEY = "notes";
var TAGS_KEY = "notes-tags";
function useNotesList(options) {
  const { api } = useNotesContext();
  return (0, import_react_query.useQuery)({
    queryKey: [NOTES_KEY, "list", options],
    queryFn: () => api.list(options),
    staleTime: 5e3
  });
}
function useCreateNote() {
  const { api } = useNotesContext();
  const qc = (0, import_react_query.useQueryClient)();
  return (0, import_react_query.useMutation)({
    mutationFn: (data) => api.create(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [NOTES_KEY] });
      qc.invalidateQueries({ queryKey: [TAGS_KEY] });
    }
  });
}
function useUpdateNote() {
  const { api } = useNotesContext();
  const qc = (0, import_react_query.useQueryClient)();
  return (0, import_react_query.useMutation)({
    mutationFn: ({ noteId, data }) => api.update(noteId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [NOTES_KEY] });
      qc.invalidateQueries({ queryKey: [TAGS_KEY] });
    }
  });
}
function useDeleteNote() {
  const { api } = useNotesContext();
  const qc = (0, import_react_query.useQueryClient)();
  return (0, import_react_query.useMutation)({
    mutationFn: (noteId) => api.delete(noteId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [NOTES_KEY] });
      qc.invalidateQueries({ queryKey: [TAGS_KEY] });
    }
  });
}
function useNoteTags(projectScope) {
  const { api } = useNotesContext();
  return (0, import_react_query.useQuery)({
    queryKey: [TAGS_KEY, projectScope],
    queryFn: () => api.tags(projectScope),
    staleTime: 1e4
  });
}

// src/NoteItem.tsx
var import_lucide_react = require("lucide-react");
var import_clsx = __toESM(require("clsx"), 1);
var import_jsx_runtime2 = require("react/jsx-runtime");
function relativeTime(dateStr) {
  if (!dateStr) return "";
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 6e4);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  const days = Math.floor(hrs / 24);
  return `${days}d`;
}
function NoteItem({ note, selected, onClick }) {
  const Icon = note.type === "prompt" ? import_lucide_react.Zap : import_lucide_react.StickyNote;
  return /* @__PURE__ */ (0, import_jsx_runtime2.jsx)(
    "button",
    {
      type: "button",
      onClick,
      className: (0, import_clsx.default)(
        "w-full text-left px-3 py-2.5 transition-all duration-200 group",
        "border-l-2",
        selected ? "bg-slate-800/70 border-l-[var(--color-phosphor-500,#00f5ff)] shadow-[inset_0_0_20px_-10px_var(--color-phosphor-500,#00f5ff)]" : "border-transparent hover:bg-slate-800/40 hover:border-l-slate-600"
      ),
      children: /* @__PURE__ */ (0, import_jsx_runtime2.jsxs)("div", { className: "flex items-start gap-2 min-w-0", children: [
        /* @__PURE__ */ (0, import_jsx_runtime2.jsx)(
          Icon,
          {
            className: (0, import_clsx.default)(
              "w-3.5 h-3.5 mt-0.5 flex-shrink-0 transition-colors duration-150",
              note.type === "prompt" ? "text-amber-400/80" : selected ? "text-[var(--color-phosphor-400,#33f7ff)]/70" : "text-slate-600 group-hover:text-slate-500"
            )
          }
        ),
        /* @__PURE__ */ (0, import_jsx_runtime2.jsxs)("div", { className: "flex-1 min-w-0", children: [
          /* @__PURE__ */ (0, import_jsx_runtime2.jsxs)("div", { className: "flex items-start gap-1.5", children: [
            /* @__PURE__ */ (0, import_jsx_runtime2.jsx)(
              "span",
              {
                className: (0, import_clsx.default)(
                  "text-[11px] leading-snug transition-colors duration-200",
                  selected ? "text-slate-100 font-medium" : "text-slate-300 group-hover:text-slate-200"
                ),
                style: { fontFamily: "var(--font-display, inherit)" },
                children: note.title || "Untitled"
              }
            ),
            note.pinned && /* @__PURE__ */ (0, import_jsx_runtime2.jsx)(import_lucide_react.Pin, { className: "w-2.5 h-2.5 text-[var(--color-phosphor-500,#00f5ff)]/60 flex-shrink-0 rotate-45" })
          ] }),
          /* @__PURE__ */ (0, import_jsx_runtime2.jsxs)("div", { className: "flex items-center gap-2 mt-0.5", children: [
            /* @__PURE__ */ (0, import_jsx_runtime2.jsx)("span", { className: (0, import_clsx.default)(
              "text-[10px] tabular-nums transition-colors",
              selected ? "text-slate-500" : "text-slate-600"
            ), children: relativeTime(note.updated_at) }),
            note.tags.length > 0 && /* @__PURE__ */ (0, import_jsx_runtime2.jsxs)("span", { className: (0, import_clsx.default)(
              "text-[10px] truncate transition-colors",
              selected ? "text-slate-500" : "text-slate-600"
            ), children: [
              note.tags.slice(0, 2).join(", "),
              note.tags.length > 2 && ` +${note.tags.length - 2}`
            ] })
          ] })
        ] })
      ] })
    }
  );
}

// src/NotesList.tsx
var import_jsx_runtime3 = require("react/jsx-runtime");
function NotesList({ activeTab, scopeFilter, selectedId, onSelect }) {
  const { projectScope } = useNotesContext();
  const [search, setSearch] = (0, import_react2.useState)("");
  const [activeTag, setActiveTag] = (0, import_react2.useState)(null);
  const listOptions = (0, import_react2.useMemo)(() => ({
    type: activeTab,
    project_scope: scopeFilter,
    search: search || void 0,
    tag: activeTag ? [activeTag] : void 0,
    limit: 100
  }), [activeTab, scopeFilter, search, activeTag]);
  const { data, isLoading } = useNotesList(listOptions);
  const { data: tagsData } = useNoteTags(scopeFilter);
  const createNote = useCreateNote();
  const handleCreate = () => {
    createNote.mutate(
      {
        title: "",
        type: activeTab,
        project_scope: scopeFilter ?? projectScope ?? "global"
      },
      {
        onSuccess: (note) => onSelect(note)
      }
    );
  };
  const items = data?.items ?? [];
  const allTags = tagsData?.tags ?? [];
  return /* @__PURE__ */ (0, import_jsx_runtime3.jsxs)(
    "div",
    {
      className: "flex flex-col h-full border-r border-slate-700/50 bg-slate-950/40",
      style: {
        width: "30%",
        minWidth: 180,
        maxWidth: 280,
        backgroundColor: "rgba(2, 6, 23, 0.55)",
        borderColor: "rgba(51, 65, 85, 0.5)"
      },
      children: [
        /* @__PURE__ */ (0, import_jsx_runtime3.jsx)("div", { className: "px-2 pt-2 pb-1.5", children: /* @__PURE__ */ (0, import_jsx_runtime3.jsxs)("div", { className: "relative", children: [
          /* @__PURE__ */ (0, import_jsx_runtime3.jsx)(import_lucide_react2.Search, { className: "absolute left-2.5 top-1/2 -translate-y-1/2 w-3 h-3 text-slate-600 pointer-events-none" }),
          /* @__PURE__ */ (0, import_jsx_runtime3.jsx)(
            "input",
            {
              value: search,
              onChange: (e) => setSearch(e.target.value),
              placeholder: "Search...",
              className: "w-full pl-8 pr-2 py-1.5 bg-slate-800/60 border border-slate-700/40 rounded-lg text-xs text-slate-300 placeholder:text-slate-600 outline-none focus:border-[var(--color-phosphor-500,#00f5ff)]/40 focus:ring-1 focus:ring-[var(--color-phosphor-500,#00f5ff)]/15 focus:shadow-[0_0_8px_-2px_var(--color-phosphor-500,#00f5ff)] transition-all"
            }
          )
        ] }) }),
        allTags.length > 0 && /* @__PURE__ */ (0, import_jsx_runtime3.jsx)("div", { className: "flex gap-1 px-2 pb-1.5 overflow-x-auto scrollbar-none", children: allTags.map((tag) => /* @__PURE__ */ (0, import_jsx_runtime3.jsx)(
          "button",
          {
            type: "button",
            onClick: () => setActiveTag(activeTag === tag ? null : tag),
            className: (0, import_clsx2.default)(
              "px-1.5 py-0.5 rounded text-[10px] font-medium flex-shrink-0 transition-colors border",
              activeTag === tag ? "bg-[var(--color-phosphor-500,#00f5ff)]/15 text-[var(--color-phosphor-400,#33f7ff)] border-[var(--color-phosphor-500,#00f5ff)]/30" : "bg-slate-800/50 text-slate-500 border-slate-700/50 hover:text-slate-400 hover:border-slate-600"
            ),
            children: tag
          },
          tag
        )) }),
        /* @__PURE__ */ (0, import_jsx_runtime3.jsx)("div", { className: "flex-1 overflow-y-auto min-h-0", children: isLoading ? /* @__PURE__ */ (0, import_jsx_runtime3.jsx)("div", { className: "px-3 py-6 text-center text-xs text-slate-600", children: "Loading..." }) : items.length === 0 ? /* @__PURE__ */ (0, import_jsx_runtime3.jsxs)("div", { className: "px-3 py-8 text-center", children: [
          activeTab === "prompt" ? /* @__PURE__ */ (0, import_jsx_runtime3.jsx)(import_lucide_react2.Zap, { className: "w-4 h-4 text-slate-700 mx-auto mb-2" }) : /* @__PURE__ */ (0, import_jsx_runtime3.jsx)(import_lucide_react2.StickyNote, { className: "w-4 h-4 text-slate-700 mx-auto mb-2" }),
          /* @__PURE__ */ (0, import_jsx_runtime3.jsx)("p", { className: "text-[11px] text-slate-600", children: search ? "No matches" : `No ${activeTab}s yet` })
        ] }) : items.map((note) => /* @__PURE__ */ (0, import_jsx_runtime3.jsx)(
          NoteItem,
          {
            note,
            selected: note.id === selectedId,
            onClick: () => onSelect(note)
          },
          note.id
        )) }),
        /* @__PURE__ */ (0, import_jsx_runtime3.jsx)("div", { className: "px-2 py-2.5 border-t border-slate-700/40", children: /* @__PURE__ */ (0, import_jsx_runtime3.jsxs)(
          "button",
          {
            type: "button",
            onClick: handleCreate,
            disabled: createNote.isPending,
            className: (0, import_clsx2.default)(
              "w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition-all duration-200",
              "bg-slate-800/60 border border-slate-700/50 text-slate-400",
              "hover:border-[var(--color-phosphor-500,#00f5ff)]/30 hover:text-[var(--color-phosphor-400,#33f7ff)] hover:bg-[var(--color-phosphor-500,#00f5ff)]/8 hover:shadow-[0_0_12px_-3px_var(--color-phosphor-500,#00f5ff)]",
              createNote.isPending && "opacity-50 cursor-wait"
            ),
            children: [
              /* @__PURE__ */ (0, import_jsx_runtime3.jsx)(import_lucide_react2.Plus, { className: "w-3.5 h-3.5" }),
              "New ",
              activeTab === "prompt" ? "Prompt" : "Note"
            ]
          }
        ) })
      ]
    }
  );
}

// src/NoteEditor.tsx
var import_react7 = require("react");

// src/PromptActions.tsx
var import_react3 = require("react");
var import_lucide_react3 = require("lucide-react");
var import_clsx3 = __toESM(require("clsx"), 1);
var import_jsx_runtime4 = require("react/jsx-runtime");
function PromptActions({ content, noteId, onRefineStarted }) {
  const { canInject, onInject, api, capabilities } = useNotesContext();
  const [copied, setCopied] = (0, import_react3.useState)(false);
  const [instruction, setInstruction] = (0, import_react3.useState)("");
  const [refining, setRefining] = (0, import_react3.useState)(false);
  const inputRef = (0, import_react3.useRef)(null);
  const handleCopy = (0, import_react3.useCallback)(async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2e3);
    } catch {
    }
  }, [content]);
  const handleInject = (0, import_react3.useCallback)(() => {
    onInject?.(content);
  }, [content, onInject]);
  const handleRefine = (0, import_react3.useCallback)(async () => {
    if (!instruction.trim()) return;
    setRefining(true);
    try {
      await api.refinePrompt(noteId, content, instruction.trim());
      setInstruction("");
      onRefineStarted?.();
    } catch (err) {
      console.warn("Refine request failed:", err);
    } finally {
      setRefining(false);
    }
  }, [api, noteId, content, instruction, onRefineStarted]);
  const handleKeyDown = (0, import_react3.useCallback)((e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleRefine();
    }
  }, [handleRefine]);
  return /* @__PURE__ */ (0, import_jsx_runtime4.jsxs)("div", { className: "border-t border-slate-700/60 bg-slate-950/60", children: [
    capabilities.prompt_refinement && /* @__PURE__ */ (0, import_jsx_runtime4.jsxs)("div", { className: "flex items-center gap-2 px-3 py-2", children: [
      /* @__PURE__ */ (0, import_jsx_runtime4.jsx)(
        "input",
        {
          ref: inputRef,
          value: instruction,
          onChange: (e) => setInstruction(e.target.value),
          onKeyDown: handleKeyDown,
          placeholder: 'Refine this prompt... (e.g. "make it focus on error handling")',
          disabled: refining,
          className: (0, import_clsx3.default)(
            "flex-1 bg-slate-800/50 border border-slate-700/50 rounded-md px-3 py-1.5",
            "text-xs text-slate-300 placeholder:text-slate-600",
            "outline-none focus:border-[var(--color-phosphor-500,#00f5ff)]/40 focus:ring-1 focus:ring-[var(--color-phosphor-500,#00f5ff)]/15",
            "transition-all",
            refining && "opacity-50"
          )
        }
      ),
      /* @__PURE__ */ (0, import_jsx_runtime4.jsx)(
        "button",
        {
          type: "button",
          onClick: handleRefine,
          disabled: refining || !instruction.trim(),
          className: (0, import_clsx3.default)(
            "p-1.5 rounded-md transition-all duration-150",
            refining ? "text-amber-400" : instruction.trim() ? "text-[var(--color-phosphor-400,#33f7ff)] hover:bg-[var(--color-phosphor-500,#00f5ff)]/10" : "text-slate-600 cursor-not-allowed"
          ),
          title: "Send refinement",
          children: refining ? /* @__PURE__ */ (0, import_jsx_runtime4.jsx)(import_lucide_react3.Loader2, { className: "w-3.5 h-3.5 animate-spin" }) : /* @__PURE__ */ (0, import_jsx_runtime4.jsx)(import_lucide_react3.SendHorizontal, { className: "w-3.5 h-3.5" })
        }
      )
    ] }),
    /* @__PURE__ */ (0, import_jsx_runtime4.jsxs)("div", { className: "flex items-center gap-2 px-3 pb-2.5", children: [
      /* @__PURE__ */ (0, import_jsx_runtime4.jsxs)(
        "button",
        {
          type: "button",
          onClick: handleCopy,
          className: (0, import_clsx3.default)(
            "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all duration-200 border",
            copied ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-400" : "border-slate-600 bg-slate-800/60 text-slate-300 hover:border-slate-500 hover:text-slate-100 hover:bg-slate-800"
          ),
          children: [
            copied ? /* @__PURE__ */ (0, import_jsx_runtime4.jsx)(import_lucide_react3.Check, { className: "w-3 h-3" }) : /* @__PURE__ */ (0, import_jsx_runtime4.jsx)(import_lucide_react3.Copy, { className: "w-3 h-3" }),
            copied ? "Copied" : "Copy"
          ]
        }
      ),
      canInject && /* @__PURE__ */ (0, import_jsx_runtime4.jsxs)(
        "button",
        {
          type: "button",
          onClick: handleInject,
          className: (0, import_clsx3.default)(
            "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all duration-200",
            "border border-[var(--color-phosphor-500,#00f5ff)]/30",
            "bg-[var(--color-phosphor-500,#00f5ff)]/10 text-[var(--color-phosphor-400,#33f7ff)]",
            "hover:bg-[var(--color-phosphor-500,#00f5ff)]/20 hover:border-[var(--color-phosphor-500,#00f5ff)]/50"
          ),
          children: [
            /* @__PURE__ */ (0, import_jsx_runtime4.jsx)(import_lucide_react3.Syringe, { className: "w-3 h-3" }),
            "Inject"
          ]
        }
      )
    ] })
  ] });
}

// src/useNoteEditorState.ts
var import_react4 = require("react");
function useNoteEditorState({ note, onDeleted }) {
  const [pinned, setPinned] = (0, import_react4.useState)(note.pinned);
  const [title, setTitle] = (0, import_react4.useState)(note.title);
  const [content, setContent] = (0, import_react4.useState)(note.content);
  const [tags, setTags] = (0, import_react4.useState)(note.tags);
  const [tagInput, setTagInput] = (0, import_react4.useState)("");
  const [mode, setMode] = (0, import_react4.useState)("edit");
  const [saveState, setSaveState] = (0, import_react4.useState)("idle");
  const [confirmDelete, setConfirmDelete] = (0, import_react4.useState)(false);
  const autoFormatAttemptedRef = (0, import_react4.useRef)(false);
  const debounceRef = (0, import_react4.useRef)(null);
  const pendingRef = (0, import_react4.useRef)(null);
  const updateNote = useUpdateNote();
  const deleteNote = useDeleteNote();
  const mutateRef = (0, import_react4.useRef)(updateNote.mutate);
  mutateRef.current = updateNote.mutate;
  const prevIdRef = (0, import_react4.useRef)(note.id);
  (0, import_react4.useEffect)(() => {
    if (prevIdRef.current === note.id) return;
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
      debounceRef.current = null;
    }
    if (pendingRef.current) {
      mutateRef.current(pendingRef.current);
      pendingRef.current = null;
    }
    prevIdRef.current = note.id;
    setPinned(note.pinned);
    setTitle(note.title);
    setContent(note.content);
    setTags(note.tags);
    setTagInput("");
    setSaveState("idle");
    setConfirmDelete(false);
    autoFormatAttemptedRef.current = false;
  }, [note.id]);
  (0, import_react4.useEffect)(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      if (pendingRef.current) mutateRef.current(pendingRef.current);
    };
  }, []);
  const save = (0, import_react4.useCallback)((updates) => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    const payload = { noteId: note.id, data: updates };
    pendingRef.current = payload;
    debounceRef.current = setTimeout(() => {
      pendingRef.current = null;
      setSaveState("saving");
      mutateRef.current(payload, {
        onSuccess: () => {
          setSaveState("saved");
          setTimeout(() => setSaveState("idle"), 1500);
        },
        onError: () => setSaveState("idle")
      });
    }, 500);
  }, [note.id]);
  const handleTitleChange = (val) => {
    setTitle(val);
    save({ title: val });
    if (val.trim()) autoFormatAttemptedRef.current = true;
  };
  const handleContentChange = (val) => {
    setContent(val);
    save({ content: val });
  };
  const handleTagKeyDown = (e) => {
    if ((e.key === "Enter" || e.key === ",") && tagInput.trim()) {
      e.preventDefault();
      const tag = tagInput.trim().replace(/,/g, "");
      if (tag && !tags.includes(tag)) {
        const next = [...tags, tag];
        setTags(next);
        save({ tags: next });
      }
      setTagInput("");
    }
    if (e.key === "Backspace" && !tagInput && tags.length > 0) {
      const next = tags.slice(0, -1);
      setTags(next);
      save({ tags: next });
    }
  };
  const removeTag = (tag) => {
    const next = tags.filter((t) => t !== tag);
    setTags(next);
    save({ tags: next });
  };
  const togglePin = () => {
    const next = !pinned;
    setPinned(next);
    save({ pinned: next });
  };
  const handleDelete = () => {
    if (!confirmDelete) {
      setConfirmDelete(true);
      setTimeout(() => setConfirmDelete(false), 3e3);
      return;
    }
    deleteNote.mutate(note.id, { onSuccess: onDeleted });
  };
  return {
    pinned,
    title,
    setTitle,
    content,
    setContent,
    tags,
    setTags,
    tagInput,
    setTagInput,
    mode,
    setMode,
    saveState,
    setSaveState,
    confirmDelete,
    autoFormatAttemptedRef,
    mutateRef,
    save,
    handleTitleChange,
    handleContentChange,
    handleTagKeyDown,
    removeTag,
    togglePin,
    handleDelete
  };
}

// src/useFormatProposal.ts
var import_react5 = require("react");
var import_react_query2 = require("@tanstack/react-query");
function useFormatProposal({ noteId, api, onAccepted }) {
  const queryClient = (0, import_react_query2.useQueryClient)();
  const [formatState, setFormatState] = (0, import_react5.useState)("idle");
  const [proposal, setProposal] = (0, import_react5.useState)(null);
  const pollRef = (0, import_react5.useRef)(null);
  const stopPolling = (0, import_react5.useCallback)(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);
  const startPolling = (0, import_react5.useCallback)((id) => {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const p = await api.getFormatProposal(id);
        if (!p || p.status === "discarded" || p.status === "accepted") {
          setFormatState("idle");
          setProposal(null);
          stopPolling();
        } else if (p.status === "complete") {
          setProposal(p);
          setFormatState("ready");
          stopPolling();
        } else if (p.status === "failed") {
          setFormatState("failed");
          setProposal(null);
          stopPolling();
        }
      } catch {
      }
    }, 2e3);
  }, [api, stopPolling]);
  const initProposal = (0, import_react5.useCallback)((id) => {
    api.getFormatProposal(id).then((p) => {
      if (!p) return;
      if (p.status === "complete") {
        setProposal(p);
        setFormatState("ready");
      } else if (p.status === "pending") {
        setProposal(p);
        setFormatState("pending");
        startPolling(p.note_id);
      }
    }).catch(() => {
    });
  }, [api, startPolling]);
  const startFormat = (0, import_react5.useCallback)(async (content, title) => {
    if (content.trim().length < 50) return;
    setFormatState("pending");
    try {
      const p = await api.startFormat(noteId, content, title);
      setProposal(p);
      startPolling(noteId);
    } catch (err) {
      console.warn("Format request failed:", err);
      setFormatState("failed");
    }
  }, [api, noteId, startPolling]);
  const acceptProposal = (0, import_react5.useCallback)(async () => {
    if (!proposal || !proposal.proposed_title && !proposal.proposed_content) return;
    try {
      await api.resolveProposal(proposal.id, "accept");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["notes"] }),
        queryClient.invalidateQueries({ queryKey: ["notes-tags"] })
      ]);
      onAccepted(proposal.proposed_title, proposal.proposed_content);
      setProposal(null);
      setFormatState("idle");
    } catch (err) {
      console.warn("Accept proposal failed:", err);
    }
  }, [proposal, api, onAccepted, queryClient]);
  const discardProposal = (0, import_react5.useCallback)(async () => {
    if (!proposal) return;
    try {
      await api.resolveProposal(proposal.id, "discard");
    } catch {
    }
    setProposal(null);
    setFormatState("idle");
  }, [proposal, api]);
  return {
    formatState,
    setFormatState,
    proposal,
    setProposal,
    pollRef,
    startPolling,
    stopPolling,
    startFormat,
    acceptProposal,
    discardProposal,
    initProposal
  };
}

// src/useVersionHistory.ts
var import_react6 = require("react");
var import_react_query3 = require("@tanstack/react-query");
function useVersionHistory({ noteId, api, onReverted }) {
  const queryClient = (0, import_react_query3.useQueryClient)();
  const [showHistory, setShowHistory] = (0, import_react6.useState)(false);
  const [versions, setVersions] = (0, import_react6.useState)([]);
  const [loadingVersions, setLoadingVersions] = (0, import_react6.useState)(false);
  const [versionError, setVersionError] = (0, import_react6.useState)(null);
  const loadVersions = (0, import_react6.useCallback)(async () => {
    setLoadingVersions(true);
    setVersionError(null);
    try {
      const v = await api.listVersions(noteId);
      setVersions(v);
    } catch (err) {
      setVersions([]);
      setVersionError(err instanceof Error ? err.message : "Failed to load version history");
    } finally {
      setLoadingVersions(false);
    }
  }, [api, noteId]);
  const toggleHistory = (0, import_react6.useCallback)(() => {
    if (!showHistory) void loadVersions();
    setShowHistory((v) => !v);
  }, [showHistory, loadVersions]);
  const revertToVersion = (0, import_react6.useCallback)(async (versionId) => {
    try {
      const reverted = await api.revertToVersion(noteId, versionId);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["notes"] }),
        queryClient.invalidateQueries({ queryKey: ["notes-tags"] })
      ]);
      onReverted(reverted.title, reverted.content, reverted.tags);
      setShowHistory(false);
    } catch (err) {
      console.warn("Revert failed:", err);
    }
  }, [api, noteId, onReverted, queryClient]);
  return { showHistory, versions, loadingVersions, versionError, toggleHistory, revertToVersion, setShowHistory };
}

// src/NoteEditorHeader.tsx
var import_lucide_react4 = require("lucide-react");
var import_clsx4 = __toESM(require("clsx"), 1);
var import_jsx_runtime5 = require("react/jsx-runtime");
function NoteEditorHeader({
  title,
  pinned,
  mode,
  saveState,
  formatState,
  contentLength,
  canFormat,
  confirmDelete,
  onTitleChange,
  onStartFormat,
  onToggleHistory,
  onTogglePin,
  onSetMode,
  onDelete
}) {
  return /* @__PURE__ */ (0, import_jsx_runtime5.jsxs)("div", { className: "flex items-center gap-3 px-4 py-2.5 border-b border-slate-700/50", children: [
    /* @__PURE__ */ (0, import_jsx_runtime5.jsx)(
      "input",
      {
        value: title,
        onChange: (e) => onTitleChange(e.target.value),
        placeholder: "Untitled",
        className: "flex-1 bg-transparent text-slate-100 text-sm font-semibold placeholder:text-slate-600 outline-none min-w-0",
        style: { fontFamily: "var(--font-display, inherit)" }
      }
    ),
    /* @__PURE__ */ (0, import_jsx_runtime5.jsxs)("div", { className: "flex items-center gap-0.5 flex-shrink-0", children: [
      formatState === "pending" && /* @__PURE__ */ (0, import_jsx_runtime5.jsx)("span", { className: "text-[10px] text-amber-400/80 tabular-nums mr-1.5 animate-pulse", children: "formatting..." }),
      formatState === "failed" && /* @__PURE__ */ (0, import_jsx_runtime5.jsx)("span", { className: "text-[10px] text-rose-400/70 tabular-nums mr-1.5", children: "format failed" }),
      formatState !== "pending" && saveState !== "idle" && /* @__PURE__ */ (0, import_jsx_runtime5.jsx)("span", { className: (0, import_clsx4.default)(
        "text-[10px] tabular-nums mr-1.5 transition-colors",
        saveState === "saving" ? "text-slate-500" : "text-emerald-400/80"
      ), children: saveState === "saving" ? "saving..." : "saved" }),
      canFormat && /* @__PURE__ */ (0, import_jsx_runtime5.jsx)(
        "button",
        {
          type: "button",
          onClick: onStartFormat,
          disabled: formatState === "pending" || contentLength < 50,
          className: (0, import_clsx4.default)(
            "p-1.5 rounded-md transition-all duration-150",
            formatState === "pending" ? "text-amber-400" : "text-slate-500 hover:text-amber-400 hover:bg-slate-800 disabled:opacity-30 disabled:cursor-not-allowed"
          ),
          title: "Format note (title + content cleanup)",
          children: formatState === "pending" ? /* @__PURE__ */ (0, import_jsx_runtime5.jsx)(import_lucide_react4.Loader2, { className: "w-3.5 h-3.5 animate-spin" }) : /* @__PURE__ */ (0, import_jsx_runtime5.jsx)(import_lucide_react4.Wand2, { className: "w-3.5 h-3.5" })
        }
      ),
      /* @__PURE__ */ (0, import_jsx_runtime5.jsx)(
        "button",
        {
          type: "button",
          onClick: onToggleHistory,
          className: "p-1.5 rounded-md transition-all duration-150 text-slate-500 hover:text-[var(--color-phosphor-400,#33f7ff)] hover:bg-slate-800",
          title: "Version history",
          children: /* @__PURE__ */ (0, import_jsx_runtime5.jsx)(import_lucide_react4.History, { className: "w-3.5 h-3.5" })
        }
      ),
      /* @__PURE__ */ (0, import_jsx_runtime5.jsx)(
        "button",
        {
          type: "button",
          onClick: onTogglePin,
          className: (0, import_clsx4.default)(
            "p-1.5 rounded-md transition-all duration-150",
            pinned ? "text-[var(--color-phosphor-400,#33f7ff)] bg-[var(--color-phosphor-500,#00f5ff)]/10" : "text-slate-500 hover:text-slate-300 hover:bg-slate-800"
          ),
          title: pinned ? "Unpin" : "Pin",
          children: pinned ? /* @__PURE__ */ (0, import_jsx_runtime5.jsx)(import_lucide_react4.Pin, { className: "w-3.5 h-3.5 rotate-45" }) : /* @__PURE__ */ (0, import_jsx_runtime5.jsx)(import_lucide_react4.PinOff, { className: "w-3.5 h-3.5" })
        }
      ),
      /* @__PURE__ */ (0, import_jsx_runtime5.jsxs)("div", { className: "flex items-center bg-slate-800 rounded-md border border-slate-700/60 ml-0.5", children: [
        /* @__PURE__ */ (0, import_jsx_runtime5.jsx)(
          "button",
          {
            type: "button",
            onClick: () => onSetMode("edit"),
            className: (0, import_clsx4.default)("p-1.5 rounded-l-md transition-all duration-150", mode === "edit" ? "text-slate-100 bg-slate-700" : "text-slate-500 hover:text-slate-300"),
            title: "Edit",
            children: /* @__PURE__ */ (0, import_jsx_runtime5.jsx)(import_lucide_react4.Pencil, { className: "w-3 h-3" })
          }
        ),
        /* @__PURE__ */ (0, import_jsx_runtime5.jsx)(
          "button",
          {
            type: "button",
            onClick: () => onSetMode("preview"),
            className: (0, import_clsx4.default)("p-1.5 rounded-r-md transition-all duration-150", mode === "preview" ? "text-slate-100 bg-slate-700" : "text-slate-500 hover:text-slate-300"),
            title: "Preview",
            children: /* @__PURE__ */ (0, import_jsx_runtime5.jsx)(import_lucide_react4.Eye, { className: "w-3 h-3" })
          }
        )
      ] }),
      /* @__PURE__ */ (0, import_jsx_runtime5.jsx)(
        "button",
        {
          type: "button",
          onClick: onDelete,
          className: (0, import_clsx4.default)("p-1.5 rounded-md transition-all duration-150 ml-0.5", confirmDelete ? "text-rose-400 bg-rose-500/10 hover:text-rose-300" : "text-slate-500 hover:text-slate-300 hover:bg-slate-800"),
          title: confirmDelete ? "Click again to confirm" : "Delete",
          children: /* @__PURE__ */ (0, import_jsx_runtime5.jsx)(import_lucide_react4.Trash2, { className: "w-3.5 h-3.5" })
        }
      )
    ] })
  ] });
}

// src/NoteEditorTagsBar.tsx
var import_lucide_react5 = require("lucide-react");
var import_jsx_runtime6 = require("react/jsx-runtime");
function NoteEditorTagsBar({ tags, tagInput, onTagInputChange, onTagKeyDown, onRemoveTag }) {
  return /* @__PURE__ */ (0, import_jsx_runtime6.jsxs)("div", { className: "flex items-center gap-1.5 px-4 py-2 border-b border-slate-800/50 overflow-x-auto scrollbar-none", children: [
    tags.map((tag) => /* @__PURE__ */ (0, import_jsx_runtime6.jsxs)("span", { className: "inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-800 text-slate-400 border border-slate-700/50 flex-shrink-0", children: [
      tag,
      /* @__PURE__ */ (0, import_jsx_runtime6.jsx)("button", { type: "button", onClick: () => onRemoveTag(tag), className: "hover:text-slate-200 transition-colors", children: /* @__PURE__ */ (0, import_jsx_runtime6.jsx)(import_lucide_react5.X, { className: "w-2.5 h-2.5" }) })
    ] }, tag)),
    /* @__PURE__ */ (0, import_jsx_runtime6.jsx)(
      "input",
      {
        value: tagInput,
        onChange: (e) => onTagInputChange(e.target.value),
        onKeyDown: onTagKeyDown,
        placeholder: tags.length === 0 ? "add tags..." : "+",
        className: "bg-transparent text-[10px] text-slate-500 placeholder:text-slate-700 outline-none min-w-[40px] flex-shrink-0"
      }
    )
  ] });
}

// src/NoteEditorContent.tsx
var import_react_markdown = __toESM(require("react-markdown"), 1);
var import_remark_gfm = __toESM(require("remark-gfm"), 1);
var import_jsx_runtime7 = require("react/jsx-runtime");
function NoteEditorContent({ mode, content, onContentChange }) {
  if (mode === "edit") {
    return /* @__PURE__ */ (0, import_jsx_runtime7.jsx)("div", { className: "flex-1 min-h-0 overflow-y-auto", children: /* @__PURE__ */ (0, import_jsx_runtime7.jsx)(
      "textarea",
      {
        value: content,
        onChange: (e) => onContentChange(e.target.value),
        placeholder: "Write something...",
        className: "w-full h-full px-4 py-3 bg-transparent text-sm text-slate-300 placeholder:text-slate-700 outline-none resize-none font-mono leading-relaxed",
        spellCheck: false
      }
    ) });
  }
  return /* @__PURE__ */ (0, import_jsx_runtime7.jsx)("div", { className: "flex-1 min-h-0 overflow-y-auto", children: /* @__PURE__ */ (0, import_jsx_runtime7.jsx)("div", { className: "px-4 py-3 text-sm text-slate-300 prose prose-invert prose-sm max-w-none prose-headings:text-slate-200 prose-a:text-[var(--color-phosphor-400,#33f7ff)] prose-code:text-amber-300 prose-code:bg-slate-800 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-slate-950 prose-pre:border prose-pre:border-slate-700/50", children: content ? /* @__PURE__ */ (0, import_jsx_runtime7.jsx)(import_react_markdown.default, { remarkPlugins: [import_remark_gfm.default], children: content }) : /* @__PURE__ */ (0, import_jsx_runtime7.jsx)("p", { className: "text-slate-600 italic", children: "Nothing here yet." }) }) });
}

// src/NoteEditorDiffView.tsx
var import_lucide_react6 = require("lucide-react");
var import_react_markdown2 = __toESM(require("react-markdown"), 1);
var import_remark_gfm2 = __toESM(require("remark-gfm"), 1);
var import_jsx_runtime8 = require("react/jsx-runtime");
function NoteEditorDiffView({ proposal, currentTitle, currentContent, onAccept, onDiscard }) {
  const titleChanged = !!proposal.proposed_title && proposal.proposed_title !== currentTitle;
  const contentChanged = proposal.proposed_content !== currentContent;
  return /* @__PURE__ */ (0, import_jsx_runtime8.jsxs)("div", { className: "flex flex-col h-full min-w-0 bg-slate-900", children: [
    /* @__PURE__ */ (0, import_jsx_runtime8.jsxs)("div", { className: "flex items-center justify-between px-4 py-2.5 border-b border-slate-700/50", children: [
      /* @__PURE__ */ (0, import_jsx_runtime8.jsxs)("div", { className: "flex items-center gap-2", children: [
        /* @__PURE__ */ (0, import_jsx_runtime8.jsx)(import_lucide_react6.Wand2, { className: "w-3.5 h-3.5 text-amber-400" }),
        /* @__PURE__ */ (0, import_jsx_runtime8.jsx)("span", { className: "text-xs font-medium text-slate-300", children: "Proposed Changes" })
      ] }),
      /* @__PURE__ */ (0, import_jsx_runtime8.jsxs)("div", { className: "flex items-center gap-1.5", children: [
        /* @__PURE__ */ (0, import_jsx_runtime8.jsxs)(
          "button",
          {
            type: "button",
            onClick: onAccept,
            className: "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/25 transition-colors",
            children: [
              /* @__PURE__ */ (0, import_jsx_runtime8.jsx)(import_lucide_react6.Check, { className: "w-3 h-3" }),
              " Accept"
            ]
          }
        ),
        /* @__PURE__ */ (0, import_jsx_runtime8.jsxs)(
          "button",
          {
            type: "button",
            onClick: onDiscard,
            className: "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium bg-slate-800 text-slate-400 border border-slate-700 hover:text-slate-300 transition-colors",
            children: [
              /* @__PURE__ */ (0, import_jsx_runtime8.jsx)(import_lucide_react6.XCircle, { className: "w-3 h-3" }),
              " Discard"
            ]
          }
        )
      ] })
    ] }),
    titleChanged && /* @__PURE__ */ (0, import_jsx_runtime8.jsxs)("div", { className: "px-4 py-2 border-b border-slate-800/50", children: [
      /* @__PURE__ */ (0, import_jsx_runtime8.jsx)("span", { className: "text-[10px] text-slate-500 uppercase tracking-wider", children: "Title" }),
      /* @__PURE__ */ (0, import_jsx_runtime8.jsxs)("div", { className: "flex gap-3 mt-1", children: [
        /* @__PURE__ */ (0, import_jsx_runtime8.jsxs)("div", { className: "flex-1 min-w-0", children: [
          /* @__PURE__ */ (0, import_jsx_runtime8.jsx)("span", { className: "text-[10px] text-rose-400/70 block mb-0.5", children: "Current" }),
          /* @__PURE__ */ (0, import_jsx_runtime8.jsx)("span", { className: "text-sm text-slate-400 line-through", children: currentTitle || "Untitled" })
        ] }),
        /* @__PURE__ */ (0, import_jsx_runtime8.jsxs)("div", { className: "flex-1 min-w-0", children: [
          /* @__PURE__ */ (0, import_jsx_runtime8.jsx)("span", { className: "text-[10px] text-emerald-400/70 block mb-0.5", children: "Proposed" }),
          /* @__PURE__ */ (0, import_jsx_runtime8.jsx)("span", { className: "text-sm text-slate-200 font-medium", children: proposal.proposed_title })
        ] })
      ] })
    ] }),
    /* @__PURE__ */ (0, import_jsx_runtime8.jsxs)("div", { className: "flex flex-1 min-h-0 overflow-hidden", children: [
      /* @__PURE__ */ (0, import_jsx_runtime8.jsxs)("div", { className: "flex-1 min-w-0 border-r border-slate-800/50 overflow-y-auto", children: [
        /* @__PURE__ */ (0, import_jsx_runtime8.jsx)("div", { className: "px-3 py-1.5 border-b border-slate-800/30 sticky top-0 bg-slate-900", children: /* @__PURE__ */ (0, import_jsx_runtime8.jsx)("span", { className: "text-[10px] text-rose-400/70 uppercase tracking-wider", children: "Current" }) }),
        contentChanged ? /* @__PURE__ */ (0, import_jsx_runtime8.jsx)("div", { className: "px-3 py-2 text-xs text-slate-400 font-mono leading-relaxed whitespace-pre-wrap", children: currentContent || "(empty)" }) : /* @__PURE__ */ (0, import_jsx_runtime8.jsx)("div", { className: "px-3 py-4 text-center text-[11px] text-slate-600", children: "Content unchanged" })
      ] }),
      /* @__PURE__ */ (0, import_jsx_runtime8.jsxs)("div", { className: "flex-1 min-w-0 overflow-y-auto", children: [
        /* @__PURE__ */ (0, import_jsx_runtime8.jsx)("div", { className: "px-3 py-1.5 border-b border-slate-800/30 sticky top-0 bg-slate-900", children: /* @__PURE__ */ (0, import_jsx_runtime8.jsx)("span", { className: "text-[10px] text-emerald-400/70 uppercase tracking-wider", children: "Proposed" }) }),
        contentChanged ? /* @__PURE__ */ (0, import_jsx_runtime8.jsx)("div", { className: "px-3 py-2 text-sm text-slate-300 prose prose-invert prose-sm max-w-none prose-headings:text-slate-200 prose-code:text-amber-300 prose-code:bg-slate-800 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-slate-950 prose-pre:border prose-pre:border-slate-700/50", children: /* @__PURE__ */ (0, import_jsx_runtime8.jsx)(import_react_markdown2.default, { remarkPlugins: [import_remark_gfm2.default], children: proposal.proposed_content ?? "" }) }) : /* @__PURE__ */ (0, import_jsx_runtime8.jsx)("div", { className: "px-3 py-4 text-center text-[11px] text-slate-600", children: "Content unchanged" })
      ] })
    ] })
  ] });
}

// src/NoteEditorHistoryView.tsx
var import_lucide_react7 = require("lucide-react");
var import_clsx5 = __toESM(require("clsx"), 1);
var import_jsx_runtime9 = require("react/jsx-runtime");
function relativeTime2(dateStr) {
  if (!dateStr) return "";
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 6e4);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}
function VersionItem({ v, onRevert }) {
  return /* @__PURE__ */ (0, import_jsx_runtime9.jsxs)("div", { className: "px-4 py-3 border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors group", children: [
    /* @__PURE__ */ (0, import_jsx_runtime9.jsxs)("div", { className: "flex items-center justify-between", children: [
      /* @__PURE__ */ (0, import_jsx_runtime9.jsxs)("div", { className: "flex items-center gap-2", children: [
        /* @__PURE__ */ (0, import_jsx_runtime9.jsxs)("span", { className: "text-xs text-slate-300 font-medium", children: [
          "v",
          v.version
        ] }),
        /* @__PURE__ */ (0, import_jsx_runtime9.jsx)("span", { className: "text-[10px] text-slate-600", children: relativeTime2(v.created_at) }),
        /* @__PURE__ */ (0, import_jsx_runtime9.jsx)("span", { className: (0, import_clsx5.default)(
          "text-[10px] px-1.5 py-0.5 rounded border",
          v.change_source === "format_accept" ? "text-amber-400/70 border-amber-500/20 bg-amber-500/5" : v.change_source === "revert" ? "text-[var(--color-phosphor-400,#33f7ff)]/70 border-[var(--color-phosphor-500,#00f5ff)]/20 bg-[var(--color-phosphor-500,#00f5ff)]/5" : "text-slate-500 border-slate-700/50 bg-slate-800/30"
        ), children: v.change_source.replace("_", " ") })
      ] }),
      /* @__PURE__ */ (0, import_jsx_runtime9.jsxs)(
        "button",
        {
          type: "button",
          onClick: () => onRevert(v.id),
          className: "opacity-0 group-hover:opacity-100 inline-flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium text-[var(--color-phosphor-400,#33f7ff)] border border-[var(--color-phosphor-500,#00f5ff)]/20 hover:bg-[var(--color-phosphor-500,#00f5ff)]/10 transition-all",
          children: [
            /* @__PURE__ */ (0, import_jsx_runtime9.jsx)(import_lucide_react7.RotateCcw, { className: "w-2.5 h-2.5" }),
            " Revert"
          ]
        }
      )
    ] }),
    /* @__PURE__ */ (0, import_jsx_runtime9.jsx)("p", { className: "text-[11px] text-slate-400 mt-1 truncate", children: v.title || "Untitled" }),
    /* @__PURE__ */ (0, import_jsx_runtime9.jsx)("p", { className: "text-[10px] text-slate-600 mt-0.5 line-clamp-2", children: v.content.substring(0, 150) })
  ] });
}
function NoteEditorHistoryView({
  versions,
  loadingVersions,
  versionError,
  onClose,
  onRevert
}) {
  return /* @__PURE__ */ (0, import_jsx_runtime9.jsxs)("div", { className: "flex flex-col h-full min-w-0 bg-slate-900", children: [
    /* @__PURE__ */ (0, import_jsx_runtime9.jsxs)("div", { className: "flex items-center justify-between px-4 py-2.5 border-b border-slate-700/50", children: [
      /* @__PURE__ */ (0, import_jsx_runtime9.jsxs)("div", { className: "flex items-center gap-2", children: [
        /* @__PURE__ */ (0, import_jsx_runtime9.jsx)(import_lucide_react7.History, { className: "w-3.5 h-3.5 text-[var(--color-phosphor-400,#33f7ff)]" }),
        /* @__PURE__ */ (0, import_jsx_runtime9.jsx)("span", { className: "text-xs font-medium text-slate-300", children: "Version History" }),
        /* @__PURE__ */ (0, import_jsx_runtime9.jsxs)("span", { className: "text-[10px] text-slate-500", children: [
          "(",
          versions.length,
          ")"
        ] })
      ] }),
      /* @__PURE__ */ (0, import_jsx_runtime9.jsx)("button", { type: "button", onClick: onClose, className: "p-1 text-slate-500 hover:text-slate-300 rounded transition-colors", children: /* @__PURE__ */ (0, import_jsx_runtime9.jsx)(import_lucide_react7.X, { className: "w-3.5 h-3.5" }) })
    ] }),
    /* @__PURE__ */ (0, import_jsx_runtime9.jsxs)("div", { className: "flex-1 overflow-y-auto", children: [
      loadingVersions && /* @__PURE__ */ (0, import_jsx_runtime9.jsx)("div", { className: "px-4 py-6 text-center text-xs text-slate-600", children: "Loading..." }),
      !loadingVersions && versionError && /* @__PURE__ */ (0, import_jsx_runtime9.jsx)("div", { className: "px-4 py-6 text-center text-xs text-rose-400/80", children: "Unable to load versions" }),
      !loadingVersions && !versionError && versions.length === 0 && /* @__PURE__ */ (0, import_jsx_runtime9.jsx)("div", { className: "px-4 py-6 text-center text-xs text-slate-600", children: "No versions yet" }),
      !loadingVersions && versions.map((v) => /* @__PURE__ */ (0, import_jsx_runtime9.jsx)(VersionItem, { v, onRevert }, v.id))
    ] })
  ] });
}

// src/NoteEditor.tsx
var import_jsx_runtime10 = require("react/jsx-runtime");
function NoteEditor({ note, onDeleted }) {
  const { api, capabilities } = useNotesContext();
  const editor = useNoteEditorState({ note, onDeleted });
  const format = useFormatProposal({
    noteId: note.id,
    api,
    onAccepted: (proposedTitle, proposedContent) => {
      if (proposedTitle) editor.setTitle(proposedTitle);
      if (proposedContent) editor.setContent(proposedContent);
      editor.autoFormatAttemptedRef.current = true;
      editor.setSaveState("saved");
      setTimeout(() => editor.setSaveState("idle"), 1500);
    }
  });
  const history = useVersionHistory({
    noteId: note.id,
    api,
    onReverted: (title, content, tags) => {
      editor.setTitle(title);
      editor.setContent(content);
      editor.setTags(tags);
      editor.setSaveState("saved");
      setTimeout(() => editor.setSaveState("idle"), 1500);
    }
  });
  (0, import_react7.useEffect)(() => {
    format.setFormatState("idle");
    format.setProposal(null);
    format.stopPolling();
    history.setShowHistory(false);
    format.initProposal(note.id);
  }, [note.id]);
  (0, import_react7.useEffect)(() => {
    if (!capabilities.title_generation) return;
    const isUntitled = !note.title.trim() || note.title === "Untitled";
    if (isUntitled && note.content.trim().length >= 50 && !editor.autoFormatAttemptedRef.current) {
      editor.autoFormatAttemptedRef.current = true;
      api.generateTitle(note.content).then((result) => {
        if (result.title) {
          editor.setTitle(result.title);
          editor.mutateRef.current({ noteId: note.id, data: { title: result.title } });
        }
      }).catch(() => {
      });
    }
  }, [capabilities.title_generation, note.id]);
  (0, import_react7.useEffect)(() => {
    return () => {
      format.stopPolling();
    };
  }, []);
  if (format.proposal && format.formatState === "ready" && (format.proposal.proposed_title || format.proposal.proposed_content)) {
    return /* @__PURE__ */ (0, import_jsx_runtime10.jsx)(
      NoteEditorDiffView,
      {
        proposal: format.proposal,
        currentTitle: editor.title,
        currentContent: editor.content,
        onAccept: format.acceptProposal,
        onDiscard: format.discardProposal
      }
    );
  }
  if (history.showHistory) {
    return /* @__PURE__ */ (0, import_jsx_runtime10.jsx)(
      NoteEditorHistoryView,
      {
        versions: history.versions,
        loadingVersions: history.loadingVersions,
        versionError: history.versionError,
        onClose: () => history.setShowHistory(false),
        onRevert: history.revertToVersion
      }
    );
  }
  return /* @__PURE__ */ (0, import_jsx_runtime10.jsxs)("div", { className: "flex flex-col h-full min-w-0 bg-slate-900", children: [
    /* @__PURE__ */ (0, import_jsx_runtime10.jsx)(
      NoteEditorHeader,
      {
        title: editor.title,
        pinned: editor.pinned,
        mode: editor.mode,
        saveState: editor.saveState,
        formatState: format.formatState,
        canFormat: capabilities.formatting,
        contentLength: editor.content.trim().length,
        confirmDelete: editor.confirmDelete,
        onTitleChange: editor.handleTitleChange,
        onStartFormat: () => format.startFormat(editor.content, editor.title),
        onToggleHistory: history.toggleHistory,
        onTogglePin: editor.togglePin,
        onSetMode: editor.setMode,
        onDelete: editor.handleDelete
      }
    ),
    /* @__PURE__ */ (0, import_jsx_runtime10.jsx)(
      NoteEditorTagsBar,
      {
        tags: editor.tags,
        tagInput: editor.tagInput,
        onTagInputChange: editor.setTagInput,
        onTagKeyDown: editor.handleTagKeyDown,
        onRemoveTag: editor.removeTag
      }
    ),
    /* @__PURE__ */ (0, import_jsx_runtime10.jsx)(
      NoteEditorContent,
      {
        mode: editor.mode,
        content: editor.content,
        onContentChange: editor.handleContentChange
      }
    ),
    note.type === "prompt" && /* @__PURE__ */ (0, import_jsx_runtime10.jsx)(
      PromptActions,
      {
        content: editor.content,
        noteId: note.id,
        onRefineStarted: () => {
          format.setFormatState("pending");
          format.startPolling(note.id);
        }
      }
    )
  ] });
}

// src/NotesPanel.tsx
var import_jsx_runtime11 = require("react/jsx-runtime");
function NotesPanel({ onPopOut }) {
  const { projectScope, scopeOptions, getScopeLabel } = useNotesContext();
  const [activeTab, setActiveTab] = (0, import_react8.useState)("note");
  const [scopeFilter, setScopeFilter] = (0, import_react8.useState)(projectScope || "global");
  const [selectedNote, setSelectedNote] = (0, import_react8.useState)(null);
  const [showScopeMenu, setShowScopeMenu] = (0, import_react8.useState)(false);
  const availableScopeOptions = scopeOptions.length > 0 ? scopeOptions : [{ value: projectScope || "global", label: getScopeLabel(projectScope || "global"), known: false }];
  const activeScopeLabel = getScopeLabel(scopeFilter);
  return /* @__PURE__ */ (0, import_jsx_runtime11.jsxs)(
    "div",
    {
      className: "flex flex-col flex-1 min-h-0 bg-slate-900",
      style: { backgroundColor: "#0f172a" },
      children: [
        /* @__PURE__ */ (0, import_jsx_runtime11.jsxs)(
          "div",
          {
            className: "flex items-center justify-between px-3 py-2.5 border-b border-slate-700/50 flex-shrink-0 bg-slate-950/60",
            style: {
              backgroundColor: "rgba(2, 6, 23, 0.78)",
              borderColor: "rgba(51, 65, 85, 0.5)"
            },
            children: [
              /* @__PURE__ */ (0, import_jsx_runtime11.jsxs)("div", { className: "flex items-center gap-2", children: [
                /* @__PURE__ */ (0, import_jsx_runtime11.jsx)(import_lucide_react8.StickyNote, { className: "w-3.5 h-3.5 text-[var(--color-phosphor-400,#33f7ff)]" }),
                /* @__PURE__ */ (0, import_jsx_runtime11.jsx)("span", { className: "text-xs font-semibold text-slate-200 tracking-wide", style: { fontFamily: "var(--font-display, inherit)" }, children: "Notes" })
              ] }),
              /* @__PURE__ */ (0, import_jsx_runtime11.jsxs)("div", { className: "flex items-center gap-1.5", children: [
                /* @__PURE__ */ (0, import_jsx_runtime11.jsxs)("div", { className: "flex items-center bg-slate-800/80 rounded-md border border-slate-700/50 mr-1", children: [
                  /* @__PURE__ */ (0, import_jsx_runtime11.jsx)(
                    "button",
                    {
                      type: "button",
                      onClick: () => {
                        setActiveTab("note");
                        setSelectedNote(null);
                      },
                      className: (0, import_clsx6.default)(
                        "px-2.5 py-1 text-[10px] font-medium rounded-l-md transition-colors",
                        activeTab === "note" ? "text-slate-200 bg-slate-700" : "text-slate-500 hover:text-slate-400"
                      ),
                      children: "Notes"
                    }
                  ),
                  /* @__PURE__ */ (0, import_jsx_runtime11.jsx)(
                    "button",
                    {
                      type: "button",
                      onClick: () => {
                        setActiveTab("prompt");
                        setSelectedNote(null);
                      },
                      className: (0, import_clsx6.default)(
                        "px-2.5 py-1 text-[10px] font-medium rounded-r-md transition-colors",
                        activeTab === "prompt" ? "text-amber-300 bg-slate-700" : "text-slate-500 hover:text-slate-400"
                      ),
                      children: "Prompts"
                    }
                  )
                ] }),
                /* @__PURE__ */ (0, import_jsx_runtime11.jsxs)("div", { className: "relative", children: [
                  /* @__PURE__ */ (0, import_jsx_runtime11.jsxs)(
                    "button",
                    {
                      type: "button",
                      onClick: () => setShowScopeMenu((v) => !v),
                      className: "flex items-center gap-1 px-2 py-1 text-[10px] font-medium text-slate-400 hover:text-slate-300 bg-slate-800/50 rounded border border-slate-700/50 transition-colors",
                      "aria-label": `Notes scope: ${activeScopeLabel}`,
                      children: [
                        activeScopeLabel,
                        /* @__PURE__ */ (0, import_jsx_runtime11.jsx)(import_lucide_react8.ChevronDown, { className: "w-2.5 h-2.5" })
                      ]
                    }
                  ),
                  showScopeMenu && /* @__PURE__ */ (0, import_jsx_runtime11.jsxs)(import_jsx_runtime11.Fragment, { children: [
                    /* @__PURE__ */ (0, import_jsx_runtime11.jsx)("div", { className: "fixed inset-0 z-[101]", onClick: () => setShowScopeMenu(false) }),
                    /* @__PURE__ */ (0, import_jsx_runtime11.jsx)(
                      "div",
                      {
                        className: "absolute right-0 top-full mt-1 w-40 bg-slate-900 border border-slate-700 rounded-md shadow-xl z-[102] py-1 overflow-hidden",
                        style: {
                          backgroundColor: "#0f172a",
                          borderColor: "rgba(51, 65, 85, 0.8)",
                          boxShadow: "0 18px 36px rgba(0, 0, 0, 0.42)"
                        },
                        children: availableScopeOptions.map((scope) => /* @__PURE__ */ (0, import_jsx_runtime11.jsx)(
                          "button",
                          {
                            type: "button",
                            onClick: () => {
                              setScopeFilter(scope.value);
                              setShowScopeMenu(false);
                            },
                            className: (0, import_clsx6.default)(
                              "w-full text-left px-3 py-1.5 text-[11px] transition-colors",
                              scopeFilter === scope.value ? "text-[var(--color-phosphor-400,#33f7ff)] bg-slate-800/50" : "text-slate-400 hover:text-slate-300 hover:bg-slate-800/30"
                            ),
                            children: scope.label
                          },
                          scope.value
                        ))
                      }
                    )
                  ] })
                ] }),
                onPopOut && /* @__PURE__ */ (0, import_jsx_runtime11.jsx)(
                  "button",
                  {
                    type: "button",
                    onClick: onPopOut,
                    className: "p-1 text-slate-500 hover:text-[var(--color-phosphor-400,#33f7ff)] rounded transition-colors",
                    title: "Open in separate window",
                    children: /* @__PURE__ */ (0, import_jsx_runtime11.jsx)(import_lucide_react8.ExternalLink, { className: "w-3.5 h-3.5" })
                  }
                )
              ] })
            ]
          }
        ),
        /* @__PURE__ */ (0, import_jsx_runtime11.jsxs)(
          "div",
          {
            className: "flex flex-1 min-h-0 overflow-hidden bg-slate-900",
            style: { backgroundColor: "#0f172a" },
            children: [
              /* @__PURE__ */ (0, import_jsx_runtime11.jsx)(
                NotesList,
                {
                  activeTab,
                  scopeFilter,
                  selectedId: selectedNote?.id ?? null,
                  onSelect: setSelectedNote
                }
              ),
              /* @__PURE__ */ (0, import_jsx_runtime11.jsx)("div", { className: "flex-1 min-w-0 bg-slate-900", style: { backgroundColor: "#0f172a" }, children: selectedNote ? /* @__PURE__ */ (0, import_jsx_runtime11.jsx)(
                NoteEditor,
                {
                  note: selectedNote,
                  onDeleted: () => setSelectedNote(null)
                }
              ) : /* @__PURE__ */ (0, import_jsx_runtime11.jsx)("div", { className: "flex items-center justify-center h-full bg-slate-900", style: { backgroundColor: "#0f172a" }, children: /* @__PURE__ */ (0, import_jsx_runtime11.jsxs)("div", { className: "text-center space-y-3", children: [
                /* @__PURE__ */ (0, import_jsx_runtime11.jsxs)("div", { className: "relative mx-auto w-12 h-12 flex items-center justify-center", children: [
                  /* @__PURE__ */ (0, import_jsx_runtime11.jsx)("div", { className: "absolute inset-0 rounded-xl bg-[var(--color-phosphor-500,#00f5ff)]/5 border border-[var(--color-phosphor-500,#00f5ff)]/10" }),
                  /* @__PURE__ */ (0, import_jsx_runtime11.jsx)(import_lucide_react8.StickyNote, { className: "w-5 h-5 text-slate-600 relative" })
                ] }),
                /* @__PURE__ */ (0, import_jsx_runtime11.jsxs)("div", { children: [
                  /* @__PURE__ */ (0, import_jsx_runtime11.jsxs)("p", { className: "text-xs text-slate-500 font-medium", children: [
                    "Select or create a ",
                    activeTab
                  ] }),
                  /* @__PURE__ */ (0, import_jsx_runtime11.jsx)("p", { className: "text-[10px] text-slate-600 mt-1", children: "Use the sidebar to browse, or press + to start fresh" })
                ] })
              ] }) }) })
            ]
          }
        )
      ]
    }
  );
}

// src/NotesButton.tsx
var import_jsx_runtime12 = require("react/jsx-runtime");
var POPUP_FEATURES = "width=700,height=800,menubar=no,toolbar=no,location=no,status=no";
function NotesButton({ className, popOutUrl = "/notes" }) {
  const { api } = useNotesContext();
  const [open, setOpen] = (0, import_react9.useState)(false);
  const [available, setAvailable] = (0, import_react9.useState)(true);
  const buttonRef = (0, import_react9.useRef)(null);
  const panelRef = (0, import_react9.useRef)(null);
  const [panelStyle, setPanelStyle] = (0, import_react9.useState)({});
  (0, import_react9.useEffect)(() => {
    api.list({ limit: 1 }).then(() => setAvailable(true)).catch(() => setAvailable(false));
  }, [api]);
  (0, import_react9.useEffect)(() => {
    if (!open || !buttonRef.current) return;
    const rect = buttonRef.current.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const GAP = 8;
    const PANEL_W = 700;
    const style = { width: PANEL_W, zIndex: 9999 };
    if (rect.top < vh / 2) {
      style.top = rect.bottom + GAP;
      style.height = `calc(100vh - ${rect.bottom + GAP + 16}px)`;
    } else {
      style.bottom = vh - rect.top + GAP;
      style.height = `calc(100vh - ${vh - rect.top + GAP + 16}px)`;
    }
    style.maxHeight = 900;
    const leftOffset = rect.left < vw / 2 ? Math.max(rect.left, GAP) : null;
    if (leftOffset !== null) {
      style.left = leftOffset;
    } else {
      style.right = Math.max(vw - rect.right, GAP);
    }
    if (leftOffset !== null && leftOffset + PANEL_W > vw - GAP) {
      style.width = vw - leftOffset - GAP;
    }
    setPanelStyle(style);
  }, [open]);
  (0, import_react9.useEffect)(() => {
    if (!open) return;
    const handler = (e) => {
      const target = e.target;
      if (buttonRef.current?.contains(target) || panelRef.current?.contains(target)) return;
      setOpen(false);
    };
    const timer = setTimeout(() => document.addEventListener("mousedown", handler), 0);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("mousedown", handler);
    };
  }, [open]);
  (0, import_react9.useEffect)(() => {
    if (!open) return;
    const handler = (e) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open]);
  const toggle = (0, import_react9.useCallback)(() => setOpen((v) => !v), []);
  const handlePopOut = (0, import_react9.useCallback)(() => {
    window.open(popOutUrl, "summitflow-notes", POPUP_FEATURES);
    setOpen(false);
  }, [popOutUrl]);
  if (!available) return null;
  return /* @__PURE__ */ (0, import_jsx_runtime12.jsxs)(import_jsx_runtime12.Fragment, { children: [
    /* @__PURE__ */ (0, import_jsx_runtime12.jsxs)(
      "button",
      {
        ref: buttonRef,
        type: "button",
        onClick: toggle,
        className: (0, import_clsx7.default)(
          "relative p-2 rounded-lg transition-all duration-200",
          "text-slate-400 hover:text-[var(--color-phosphor-400,#33f7ff)] hover:bg-slate-800/50",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-phosphor-500,#00f5ff)]/40",
          "active:bg-slate-800",
          open && "text-[var(--color-phosphor-400,#33f7ff)] bg-slate-800/50",
          className
        ),
        "aria-label": "Notes",
        "aria-expanded": open,
        title: "Notes",
        children: [
          /* @__PURE__ */ (0, import_jsx_runtime12.jsx)(import_lucide_react9.StickyNote, { className: "w-4 h-4" }),
          open && /* @__PURE__ */ (0, import_jsx_runtime12.jsx)("span", { className: "absolute bottom-0 left-1/2 -translate-x-1/2 w-1 h-1 rounded-full bg-[var(--color-phosphor-500,#00f5ff)]" })
        ]
      }
    ),
    open && (0, import_react_dom.createPortal)(
      /* @__PURE__ */ (0, import_jsx_runtime12.jsxs)(
        "div",
        {
          ref: panelRef,
          className: (0, import_clsx7.default)(
            "fixed flex flex-col bg-slate-900",
            "border border-slate-700/70 rounded-lg",
            "shadow-2xl shadow-black/60",
            "overflow-hidden"
          ),
          style: {
            ...panelStyle,
            backgroundColor: "#0f172a",
            borderColor: "rgba(51, 65, 85, 0.7)",
            boxShadow: "0 25px 50px -12px rgba(0, 0, 0, 0.55)"
          },
          children: [
            /* @__PURE__ */ (0, import_jsx_runtime12.jsx)("div", { className: "h-px w-full flex-shrink-0", style: {
              background: "linear-gradient(90deg, transparent 0%, var(--color-phosphor-500, #00f5ff) 30%, var(--color-phosphor-400, #33f7ff) 50%, var(--color-phosphor-500, #00f5ff) 70%, transparent 100%)",
              opacity: 0.35
            } }),
            /* @__PURE__ */ (0, import_jsx_runtime12.jsx)(NotesPanel, { onPopOut: handlePopOut })
          ]
        }
      ),
      document.body
    )
  ] });
}

// src/NotesWorkspace.tsx
var import_jsx_runtime13 = require("react/jsx-runtime");
function NotesWorkspaceShell() {
  const { projectScope, getScopeLabel } = useNotesContext();
  const scopeLabel = getScopeLabel(projectScope || "global");
  return /* @__PURE__ */ (0, import_jsx_runtime13.jsxs)("div", { className: "relative flex h-screen flex-col overflow-hidden bg-[#05030b]", children: [
    /* @__PURE__ */ (0, import_jsx_runtime13.jsx)(
      "div",
      {
        className: "pointer-events-none absolute inset-0",
        style: {
          background: "radial-gradient(ellipse 80% 60% at 50% 0%, rgba(44,16,84,0.72) 0%, transparent 72%)",
          opacity: 0.85
        }
      }
    ),
    /* @__PURE__ */ (0, import_jsx_runtime13.jsx)("div", { className: "pointer-events-none absolute inset-0 bg-[linear-gradient(180deg,rgba(8,6,18,0.1),rgba(8,6,18,0.9))]" }),
    /* @__PURE__ */ (0, import_jsx_runtime13.jsxs)("div", { className: "relative z-10 flex items-center justify-between gap-3 px-4 py-3", children: [
      /* @__PURE__ */ (0, import_jsx_runtime13.jsx)("span", { className: "rounded-full border border-slate-700/70 bg-slate-950/70 px-3 py-1 text-[10px] uppercase tracking-[0.18em] text-slate-300", children: "Notes" }),
      /* @__PURE__ */ (0, import_jsx_runtime13.jsxs)("span", { className: "rounded-full border border-slate-700/70 bg-slate-950/70 px-3 py-1 text-[10px] uppercase tracking-[0.18em] text-slate-400", children: [
        "project: ",
        scopeLabel
      ] })
    ] }),
    /* @__PURE__ */ (0, import_jsx_runtime13.jsx)("div", { className: "relative z-10 flex-1 px-4 pb-4", children: /* @__PURE__ */ (0, import_jsx_runtime13.jsx)("div", { className: "h-full overflow-hidden rounded-[1.75rem] border border-slate-800/80 bg-[#0b0615]/80 shadow-[0_28px_80px_rgba(3,6,18,0.45)] backdrop-blur", children: /* @__PURE__ */ (0, import_jsx_runtime13.jsx)(NotesPanel, {}) }) })
  ] });
}
function NotesWorkspace({ apiPrefix, projectScope }) {
  return /* @__PURE__ */ (0, import_jsx_runtime13.jsx)(NotesProvider, { apiPrefix, projectScope: projectScope || "global", children: /* @__PURE__ */ (0, import_jsx_runtime13.jsx)(NotesWorkspaceShell, {}) });
}
// Annotate the CommonJS export names for ESM import in node:
0 && (module.exports = {
  NotesButton,
  NotesPanel,
  NotesProvider,
  NotesWorkspace
});
