/**
 * Follow-ups the host holds until the running turn ends: dashed chips above the composer. The host's queue has no
 * way to drop one, so a chip has no remove button.
 */
export function QueuedChips({ queued }: { queued: string[] }) {
  if (queued.length === 0) return null;
  return (
    <div className="mb-2 flex flex-wrap items-center gap-2 text-[12.5px] text-muted-foreground" data-testid="queued-chips">
      <span>Queued for after this turn:</span>
      <ul aria-label="Queued messages" className="m-0 flex min-w-0 list-none flex-wrap gap-2 p-0">
        {queued.map((text, index) => (
          <li
            key={`${index}:${text}`}
            data-testid="queued-message"
            className="min-w-0 max-w-full rounded-md border border-dashed border-input px-2.5 py-0.5 text-foreground"
          >
            <span className="block truncate" title={text}>
              {text}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
