<script setup lang="ts">
import { computed, ref } from 'vue'
import { mdiChevronDown, mdiChevronUp, mdiLockOutline, mdiOpenInNew, mdiPencilOutline } from '@mdi/js'
import type { TasmotaChannel, TasmotaDevice } from '../api'
import { tasmota } from '../stores/tasmota'
import MdiIcon from './mdi-icon.vue'
import ToggleSwitch from './toggle-switch.vue'
import WifiSignal from './wifi-signal.vue'

const props = defineProps<{ device: TasmotaDevice; canEdit: boolean }>()
const emit = defineEmits<{ edit: [device: TasmotaDevice] }>()

const SUMMARY_READINGS = ['Temperature', 'Humidity', 'Pressure', 'Illuminance', 'CO2']

const busyChannel = ref<number | null>(null)
const error = ref('')
const showDetails = ref(false)
let errorTimer: number | undefined

const offline = computed(() => props.device.online === false)

const statusLabel = computed(() => {
  if (props.device.online === true) return 'Online'
  if (props.device.online === false) return 'Offline'
  return 'Unknown'
})

function formatValue(value: number, unit: string) {
  return unit ? `${value} ${unit}` : String(value)
}

const summary = computed(() => {
  const readings = props.device.sensors
  const picked = SUMMARY_READINGS.flatMap((name) => {
    const reading = readings.find((r) => r.name === name)
    return reading ? [formatValue(reading.value, reading.unit)] : []
  })
  const power = readings.find((r) => r.sensor === 'ENERGY' && r.name === 'Power')
  if (power) picked.push(formatValue(power.value, power.unit))
  if (picked.length) return picked.join(' · ')

  if (offline.value || !props.device.channels.some((c) => c.state)) return 'No data'
  const channels = props.device.channels
  if (channels.length === 1) return channels[0].state === 'ON' ? 'Power on' : 'Power off'
  const on = channels.filter((c) => c.state === 'ON').length
  return channels.length ? `${on} of ${channels.length} on` : 'No relays'
})

const details = computed(() => {
  const d = props.device
  return [
    ['Model', d.model],
    ['Firmware', d.firmware],
    ['IP address', d.host],
    ['MAC address', d.mac],
    ['Uptime', d.uptime],
    ['MQTT topic', d.topic],
    ['Last seen', d.last_seen ? new Date(`${d.last_seen}Z`).toLocaleString() : null],
  ].filter((row): row is [string, string] => !!row[1])
})

async function toggle(channel: TasmotaChannel) {
  error.value = ''
  busyChannel.value = channel.channel
  try {
    await tasmota.setPower(props.device.id, channel.channel, channel.state === 'ON' ? 'off' : 'on')
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Command failed'
    window.clearTimeout(errorTimer)
    errorTimer = window.setTimeout(() => (error.value = ''), 6000)
  } finally {
    busyChannel.value = null
  }
}

function channelLabel(channel: TasmotaChannel) {
  return channel.label || `Relay ${channel.channel}`
}
</script>

<template>
  <article class="card flex flex-col gap-2.5 p-4" :class="offline ? 'opacity-80' : ''">
    <header class="flex items-start gap-2">
      <div class="min-w-0 flex-1">
        <h3 class="truncate font-bold" :title="device.friendly_name ?? undefined">{{ device.display_name }}</h3>
        <p class="flex items-center gap-1.5 text-sm text-muted">
          <span
            class="h-2 w-2 rounded-full"
            :class="device.online ? 'bg-emerald-500' : device.online === false ? 'bg-gray-400' : 'bg-amber-400'"
            aria-hidden="true"
          />
          {{ statusLabel }}
          <MdiIcon
            v-if="device.auth_required"
            :path="mdiLockOutline"
            :size="14"
            class="ml-1"
            title="The web interface requires a login"
          />
        </p>
      </div>
      <button v-if="canEdit" class="btn-icon -mt-1 -mr-1 h-8 w-8" title="Edit device" @click="emit('edit', device)">
        <MdiIcon :path="mdiPencilOutline" :size="18" />
      </button>
      <ToggleSwitch
        v-if="device.channels.length === 1"
        :checked="device.channels[0].state === null ? null : device.channels[0].state === 'ON'"
        :disabled="offline || device.channels[0].state === null"
        :busy="busyChannel === 1"
        :label="`Switch ${device.display_name} ${device.channels[0].state === 'ON' ? 'off' : 'on'}`"
        @toggle="toggle(device.channels[0])"
      />
    </header>

    <p class="text-[15px]">{{ summary }}</p>

    <ul v-if="device.channels.length > 1" class="flex flex-col gap-1.5">
      <li v-for="channel in device.channels" :key="channel.channel" class="flex items-center gap-2 text-sm">
        <span class="min-w-0 flex-1 truncate">{{ channelLabel(channel) }}</span>
        <ToggleSwitch
          :checked="channel.state === null ? null : channel.state === 'ON'"
          :disabled="offline || channel.state === null"
          :busy="busyChannel === channel.channel"
          :label="`Switch ${channelLabel(channel)} ${channel.state === 'ON' ? 'off' : 'on'}`"
          @toggle="toggle(channel)"
        />
      </li>
    </ul>

    <p v-if="error" class="error-box py-1.5" role="alert">{{ error }}</p>

    <WifiSignal :rssi="device.wifi?.rssi" :signal="device.wifi?.signal" :muted="offline" />

    <div class="mt-auto flex items-center gap-2 pt-1">
      <a
        v-if="device.web_url && !offline"
        :href="device.web_url"
        target="_blank"
        rel="noopener noreferrer"
        class="btn px-2.5 py-1 text-sm"
      >
        Open web UI
        <MdiIcon :path="mdiOpenInNew" :size="14" />
      </a>
      <span v-else class="btn pointer-events-none px-2.5 py-1 text-sm opacity-40" aria-disabled="true">
        Open web UI
        <MdiIcon :path="mdiOpenInNew" :size="14" />
      </span>
      <button
        class="ml-auto inline-flex items-center gap-0.5 text-xs text-muted hover:text-ink"
        :aria-expanded="showDetails"
        @click="showDetails = !showDetails"
      >
        Details
        <MdiIcon :path="showDetails ? mdiChevronUp : mdiChevronDown" :size="16" />
      </button>
    </div>

    <dl v-if="showDetails" class="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 border-t border-line pt-2 text-xs">
      <template v-for="[label, value] in details" :key="label">
        <dt class="text-muted">{{ label }}</dt>
        <dd class="break-words">{{ value }}</dd>
      </template>
      <template v-for="reading in device.sensors" :key="`${reading.sensor}-${reading.name}`">
        <dt class="text-muted">{{ reading.sensor === 'ENERGY' ? 'Energy' : reading.sensor }} {{ reading.name }}</dt>
        <dd>{{ formatValue(reading.value, reading.unit) }}</dd>
      </template>
    </dl>
  </article>
</template>
