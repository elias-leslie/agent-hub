export default function Loading() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="flex flex-col items-center gap-5 animate-fade-up">
        <div className="relative">
          <div className="w-12 h-12 rounded-full border-4 border-slate-800/60" />
          <div className="absolute inset-0 w-12 h-12 rounded-full border-4 border-transparent border-t-amber-500 animate-spin" />
        </div>
        <div className="space-y-2 text-center">
          <div className="h-4 w-32 rounded-lg animate-shimmer" />
          <div className="h-3 w-24 rounded-lg animate-shimmer mx-auto" />
        </div>
      </div>
    </div>
  )
}
