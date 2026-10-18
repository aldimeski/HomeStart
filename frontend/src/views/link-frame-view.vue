<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { mdiAlertCircleOutline, mdiOpenInNew, mdiRefresh } from '@mdi/js'
import PageHeader from '../components/page-header.vue'
import MdiIcon from '../components/mdi-icon.vue'
import { api, type EmbedCheck } from '../api'
import { links } from '../stores/links'

const LOAD_TIMEOUT_MS = 15000

const props = defineProps<{ id: string }>()

const link = computed(() => links.byId(Number(props.id)))
const status = ref<'loading' | 'loaded' | 'failed'>('loading')
const failureReason = ref('')
const frameKey = ref(0)
let timer: number | undefined

function fail(reason: string) {
  status.value = 'failed'
  failureReason.value = reason
  window.clearTimeout(timer)
}

function start() {
  window.clearTimeout(timer)
  status.value = 'loading'
  failureReason.value = ''
  frameKey.value++

  const current = link.value
  if (!current) return

  if (location.protocol === 'https:' && current.url.startsWith('http:')) {
    fail('HomeStart is served over HTTPS, so the browser blocks embedding this HTTP page (mixed content).')
    return
  }

  timer = window.setTimeout(() => {
    if (status.value === 'loading') fail('The page did not load within 15 seconds.')
  }, LOAD_TIMEOUT_MS)

  // A cross-origin iframe still fires "load" when the target refuses to be framed,
  // so the server checks the response headers to detect that case.
  api<EmbedCheck>('GET', `/api/links/${current.id}/embed-check`)
    .then((check) => {
      if (link.value?.id === current.id && check.embeddable === false) {
        fail(check.reason ?? 'The site does not allow being shown inside another page.')
      }
    })
    .catch(() => {})
}

function onFrameLoad() {
  if (status.value === 'loading') {
    status.value = 'loaded'
    window.clearTimeout(timer)
  }
}

watch(
  () => link.value?.id,
  () => start(),
  { immediate: true },
)

onBeforeUnmount(() => window.clearTimeout(timer))
</script>

<template>
  <div v-if="link" class="flex h-full flex-col">
    <PageHeader :title="link.title">
      <template #badge>
        <span class="pill max-w-[40vw] truncate" :title="link.url">{{ link.url }}</span>
      </template>
      <template #actions>
        <button class="btn hidden sm:inline-flex" title="Reload page" @click="start">
          <MdiIcon :path="mdiRefresh" :size="18" />
        </button>
        <a class="btn" :href="link.url" target="_blank" rel="noopener noreferrer">
          <MdiIcon :path="mdiOpenInNew" :size="18" class="sm:hidden" />
          <span class="hidden sm:inline">Open in new tab</span>
        </a>
      </template>
    </PageHeader>

    <div class="relative min-h-0 flex-1 bg-white">
      <iframe
        v-if="status !== 'failed'"
        :key="frameKey"
        :src="link.url"
        :title="link.title"
        class="h-full w-full border-0"
        sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox allow-modals allow-downloads"
        allow="fullscreen; clipboard-write"
        referrerpolicy="no-referrer"
        @load="onFrameLoad"
      />

      <div
        v-if="status === 'loading'"
        class="pointer-events-none absolute inset-x-0 top-0 h-0.5 animate-pulse bg-accent"
        aria-hidden="true"
      />

      <div v-if="status === 'failed'" class="absolute inset-0 flex items-center justify-center bg-page p-6">
        <div class="card max-w-md p-6 text-center" role="alert">
          <MdiIcon :path="mdiAlertCircleOutline" :size="40" class="mx-auto mb-3 text-danger" />
          <h2 class="mb-2 text-lg font-semibold">This page could not be shown here</h2>
          <p class="mb-1 text-sm text-muted">{{ failureReason }}</p>
          <p class="mb-5 text-sm text-muted">You can open it in a new browser tab instead.</p>
          <div class="flex justify-center gap-2">
            <button class="btn" @click="start">Try again</button>
            <a class="btn btn-primary" :href="link.url" target="_blank" rel="noopener noreferrer">
              <MdiIcon :path="mdiOpenInNew" :size="18" />
              Open in new tab
            </a>
          </div>
        </div>
      </div>
    </div>
  </div>

  <div v-else-if="links.state.loaded" class="flex h-full items-center justify-center p-6 text-muted">
    This link no longer exists.
  </div>
</template>
