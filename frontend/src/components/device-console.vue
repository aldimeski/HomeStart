<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { mdiArrowCollapseDown, mdiClose, mdiDeleteSweepOutline, mdiPause, mdiPlay, mdiSend } from '@mdi/js'
import type { ConsoleLine, ConsoleSource, TasmotaDevice } from '../api'
import MdiIcon from './mdi-icon.vue'

const props = defineProps<{ device: TasmotaDevice }>()
const emit = defineEmits<{ close: [] }>()

const MAX_LINES = 1000
const MAX_HISTORY = 50
const RECONNECT_DELAY_MS = 3000
// Closed by the server on purpose (not found, not logged in, wrong origin); retrying would not help.
const FINAL_CLOSE_CODES = [4401, 4403, 4404]

type ServerMessage =
  | { type: 'hello'; source: ConsoleSource; notice: string | null; can_write: boolean; lines: ConsoleLine[] }
  | { type: 'source'; source: ConsoleSource; notice: string | null }
  | { type: 'lines'; lines: ConsoleLine[] }
  | { type: 'reset'; lines: ConsoleLine[] }

const lines = ref<ConsoleLine[]>([])
const pending = ref<ConsoleLine[]>([])
const paused = ref(false)
const autoScroll = ref(true)
const source = ref<ConsoleSource | null>(null)
const notice = ref<string | null>(null)
const canWrite = ref(false)
const connection = ref<'connecting' | 'live' | 'lost' | 'closed'>('connecting')
const command = ref('')
const output = ref<HTMLElement | null>(null)

const history: string[] = []
let historyIndex = -1
let socket: WebSocket | null = null
let reconnectTimer: number | undefined
let unmounted = false

function trim(list: ConsoleLine[]) {
  return list.length > MAX_LINES ? list.slice(-MAX_LINES) : list
}

async function scrollToEnd() {
  if (!autoScroll.value) return
  await nextTick()
  if (output.value) output.value.scrollTop = output.value.scrollHeight
}

function show(newLines: ConsoleLine[]) {
  if (paused.value) pending.value = trim([...pending.value, ...newLines])
  else {
    lines.value = trim([...lines.value, ...newLines])
    scrollToEnd()
  }
}

function onMessage(event: MessageEvent) {
  const message = JSON.parse(event.data) as ServerMessage
  switch (message.type) {
    case 'hello':
      canWrite.value = message.can_write
      source.value = message.source
      notice.value = message.notice
      lines.value = trim(message.lines)
      pending.value = []
      scrollToEnd()
      break
    case 'source':
      source.value = message.source
      notice.value = message.notice
      break
    case 'lines':
      show(message.lines)
      break
    case 'reset':
      lines.value = trim(message.lines)
      pending.value = []
      scrollToEnd()
      break
  }
}

function connect() {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  connection.value = 'connecting'
  socket = new WebSocket(`${protocol}//${location.host}/ws/tasmota/console/${props.device.id}`)
  socket.onopen = () => (connection.value = 'live')
  socket.onmessage = onMessage
  socket.onclose = (event) => {
    socket = null
    if (unmounted) return
    if (FINAL_CLOSE_CODES.includes(event.code)) {
      connection.value = 'closed'
      return
    }
    connection.value = 'lost'
    reconnectTimer = window.setTimeout(connect, RECONNECT_DELAY_MS)
  }
}

function togglePause() {
  paused.value = !paused.value
  if (!paused.value && pending.value.length) {
    lines.value = trim([...lines.value, ...pending.value])
    pending.value = []
    scrollToEnd()
  }
}

function clear() {
  lines.value = []
  pending.value = []
}

function toggleAutoScroll() {
  autoScroll.value = !autoScroll.value
  scrollToEnd()
}

function send() {
  const text = command.value.trim()
  if (!text || !socket || socket.readyState !== WebSocket.OPEN) return
  socket.send(JSON.stringify({ type: 'command', command: text }))
  if (history[history.length - 1] !== text) history.push(text)
  if (history.length > MAX_HISTORY) history.shift()
  historyIndex = -1
  command.value = ''
  // A sent command is something the user wants to see answered.
  if (paused.value) togglePause()
}

function browseHistory(step: number) {
  if (!history.length) return
  if (historyIndex === -1) historyIndex = history.length
  historyIndex = Math.min(Math.max(historyIndex + step, 0), history.length)
  command.value = historyIndex === history.length ? '' : history[historyIndex]
  if (historyIndex === history.length) historyIndex = -1
}

onMounted(connect)
onBeforeUnmount(() => {
  unmounted = true
  window.clearTimeout(reconnectTimer)
  socket?.close()
})
</script>

<template>
  <article class="card flex flex-col overflow-hidden" :aria-label="`Console of ${device.display_name}`">
    <header class="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line px-3 py-2">
      <h3 class="min-w-0 truncate font-semibold">{{ device.display_name }}</h3>
      <span v-if="connection === 'live' && source" class="pill" :title="source === 'http' ? 'Full device log over HTTP' : 'MQTT messages of this device'">
        {{ source === 'http' ? 'Live log' : 'MQTT only' }}
      </span>
      <span v-else-if="connection === 'connecting'" class="text-xs text-muted">Connecting…</span>
      <span v-else-if="connection === 'lost'" class="text-xs text-danger">Connection lost, reconnecting…</span>
      <span v-else class="text-xs text-danger">Console closed by the server</span>
      <span v-if="paused" class="text-xs text-muted">
        Paused{{ pending.length ? ` · ${pending.length} new line${pending.length === 1 ? '' : 's'}` : '' }}
      </span>

      <div class="ml-auto flex items-center gap-0.5">
        <button
          class="btn-icon h-8 w-8"
          :title="paused ? 'Resume' : 'Pause'"
          :aria-pressed="paused"
          @click="togglePause"
        >
          <MdiIcon :path="paused ? mdiPlay : mdiPause" :size="18" />
        </button>
        <button class="btn-icon h-8 w-8" title="Clear the display" @click="clear">
          <MdiIcon :path="mdiDeleteSweepOutline" :size="18" />
        </button>
        <button
          class="btn-icon h-8 w-8"
          :class="autoScroll ? 'text-accent' : ''"
          :title="autoScroll ? 'Auto-scroll is on' : 'Auto-scroll is off'"
          :aria-pressed="autoScroll"
          @click="toggleAutoScroll"
        >
          <MdiIcon :path="mdiArrowCollapseDown" :size="18" />
        </button>
        <button class="btn-icon h-8 w-8" title="Close the console" @click="emit('close')">
          <MdiIcon :path="mdiClose" :size="18" />
        </button>
      </div>
    </header>

    <p v-if="notice" class="border-b border-line bg-accent-soft px-3 py-1.5 text-xs text-accent" role="status">
      {{ notice }}
    </p>

    <div
      ref="output"
      class="console-output h-64 overflow-y-auto xl:h-auto xl:min-h-0 xl:flex-1 px-3 py-2 font-mono text-xs leading-5 break-all whitespace-pre-wrap"
      role="log"
      aria-live="off"
    >
      <p v-if="!lines.length" class="text-gray-500">No log lines yet.</p>
      <div
        v-for="line in lines"
        :key="line.id"
        :class="line.kind === 'command' ? 'text-sky-300' : line.kind === 'error' ? 'text-red-400' : ''"
      >{{ line.kind === 'command' ? `> ${line.text}` : line.text }}</div>
    </div>

    <form v-if="canWrite" class="flex gap-2 border-t border-line p-2" @submit.prevent="send">
      <label class="sr-only" :for="`console-command-${device.id}`">Command for {{ device.display_name }}</label>
      <input
        :id="`console-command-${device.id}`"
        v-model="command"
        class="input font-mono"
        maxlength="255"
        autocomplete="off"
        spellcheck="false"
        placeholder="Enter a command, e.g. Status 0"
        :disabled="connection !== 'live'"
        @keydown.up.prevent="browseHistory(-1)"
        @keydown.down.prevent="browseHistory(1)"
      />
      <button type="submit" class="btn" :disabled="connection !== 'live' || !command.trim()" title="Send command">
        <MdiIcon :path="mdiSend" :size="16" />
        <span class="hidden sm:inline">Send</span>
      </button>
    </form>
    <p v-else-if="connection === 'live'" class="border-t border-line px-3 py-2 text-xs text-muted">
      Read only. Only administrators can send commands.
    </p>
  </article>
</template>

<style scoped>
/* A terminal look in both themes, so log lines read the same everywhere. */
.console-output {
  background: #111418;
  color: #d4d7dc;
}
</style>
