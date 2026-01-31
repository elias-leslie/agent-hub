import { useState } from "react";
import { Copy, Check } from "lucide-react";

interface NewSecretBannerProps {
  secret: string;
  onDismiss: () => void;
}

export function NewSecretBanner({ secret, onDismiss }: NewSecretBannerProps) {
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    navigator.clipboard.writeText(secret);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="bg-amber-900/20 border border-amber-800/50 rounded-lg p-4 mb-6">
      <p className="text-sm text-amber-300 mb-2 font-medium">
        New secret generated - save it now!
      </p>
      <div className="flex items-center gap-2">
        <code className="flex-1 p-3 bg-slate-950 rounded font-mono text-sm text-slate-100 break-all">
          {secret}
        </code>
        <button
          onClick={handleCopy}
          className="p-2 rounded bg-slate-800 hover:bg-slate-700 transition-colors"
        >
          {copied ? (
            <Check className="h-5 w-5 text-emerald-400" />
          ) : (
            <Copy className="h-5 w-5 text-slate-400" />
          )}
        </button>
      </div>
      <button
        onClick={onDismiss}
        className="mt-3 text-sm text-slate-400 hover:text-slate-300"
      >
        Dismiss
      </button>
    </div>
  );
}
