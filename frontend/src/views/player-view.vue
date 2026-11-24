<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  mdiChevronRight,
  mdiFolderOutline,
  mdiHarddisk,
  mdiMagnify,
  mdiPlay,
  mdiPlaylistMusic,
  mdiPlaylistPlus,
  mdiShuffleVariant,
  mdiStarOutline,
} from '@mdi/js'
import { api, type Album, type FolderListing, type Genre, type MusicLocation, type Page, type PlaySelection, type Track } from '../api'
import PageHeader from '../components/page-header.vue'
import MdiIcon from '../components/mdi-icon.vue'
import AlbumCover from '../components/album-cover.vue'
import PlaylistPickerDialog from '../components/playlist-picker-dialog.vue'
import PlaylistsPanel from '../components/playlists-panel.vue'
import TrackList from '../components/track-list.vue'
import { session } from '../stores/session'
import { player } from '../stores/player'

const PAGE = 60
const SEARCH_DELAY_MS = 300

type Tab = 'albums' | 'genres' | 'folders' | 'playlists'
type GenreFilter = { name: string | null }

const tab = ref<Tab>('albums')
const error = ref('')
const query = ref('')
const sort = ref<'title' | 'artist' | 'year'>('title')

const albums = ref<Album[]>([])
const albumTotal = ref(0)
const genres = ref<Genre[]>([])
const genre = ref<GenreFilter | null>(null)
const openAlbum = ref<{ album: Album; tracks: Track[] } | null>(null)
const locations = ref<MusicLocation[]>([])
const folder = ref<FolderListing | null>(null)
const results = ref<Track[]>([])
const resultTotal = ref(0)
const loading = ref(false)

const searching = computed(() => query.value.trim().length > 0)

function fail(e: unknown, fallback: string) {
  error.value = e instanceof Error ? e.message : fallback
}

function genreParams(): Record<string, string> {
  if (!genre.value) return {}
  return genre.value.name === null ? { no_genre: 'true' } : { genre: genre.value.name }
}

function qs(params: Record<string, string | number>) {
  return new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])).toString()
}

async function loadAlbums(more = false) {
  loading.value = true
  try {
    const page = await api<Page<Album>>(
      'GET',
      `/api/player/albums?${qs({ sort: sort.value, limit: PAGE, offset: more ? albums.value.length : 0, ...genreParams() })}`,
    )
    albums.value = more ? [...albums.value, ...page.items] : page.items
    albumTotal.value = page.total
  } catch (e) {
    fail(e, 'Could not load the albums')
  } finally {
    loading.value = false
  }
}

async function loadResults(more = false) {
  loading.value = true
  try {
    const page = await api<Page<Track>>(
      'GET',
      `/api/player/tracks?${qs({ q: query.value.trim(), limit: PAGE, offset: more ? results.value.length : 0 })}`,
    )
    results.value = more ? [...results.value, ...page.items] : page.items
    resultTotal.value = page.total
  } catch (e) {
    fail(e, 'Could not search')
  } finally {
    loading.value = false
  }
}

async function showAlbum(album: Album) {
  try {
    openAlbum.value = await api('GET', `/api/player/albums/${album.id}`)
  } catch (e) {
    fail(e, 'Could not open the album')
  }
}

async function openFolder(sourceId: number, path = '') {
  try {
    folder.value = await api<FolderListing>('GET', `/api/player/folders?${qs({ source_id: sourceId, path })}`)
  } catch (e) {
    fail(e, 'Could not open the folder')
  }
}

const crumbs = computed(() => {
  if (!folder.value) return []
  const parts = folder.value.path ? folder.value.path.split('/') : []
  return parts.map((name, i) => ({ name, path: parts.slice(0, i + 1).join('/') }))
})

async function pickGenre(g: Genre) {
  genre.value = { name: g.name }
  await loadAlbums()
}

function showTab(next: Tab) {
  tab.value = next
  error.value = ''
  openAlbum.value = null
  genre.value = null
  folder.value = null
  if (next === 'albums') loadAlbums()
}

const PLAY_LIST_MAX = 500

// What is being added to a playlist, as asked for by one of the "Add to playlist" buttons.
const picking = ref<{ selection: PlaySelection; what: string } | null>(null)
const notice = ref('')

function pickPlaylist(selection: PlaySelection, what: string) {
  picking.value = { selection, what }
}

async function offerOnPanel(section: 'favorites' | 'suggestions', kind: 'track' | 'album' | 'folder', ref: string, what: string) {
  error.value = ''
  notice.value = ''
  try {
    await api('POST', '/api/config/player/panel/items', { section, kind, ref })
    notice.value = `"${what}" is now on the openpanel.`
  } catch (e) {
    fail(e, 'Could not put it on the openpanel')
  }
}

async function refreshAlbum(id: number) {
  try {
    await api('POST', `/api/config/player/albums/${id}/refresh`)
    // The lookup runs in the background; the album is shown again once it has had time.
    window.setTimeout(() => openAlbum.value && showAlbum(openAlbum.value.album), 4000)
  } catch (e) {
    fail(e, 'Could not start the lookup')
  }
}

function playResult(track: Track) {
  // A search result plays on from the track that was clicked, through the results shown.
  player.play({ track_ids: results.value.slice(0, PLAY_LIST_MAX).map((t) => t.id) }, { startTrackId: track.id })
}

function formatDuration(seconds: number) {
  const minutes = Math.round(seconds / 60)
  return minutes >= 60 ? `${Math.floor(minutes / 60)} h ${minutes % 60} min` : `${minutes} min`
}

let searchTimer: number | undefined
watch(query, () => {
  window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => (searching.value ? loadResults() : null), SEARCH_DELAY_MS)
})
watch(sort, () => loadAlbums())

onMounted(async () => {
  await Promise.all([
    loadAlbums(),
    api<Genre[]>('GET', '/api/player/genres').then((g) => (genres.value = g)),
    api<MusicLocation[]>('GET', '/api/player/locations').then((l) => (locations.value = l)),
  ]).catch((e) => fail(e, 'Could not load the library'))
})
</script>

<template>
  <div class="flex h-full flex-col">
    <PageHeader title="Player">
      <template #actions>
        <div class="relative">
          <MdiIcon :path="mdiMagnify" :size="18" class="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-muted" />
          <input v-model="query" class="input w-52 pl-9 md:w-72" type="search" placeholder="Search title, artist, album" aria-label="Search" />
        </div>
      </template>
    </PageHeader>

    <nav v-if="!searching" class="flex gap-1 border-b border-line bg-surface px-4 md:px-7" aria-label="Library views">
      <button
        v-for="item in [{ id: 'albums', label: 'Albums' }, { id: 'genres', label: 'Genres' }, { id: 'folders', label: 'Folders' }, { id: 'playlists', label: 'Playlists' }] as const"
        :key="item.id"
        class="-mb-px border-b-2 px-3 py-2.5 text-sm font-medium"
        :class="tab === item.id ? 'border-accent text-accent' : 'border-transparent text-muted hover:text-ink'"
        @click="showTab(item.id)"
      >
        {{ item.label }}
      </button>
    </nav>

    <div class="flex-1 overflow-y-auto p-4 md:p-7">
      <p v-if="error" class="error-box mb-3" role="alert">{{ error }}</p>
      <p v-if="notice" class="mb-3 text-sm text-accent" role="status">{{ notice }}</p>

      <!-- search results -->
      <template v-if="searching">
        <p class="mb-3 text-sm text-muted">{{ resultTotal }} tracks found</p>
        <TrackList
          :tracks="results"
          show-album
          @play="playResult"
          @queue="(t) => player.enqueue({ track_id: t.id })"
          @playlist="(t) => pickPlaylist({ track_id: t.id }, `${t.title} – ${t.artist}`)"
          @favorite="(t) => offerOnPanel('favorites', 'track', String(t.id), t.title)"
        />
        <button v-if="results.length < resultTotal" class="btn mt-3" :disabled="loading" @click="loadResults(true)">Show more</button>
      </template>

      <!-- one album -->
      <template v-else-if="openAlbum">
        <button class="btn mb-3" @click="openAlbum = null">← Back</button>
        <div class="mb-3 flex items-center gap-4">
          <AlbumCover :album-id="openAlbum.album.id" :has-cover="openAlbum.album.has_cover" :size="300" :box="120" />
          <div class="min-w-0">
            <h2 class="text-xl font-semibold">{{ openAlbum.album.title }}</h2>
            <p class="text-sm text-muted">
          {{ openAlbum.album.artist }}<template v-if="openAlbum.album.year"> · {{ openAlbum.album.year }}</template>
          · {{ openAlbum.album.tracks }} tracks · {{ formatDuration(openAlbum.album.duration_s) }}
            </p>
            <button v-if="session.isAdmin.value" class="mt-1 text-xs text-accent" @click="refreshAlbum(openAlbum.album.id)">
              Look up the picture and details again
            </button>
          </div>
        </div>
        <div class="mb-3 flex flex-wrap gap-2">
          <button class="btn btn-primary" @click="player.play({ album_id: openAlbum.album.id })">
            <MdiIcon :path="mdiPlay" :size="18" />
            Play album
          </button>
          <button class="btn" @click="player.play({ album_id: openAlbum.album.id }, { shuffle: true })">
            <MdiIcon :path="mdiShuffleVariant" :size="18" />
            Shuffle
          </button>
          <button class="btn" @click="player.enqueue({ album_id: openAlbum.album.id })">
            <MdiIcon :path="mdiPlaylistPlus" :size="18" />
            Add to queue
          </button>
          <button class="btn" @click="pickPlaylist({ album_id: openAlbum.album.id }, openAlbum.album.title)">
            <MdiIcon :path="mdiPlaylistMusic" :size="18" />
            Add to playlist
          </button>
          <button v-if="session.isAdmin.value" class="btn" @click="offerOnPanel('suggestions', 'album', String(openAlbum.album.id), openAlbum.album.title)">
            <MdiIcon :path="mdiStarOutline" :size="18" />
            Offer on the openpanel
          </button>
        </div>
        <TrackList
          :tracks="openAlbum.tracks"
          @play="(t) => player.play({ album_id: openAlbum!.album.id }, { startTrackId: t.id })"
          @queue="(t) => player.enqueue({ track_id: t.id })"
          @playlist="(t) => pickPlaylist({ track_id: t.id }, `${t.title} – ${t.artist}`)"
          @favorite="(t) => offerOnPanel('favorites', 'track', String(t.id), t.title)"
        />
      </template>

      <!-- playlists -->
      <PlaylistsPanel v-else-if="tab === 'playlists'" />

      <!-- albums, also of one genre -->
      <template v-else-if="tab === 'albums' || genre">
        <div class="mb-3 flex flex-wrap items-center gap-3">
          <button v-if="genre" class="btn" @click="genre = null">← Genres</button>
          <h2 v-if="genre" class="text-lg font-semibold">{{ genre.name ?? 'No genre' }}</h2>
          <label class="ml-auto flex items-center gap-2 text-sm text-muted">
            Sort by
            <select v-model="sort" class="input w-auto py-1">
              <option value="title">Title</option>
              <option value="artist">Artist</option>
              <option value="year">Year</option>
            </select>
          </label>
        </div>
        <ul class="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          <li v-for="album in albums" :key="album.id">
            <div class="card flex w-full items-center gap-1 pr-2 hover:bg-surface-2">
              <button class="flex min-w-0 flex-1 items-center gap-3 p-3 text-left" @click="showAlbum(album)">
                <AlbumCover :album-id="album.id" :has-cover="album.has_cover" :size="96" :box="56" />
                <span class="min-w-0">
                  <span class="block truncate font-medium">{{ album.title }}</span>
                  <span class="block truncate text-sm text-muted">{{ album.artist }}<template v-if="album.year"> · {{ album.year }}</template></span>
                  <span class="block text-xs text-muted">{{ album.tracks }} tracks · {{ formatDuration(album.duration_s) }}</span>
                </span>
              </button>
              <button class="btn-icon shrink-0" :title="`Play ${album.title}`" :aria-label="`Play ${album.title}`" @click="player.play({ album_id: album.id })">
                <MdiIcon :path="mdiPlay" :size="22" />
              </button>
            </div>
          </li>
        </ul>
        <p v-if="!albums.length && !loading" class="py-8 text-center text-sm text-muted">
          No albums yet. An administrator adds music locations under Configuration → Player.
        </p>
        <button v-if="albums.length < albumTotal" class="btn mt-3" :disabled="loading" @click="loadAlbums(true)">Show more</button>
      </template>

      <!-- genres -->
      <template v-else-if="tab === 'genres'">
        <ul class="card divide-y divide-line">
          <li v-for="g in genres" :key="g.name ?? ''">
            <button class="flex w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-surface-2" @click="pickGenre(g)">
              <span class="flex-1 font-medium">{{ g.name ?? 'No genre' }}</span>
              <span class="text-sm text-muted">{{ g.albums }} albums · {{ g.tracks }} tracks</span>
              <MdiIcon :path="mdiChevronRight" :size="18" class="text-muted" />
            </button>
          </li>
          <li v-if="!genres.length" class="px-4 py-6 text-center text-sm text-muted">No music yet.</li>
        </ul>
      </template>

      <!-- folders: location → folder → subfolder → file -->
      <template v-else>
        <template v-if="!folder">
          <ul class="card divide-y divide-line">
            <li v-for="location in locations" :key="location.id">
              <button class="flex w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-surface-2" @click="openFolder(location.id)">
                <MdiIcon :path="mdiHarddisk" :size="20" class="text-muted" />
                <span class="flex-1 font-medium">{{ location.name }}</span>
                <span class="text-sm text-muted">{{ location.tracks }} tracks</span>
                <MdiIcon :path="mdiChevronRight" :size="18" class="text-muted" />
              </button>
            </li>
            <li v-if="!locations.length" class="px-4 py-6 text-center text-sm text-muted">No locations yet.</li>
          </ul>
        </template>
        <template v-else>
          <nav class="mb-3 flex flex-wrap items-center gap-1 text-sm" aria-label="Folder path">
            <button class="text-accent" @click="folder = null">Locations</button>
            <MdiIcon :path="mdiChevronRight" :size="16" class="text-muted" />
            <button class="text-accent" @click="openFolder(folder.source_id)">{{ folder.source_name }}</button>
            <template v-for="crumb in crumbs" :key="crumb.path">
              <MdiIcon :path="mdiChevronRight" :size="16" class="text-muted" />
              <button class="text-accent" @click="openFolder(folder.source_id, crumb.path)">{{ crumb.name }}</button>
            </template>
          </nav>
          <div class="mb-3 flex flex-wrap gap-2">
            <button class="btn btn-primary" @click="player.play({ source_id: folder.source_id, path: folder.path })">
              <MdiIcon :path="mdiPlay" :size="18" />
              Play folder
            </button>
            <button class="btn" @click="player.play({ source_id: folder.source_id, path: folder.path }, { shuffle: true })">
              <MdiIcon :path="mdiShuffleVariant" :size="18" />
              Shuffle
            </button>
            <button class="btn" @click="player.enqueue({ source_id: folder.source_id, path: folder.path })">
              <MdiIcon :path="mdiPlaylistPlus" :size="18" />
              Add to queue
            </button>
            <button class="btn" @click="pickPlaylist({ source_id: folder.source_id, path: folder.path }, folder.path || folder.source_name)">
              <MdiIcon :path="mdiPlaylistMusic" :size="18" />
              Add to playlist
            </button>
            <button
              v-if="session.isAdmin.value"
              class="btn"
              @click="offerOnPanel('suggestions', 'folder', `${folder.source_id}:${folder.path}`, folder.path || folder.source_name)"
            >
              <MdiIcon :path="mdiStarOutline" :size="18" />
              Offer on the openpanel
            </button>
          </div>
          <ul v-if="folder.folders.length" class="card mb-3 divide-y divide-line">
            <li v-for="sub in folder.folders" :key="sub.path" class="flex items-center pr-2 hover:bg-surface-2">
              <button class="flex min-w-0 flex-1 items-center gap-3 px-3 py-2.5 text-left" @click="openFolder(folder.source_id, sub.path)">
                <MdiIcon :path="mdiFolderOutline" :size="20" class="text-muted" />
                <span class="flex-1 truncate font-medium">{{ sub.name }}</span>
                <span class="text-sm text-muted">{{ sub.tracks }} tracks</span>
                <MdiIcon :path="mdiChevronRight" :size="18" class="text-muted" />
              </button>
              <button class="btn-icon shrink-0" :title="`Play ${sub.name}`" :aria-label="`Play ${sub.name}`" @click="player.play({ source_id: folder.source_id, path: sub.path })">
                <MdiIcon :path="mdiPlay" :size="20" />
              </button>
            </li>
          </ul>
          <TrackList
            v-if="folder.tracks.length"
            :tracks="folder.tracks"
            show-album
            @play="(t) => player.play({ source_id: folder!.source_id, path: folder!.path }, { startTrackId: t.id })"
            @queue="(t) => player.enqueue({ track_id: t.id })"
            @playlist="(t) => pickPlaylist({ track_id: t.id }, `${t.title} – ${t.artist}`)"
            @favorite="(t) => offerOnPanel('favorites', 'track', String(t.id), t.title)"
          />
        </template>
      </template>
    </div>
    <PlaylistPickerDialog v-if="picking" :selection="picking.selection" :what="picking.what" @close="picking = null" />
  </div>
</template>
