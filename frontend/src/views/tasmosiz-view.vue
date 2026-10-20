<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { mdiAccessPointNetwork, mdiPlus, mdiRefresh } from '@mdi/js'
import { api, type ScanResult, type TasmotaDevice } from '../api'
import { tasmota } from '../stores/tasmota'
import { session } from '../stores/session'
import PageHeader from '../components/page-header.vue'
import MdiIcon from '../components/mdi-icon.vue'
import TasmotaDeviceCard from '../components/tasmota-device-card.vue'
import DeviceDialog from '../components/device-dialog.vue'
import DeviceConsole from '../components/device-console.vue'
import ZigbeeSection from '../components/zigbee-section.vue'

const MAX_CONSOLES = 4

const refreshing = ref(false)
const scanning = ref(false)
const notice = ref('')
const error = ref('')
const editing = ref<TasmotaDevice | null>(null)
const adding = ref(false)
const consoleIds = ref<number[]>([])
const toast = ref('')
let toastTimer: number | undefined

const consoles = computed(() =>
  consoleIds.value.flatMap((id) => tasmota.state.devices.filter((device) => device.id === id)),
)

// A device removed while its console is open takes the console with it.
watch(
  () => tasmota.state.devices.map((device) => device.id),
  (ids) => (consoleIds.value = consoleIds.value.filter((id) => ids.includes(id))),
)

async function toggleConsole(device: TasmotaDevice) {
  if (consoleIds.value.includes(device.id)) {
    closeConsole(device.id)
    return
  }
  if (consoleIds.value.length >= MAX_CONSOLES) {
    // Shown at the bottom of the window: the button is far from the page's message area at the top.
    toast.value = `At most ${MAX_CONSOLES} consoles can be open at the same time. Close one to open the console of ${device.display_name}.`
    window.clearTimeout(toastTimer)
    toastTimer = window.setTimeout(() => (toast.value = ''), 6000)
    return
  }
  toast.value = ''
  consoleIds.value.push(device.id)
  await nextTick()
  document.getElementById(`console-${device.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
}

function closeConsole(id: number) {
  consoleIds.value = consoleIds.value.filter((item) => item !== id)
  toast.value = ''
}

const groups = computed(() => {
  const map = new Map<string, TasmotaDevice[]>()
  for (const device of tasmota.state.devices) {
    const key = device.group_name ?? ''
    if (!map.has(key)) map.set(key, [])
    map.get(key)!.push(device)
  }
  return [...map.entries()].map(([name, devices]) => ({ name, devices }))
})
const bridges = computed(() => tasmota.state.devices.filter((device) => device.zigbee))
const groupNames = computed(() => groups.value.map((g) => g.name).filter(Boolean))
const hasNamedGroups = computed(() => groupNames.value.length > 0)

async function refresh() {
  error.value = ''
  refreshing.value = true
  try {
    await tasmota.refresh()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Refresh failed'
  } finally {
    // Answers arrive over the live connection; keep the button busy briefly so the click is visible.
    window.setTimeout(() => (refreshing.value = false), 800)
  }
}

async function scan() {
  error.value = notice.value = ''
  scanning.value = true
  try {
    const result = await api<ScanResult>('POST', '/api/tasmota/scan')
    const parts = [`${result.found} Tasmota device${result.found === 1 ? '' : 's'} found in ${result.subnet}`]
    if (result.new) parts.push(`${result.new} new`)
    if (result.auth_required) parts.push(`${result.auth_required} require a login (set the credentials in Configuration → Devices)`)
    notice.value = `${parts.join(', ')}.`
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Scan failed'
  } finally {
    scanning.value = false
  }
}

onMounted(() => {
  tasmota.connect()
  refresh()
})
onBeforeUnmount(() => {
  window.clearTimeout(toastTimer)
  tasmota.disconnect()
})
</script>

<template>
  <div class="flex h-full flex-col">
    <PageHeader title="TasmoSiz">
      <template #badge>
        <span v-if="tasmota.state.loaded" class="pill">
          {{ tasmota.state.devices.length }} devices · {{ tasmota.onlineCount.value }} online
        </span>
      </template>
      <template #actions>
        <button class="btn" :disabled="refreshing" title="Ask all devices for their current state" @click="refresh">
          <MdiIcon :path="mdiRefresh" :size="18" :class="refreshing ? 'animate-spin' : ''" />
          <span class="hidden sm:inline">Refresh</span>
        </button>
        <template v-if="session.isAdmin.value">
          <button class="btn" :disabled="scanning" title="Search the local network for Tasmota devices" @click="scan">
            <MdiIcon :path="mdiAccessPointNetwork" :size="18" :class="scanning ? 'animate-pulse' : ''" />
            <span class="hidden sm:inline">{{ scanning ? 'Scanning…' : 'Scan network' }}</span>
          </button>
          <button class="btn" title="Add a device manually" @click="adding = true">
            <MdiIcon :path="mdiPlus" :size="18" />
            <span class="hidden lg:inline">Add device</span>
          </button>
        </template>
      </template>
    </PageHeader>

    <!-- Wide screens: cards and consoles side by side, each scrolling on its own; narrow: consoles below. -->
    <div class="min-h-0 flex-1 overflow-y-auto xl:flex xl:overflow-hidden">
      <div class="p-4 md:p-7 xl:min-w-0 xl:flex-1 xl:overflow-y-auto">
        <p v-if="!tasmota.state.mqttConnected" class="error-box mb-4" role="status">
          The MQTT broker is not connected. Live updates and switching are paused; HomeStart keeps retrying.
        </p>
        <p v-else-if="tasmota.state.loaded && !tasmota.state.liveConnected" class="error-box mb-4" role="status">
          Connection to HomeStart lost. Reconnecting…
        </p>
        <p v-if="error" class="error-box mb-4" role="alert">{{ error }}</p>
        <p v-if="notice" class="mb-4 rounded-lg bg-accent-soft px-3 py-2 text-sm text-accent" role="status">{{ notice }}</p>

        <p v-if="!tasmota.state.loaded" class="text-muted">Loading devices…</p>
        <div v-else-if="!tasmota.state.devices.length" class="card p-6 text-center text-muted">
          No Tasmota devices found yet. Devices appear automatically when they publish on MQTT.
        </div>

        <section v-for="group in groups" :key="group.name" class="mb-6">
          <h2 v-if="hasNamedGroups" class="mb-3 text-sm font-semibold tracking-wide text-muted uppercase">
            {{ group.name || 'Other devices' }}
          </h2>
          <div class="grid grid-cols-[repeat(auto-fill,minmax(250px,1fr))] gap-4">
            <TasmotaDeviceCard
              v-for="device in group.devices"
              :key="device.id"
              :device="device"
              :can-edit="session.isAdmin.value"
              :console-open="consoleIds.includes(device.id)"
              @edit="editing = $event"
              @console="toggleConsole"
            />
          </div>
        </section>

        <ZigbeeSection v-for="bridge in bridges" :key="`zigbee-${bridge.id}`" :bridge="bridge" :is-admin="session.isAdmin.value" />
      </div>

      <aside
        v-if="consoles.length"
        class="px-4 pb-6 md:px-7 xl:flex xl:w-[46%] xl:max-w-[56rem] xl:shrink-0 xl:flex-col xl:border-l xl:border-line xl:p-4"
        aria-labelledby="consoles-heading"
      >
        <h2 id="consoles-heading" class="mb-3 text-sm font-semibold tracking-wide text-muted uppercase">
          Consoles · {{ consoles.length }} of {{ MAX_CONSOLES }}
        </h2>
        <div class="flex flex-col gap-4 xl:min-h-0 xl:flex-1 xl:gap-3 xl:overflow-y-auto">
          <DeviceConsole
            v-for="device in consoles"
            :id="`console-${device.id}`"
            :key="device.id"
            :device="device"
            class="xl:min-h-80 xl:flex-1"
            @close="closeConsole(device.id)"
          />
        </div>
      </aside>
    </div>

    <p
      v-if="toast"
      class="fixed bottom-4 left-1/2 z-40 w-[min(32rem,calc(100%-2rem))] -translate-x-1/2 rounded-lg border border-line bg-surface px-4 py-3 text-sm shadow-lg"
      role="status"
    >
      {{ toast }}
    </p>

    <DeviceDialog v-if="editing" :device="editing" :groups="groupNames" @close="editing = null" />
    <DeviceDialog v-if="adding" :groups="groupNames" @close="adding = false" />
  </div>
</template>
