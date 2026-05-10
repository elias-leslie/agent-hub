'use client'

import { Settings } from 'lucide-react'
import { useState } from 'react'
import { PolicyModal } from './PolicyModal'
import styles from './runtime-context.module.css'

interface Props {
  profile: string
}

export function PolicySettingsPanel({ profile }: Props) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button
        type="button"
        className={styles.btn}
        onClick={() => setOpen(true)}
        title="Edit per-profile injection caps"
      >
        <Settings width={12} height={12} />
        Policy
      </button>
      <PolicyModal
        profile={profile}
        isOpen={open}
        onClose={() => setOpen(false)}
      />
    </>
  )
}
