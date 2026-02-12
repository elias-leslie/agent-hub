import { Tags } from "lucide-react";
import { parseTagsFromInput } from "./utils";

interface TagFilteringSectionProps {
  includeTags: string[];
  excludeTags: string[];
  onUpdateTags: (field: "include_tags" | "exclude_tags", tags: string[]) => void;
}

export function TagFilteringSection({
  includeTags,
  excludeTags,
  onUpdateTags,
}: TagFilteringSectionProps) {
  const handleTagChange = (field: "include_tags" | "exclude_tags", value: string) => {
    const tags = parseTagsFromInput(value);
    onUpdateTags(field, tags);
  };

  return (
    <div className="space-y-5 p-5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800/50">
      <div className="flex items-center gap-2">
        <Tags className="h-5 w-5 text-slate-400" />
        <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300 uppercase tracking-wider">
          Tag Filtering
        </h3>
      </div>

      <p className="text-xs text-slate-500 dark:text-slate-400">
        Include = only inject these tagged episodes. Exclude = never inject
        these tagged episodes.
      </p>

      {/* Include Tags */}
      <div className="space-y-1.5">
        <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
          Include Tags
        </label>
        <input
          type="text"
          value={includeTags.join(", ")}
          onChange={(e) => handleTagChange("include_tags", e.target.value)}
          placeholder="e.g. python, deployment, security"
          className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40 placeholder:text-slate-400 dark:placeholder:text-slate-500"
        />
        <p className="text-[11px] text-slate-400 dark:text-slate-500">
          Comma-separated whitelist of episode tags
        </p>
      </div>

      {/* Exclude Tags */}
      <div className="space-y-1.5">
        <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
          Exclude Tags
        </label>
        <input
          type="text"
          value={excludeTags.join(", ")}
          onChange={(e) => handleTagChange("exclude_tags", e.target.value)}
          placeholder="e.g. deprecated, internal, draft"
          className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40 placeholder:text-slate-400 dark:placeholder:text-slate-500"
        />
        <p className="text-[11px] text-slate-400 dark:text-slate-500">
          Comma-separated blacklist of episode tags
        </p>
      </div>
    </div>
  );
}
