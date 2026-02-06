"use client";

import { Suspense, useCallback, useMemo } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { Brain } from "lucide-react";
import { cn } from "@/lib/utils";
import { useMemory } from "@/hooks/use-memory";
import { CATEGORY_CONFIG } from "@/lib/memory-config";
import { MemoryTabs, type MemoryTabId } from "@/components/memory/MemoryTabs";
import { EpisodesTab } from "@/components/memory/tabs/EpisodesTab";
import { EntitiesTab } from "@/components/memory/tabs/EntitiesTab";
import { SessionsTab } from "@/components/memory/tabs/SessionsTab";
import { CaptureTab } from "@/components/memory/tabs/CaptureTab";
import { AnalyticsTab } from "@/components/memory/tabs/AnalyticsTab";

function MemoryPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const activeTab = (searchParams.get("tab") as MemoryTabId) || "episodes";

  const handleTabChange = useCallback(
    (tab: MemoryTabId) => {
      const params = new URLSearchParams(searchParams.toString());
      if (tab === "episodes") {
        params.delete("tab");
      } else {
        params.set("tab", tab);
      }
      const qs = params.toString();
      router.push(qs ? `/memory?${qs}` : "/memory", { scroll: false });
    },
    [router, searchParams]
  );

  return (
    <div className="flex flex-col h-[calc(100vh-56px)]">
      <MemoryTabs activeTab={activeTab} onTabChange={handleTabChange} />
      {activeTab === "episodes" && <EpisodesTab />}
      {activeTab === "entities" && <EntitiesTab />}
      {activeTab === "sessions" && <SessionsTab />}
      {activeTab === "capture" && <CaptureTab />}
      {activeTab === "analytics" && <AnalyticsTab />}
    </div>
  );
}

function LoadingState() {
  return (
    <div className="flex h-[calc(100vh-56px)]">
      <div className="flex-1 p-4">
        <div className="animate-pulse space-y-4">
          <div className="h-10 bg-slate-700 rounded-lg" />
          <div className="space-y-2">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="h-12 bg-slate-700 rounded" />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function MemoryPage() {
  const { stats, isLoadingStats } = useMemory({});

  const categoryStats = useMemo(() => {
    if (!stats?.by_category) return [];
    return stats.by_category.slice(0, 4);
  }, [stats]);

  return (
    <div className="min-h-screen bg-slate-950">
      <header className="sticky top-0 z-30 border-b border-slate-800 bg-slate-900/95 backdrop-blur-sm">
        <div className="px-4 lg:px-6">
          <div className="flex items-center justify-between h-14">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <div className="p-1.5 rounded-lg bg-emerald-900/30">
                  <Brain className="w-5 h-5 text-emerald-400" />
                </div>
                <h1 className="text-lg font-bold text-slate-100 tracking-tight">
                  Memory
                </h1>
              </div>

              <div className="hidden sm:flex items-center gap-3 text-xs font-mono tabular-nums">
                <span className="text-slate-400">
                  {isLoadingStats ? "..." : stats?.total ?? 0} total
                </span>
                {categoryStats.length > 0 && (
                  <>
                    <span className="text-slate-600">|</span>
                    {categoryStats.map((cat) => (
                      <span
                        key={cat.category}
                        className={cn("flex items-center gap-1", CATEGORY_CONFIG[cat.category].color)}
                      >
                        {CATEGORY_CONFIG[cat.category].icon}
                        {cat.count}
                      </span>
                    ))}
                  </>
                )}
              </div>
            </div>

          </div>
        </div>
      </header>

      <Suspense fallback={<LoadingState />}>
        <MemoryPageContent />
      </Suspense>
    </div>
  );
}
