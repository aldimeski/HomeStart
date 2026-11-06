<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { mdiOpenInNew, mdiRefresh, mdiStop } from '@mdi/js'
import PageHeader from '../components/page-header.vue'
import MdiIcon from '../components/mdi-icon.vue'
import { radio } from '../stores/radio'

const state = radio.state
const tab = ref<'radio' | 'home'>('radio')
const homeOpened = ref(false)
const homeKey = ref(0)
const error = ref('')

const current = computed(() => state.stations.find((s) => s.id === state.currentId) ?? null)
const statusText = computed(() => {
  switch (state.play) {
    case 'connecting':
      return 'Connecting…'
    case 'buffering':
      return 'Buffering…'
    case 'playing':
      return 'Playing live'
    case 'error':
      return `Cannot play this station (error code ${state.errorCode})`
    default:
      return ''
  }
})

function showTab(name: 'radio' | 'home') {
  tab.value = name
  // The openHAB page is loaded on the first visit, not when the module opens.
  if (name === 'home') homeOpened.value = true
}

onMounted(() => {
  radio.load().catch((e) => (error.value = e instanceof Error ? e.message : 'Could not load the stations'))
})
</script>

<template>
  <div class="flex h-full flex-col">
    <PageHeader title="Radiopanel" />

    <nav class="flex gap-1 border-b border-line bg-surface px-4 md:px-7" aria-label="Radiopanel sections">
      <button
        class="-mb-px border-b-2 px-3 py-2.5 text-sm font-medium"
        :class="tab === 'radio' ? 'border-accent text-accent' : 'border-transparent text-muted hover:text-ink'"
        @click="showTab('radio')"
      >
        Radio
      </button>
      <button
        v-if="state.openhabEnabled"
        class="-mb-px border-b-2 px-3 py-2.5 text-sm font-medium"
        :class="tab === 'home' ? 'border-accent text-accent' : 'border-transparent text-muted hover:text-ink'"
        @click="showTab('home')"
      >
        Home
      </button>
    </nav>

    <div v-show="tab === 'radio'" class="min-h-0 flex-1 overflow-y-auto p-4 md:p-7">
      <p v-if="error" class="error-box mb-3" role="alert">{{ error }}</p>

      <div class="card mb-4 flex max-w-3xl items-center gap-3 p-4">
        <div class="min-w-0 flex-1">
          <div class="font-semibold">{{ current ? current.name : 'Choose a station' }}</div>
          <div v-if="state.title" class="truncate text-sm">{{ state.title }}</div>
          <div class="text-sm" :class="state.play === 'error' ? 'text-danger' : 'text-muted'">{{ statusText }}</div>
        </div>
        <button class="btn" :disabled="!current" @click="radio.stop()">
          <MdiIcon :path="mdiStop" :size="18" />
          Stop
        </button>
      </div>

      <ul class="grid max-w-3xl gap-2">
        <li v-for="station in state.stations" :key="station.id">
          <button
            class="card w-full px-4 py-3 text-left transition-colors hover:bg-surface-2"
            :class="station.id === state.currentId ? 'border-accent bg-accent-soft' : ''"
            @click="radio.play(station)"
          >
            <span class="block font-medium">{{ station.name }}</span>
            <span v-if="station.sub" class="block text-sm text-muted">{{ station.sub }}</span>
          </button>
        </li>
      </ul>
      <p v-if="state.loaded && !state.stations.length" class="text-sm text-muted">
        No stations yet. An administrator can add them under Configuration → Radio.
      </p>
    </div>

    <div v-if="homeOpened" v-show="tab === 'home'" class="flex min-h-0 flex-1 flex-col">
      <div class="flex items-center gap-2 border-b border-line bg-surface px-4 py-2 md:px-7">
        <button class="btn" @click="homeKey++">
          <MdiIcon :path="mdiRefresh" :size="18" />
          Reload
        </button>
        <a class="btn" :href="state.openhabStart" target="_blank" rel="noopener noreferrer">
          <MdiIcon :path="mdiOpenInNew" :size="18" />
          Open in new tab
        </a>
      </div>
      <iframe :key="homeKey" :src="state.openhabStart" title="openHAB" class="min-h-0 w-full flex-1 border-0 bg-white" />
    </div>
  </div>
</template>
