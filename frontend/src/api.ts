export class ApiError extends Error {
  status: number
  /** The whole error answer, for endpoints that send more than a message. */
  data: unknown

  constructor(status: number, message: string, data: unknown = null) {
    super(message)
    this.status = status
    this.data = data
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
    throw new ApiError(response.status, errorMessage(data, response.status), data)
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

export interface ZigbeeDevice {
  short: string
  name: string | null
  display_name: string
  ieee: string | null
  model: string | null
  manufacturer: string | null
  kind: 'light' | 'sensor' | 'remote' | 'other'
  power: boolean | null
  dimmer: number | null
  reachable: boolean | null
  battery: number | null
  link_quality: number | null
  /** Epoch seconds. */
  last_seen: number | null
  readings: { name: string; value: number | string; unit: string }[]
}

export interface ZigbeeMapNode {
  short: string
  type: 'coordinator' | 'router' | 'end_device'
  name: string | null
  known: boolean
}

export interface ZigbeeNetwork {
  devices: ZigbeeDevice[]
  join_open: boolean
  /** null while closed, or when open until the bridge restarts. */
  join_seconds_left: number | null
  map: { nodes: ZigbeeMapNode[]; links: { a: string; b: string; link_quality: number | null }[] } | null
  map_scanned_at: number | null
  map_scanning: boolean
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
  /** Set for Zigbee bridges. */
  zigbee: ZigbeeNetwork | null
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

export type OpenState = 'open' | 'closed' | 'unsupported' | 'unknown'
export type CarSide = 'front_left' | 'front_right' | 'rear_left' | 'rear_right'

export interface SkodaVehicle {
  vin: string
  name?: string
  title?: string
  model?: string
  model_year?: string
  license_plate?: string | null
  doors?: Record<CarSide, OpenState>
  windows?: Record<CarSide, OpenState>
  windows_overall?: OpenState
  trunk?: OpenState
  bonnet?: OpenState
  sunroof?: OpenState
  lock?: 'locked' | 'unlocked' | 'unknown'
  lights?: string
  position?: { latitude: number; longitude: number; address: string | null }
  mileage_km?: number | null
  fuel_percent?: number | null
  battery_percent?: number | null
  range_km?: number | null
  engine_type?: string | null
  captured_at?: string | null
  /** Parts the vehicle or account did not provide during the last refresh. */
  unavailable: string[]
  has_image: boolean
  updated_at: string
}

export interface SkodaAccount {
  connected: boolean
  username?: string | null
  last_sync?: string | null
  last_error?: string | null
}

export interface SkodaOverview {
  account: SkodaAccount
  vehicles: SkodaVehicle[]
}

export interface RadioStation {
  id: number
  slug: string
  name: string
  sub: string | null
  urls: string[]
  content_type: string | null
  sort_order: number
}

export type RadioStationInput = Pick<RadioStation, 'slug' | 'name' | 'sub' | 'urls' | 'content_type'>

/** A station as the Radiopanel gets it: no source addresses. */
export interface PanelStation {
  id: string
  name: string
  sub: string | null
}

export interface PanelStations {
  openhab_enabled: boolean
  openhab_start: string
  stations: PanelStation[]
}

export interface PanelStatus {
  stations: { id: string; name: string; listeners: number; title: string | null }[]
}

export interface MusicSource {
  id: number
  name: string
  kind: 'local' | 'smb'
  path: string | null
  network_path: string | null
  username: string | null
  has_password: boolean
  enabled: boolean
  last_scan_at: string | null
  last_scan_status: ScanStatus | null
  tracks: number
  missing: number
}

export interface MusicSourceInput {
  name: string
  kind: 'local' | 'smb'
  path?: string | null
  network_path?: string | null
  username?: string | null
  /** Left out when editing = the saved password stays. Never sent back by the server. */
  password?: string | null
  enabled: boolean
}

export interface MusicSourceTest {
  ok: boolean
  message: string
  tracks: number | null
}

export type ScanStatus = 'running' | 'done' | 'failed' | 'cancelled'

export interface MusicScan {
  id: number
  source_id: number
  started_at: string
  finished_at: string | null
  /** null when the schedule started it. */
  started_by: string | null
  status: ScanStatus
  added: number
  changed: number
  removed: number
  errors: number
  error_message: string | null
}

export interface MusicScanDetail extends MusicScan {
  added_files: string[]
  changed_files: string[]
  removed_files: string[]
  new_folders: string[]
  removed_folders: string[]
  error_list: string[]
}

export interface Track {
  id: number
  title: string
  artist: string
  album_id: number | null
  album: string | null
  track_no: number | null
  disc_no: number | null
  year: number | null
  genre: string | null
  duration_s: number | null
  format: string
  has_cover: boolean
}

export interface Album {
  id: number
  title: string
  artist: string
  year: number | null
  genre: string | null
  tracks: number
  duration_s: number
  has_cover: boolean
}

export interface Page<T> {
  items: T[]
  total: number
}

export interface Genre {
  /** null = tracks without a genre. */
  name: string | null
  tracks: number
  albums: number
}

export interface MusicLocation {
  id: number
  name: string
  tracks: number
}

export interface FolderListing {
  source_id: number
  source_name: string
  path: string
  folders: { name: string; path: string; tracks: number }[]
  tracks: Track[]
}

export interface PlayerState {
  status: 'stopped' | 'playing' | 'paused'
  index: number
  shuffle: boolean
  repeat: 'off' | 'all' | 'one'
  version: number
  current_id: number | null
  next_id: number | null
  queue: Track[]
}

/** What to play or add: a track, several, an album, or a folder with everything below it. */
export type PlaySelection =
  | { track_id: number }
  | { track_ids: number[] }
  | { album_id: number }
  | { source_id: number; path: string }
  | { playlist_id: number }

export interface MetadataStatus {
  online_enabled: boolean
  contact_set: boolean
  running: boolean
  /** Albums still waiting for a picture or an online lookup. */
  pending: number
  albums: number
  with_cover: number
  found: number
  not_found: number
  errors: number
}

export interface Playlist {
  id: number
  name: string
  /** Made by an administrator for the openpanel; everybody can play it. */
  panel: boolean
  editable: boolean
  tracks: number
  /** Entries that can be played now. */
  playable: number
  duration_s: number
}

export interface PlaylistEntry extends Track {
  entry_id: number
  available: boolean
}

export interface PlaylistDetail {
  playlist: Playlist
  tracks: PlaylistEntry[]
}

export type PanelKind = 'track' | 'album' | 'folder' | 'playlist'

export interface PanelItem {
  id: number
  section: 'favorites' | 'suggestions'
  kind: PanelKind
  ref: string
  title: string | null
  name: string
  available: boolean
  sort_order: number
}

export interface PanelContent {
  favorites: PanelItem[]
  suggestions: PanelItem[]
  playlists: Playlist[]
}
