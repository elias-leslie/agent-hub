import { useEffect, useState } from 'react'

interface ConfirmationModalProps {
  isOpen: boolean
  onClose: () => void
  onConfirm: (reason: string) => void
  title: string
  description: string
  confirmText: string
  confirmClassName: string
  isPending: boolean
  isDanger?: boolean
}

export function ConfirmationModal({
  isOpen,
  onClose,
  onConfirm,
  title,
  description,
  confirmText,
  confirmClassName,
  isPending,
  isDanger = false,
}: ConfirmationModalProps) {
  const [reason, setReason] = useState('')

  useEffect(() => {
    if (!isOpen) setReason('')
  }, [isOpen])

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4 backdrop-blur-sm">
      <div className="panel-surface max-w-md w-full p-6">
        <p className="section-kicker">
          {isDanger ? 'Permanent Block' : 'Temporary Suspension'}
        </p>
        <h3
          className={`section-heading mt-2 ${isDanger ? 'text-red-300' : 'text-slate-100'}`}
        >
          {title}
        </h3>
        <p className="section-copy mt-2 mb-4">{description}</p>
        <input
          type="text"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder={`Reason for ${isDanger ? 'blocking' : 'suspension'}`}
          className={`control-input ${
            isDanger ? 'focus:border-red-500' : 'focus:border-amber-500'
          } mb-4`}
        />
        <div className="flex gap-3">
          <button
            onClick={onClose}
            className="button-secondary flex-1 justify-center"
          >
            Cancel
          </button>
          <button
            onClick={() => onConfirm(reason)}
            disabled={!reason.trim() || isPending}
            className={`flex-1 rounded-xl px-4 py-2.5 text-sm font-medium text-white transition disabled:cursor-not-allowed disabled:opacity-50 ${confirmClassName}`}
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  )
}
