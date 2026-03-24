export default function Loading() {
  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center">
      <div className="flex flex-col items-center gap-4">
        <div className="relative">
          <div className="w-12 h-12 rounded-full border-4 border-slate-800" />
          <div className="absolute inset-0 w-12 h-12 rounded-full border-4 border-transparent border-t-blue-500 animate-spin" />
        </div>
        <div className="space-y-2 text-center">
          <div className="h-4 w-32 bg-slate-200 dark:bg-slate-800 rounded animate-pulse" />
          <div className="h-3 w-24 bg-slate-200 dark:bg-slate-800 rounded animate-pulse mx-auto" />
        </div>
      </div>
    </div>
  );
}
