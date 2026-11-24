<script setup lang="ts">
import { mdiPlay, mdiPlaylistMusic, mdiPlaylistPlus, mdiStarOutline } from '@mdi/js'
import type { Track } from '../api'
import MdiIcon from './mdi-icon.vue'
import { player } from '../stores/player'
import { session } from '../stores/session'

defineProps<{ tracks: Track[]; showAlbum?: boolean }>()
const emit = defineEmits<{ play: [track: Track]; queue: [track: Track]; playlist: [track: Track]; favorite: [track: Track] }>()

function duration(seconds: number | null) {
  if (seconds == null) return ''
  const total = Math.round(seconds)
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}
</script>

<template>
  <ul class="card divide-y divide-line">
    <li v-for="track in tracks" :key="track.id" class="flex items-center gap-2 px-3 py-2">
      <button class="btn-icon shrink-0" :title="`Play ${track.title}`" :aria-label="`Play ${track.title}`" @click="emit('play', track)">
        <MdiIcon :path="mdiPlay" :size="20" />
      </button>
      <span class="w-6 shrink-0 text-right text-sm text-muted tabular-nums">{{ track.track_no ?? '' }}</span>
      <div class="min-w-0 flex-1">
        <div class="truncate font-medium" :class="player.state.currentId === track.id ? 'text-accent' : ''">{{ track.title }}</div>
        <div class="truncate text-sm text-muted">
          {{ track.artist }}<template v-if="showAlbum && track.album"> · {{ track.album }}</template>
        </div>
      </div>
      <span class="shrink-0 text-sm text-muted tabular-nums">{{ duration(track.duration_s) }}</span>
      <button class="btn-icon shrink-0" title="Add to queue" aria-label="Add to queue" @click="emit('queue', track)">
        <MdiIcon :path="mdiPlaylistPlus" :size="20" />
      </button>
      <button class="btn-icon shrink-0" title="Add to playlist" aria-label="Add to playlist" @click="emit('playlist', track)">
        <MdiIcon :path="mdiPlaylistMusic" :size="20" />
      </button>
      <button
        v-if="session.isAdmin.value"
        class="btn-icon shrink-0"
        title="Add to the favourites of the openpanel"
        aria-label="Add to the favourites of the openpanel"
        @click="emit('favorite', track)"
      >
        <MdiIcon :path="mdiStarOutline" :size="20" />
      </button>
    </li>
  </ul>
</template>
