import { reactive } from 'vue'
import { api, type PanelStation, type PanelStations, type PanelStatus } from '../api'

const TITLE_INTERVAL_MS = 10000

type PlayState = 'idle' | 'connecting' | 'playing' | 'buffering' | 'error'

const state = reactive<{
  stations: PanelStation[]
  openhabEnabled: boolean
  openhabStart: string
  loaded: boolean
  currentId: string | null
  play: PlayState
  title: string
  errorCode: number
}>({
  stations: [],
  openhabEnabled: false,
  openhabStart: '',
  loaded: false,
  currentId: null,
  play: 'idle',
  title: '',
  errorCode: 0,
})

// One audio element for the whole application, so the sound goes on while other pages are open.
const audio = new Audio()
audio.preload = 'none'
let titleTimer: number | undefined

audio.addEventListener('playing', () => state.currentId && (state.play = 'playing'))
audio.addEventListener('waiting', () => state.currentId && (state.play = 'buffering'))
audio.addEventListener('error', () => {
  if (!state.currentId) return
  state.play = 'error'
  state.errorCode = audio.error?.code ?? 0
})

async function loadTitle() {
  const id = state.currentId
  if (!id) return
  try {
    const status = await api<PanelStatus>('GET', '/openpanel/status')
    if (state.currentId === id) state.title = status.stations.find((s) => s.id === id)?.title ?? ''
  } catch {
    // The title is a nicety; the sound does not depend on it.
  }
}

export const radio = {
  state,

  async load() {
    const data = await api<PanelStations>('GET', '/openpanel/stations')
    state.stations = data.stations
    state.openhabEnabled = data.openhab_enabled
    state.openhabStart = data.openhab_start
    state.loaded = true
  },

  play(station: PanelStation) {
    state.currentId = station.id
    state.play = 'connecting'
    state.title = ''
    audio.src = `/openpanel/radio/${encodeURIComponent(station.id)}`
    audio.play().catch(() => {})
    window.clearInterval(titleTimer)
    titleTimer = window.setInterval(loadTitle, TITLE_INTERVAL_MS)
    window.setTimeout(loadTitle, 3000)
  },

  stop() {
    state.currentId = null
    state.play = 'idle'
    state.title = ''
    window.clearInterval(titleTimer)
    audio.pause()
    // Without a source the connection to the server is closed and the station is released.
    audio.removeAttribute('src')
    audio.load()
  },
}
