import { redirect } from 'next/navigation'

/**
 * The full session page was replaced by the session expanding in place in
 * the list. Old links (including ?tab=…) land on that expanded session.
 */
export default async function SessionRedirect({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = await params
  redirect(`/sessions?sel=${encodeURIComponent(id)}`)
}
