import { computed, reactive } from 'vue'
import { api, type TasmotaDevice } from '../api'

const RECONNECT_DELAY_MS = 3000

type ServerMessage =
  | { type: 'snapshot'; devices: TasmotaDevice[]; mqtt_connected: boolean }
  | { type: 'device'; device: TasmotaDevice }
  | { type: 'removed'; id: number }
  | { type: 'mqtt'; connected: boolean }

const state = reactive({
  devices: [] as TasmotaDevice[],
  mqttConnected: true,
  liveConnected: false,
  loaded: false,
})

let socket: WebSocket | null = null
let wanted = false
let reconnectTimer: number | undefined

function sortDevices(devices: TasmotaDevice[]) {
  return devices.sort(
    (a, b) =>
      (a.group_name ?? '').localeCompare(b.group_name ?? '') || a.display_name.localeCompare(b.display_name),
  )
}

function upsert(device: TasmotaDevice) {
  const index = state.devices.findIndex((item) => item.id === device.id)
  if (index === -1) {
    state.devices.push(device)
    sortDevices(state.devices)
  } else {
    const nameChanged =
      state.devices[index].display_name !== device.display_name || state.devices[index].group_name !== device.group_name
    state.devices[index] = device
    if (nameChanged) sortDevices(state.devices)
  }
}

function onMessage(event: MessageEvent) {
  const message = JSON.parse(event.data) as ServerMessage
  switch (message.type) {
    case 'snapshot':
      state.devices = sortDevices(message.devices)
      state.mqttConnected = message.mqtt_connected
      state.loaded = true
      break
    case 'device':
      upsert(message.device)
      break
    case 'removed':
      state.devices = state.devices.filter((device) => device.id !== message.id)
      break
    case 'mqtt':
      state.mqttConnected = message.connected
      break
  }
}

function open() {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  socket = new WebSocket(`${protocol}//${location.host}/ws/tasmota`)
  socket.onopen = () => (state.liveConnected = true)
  socket.onmessage = onMessage
  socket.onclose = () => {
    state.liveConnected = false
    socket = null
    if (wanted) reconnectTimer = window.setTimeout(open, RECONNECT_DELAY_MS)
  }
}

export const tasmota = {
  state,
  onlineCount: computed(() => state.devices.filter((device) => device.online).length),

  /** Starts live updates; the server sends the full list first and then every change. */
  connect() {
    wanted = true
    if (!socket) open()
  },

  disconnect() {
    wanted = false
    window.clearTimeout(reconnectTimer)
    socket?.close()
    socket = null
  },

  refresh() {
    return api('POST', '/api/tasmota/refresh')
  },

  async setPower(id: number, channel: number, action: 'on' | 'off' | 'toggle') {
    upsert(await api<TasmotaDevice>('POST', `/api/tasmota/devices/${id}/power`, { channel, action }))
  },

  async update(id: number, data: { name: string | null; group_name: string | null }) {
    upsert(await api<TasmotaDevice>('PUT', `/api/tasmota/devices/${id}`, data))
  },

  async add(data: { name: string | null; host: string; port: number; group_name: string | null }) {
    upsert(await api<TasmotaDevice>('POST', '/api/tasmota/devices', data))
  },

  async remove(id: number) {
    await api('DELETE', `/api/tasmota/devices/${id}`)
    state.devices = state.devices.filter((device) => device.id !== id)
  },
}
