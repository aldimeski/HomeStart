<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  mdiArrowDown,
  mdiArrowUp,
  mdiChevronRight,
  mdiClose,
  mdiDeleteOutline,
  mdiPencilOutline,
  mdiPlay,
  mdiPlaylistPlus,
  mdiPlus,
  mdiShuffleVariant,
  mdiStarOutline,
} from '@mdi/js'
import { api, type PanelItem, type Playlist, type PlaylistDetail } from '../api'
import { player } from '../stores/player'
import { session } from '../stores/session'
import MdiIcon from './mdi-icon.vue'
import PlaylistNameDialog from './playlist-name-dialog.vue'

const playlists = ref<Playlist[]>([])
const loaded = ref(false)
const open = ref<PlaylistDetail | null>(null)
const creating = ref(false)
const renaming = ref(false)
const error = ref('')
const notice = ref('')

function fail(e: unknown, fallback: string) {
  error.value = e instanceof Error ? e.message : fallback
}

async function load() {
  playlists.value = await api<Playlist[]>('GET', '/api/player/playlists')
  loaded.value = true
}

async function show(id: number) {
  error.value = ''
  notice.value = ''
  try {
    open.value = await api<PlaylistDetail>('GET', `/api/player/playlists/${id}`)
  } catch (e) {
    fail(e, 'Could not open the playlist')
  }
}

async function change(request: Promise<PlaylistDetail>) {
  error.value = ''
  try {
    open.value = await request
    await load()
  } catch (e) {
    fail(e, 'Could not change the playlist')
  }
}

function remove(entryId: number) {
  const id = open.value?.playlist.id
  if (id !== undefined) change(api('DELETE', `/api/player/playlists/${id}/tracks/${entryId}`))
}

function move(index: number, delta: number) {
  if (!open.value) return
  const ids = open.value.tracks.map((t) => t.entry_id)
  const [moved] = ids.splice(index, 1)
  ids.splice(index + delta, 0, moved)
  change(api('PUT', `/api/player/playlists/${open.value.playlist.id}/order`, { entry_ids: ids }))
}

async function deletePlaylist() {
  const playlist = open.value?.playlist
  if (!playlist || !confirm(`Delete the playlist "${playlist.name}"?`)) return
  try {
    await api('DELETE', `/api/player/playlists/${playlist.id}`)
    open.value = null
    await load()
  } catch (e) {
    fail(e, 'Could not delete the playlist')
  }
}

async function offerOnPanel() {
  const playlist = open.value?.playlist
  if (!playlist) return
  notice.value = ''
  try {
    await api<PanelItem>('POST', '/api/config/player/panel/items', { section: 'suggestions', kind: 'playlist', ref: String(playlist.id) })
    notice.value = 'Now offered on the openpanel.'
  } catch (e) {
    fail(e, 'Could not offer the playlist')
  }
}

function minutes(seconds: number) {
  const m = Math.round(seconds / 60)
  return m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min`
}

function clock(seconds: number | null) {
  if (seconds == null) return ''
  const total = Math.round(seconds)
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

onMounted(() => load().catch((e) => fail(e, 'Could not load the playlists')))
</script>

<template>
  <div>
    <p v-if="error" class="error-box mb-3" role="alert">{{ error }}</p>

    <template v-if="!open">
      <div class="mb-3 flex justify-end">
        <button class="btn btn-primary" @click="creating = true">
          <MdiIcon :path="mdiPlus" :size="18" />
          New playlist
        </button>
      </div>
      <ul class="card divide-y divide-line">
        <li v-for="playlist in playlists" :key="playlist.id" class="flex items-center pr-2 hover:bg-surface-2">
          <button class="flex min-w-0 flex-1 items-center gap-3 px-3 py-2.5 text-left" @click="show(playlist.id)">
            <span class="min-w-0 flex-1 truncate font-medium">{{ playlist.name }}</span>
            <span v-if="playlist.panel" class="pill shrink-0">panel</span>
            <span class="shrink-0 text-sm text-muted">{{ playlist.tracks }} tracks</span>
            <MdiIcon :path="mdiChevronRight" :size="18" class="text-muted" />
          </button>
          <button
            class="btn-icon shrink-0"
            :title="`Play ${playlist.name}`"
            :aria-label="`Play ${playlist.name}`"
            :disabled="!playlist.playable"
            @click="player.play({ playlist_id: playlist.id })"
          >
            <MdiIcon :path="mdiPlay" :size="20" />
          </button>
        </li>
        <li v-if="loaded && !playlists.length" class="px-4 py-6 text-center text-sm text-muted">
          No playlists yet. Make one here, or press "Add to playlist" on a track, album or folder.
        </li>
      </ul>
    </template>

    <template v-else>
      <button class="btn mb-3" @click="((open = null), load())">← Playlists</button>
      <div class="mb-3 flex flex-wrap items-center gap-3">
        <div class="min-w-0">
          <h2 class="truncate text-xl font-semibold">{{ open.playlist.name }}</h2>
          <p class="text-sm text-muted">
            {{ open.playlist.tracks }} tracks · {{ minutes(open.playlist.duration_s) }}
            <template v-if="open.playlist.panel"> · panel playlist, shown to everybody</template>
            <template v-if="open.playlist.playable < open.playlist.tracks"> · {{ open.playlist.tracks - open.playlist.playable }} not available</template>
          </p>
        </div>
      </div>
      <div class="mb-3 flex flex-wrap gap-2">
        <button class="btn btn-primary" :disabled="!open.playlist.playable" @click="player.play({ playlist_id: open.playlist.id })">
          <MdiIcon :path="mdiPlay" :size="18" />
          Play
        </button>
        <button class="btn" :disabled="!open.playlist.playable" @click="player.play({ playlist_id: open.playlist.id }, { shuffle: true })">
          <MdiIcon :path="mdiShuffleVariant" :size="18" />
          Shuffle
        </button>
        <button class="btn" :disabled="!open.playlist.playable" @click="player.enqueue({ playlist_id: open.playlist.id })">
          <MdiIcon :path="mdiPlaylistPlus" :size="18" />
          Add to queue
        </button>
        <template v-if="open.playlist.editable">
          <button class="btn" @click="renaming = true">
            <MdiIcon :path="mdiPencilOutline" :size="18" />
            Rename
          </button>
          <button class="btn hover:text-danger" @click="deletePlaylist">
            <MdiIcon :path="mdiDeleteOutline" :size="18" />
            Delete
          </button>
        </template>
        <button v-if="open.playlist.panel && session.isAdmin.value" class="btn" @click="offerOnPanel">
          <MdiIcon :path="mdiStarOutline" :size="18" />
          Offer on the openpanel
        </button>
      </div>
      <p v-if="notice" class="mb-3 text-sm text-accent" role="status">{{ notice }}</p>

      <ul class="card divide-y divide-line">
        <li v-for="(track, index) in open.tracks" :key="track.entry_id" class="flex items-center gap-2 px-3 py-2" :class="track.available ? '' : 'opacity-50'">
          <button
            class="btn-icon shrink-0"
            :title="`Play ${track.title}`"
            :aria-label="`Play ${track.title}`"
            :disabled="!track.available"
            @click="player.play({ playlist_id: open.playlist.id }, { startTrackId: track.id })"
          >
            <MdiIcon :path="mdiPlay" :size="20" />
          </button>
          <span class="w-6 shrink-0 text-right text-sm text-muted tabular-nums">{{ index + 1 }}</span>
          <div class="min-w-0 flex-1">
            <div class="truncate font-medium" :class="player.state.currentId === track.id ? 'text-accent' : ''">{{ track.title }}</div>
            <div class="truncate text-sm text-muted">
              {{ track.artist }}<template v-if="track.album"> · {{ track.album }}</template>
              <template v-if="!track.available"> · not available</template>
            </div>
          </div>
          <span class="shrink-0 text-sm text-muted tabular-nums">{{ clock(track.duration_s) }}</span>
          <template v-if="open.playlist.editable">
            <button class="btn-icon shrink-0" title="Move up" :disabled="index === 0" @click="move(index, -1)">
              <MdiIcon :path="mdiArrowUp" :size="18" />
            </button>
            <button class="btn-icon shrink-0" title="Move down" :disabled="index === open.tracks.length - 1" @click="move(index, 1)">
              <MdiIcon :path="mdiArrowDown" :size="18" />
            </button>
            <button class="btn-icon shrink-0 hover:text-danger" title="Remove from the playlist" @click="remove(track.entry_id)">
              <MdiIcon :path="mdiClose" :size="18" />
            </button>
          </template>
        </li>
        <li v-if="!open.tracks.length" class="px-4 py-6 text-center text-sm text-muted">
          Empty. Press "Add to playlist" on a track, album or folder.
        </li>
      </ul>
    </template>

    <PlaylistNameDialog v-if="creating" @close="creating = false" @saved="(p) => (load(), show(p.id))" />
    <PlaylistNameDialog v-if="renaming && open" :playlist="open.playlist" @close="renaming = false" @saved="show(open.playlist.id).then(load)" />
  </div>
</template>
