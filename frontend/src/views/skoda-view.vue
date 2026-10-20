<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { mdiCarSide, mdiGasStation, mdiBatteryHigh, mdiLock, mdiLockOpenVariant, mdiHelpCircleOutline, mdiMapMarkerDistance, mdiRefresh, mdiSpeedometer } from '@mdi/js'
import { api, type CarSide, type OpenState, type SkodaOverview, type SkodaVehicle } from '../api'
import PageHeader from '../components/page-header.vue'
import MdiIcon from '../components/mdi-icon.vue'
import CarTopView from '../components/car-top-view.vue'
import VehicleMap from '../components/vehicle-map.vue'

const overview = ref<SkodaOverview | null>(null)
const selectedVin = ref<string | null>(null)
const refreshing = ref(false)
const error = ref('')
const imageFailed = ref<Record<string, boolean>>({})

const vehicle = computed<SkodaVehicle | null>(() => {
  const vehicles = overview.value?.vehicles ?? []
  return vehicles.find((v) => v.vin === selectedVin.value) ?? vehicles[0] ?? null
})

const SIDES: { side: CarSide; label: string }[] = [
  { side: 'front_left', label: 'Front left' },
  { side: 'front_right', label: 'Front right' },
  { side: 'rear_left', label: 'Rear left' },
  { side: 'rear_right', label: 'Rear right' },
]

/** Server times without a zone are UTC; times from Škoda carry their own zone. */
function parseTime(value: string) {
  return new Date(/(Z|[+-]\d\d:\d\d)$/.test(value) ? value : `${value}Z`)
}

function formatTime(value: string | null | undefined) {
  return value ? parseTime(value).toLocaleString() : 'unknown'
}

function ago(value: string | null | undefined) {
  if (!value) return ''
  const minutes = Math.round((Date.now() - parseTime(value).getTime()) / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 48) return `${hours} h ago`
  return parseTime(value).toLocaleDateString()
}

function stateLabel(state: OpenState | undefined) {
  if (state === 'open') return 'Open'
  if (state === 'closed') return 'Closed'
  if (state === 'unsupported') return 'Not available'
  return 'Unknown'
}

function stateDot(state: OpenState | undefined) {
  if (state === 'open') return 'bg-red-500'
  if (state === 'closed') return 'bg-emerald-500'
  return 'bg-gray-400'
}

const statusRows = computed(() => {
  const v = vehicle.value
  if (!v?.doors) return []
  const rows: { label: string; state: OpenState | undefined }[] = [
    ...SIDES.map(({ side, label }) => ({ label: `${label} door`, state: v.doors?.[side] })),
    ...SIDES.map(({ side, label }) => ({ label: `${label} window`, state: v.windows?.[side] })),
    { label: 'Boot', state: v.trunk },
    { label: 'Bonnet', state: v.bonnet },
  ]
  if (v.sunroof && v.sunroof !== 'unsupported') rows.push({ label: 'Sunroof', state: v.sunroof })
  return rows
})

const openParts = computed(() => statusRows.value.filter((row) => row.state === 'open').length)

const lock = computed(() => {
  const state = vehicle.value?.lock
  if (state === 'locked') return { icon: mdiLock, text: 'Locked', tone: 'text-emerald-600 dark:text-emerald-400' }
  if (state === 'unlocked') return { icon: mdiLockOpenVariant, text: 'Unlocked', tone: 'text-red-600 dark:text-red-400' }
  return { icon: mdiHelpCircleOutline, text: 'Lock state unknown', tone: 'text-muted' }
})

const energy = computed(() => {
  const v = vehicle.value
  if (!v) return null
  if (v.battery_percent != null && v.engine_type === 'electric') return { icon: mdiBatteryHigh, label: 'Battery', value: `${v.battery_percent} %` }
  if (v.fuel_percent != null) return { icon: mdiGasStation, label: 'Fuel', value: `${v.fuel_percent} %` }
  if (v.battery_percent != null) return { icon: mdiBatteryHigh, label: 'Battery', value: `${v.battery_percent} %` }
  return null
})

function number(value: number) {
  return value.toLocaleString()
}

async function load() {
  try {
    overview.value = await api<SkodaOverview>('GET', '/api/skoda/vehicles')
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Could not load vehicle data'
  }
}

/** force=false lets the server decide (first visit after login, or data older than 15 minutes). */
async function refresh(force: boolean) {
  if (!overview.value?.account.connected) return
  error.value = ''
  refreshing.value = true
  try {
    const result = await api<SkodaOverview & { refreshed: boolean }>('POST', '/api/skoda/refresh', { force })
    overview.value = { account: result.account, vehicles: result.vehicles }
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Refresh failed'
  } finally {
    refreshing.value = false
  }
}

onMounted(async () => {
  await load()
  await refresh(false)
})
</script>

<template>
  <div class="flex h-full flex-col">
    <PageHeader title="Škoda">
      <template #badge>
        <span v-if="overview?.account.last_sync" class="pill" :title="formatTime(overview.account.last_sync)">
          Updated {{ ago(overview.account.last_sync) }}
        </span>
      </template>
      <template #actions>
        <button
          v-if="overview?.account.connected"
          class="btn"
          :disabled="refreshing"
          title="Ask Škoda for the current vehicle data"
          @click="refresh(true)"
        >
          <MdiIcon :path="mdiRefresh" :size="18" :class="refreshing ? 'animate-spin' : ''" />
          <span class="hidden sm:inline">{{ refreshing ? 'Updating…' : 'Refresh' }}</span>
        </button>
      </template>
    </PageHeader>

    <div class="flex-1 overflow-y-auto p-4 md:p-7">
      <p v-if="error" class="error-box mb-4" role="alert">{{ error }}</p>
      <p v-if="!overview" class="text-muted">Loading…</p>

      <div v-else-if="!overview.account.connected" class="card mx-auto max-w-lg p-8 text-center">
        <MdiIcon :path="mdiCarSide" :size="56" class="mx-auto mb-3 text-muted" />
        <h2 class="mb-2 text-lg font-semibold">Connect your MyŠkoda account</h2>
        <p class="mb-5 text-sm text-muted">
          Add the email and password of your MyŠkoda account under My account to see your vehicles here.
        </p>
        <RouterLink to="/config/account" class="btn btn-primary">Open My account</RouterLink>
      </div>

      <template v-else>
        <p v-if="overview.account.last_error" class="error-box mb-4" role="status">
          {{ overview.account.last_error }}
          <template v-if="overview.vehicles.length">
            Showing the data saved {{ formatTime(overview.account.last_sync) }}.
          </template>
        </p>
        <p v-if="refreshing && !overview.vehicles.length" class="text-muted">Loading vehicles from Škoda…</p>
        <div v-else-if="!overview.vehicles.length" class="card p-6 text-center text-muted">
          No vehicles are registered on this MyŠkoda account.
        </div>

        <div v-if="overview.vehicles.length > 1" class="mb-4 flex flex-wrap gap-2" role="tablist" aria-label="Vehicles">
          <button
            v-for="item in overview.vehicles"
            :key="item.vin"
            role="tab"
            :aria-selected="item.vin === vehicle?.vin"
            class="btn"
            :class="item.vin === vehicle?.vin ? 'border-accent text-accent' : ''"
            @click="selectedVin = item.vin"
          >
            {{ item.name ?? item.title ?? item.vin }}
          </button>
        </div>

        <template v-if="vehicle">
          <section class="card mb-4 flex flex-col items-center gap-5 p-5 sm:flex-row">
            <img
              v-if="vehicle.has_image && !imageFailed[vehicle.vin]"
              :src="`/api/skoda/vehicles/${vehicle.vin}/image`"
              :alt="vehicle.title ?? 'Vehicle'"
              class="h-32 w-auto max-w-full object-contain sm:h-36"
              @error="imageFailed[vehicle.vin] = true"
            />
            <div v-else class="flex h-32 w-48 items-center justify-center rounded-lg bg-surface-2 text-muted" aria-hidden="true">
              <MdiIcon :path="mdiCarSide" :size="88" />
            </div>
            <div class="min-w-0 text-center sm:text-left">
              <h2 class="text-xl font-bold">{{ vehicle.title ?? 'Škoda' }}</h2>
              <p v-if="vehicle.name && vehicle.name !== vehicle.title" class="text-muted">{{ vehicle.name }}</p>
              <div class="mt-2 flex flex-wrap items-center justify-center gap-2 sm:justify-start">
                <span v-if="vehicle.license_plate" class="rounded border border-ink/40 px-2 py-0.5 font-mono text-sm font-semibold tracking-wider">
                  {{ vehicle.license_plate }}
                </span>
                <span class="font-mono text-xs text-muted">VIN {{ vehicle.vin }}</span>
                <span v-if="vehicle.model_year" class="text-xs text-muted">· {{ vehicle.model_year }}</span>
              </div>
            </div>
          </section>

          <div class="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <div class="card flex items-center gap-3 p-4">
              <MdiIcon :path="lock.icon" :size="30" :class="lock.tone" />
              <div>
                <p class="text-xs text-muted">Doors</p>
                <p class="font-semibold" :class="lock.tone">{{ lock.text }}</p>
              </div>
            </div>
            <div class="card flex items-center gap-3 p-4">
              <MdiIcon :path="mdiSpeedometer" :size="30" class="text-muted" />
              <div>
                <p class="text-xs text-muted">Mileage</p>
                <p class="font-semibold">{{ vehicle.mileage_km != null ? `${number(vehicle.mileage_km)} km` : '–' }}</p>
              </div>
            </div>
            <div class="card flex items-center gap-3 p-4">
              <MdiIcon :path="energy?.icon ?? mdiGasStation" :size="30" class="text-muted" />
              <div>
                <p class="text-xs text-muted">{{ energy?.label ?? 'Fuel' }}</p>
                <p class="font-semibold">{{ energy?.value ?? '–' }}</p>
              </div>
            </div>
            <div class="card flex items-center gap-3 p-4">
              <MdiIcon :path="mdiMapMarkerDistance" :size="30" class="text-muted" />
              <div>
                <p class="text-xs text-muted">Range</p>
                <p class="font-semibold">{{ vehicle.range_km != null ? `${number(vehicle.range_km)} km` : '–' }}</p>
              </div>
            </div>
          </div>

          <div class="grid gap-4 lg:grid-cols-2">
            <section class="card p-5" aria-labelledby="doors-heading">
              <h3 id="doors-heading" class="mb-1 font-semibold">Doors and windows</h3>
              <p class="mb-4 text-sm text-muted">
                {{ !vehicle.doors ? 'Not provided by the vehicle.' : openParts ? `${openParts} open` : 'Everything is closed' }}
              </p>
              <div v-if="vehicle.doors" class="flex flex-col items-center gap-6 sm:flex-row sm:items-start">
                <CarTopView :vehicle="vehicle" />
                <ul class="w-full space-y-1.5 text-sm">
                  <li v-for="row in statusRows" :key="row.label" class="flex items-center gap-2">
                    <span class="h-2.5 w-2.5 shrink-0 rounded-full" :class="stateDot(row.state)" aria-hidden="true" />
                    <span class="flex-1">{{ row.label }}</span>
                    <span :class="row.state === 'open' ? 'font-semibold text-red-600 dark:text-red-400' : 'text-muted'">
                      {{ stateLabel(row.state) }}
                    </span>
                  </li>
                </ul>
              </div>
            </section>

            <section class="card p-5" aria-labelledby="location-heading">
              <h3 id="location-heading" class="mb-1 font-semibold">Location</h3>
              <template v-if="vehicle.position">
                <p class="mb-3 text-sm text-muted">{{ vehicle.position.address ?? 'Address unknown' }}</p>
                <VehicleMap
                  :latitude="vehicle.position.latitude"
                  :longitude="vehicle.position.longitude"
                  :label="vehicle.title ?? 'Vehicle'"
                />
              </template>
              <p v-else class="text-sm text-muted">
                No parking position. Škoda only reports where the car is parked, not while it is driving.
              </p>
              <p class="mt-3 text-xs text-muted">
                Car reported {{ formatTime(vehicle.captured_at) }} · HomeStart updated {{ formatTime(vehicle.updated_at) }}
              </p>
            </section>
          </div>

          <p v-if="vehicle.unavailable.length" class="mt-4 text-xs text-muted">
            Not provided by this vehicle or account: {{ vehicle.unavailable.join(', ') }}.
          </p>
        </template>
      </template>
    </div>
  </div>
</template>
