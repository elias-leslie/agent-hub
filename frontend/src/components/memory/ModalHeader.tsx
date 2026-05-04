import { Settings, X } from 'lucide-react'

export function ModalHeader({ onClose }: { onClose: () => void }) {
  return (
    <div className="flex items-center justify-between p-4 border-b border-slate-800">
      <div className="flex items-center gap-3">
        <div className="p-2 rounded-full bg-blue-900/30">
          <Settings className="w-5 h-5 text-amber-400" />
        </div>
        <h2 className="text-lg font-semibold text-slate-100">
          Memory Settings
        </h2>
      </div>
      <button
        onClick={onClose}
        className="p-1 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 cursor-pointer"
      >
        <X className="w-5 h-5" />
      </button>
    </div>
  )
}
