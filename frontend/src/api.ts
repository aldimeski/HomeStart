export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

type UnauthorizedHandler = () => void
let onUnauthorized: UnauthorizedHandler = () => {}

export function setUnauthorizedHandler(handler: UnauthorizedHandler) {
  onUnauthorized = handler
}

function errorMessage(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length) {
    // FastAPI validation errors: show the first message without the "Value error," prefix.
    const msg = String(detail[0]?.msg ?? 'Invalid input')
    return msg.replace(/^Value error, /, '')
  }
  return `Request failed (${status})`
}

export async function api<T = unknown>(
  method: string,
  url: string,
  body?: unknown,
  options: { skipUnauthorizedHandler?: boolean } = {},
): Promise<T> {
  const headers: Record<string, string> = { 'X-HomeStart': '1' }
  let payload: BodyInit | undefined
  if (body instanceof FormData) {
    payload = body
  } else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }

  const response = await fetch(url, { method, headers, body: payload, credentials: 'same-origin' })
  if (response.status === 204) return undefined as T

  const data = await response.json().catch(() => null)
  if (!response.ok) {
    if (response.status === 401 && !options.skipUnauthorizedHandler) onUnauthorized()
    throw new ApiError(response.status, errorMessage(data, response.status))
  }
  return data as T
}

export interface User {
  id: number
  username: string
  role: 'admin' | 'user'
  is_active: boolean
  created_at: string
  last_login: string | null
}

export type Theme = 'system' | 'light' | 'dark'

export interface UserSettings {
  theme: Theme
  sidebar_collapsed: boolean
  sholink_expanded: boolean
}

export interface Me {
  user: User
  settings: UserSettings
}

export interface Link {
  id: number
  title: string
  url: string
  icon: string
  open_in_new_tab: boolean
  sort_order: number
}

export type LinkInput = Pick<Link, 'title' | 'url' | 'icon' | 'open_in_new_tab'>

export interface EmbedCheck {
  reachable: boolean
  embeddable: boolean | null
  reason: string | null
}

export interface TasmotaChannel {
  channel: number
  /** Name set in HomeStart, otherwise the device's FriendlyName. */
  label: string | null
  custom_label: string | null
  device_label: string | null
  state: 'ON' | 'OFF' | null
  /** Locked by an administrator: nobody can switch it until it is unlocked. */
  locked: boolean
  icon: string | null
}

export interface SensorReading {
  sensor: string
  name: string
  value: number
  unit: string
}

export interface TasmotaDevice {
  id: number
  name: string | null
  display_name: string
  friendly_name: string | null
  icon: string | null
  topic: string | null
  host: string | null
  port: number
  mac: string | null
  hostname: string | null
  firmware: string | null
  model: string | null
  group_name: string | null
  source: 'mqtt' | 'scan' | 'manual'
  auth_required: boolean
  online: boolean | null
  last_seen: string | null
  channels: TasmotaChannel[]
  sensors: SensorReading[]
  wifi: { rssi?: number; signal?: number } | null
  uptime: string | null
  web_url: string | null
}

export interface ConsoleLine {
  id: number
  kind: 'log' | 'command' | 'error'
  text: string
}

export type ConsoleSource = 'http' | 'mqtt'

export interface ScanResult {
  subnet: string
  found: number
  new: number
  auth_required: number
}
