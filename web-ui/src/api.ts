// Read-only client for /api/v1 (GET only; the dashboard never writes through the API).

export class ApiError extends Error {
  readonly status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export interface Envelope<T> {
  data: T
  as_of: string
}

export interface ListEnvelope<T> {
  items: T[]
  as_of: string
  next: string | null
}

export const SIGNIN_PATH = '/app/signin'

/** Where the sign-in page sends people back to: a same-site /app/ path, the server checks it again on /login. */
export function signinUrl(next: string): string {
  const target = next.startsWith('/app/') && !next.startsWith('/app/signin') ? next : '/app/'
  return `${SIGNIN_PATH}?next=${encodeURIComponent(target)}`
}

export interface GetOptions {
  /** Default true: a 401 sends the browser to the sign-in page. The route guard sets false and routes itself. */
  redirectOn401?: boolean
}

export async function apiGet<T>(path: string, params?: Record<string, string | number>, opts: GetOptions = {}): Promise<T> {
  const qs = params ? '?' + new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])).toString() : ''
  let resp: Response
  try {
    resp = await fetch(`/api/v1${path}${qs}`, { method: 'GET', credentials: 'same-origin', headers: { Accept: 'application/json' } })
  } catch (e) {
    throw new ApiError(0, `network error: ${e instanceof Error ? e.message : String(e)}`) // status 0 = never reached the server (offline)
  }
  if (resp.status === 401 && opts.redirectOn401 !== false) {
    if (!window.location.pathname.startsWith(SIGNIN_PATH)) window.location.assign(signinUrl(window.location.pathname + window.location.search))
    throw new ApiError(401, 'unauthorized')
  }
  if (!resp.ok) {
    const detail = await resp.json().then(
      (b: unknown) => (typeof b === 'object' && b !== null && 'error' in b ? String((b as { error: unknown }).error) : ''),
      () => '', // body is not JSON: keep the status only
    )
    throw new ApiError(resp.status, detail || `HTTP ${resp.status}`)
  }
  return (await resp.json()) as T
}

export interface Me {
  account: string
}

export function getMe(opts?: GetOptions): Promise<Envelope<Me>> {
  return apiGet<Envelope<Me>>('/me', undefined, opts)
}
