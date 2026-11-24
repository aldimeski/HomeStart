import { reactive, watch } from 'vue'
import { api, type PlaySelection, type PlayerState, type Track } from '../api'
import { radio } from './radio'

const CLIENT_KEY = 'homestart-player-client'
// The next track is loaded this many seconds before the current one ends, so the change is without a pause.
const PRELOAD_SECONDS = 20
// "Previous" restarts the track when it has been playing longer than this.
const RESTART_AFTER_SECONDS = 3

type Command = { action: string } & Record<string, unknown>

// crypto.randomUUID() exists only on HTTPS and localhost; HomeStart is normally opened over plain HTTP on the local network.
function randomId(): string {
  const bytes = new Uint8Array(16)
  if (typeof crypto !== 'undefined' && crypto.getRandomValues) crypto.getRandomValues(bytes)
  else bytes.forEach((_, i) => (bytes[i] = Math.floor(Math.random() * 256)))
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
}

function makeClientId(): string {
  try {
    const stored = localStorage.getItem(CLIENT_KEY)
    if (stored) return stored
    const created = randomId()
    localStorage.setItem(CLIENT_KEY, created)
    return created
  } catch {
    return randomId()
  }
}

// One session of the server per browser: the queue stays when the page is reloaded.
const clientId = makeClientId()

const state = reactive({
  loaded: false,
  status: 'stopped' as PlayerState['status'],
  index: 0,
  shuffle: false,
  repeat: 'off' as PlayerState['repeat'],
  version: -1,
  currentId: null as number | null,
  nextId: null as number | null,
  queue: [] as Track[],
  position: 0,
  duration: 0,
  volume: 1,
  waiting: false,
  error: '',
})

// Two audio elements: one plays while the other has the next track loaded, so the change needs no loading.
const elements = [new Audio(), new Audio()]
const loadedId: (number | null)[] = [null, null]
let active = 0
let events: EventSource | null = null
let stopWatching: (() => void) | null = null

const streamUrl = (id: number) => `/player/stream/${id}?sid=${encodeURIComponent(clientId)}`
const playing = () => elements[active]

function release(index: number) {
  const element = elements[index]
  element.pause()
  // Without a source the connection to the server is closed.
  element.removeAttribute('src')
  element.load()
  loadedId[index] = null
}

function load(index: number, id: number) {
  loadedId[index] = id
  elements[index].src = streamUrl(id)
}

function preloadNext() {
  const next = state.nextId
  const spare = 1 - active
  if (next === null) {
    if (loadedId[spare] !== null) release(spare)
    return
  }
  if (loadedId[spare] === next) return
  if (loadedId[spare] !== null) release(spare)
  const element = playing()
  const remaining = Number.isFinite(element.duration) ? element.duration - element.currentTime : Infinity
  if (remaining < PRELOAD_SECONDS) load(spare, next)
}

function sync() {
  const id = state.currentId
  if (state.status === 'stopped' || id === null) {
    release(0)
    release(1)
    state.position = 0
    state.duration = 0
    return
  }
  if (loadedId[active] !== id) {
    if (loadedId[1 - active] === id) {
      // Already loaded ahead: change over to it.
      release(active)
      active = 1 - active
    } else {
      load(active, id)
    }
  }
  if (loadedId[1 - active] !== null && loadedId[1 - active] !== state.nextId) release(1 - active)
  const element = playing()
  if (state.status === 'playing') {
    if (radio.state.currentId) radio.stop()
    element.play().catch((e: unknown) => {
      // The browser did not allow sound without a click: stay paused instead of pretending to play.
      if (e instanceof DOMException && e.name === 'NotAllowedError') send({ action: 'pause' })
    })
  } else {
    element.pause()
  }
  preloadNext()
}

function apply(next: PlayerState) {
  // Answers and events may arrive out of order; an older one must not undo a newer one.
  if (next.version < state.version) return
  state.version = next.version
  state.status = next.status
  state.index = next.index
  state.shuffle = next.shuffle
  state.repeat = next.repeat
  state.currentId = next.current_id
  state.nextId = next.next_id
  state.queue = next.queue
  state.loaded = true
  sync()
  updateMediaSession()
}

async function send(command: Command) {
  state.error = ''
  try {
    apply(await api<PlayerState>('POST', '/api/player/session/command', { client_id: clientId, ...command }))
  } catch (e) {
    state.error = e instanceof Error ? e.message : 'The player could not do that'
  }
}

function onEnded(index: number) {
  if (index !== active) return
  if (state.repeat === 'one') {
    elements[active].currentTime = 0
    elements[active].play().catch(() => {})
    return
  }
  const spare = 1 - active
  if (state.nextId !== null && loadedId[spare] === state.nextId && elements[spare].readyState >= 2) {
    // Start the track that is ready at once; the server's answer then finds it already playing.
    const finished = active
    active = spare
    elements[active].play().catch(() => {})
    release(finished)
  }
  send({ action: 'ended' })
}

function onTimeUpdate(index: number) {
  if (index !== active) return
  const element = elements[active]
  state.position = element.currentTime
  const known = state.queue[state.index]?.duration_s ?? 0
  state.duration = Number.isFinite(element.duration) ? element.duration : known
  if (state.status === 'playing') preloadNext()
}

elements.forEach((element, index) => {
  element.preload = 'auto'
  element.addEventListener('ended', () => onEnded(index))
  element.addEventListener('timeupdate', () => onTimeUpdate(index))
  element.addEventListener('waiting', () => index === active && (state.waiting = true))
  element.addEventListener('playing', () => index === active && (state.waiting = false))
  element.addEventListener('error', () => {
    if (loadedId[index] === null) return
    if (index === active) {
      const title = state.queue[state.index]?.title ?? 'this track'
      state.error = `Cannot play "${title}"`
      send({ action: 'error' })
    } else {
      release(index)
    }
  })
})

function updateMediaSession() {
  if (!('mediaSession' in navigator)) return
  const track = state.queue[state.index]
  navigator.mediaSession.metadata = track
    ? new MediaMetadata({ title: track.title, artist: track.artist, album: track.album ?? '' })
    : null
  navigator.mediaSession.playbackState = state.status === 'playing' ? 'playing' : state.status === 'paused' ? 'paused' : 'none'
}

function setUpMediaKeys() {
  if (!('mediaSession' in navigator)) return
  const handlers: [MediaSessionAction, () => void][] = [
    ['play', () => player.resume()],
    ['pause', () => player.pause()],
    ['stop', () => player.stop()],
    ['nexttrack', () => player.next()],
    ['previoustrack', () => player.prev()],
  ]
  for (const [action, handler] of handlers) navigator.mediaSession.setActionHandler(action, handler)
}

export const player = {
  state,

  /** Joins the listening session of this browser; call once the user is logged in. */
  async init() {
    if (events) return
    setUpMediaKeys()
    // A reloaded page does not start sound by itself.
    stopWatching = watch(
      () => radio.state.currentId,
      (id) => id && state.status === 'playing' && send({ action: 'pause' }),
    )
    try {
      const first = await api<PlayerState>('GET', `/api/player/session?client_id=${encodeURIComponent(clientId)}`)
      const wasPlaying = first.status === 'playing'
      if (wasPlaying) first.status = 'paused'
      apply(first)
      if (wasPlaying) await send({ action: 'pause' })
    } catch {
      // The page still works without it; the next command tries again.
    }
    events = new EventSource(`/api/player/session/events?client_id=${encodeURIComponent(clientId)}`)
    events.onmessage = (message) => apply(JSON.parse(message.data) as PlayerState)
  },

  dispose() {
    events?.close()
    events = null
    stopWatching?.()
    release(0)
    release(1)
  },

  play: (selection: PlaySelection, options: { startTrackId?: number; shuffle?: boolean } = {}) =>
    send({ action: 'play', ...selection, start_track_id: options.startTrackId, shuffle: options.shuffle }),
  enqueue: (selection: PlaySelection) => send({ action: 'enqueue', ...selection }),
  playNext: (selection: PlaySelection) => send({ action: 'play_next', ...selection }),
  pause: () => send({ action: 'pause' }),
  resume: () => send({ action: 'resume' }),
  stop: () => send({ action: 'stop' }),
  next: () => send({ action: 'next' }),
  jump: (index: number) => send({ action: 'jump', index }),
  clear: () => send({ action: 'clear' }),
  toggle: () => (state.status === 'playing' ? player.pause() : player.resume()),
  toggleShuffle: () => send({ action: 'shuffle', on: !state.shuffle }),
  cycleRepeat: () => send({ action: 'repeat', mode: state.repeat === 'off' ? 'all' : state.repeat === 'all' ? 'one' : 'off' }),

  prev() {
    // Like most players: a track that has been playing a while starts again, a new one goes back.
    if (playing().currentTime > RESTART_AFTER_SECONDS || state.index === 0) {
      playing().currentTime = 0
      state.position = 0
      return
    }
    return send({ action: 'prev' })
  },

  seek(seconds: number) {
    playing().currentTime = seconds
    state.position = seconds
  },

  setVolume(volume: number) {
    state.volume = volume
    elements.forEach((element) => (element.volume = volume))
  },
}
