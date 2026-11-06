<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { mdiArrowDown, mdiArrowUp, mdiDeleteOutline, mdiPencilOutline, mdiPlus } from '@mdi/js'
import { api, type RadioStation } from '../../api'
import { radio } from '../../stores/radio'
import RadioStationDialog from '../../components/radio-station-dialog.vue'
import MdiIcon from '../../components/mdi-icon.vue'

const stations = ref<RadioStation[]>([])
const loaded = ref(false)
const editing = ref<RadioStation | null>(null)
const adding = ref(false)
const error = ref('')

async function load() {
  stations.value = await api<RadioStation[]>('GET', '/api/radio/stations')
  loaded.value = true
  // The Radiopanel shows the new list the next time it opens.
  radio.load().catch(() => {})
}

async function move(index: number, delta: number) {
  const ids = stations.value.map((s) => s.id)
  const [moved] = ids.splice(index, 1)
  ids.splice(index + delta, 0, moved)
  error.value = ''
  try {
    stations.value = await api<RadioStation[]>('PUT', '/api/radio/stations/order', { ids })
    radio.load().catch(() => {})
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Could not save the order'
    await load().catch(() => {})
  }
}

async function remove(station: RadioStation) {
  if (!confirm(`Delete the station "${station.name}"?`)) return
  error.value = ''
  try {
    await api('DELETE', `/api/radio/stations/${station.id}`)
    if (radio.state.currentId === station.slug) radio.stop()
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Could not delete the station'
  }
}

onMounted(() => {
  load().catch((e) => (error.value = e instanceof Error ? e.message : 'Could not load the stations'))
})
</script>

<template>
  <div class="max-w-4xl">
    <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 class="text-lg font-semibold">Radio stations</h2>
        <p class="text-sm text-muted">Shown in the Radiopanel and at /openpanel.</p>
      </div>
      <button class="btn btn-primary" @click="adding = true">
        <MdiIcon :path="mdiPlus" :size="18" />
        Add station
      </button>
    </div>

    <p v-if="error" class="error-box mb-3" role="alert">{{ error }}</p>

    <ul class="card divide-y divide-line">
      <li v-for="(station, index) in stations" :key="station.id" class="flex items-center gap-3 px-3 py-2.5">
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2 font-medium">
            <span class="truncate">{{ station.name }}</span>
            <span class="pill shrink-0">{{ station.slug }}</span>
          </div>
          <div class="truncate text-sm text-muted">{{ station.urls.join('  ·  ') }}</div>
        </div>
        <div class="flex shrink-0 items-center">
          <button class="btn-icon" title="Move up" :disabled="index === 0" @click="move(index, -1)">
            <MdiIcon :path="mdiArrowUp" :size="18" />
          </button>
          <button class="btn-icon" title="Move down" :disabled="index === stations.length - 1" @click="move(index, 1)">
            <MdiIcon :path="mdiArrowDown" :size="18" />
          </button>
          <button class="btn-icon" title="Edit" @click="editing = station">
            <MdiIcon :path="mdiPencilOutline" :size="18" />
          </button>
          <button class="btn-icon hover:text-danger" title="Delete" @click="remove(station)">
            <MdiIcon :path="mdiDeleteOutline" :size="18" />
          </button>
        </div>
      </li>
      <li v-if="loaded && !stations.length" class="px-4 py-6 text-center text-sm text-muted">No stations yet.</li>
    </ul>

    <RadioStationDialog v-if="adding" @close="adding = false" @saved="load" />
    <RadioStationDialog v-if="editing" :station="editing" @close="editing = null" @saved="load" />
  </div>
</template>
