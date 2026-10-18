<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  mdiChevronDown,
  mdiChevronUp,
  mdiConsoleLine,
  mdiLock,
  mdiLockOpenVariantOutline,
  mdiLockOutline,
  mdiOpenInNew,
  mdiPencilOutline,
} from '@mdi/js'
import type { TasmotaChannel, TasmotaDevice } from '../api'
import { tasmota } from '../stores/tasmota'
import LinkIcon from './link-icon.vue'
import MdiIcon from './mdi-icon.vue'
import ToggleSwitch from './toggle-switch.vue'
import WifiSignal from './wifi-signal.vue'

const props = defineProps<{ device: TasmotaDevice; canEdit: boolean; consoleOpen?: boolean }>()
const emit = defineEmits<{ edit: [device: TasmotaDevice]; console: [device: TasmotaDevice] }>()

const SUMMARY_READINGS = ['Temperature', 'Humidity', 'Pressure', 'Illuminance', 'CO2']

const busyChannel = ref<number | null>(null)
const lockingChannel = ref<number | null>(null)
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
    showError(e instanceof Error ? e.message : 'Command failed')
  } finally {
    busyChannel.value = null
  }
}

async function toggleLock(channel: TasmotaChannel) {
  error.value = ''
  lockingChannel.value = channel.channel
  try {
    await tasmota.setLock(props.device.id, channel.channel, !channel.locked)
  } catch (e) {
    showError(e instanceof Error ? e.message : 'Could not change the lock')
  } finally {
    lockingChannel.value = null
  }
}

function showError(message: string) {
  error.value = message
  window.clearTimeout(errorTimer)
  errorTimer = window.setTimeout(() => (error.value = ''), 6000)
}

/** For screen readers and tooltips: a lone unnamed relay is named after its device. */
function accessibleName(channel: TasmotaChannel) {
  return channel.label ?? (props.device.channels.length === 1 ? props.device.display_name : channelLabel(channel))
}

function channelLabel(channel: TasmotaChannel) {
  if (channel.label) return channel.label
  return props.device.channels.length === 1 ? 'Power' : `Relay ${channel.channel}`
}
</script>

<template>
  <article class="card flex flex-col gap-2.5 p-4" :class="offline ? 'opacity-80' : ''">
    <header class="flex items-start gap-2">
      <div class="min-w-0 flex-1">
        <h3 class="flex items-center gap-2 font-bold" :title="device.friendly_name ?? undefined">
          <LinkIcon v-if="device.icon" :icon="device.icon" :size="22" />
          <span class="truncate">{{ device.display_name }}</span>
        </h3>
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
    </header>

    <p class="text-[15px]">{{ summary }}</p>

    <WifiSignal :rssi="device.wifi?.rssi" :signal="device.wifi?.signal" :muted="offline" />

    <ul v-if="device.channels.length" class="flex flex-col gap-1.5">
      <li v-for="channel in device.channels" :key="channel.channel" class="flex items-center gap-2 text-sm">
        <LinkIcon
          v-if="channel.icon"
          :icon="channel.icon"
          :size="22"
          :state="channel.state === 'ON' && !offline ? 'on' : 'off'"
          :class="offline ? 'opacity-50' : ''"
        />
        <span class="min-w-0 flex-1 truncate">{{ channelLabel(channel) }}</span>
        <button
          v-if="canEdit"
          class="btn-icon h-7 w-7"
          :class="channel.locked ? 'text-amber-600 dark:text-amber-400' : 'opacity-60 hover:opacity-100'"
          :disabled="lockingChannel === channel.channel"
          :aria-pressed="channel.locked"
          :aria-label="`${channel.locked ? 'Unlock' : 'Lock'} ${accessibleName(channel)}`"
          :title="channel.locked ? 'Locked: nobody can switch it. Click to unlock.' : 'Lock this switch so nobody can change it'"
          @click="toggleLock(channel)"
        >
          <MdiIcon :path="channel.locked ? mdiLock : mdiLockOpenVariantOutline" :size="16" />
        </button>
        <span v-else-if="channel.locked" class="text-amber-600 dark:text-amber-400" title="Locked by an administrator">
          <MdiIcon :path="mdiLock" :size="16" />
          <span class="sr-only">Locked by an administrator</span>
        </span>
        <ToggleSwitch
          :checked="channel.state === null ? null : channel.state === 'ON'"
          :disabled="offline || channel.locked || channel.state === null"
          :busy="busyChannel === channel.channel"
          :label="`Switch ${accessibleName(channel)} ${channel.state === 'ON' ? 'off' : 'on'}`"
          @toggle="toggle(channel)"
        />
      </li>
    </ul>

    <p v-if="error" class="error-box py-1.5" role="alert">{{ error }}</p>

    <div class="mt-auto flex flex-wrap items-center gap-2 pt-1">
      <a
        v-if="device.web_url && !offline"
        :href="device.web_url"
        target="_blank"
        rel="noopener noreferrer"
        class="btn px-2.5 py-1 text-sm whitespace-nowrap"
        title="Open the device's web interface in a new tab"
      >
        Web UI
        <MdiIcon :path="mdiOpenInNew" :size="14" />
      </a>
      <span v-else class="btn pointer-events-none px-2.5 py-1 text-sm whitespace-nowrap opacity-40" aria-disabled="true">
        Web UI
        <MdiIcon :path="mdiOpenInNew" :size="14" />
      </span>
      <button
        class="btn px-2.5 py-1 text-sm whitespace-nowrap"
        :class="consoleOpen ? 'border-accent text-accent' : ''"
        :aria-pressed="consoleOpen"
        :title="consoleOpen ? 'Close the console' : 'Show the live log below the devices'"
        @click="emit('console', device)"
      >
        <MdiIcon :path="mdiConsoleLine" :size="14" />
        Console
      </button>
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
