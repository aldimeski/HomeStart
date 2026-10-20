<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  mdiBattery,
  mdiBattery20,
  mdiBattery50,
  mdiBattery80,
  mdiLightbulbOutline,
  mdiRemote,
  mdiThermometer,
  mdiZigbee,
} from '@mdi/js'
import type { ZigbeeDevice } from '../api'
import { tasmota } from '../stores/tasmota'
import MdiIcon from './mdi-icon.vue'
import ToggleSwitch from './toggle-switch.vue'

const props = defineProps<{ device: ZigbeeDevice; bridgeId: number; bridgeOnline: boolean }>()

const busy = ref(false)
const error = ref('')
let errorTimer: number | undefined

const kindIcon = computed(
  () => ({ light: mdiLightbulbOutline, sensor: mdiThermometer, remote: mdiRemote, other: mdiZigbee })[props.device.kind],
)

const batteryIcon = computed(() => {
  const level = props.device.battery ?? 0
  if (level >= 90) return mdiBattery
  if (level >= 60) return mdiBattery80
  if (level >= 30) return mdiBattery50
  return mdiBattery20
})

// Battery devices sleep between reports, so "not reachable" is normal for them; their last report matters.
const status = computed(() => {
  const d = props.device
  if (d.kind === 'light' || d.battery === null) {
    if (d.reachable === false) return { text: 'Not reachable', dot: 'bg-gray-400' }
    return { text: 'Reachable', dot: 'bg-emerald-500' }
  }
  return { text: d.last_seen ? `Last report ${ago(d.last_seen)}` : 'No report yet', dot: 'bg-sky-500' }
})

function ago(epoch: number) {
  const minutes = Math.round((Date.now() / 1000 - epoch) / 60)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 48) return `${hours} h ago`
  return `${Math.round(hours / 24)} days ago`
}

function formatReading(reading: ZigbeeDevice['readings'][number]) {
  return reading.unit ? `${reading.value} ${reading.unit}` : String(reading.value)
}

async function toggle() {
  error.value = ''
  busy.value = true
  try {
    await tasmota.zigbeePower(props.bridgeId, props.device.short, props.device.power ? 'off' : 'on')
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Command failed'
    window.clearTimeout(errorTimer)
    errorTimer = window.setTimeout(() => (error.value = ''), 6000)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <article class="card flex flex-col gap-2.5 p-4" :class="bridgeOnline ? '' : 'opacity-80'">
    <header class="flex items-start gap-2">
      <MdiIcon
        :path="kindIcon"
        :size="22"
        class="mt-0.5"
        :class="device.kind === 'light' && device.power ? 'text-amber-500 dark:text-amber-400' : 'text-muted'"
      />
      <div class="min-w-0 flex-1">
        <h3 class="truncate font-bold" :title="device.name ?? device.short">{{ device.display_name }}</h3>
        <p class="flex items-center gap-1.5 text-sm text-muted">
          <span class="h-2 w-2 shrink-0 rounded-full" :class="status.dot" aria-hidden="true" />
          <span class="truncate">{{ status.text }}</span>
        </p>
      </div>
    </header>

    <p v-if="device.model" class="truncate text-xs text-muted" :title="`${device.manufacturer ?? ''} ${device.model}`">
      {{ device.model }}
    </p>

    <div v-if="device.kind === 'light'" class="flex items-center gap-2 text-sm">
      <span class="flex-1">
        {{ device.power === null ? 'State unknown' : device.power ? 'On' : 'Off' }}
        <span v-if="device.power && device.dimmer !== null" class="text-muted">· {{ Math.round((device.dimmer / 254) * 100) }} %</span>
      </span>
      <ToggleSwitch
        :checked="device.power"
        :disabled="!bridgeOnline || device.power === null"
        :busy="busy"
        :label="`Switch ${device.display_name} ${device.power ? 'off' : 'on'}`"
        @toggle="toggle"
      />
    </div>

    <ul v-if="device.readings.length" class="space-y-0.5 text-sm">
      <li v-for="reading in device.readings" :key="reading.name" class="flex justify-between gap-2">
        <span class="text-muted">{{ reading.name }}</span>
        <span class="font-medium">{{ formatReading(reading) }}</span>
      </li>
    </ul>

    <p v-if="error" class="error-box py-1.5" role="alert">{{ error }}</p>

    <footer class="mt-auto flex items-center gap-3 pt-1 text-xs text-muted">
      <span v-if="device.battery !== null" class="inline-flex items-center gap-1" :title="`Battery ${device.battery} %`">
        <MdiIcon :path="batteryIcon" :size="16" :class="device.battery < 20 ? 'text-danger' : ''" />
        {{ device.battery }} %
      </span>
      <span v-if="device.link_quality !== null" :title="'Zigbee link quality (0–255)'">LQI {{ device.link_quality }}</span>
      <span class="ml-auto font-mono">{{ device.short }}</span>
    </footer>
  </article>
</template>
