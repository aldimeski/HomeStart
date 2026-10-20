<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { mdiGraphOutline, mdiZigbee } from '@mdi/js'
import type { TasmotaDevice } from '../api'
import { tasmota } from '../stores/tasmota'
import MdiIcon from './mdi-icon.vue'
import ToggleSwitch from './toggle-switch.vue'
import ZigbeeDeviceCard from './zigbee-device-card.vue'
import ZigbeeMapDialog from './zigbee-map-dialog.vue'

const props = defineProps<{ bridge: TasmotaDevice; isAdmin: boolean }>()

const network = computed(() => props.bridge.zigbee!)
const online = computed(() => props.bridge.online !== false)
const joinBusy = ref(false)
const error = ref('')
const showMap = ref(false)
const secondsLeft = ref<number | null>(null)
let deadline = 0
let timer: number | undefined

// The server sends the remaining time with each update; the browser counts down between updates.
watch(
  () => [network.value.join_open, network.value.join_seconds_left] as const,
  ([open, left]) => {
    window.clearInterval(timer)
    secondsLeft.value = open ? left : null
    if (open && left !== null) {
      deadline = Date.now() + left * 1000
      timer = window.setInterval(() => {
        secondsLeft.value = Math.max(0, Math.round((deadline - Date.now()) / 1000))
        if (secondsLeft.value === 0) window.clearInterval(timer)
      }, 1000)
    }
  },
  { immediate: true },
)
onBeforeUnmount(() => window.clearInterval(timer))

const joinOpen = computed(() => network.value.join_open && secondsLeft.value !== 0)

async function toggleJoin() {
  error.value = ''
  joinBusy.value = true
  try {
    await tasmota.zigbeeJoin(props.bridge.id, !joinOpen.value)
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Could not change pairing'
  } finally {
    joinBusy.value = false
  }
}
</script>

<template>
  <section class="mb-6" :aria-labelledby="`zigbee-${bridge.id}`">
    <div class="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2">
      <h2 :id="`zigbee-${bridge.id}`" class="flex items-center gap-1.5 text-sm font-semibold tracking-wide text-muted uppercase">
        <MdiIcon :path="mdiZigbee" :size="18" />
        Zigbee · {{ bridge.display_name }}
      </h2>
      <span class="text-xs text-muted">{{ network.devices.length }} device{{ network.devices.length === 1 ? '' : 's' }}</span>

      <div class="ml-auto flex items-center gap-3">
        <label v-if="isAdmin" class="flex items-center gap-2 text-sm">
          <span>
            Join
            <span v-if="joinOpen" class="font-medium text-accent">
              {{ secondsLeft === null ? 'open' : `${secondsLeft} s` }}
            </span>
          </span>
          <ToggleSwitch
            :checked="joinOpen"
            :disabled="!online"
            :busy="joinBusy"
            :label="joinOpen ? 'Close Zigbee pairing' : 'Allow new Zigbee devices to join for 60 seconds'"
            @toggle="toggleJoin"
          />
        </label>
        <span v-else-if="joinOpen" class="pill">Pairing open</span>
        <button type="button" class="btn px-2.5 py-1 text-sm" @click="showMap = true">
          <MdiIcon :path="mdiGraphOutline" :size="16" />
          Map
        </button>
      </div>
    </div>

    <p v-if="error" class="error-box mb-3" role="alert">{{ error }}</p>
    <p v-if="joinOpen && isAdmin" class="mb-3 rounded-lg bg-accent-soft px-3 py-2 text-sm text-accent" role="status">
      Pairing is open. Put the new device into pairing mode now; it appears here once the bridge has added it.
    </p>

    <div v-if="network.devices.length" class="grid grid-cols-[repeat(auto-fill,minmax(250px,1fr))] gap-4">
      <ZigbeeDeviceCard
        v-for="device in network.devices"
        :key="device.short"
        :device="device"
        :bridge-id="bridge.id"
        :bridge-online="online"
      />
    </div>
    <p v-else class="card p-4 text-sm text-muted">
      No Zigbee devices reported yet. {{ isAdmin ? 'Turn on Join to pair a device.' : '' }}
    </p>

    <ZigbeeMapDialog v-if="showMap" :bridge="bridge" :can-scan="isAdmin" @close="showMap = false" />
  </section>
</template>
