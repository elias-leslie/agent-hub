export function getPersonaDisplayName(name?: string | null): string {
  const trimmed = name?.trim()
  return trimmed && trimmed.length > 0 ? trimmed : 'Persona'
}

export function getPersonaPossessive(name?: string | null): string {
  const displayName = getPersonaDisplayName(name)
  return displayName.endsWith('s') ? `${displayName}'` : `${displayName}'s`
}
