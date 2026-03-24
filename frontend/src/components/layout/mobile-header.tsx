import Link from "next/link";
import { Menu, Zap } from "lucide-react";

interface MobileHeaderProps {
  onMenuClick: () => void;
}

export function MobileHeader({ onMenuClick }: MobileHeaderProps) {
  return (
    <header className="lg:hidden flex items-center justify-between h-14 px-4 border-b border-slate-800 bg-slate-900">
      <button
        onClick={onMenuClick}
        className="p-2 -ml-2 rounded-lg hover:bg-slate-800"
      >
        <Menu className="h-5 w-5 text-slate-400" />
      </button>

      <Link href="/" className="flex items-center gap-2">
        <div className="p-1.5 rounded-md bg-gradient-to-br from-amber-500 to-orange-600">
          <Zap className="h-4 w-4 text-white" />
        </div>
        <span className="text-sm font-semibold text-slate-100">
          Agent Hub
        </span>
      </Link>

      {/* Placeholder for balance */}
      <div className="w-9" />
    </header>
  );
}
