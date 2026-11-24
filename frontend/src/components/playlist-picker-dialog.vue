<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { mdiPlus } from '@mdi/js'
import { api, type PlaySelection, type Playlist, type PlaylistDetail } from '../api'
import BaseDialog from './base-dialog.vue'
import MdiIcon from './mdi-icon.vue'
import PlaylistNameDialog from './playlist-name-dialog.vue'

const props = defineProps<{ selection: PlaySelection; what: string }>()
const emit = defineEmits<{ close: [] }>()

const playlists = ref<Playlist[]>([])
const loaded = ref(false)
const error = ref('')
const message = ref('')
const creating = ref(false)

async function load() {
  const all = await api<Playlist[]>('GET', '/api/player/playlists')
  playlists.value = all.filter((p) => p.editable)
  loaded.value = true
}

async function addTo(playlist: Playlist) {
  error.value = ''
  message.value = ''
  try {
    const before = playlist.tracks
    const detail = await api<PlaylistDetail>('POST', `/api/player/playlists/${playlist.id}/tracks`, props.selection)
    message.value = `Added ${detail.playlist.tracks - before} track${detail.playlist.tracks - before === 1 ? '' : 's'} to "${playlist.name}".`
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Could not add to the playlist'
  }
}

onMounted(() => load().catch((e) => (error.value = e instanceof Error ? e.message : 'Could not load the playlists')))
</script>

<template>
  <BaseDialog title="Add to playlist" @close="emit('close')">
    <p class="mb-3 truncate text-sm text-muted">{{ what }}</p>
    <p v-if="message" class="mb-3 text-sm text-accent" role="status">{{ message }}</p>
    <p v-if="error" class="error-box mb-3" role="alert">{{ error }}</p>
    <ul class="card divide-y divide-line">
      <li v-for="playlist in playlists" :key="playlist.id">
        <button class="flex w-full items-center gap-2 px-3 py-2.5 text-left hover:bg-surface-2" @click="addTo(playlist)">
          <span class="min-w-0 flex-1 truncate font-medium">{{ playlist.name }}</span>
          <span v-if="playlist.panel" class="pill shrink-0">panel</span>
          <span class="shrink-0 text-sm text-muted">{{ playlist.tracks }} tracks</span>
        </button>
      </li>
      <li v-if="loaded && !playlists.length" class="px-4 py-4 text-center text-sm text-muted">No playlists yet.</li>
    </ul>
    <button class="btn mt-3" @click="creating = true">
      <MdiIcon :path="mdiPlus" :size="18" />
      New playlist
    </button>
    <PlaylistNameDialog v-if="creating" @close="creating = false" @saved="(p) => addTo(p).then(load)" />
    <template #footer>
      <button class="btn" @click="emit('close')">Done</button>
    </template>
  </BaseDialog>
</template>
