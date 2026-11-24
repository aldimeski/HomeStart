<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { mdiDeleteOutline, mdiFileSearchOutline, mdiPencilOutline, mdiPlus, mdiRefresh, mdiStop } from '@mdi/js'
import { api, type MetadataStatus, type MusicScan, type MusicSource } from '../../api'
import MdiIcon from '../../components/mdi-icon.vue'
import MusicSourceDialog from '../../components/music-source-dialog.vue'
import PanelContentConfig from '../../components/panel-content-config.vue'
import ScanReportDialog from '../../components/scan-report-dialog.vue'

const POLL_MS = 2000

const sources = ref<MusicSource[]>([])
const loaded = ref(false)
const scanning = ref(false)
const history = ref<Record<number, MusicScan[]>>({})
const editing = ref<MusicSource | null>(null)
const adding = ref(false)
const reportId = ref<number | null>(null)
const error = ref('')
const metadata = ref<MetadataStatus | null>(null)
let timer: number | undefined
let metadataTimer: number | undefined

async function load() {
  sources.value = await api<MusicSource[]>('GET', '/api/config/player/sources')
  const status = await api<{ scanning: boolean }>('GET', '/api/config/player/status')
  scanning.value = status.scanning
  loaded.value = true
  await Promise.all(
    sources.value.map(async (s) => {
      history.value[s.id] = await api<MusicScan[]>('GET', `/api/config/player/sources/${s.id}/scans?limit=3`)
    }),
  )
  // While a scan runs the page follows it until it is over.
  window.clearTimeout(timer)
  if (scanning.value) timer = window.setTimeout(() => load().catch(() => {}), POLL_MS)
}

async function run(action: () => Promise<unknown>, fallback: string) {
  error.value = ''
  try {
    await action()
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : fallback
    await load().catch(() => {})
  }
}

const scan = (source: MusicSource) =>
  run(() => api('POST', `/api/config/player/sources/${source.id}/scan`), 'Could not start the scan')
const scanAll = () => run(() => api('POST', '/api/config/player/scan'), 'Could not start the scan')
const cancel = () => run(() => api('POST', '/api/config/player/scan/cancel'), 'Could not cancel the scan')

async function removeMissing(source: MusicSource) {
  if (!confirm(`Remove the ${source.missing} missing files of "${source.name}" from the library for good?`)) return
  await run(() => api('POST', `/api/config/player/sources/${source.id}/remove-missing`), 'Could not remove the files')
}

async function remove(source: MusicSource) {
  if (!confirm(`Remove the location "${source.name}" from HomeStart? The files themselves are not touched.`)) return
  await run(() => api('DELETE', `/api/config/player/sources/${source.id}`), 'Could not remove the location')
}

function when(value: string | null) {
  return value ? new Date(value + 'Z').toLocaleString() : 'never'
}

function summary(scan: MusicScan | undefined) {
  if (!scan) return ''
  if (scan.status === 'running') return 'Scanning…'
  if (scan.status === 'failed') return `Scan failed: ${scan.error_message ?? 'unknown error'}`
  const result = `${scan.added} new, ${scan.changed} changed, ${scan.removed} removed`
  return scan.status === 'cancelled' ? `Cancelled (${result})` : result
}

async function loadMetadata() {
  metadata.value = await api<MetadataStatus>('GET', '/api/config/player/metadata')
  // While albums are being looked up the numbers follow along.
  window.clearTimeout(metadataTimer)
  if (metadata.value.running) metadataTimer = window.setTimeout(() => loadMetadata().catch(() => {}), POLL_MS)
}

async function metadataAction(action: () => Promise<MetadataStatus>) {
  error.value = ''
  try {
    metadata.value = await action()
    window.clearTimeout(metadataTimer)
    metadataTimer = window.setTimeout(() => loadMetadata().catch(() => {}), POLL_MS)
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Could not do that'
  }
}

const switchOnline = (on: boolean) =>
  metadataAction(() => api<MetadataStatus>('PUT', '/api/config/player/metadata', { online_enabled: on }))
const lookUpNow = () => metadataAction(() => api<MetadataStatus>('POST', '/api/config/player/metadata/run'))
const retryFailed = () => metadataAction(() => api<MetadataStatus>('POST', '/api/config/player/metadata/retry'))

onMounted(() => {
  loadMetadata().catch(() => {})
  load().catch((e) => (error.value = e instanceof Error ? e.message : 'Could not load the locations'))
})
onBeforeUnmount(() => {
  window.clearTimeout(timer)
  window.clearTimeout(metadataTimer)
})
</script>

<template>
  <div class="max-w-4xl">
    <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 class="text-lg font-semibold">Music locations</h2>
        <p class="text-sm text-muted">Folders of the server and network shares HomeStart reads music from. Scan again to pick up added and deleted files.</p>
      </div>
      <div class="flex gap-2">
        <button v-if="scanning" class="btn" @click="cancel">
          <MdiIcon :path="mdiStop" :size="18" />
          Cancel scan
        </button>
        <button v-else class="btn" :disabled="!sources.some((s) => s.enabled)" @click="scanAll">
          <MdiIcon :path="mdiRefresh" :size="18" />
          Scan all
        </button>
        <button class="btn btn-primary" @click="adding = true">
          <MdiIcon :path="mdiPlus" :size="18" />
          Add location
        </button>
      </div>
    </div>

    <p v-if="error" class="error-box mb-3" role="alert">{{ error }}</p>

    <ul class="card divide-y divide-line">
      <li v-for="source in sources" :key="source.id" class="px-3 py-3">
        <div class="flex items-center gap-3">
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2 font-medium">
              <span class="truncate">{{ source.name }}</span>
              <span class="pill shrink-0">{{ source.kind === 'smb' ? 'network share' : 'server folder' }}</span>
              <span v-if="!source.enabled" class="pill shrink-0">switched off</span>
            </div>
            <div class="truncate text-sm text-muted">
              {{ source.kind === 'smb' ? source.network_path : source.path }}
              <template v-if="source.kind === 'smb'"> · {{ source.username ? `user ${source.username}` : 'guest' }}</template>
            </div>
          </div>
          <div class="flex shrink-0 items-center">
            <button class="btn" :disabled="scanning || !source.enabled" @click="scan(source)">
              <MdiIcon :path="mdiRefresh" :size="18" />
              Scan again
            </button>
            <button class="btn-icon" title="Edit" @click="editing = source">
              <MdiIcon :path="mdiPencilOutline" :size="18" />
            </button>
            <button class="btn-icon hover:text-danger" title="Remove location" :disabled="scanning" @click="remove(source)">
              <MdiIcon :path="mdiDeleteOutline" :size="18" />
            </button>
          </div>
        </div>
        <div class="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted">
          <span>{{ source.tracks }} tracks</span>
          <span>Last scan: {{ when(source.last_scan_at) }}</span>
          <span :class="history[source.id]?.[0]?.status === 'failed' ? 'text-danger' : ''">{{ summary(history[source.id]?.[0]) }}</span>
          <button v-if="history[source.id]?.[0]" class="inline-flex items-center gap-1 text-accent" @click="reportId = history[source.id][0].id">
            <MdiIcon :path="mdiFileSearchOutline" :size="16" />
            Report
          </button>
          <button v-if="source.missing" class="text-accent" @click="removeMissing(source)">
            {{ source.missing }} missing – remove from library
          </button>
        </div>
        <ul v-if="(history[source.id]?.length ?? 0) > 1" class="mt-2 space-y-0.5 border-t border-line pt-2 text-xs text-muted">
          <li v-for="old in history[source.id].slice(1)" :key="old.id" class="flex gap-3">
            <span class="shrink-0">{{ when(old.started_at) }}</span>
            <span class="truncate">{{ summary(old) }}</span>
            <button class="shrink-0 text-accent" @click="reportId = old.id">Report</button>
          </li>
        </ul>
      </li>
      <li v-if="loaded && !sources.length" class="px-4 py-6 text-center text-sm text-muted">No locations yet.</li>
    </ul>


    <section v-if="metadata" class="card mt-6 p-4" aria-labelledby="metadata-title">
      <h2 id="metadata-title" class="text-lg font-semibold">Album pictures and details</h2>
      <p class="mt-1 text-sm text-muted">
        Pictures are taken from the music files and the folders (cover.jpg, folder.jpg, front.jpg). With the lookup switched on,
        albums without them are also searched on MusicBrainz (year, genre) and the Cover Art Archive (picture).
      </p>
      <label class="mt-3 flex items-center gap-2 text-sm">
        <input type="checkbox" :checked="metadata.online_enabled" @change="switchOnline(($event.target as HTMLInputElement).checked)" />
        Look up albums online
      </label>
      <p class="mt-1 text-xs text-muted">
        Only the artist and album names and the number of tracks are sent – never paths, locations or passwords.
        <template v-if="!metadata.contact_set">
          MusicBrainz asks for contact details: set <code>musicbrainz_contact</code> in the [player] section of homestart.ini.
        </template>
      </p>
      <div class="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted">
        <span>{{ metadata.with_cover }} of {{ metadata.albums }} albums have a picture</span>
        <span>{{ metadata.found }} found online</span>
        <span>{{ metadata.not_found }} not found</span>
        <span v-if="metadata.errors" class="text-danger">{{ metadata.errors }} failed</span>
        <span v-if="metadata.running">Looking up… {{ metadata.pending }} waiting</span>
        <span v-else-if="metadata.pending">{{ metadata.pending }} waiting</span>
      </div>
      <div class="mt-3 flex flex-wrap gap-2">
        <button class="btn" :disabled="metadata.running || !metadata.pending" @click="lookUpNow">Look up now</button>
        <button class="btn" :disabled="metadata.running || !metadata.online_enabled || !(metadata.not_found || metadata.errors)" @click="retryFailed">
          Try again for those not found
        </button>
      </div>
    </section>

    <PanelContentConfig />

    <MusicSourceDialog v-if="adding" @close="adding = false" @saved="load" />
    <MusicSourceDialog v-if="editing" :source="editing" @close="editing = null" @saved="load" />
    <ScanReportDialog v-if="reportId !== null" :scan-id="reportId" @close="reportId = null" />
  </div>
</template>
