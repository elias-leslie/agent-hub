/** A context request the server refused or failed; the status lets the page say what to do about it. */
export class ContextHttpError extends Error {
  readonly status: number

  constructor(status: number, what?: string) {
    super(
      `Agent Hub answered ${status}${what ? ` for ${what.toLowerCase()}` : ''}`,
    )
    this.name = 'ContextHttpError'
    this.status = status
  }

  /** 401 and 403: the page is open to anyone, but this data is for the owner. */
  get needsOwner() {
    return this.status === 401 || this.status === 403
  }
}
