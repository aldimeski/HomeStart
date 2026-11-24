<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  mdiClose,
  mdiPause,
  mdiPlay,
  mdiPlaylistMusic,
  mdiRepeat,
  mdiRepeatOnce,
  mdiShuffleVariant,
  mdiSkipNext,
  mdiSkipPrevious,
  mdiStop,
  mdiVolumeHigh,
} from '@mdi/js'
import AlbumCover from './album-cover.vue'
import PlaylistPickerDialog from './playlist-picker-dialog.vue'
import MdiIcon from './mdi-icon.vue'
import { player } from '../stores/player'

const state = player.state
const showQueue = ref(false)
const saving = ref(false)
const QUEUE_SAVE_MAX = 500

const track = computed(() => state.queue[state.index] ?? null)
const playing = computed(() => state.status === 'playing')

function clock(seconds: number) {
  const total = Math.max(0, Math.floor(seconds))
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

function onSeek(event: Event) {
  player.seek(Number((event.target as HTMLInputElement).value))
}

function onVolume(event: Event) {
  player.setVolume(Number((event.target as HTMLInputElement).value))
}
</script>

<template>
  <section v-if="track" class="relative shrink-0 border-t border-line bg-surface" aria-label="Player">
    <div
      v-if="showQueue"
      class="absolute right-2 bottom-full left-2 z-20 mb-2 max-h-72 overflow-y-auto rounded-xl border border-line bg-surface shadow-xl md:left-auto md:w-96"
    >
      <div class="flex items-center justify-between border-b border-line px-3 py-2">
        <h2 class="text-sm font-semibold">Queue ({{ state.queue.length }})</h2>
        <div class="flex items-center gap-1">
          <button class="btn py-1 text-xs" @click="saving = true">Save as playlist</button>
          <button class="btn py-1 text-xs" @click="player.clear()">Clear</button>
          <button class="btn-icon" aria-label="Close queue" @click="showQueue = false">
            <MdiIcon :path="mdiClose" :size="18" />
          </button>
        </div>
      </div>
      <ol>
        <li v-for="(item, index) in state.queue" :key="`${index}-${item.id}`">
          <button
            class="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-surface-2"
            :class="index === state.index ? 'font-semibold text-accent' : ''"
            @click="player.jump(index)"
          >
            <span class="w-6 shrink-0 text-right text-muted tabular-nums">{{ index + 1 }}</span>
            <span class="min-w-0 flex-1">
              <span class="block truncate">{{ item.title }}</span>
              <span class="block truncate text-xs text-muted">{{ item.artist }}</span>
            </span>
          </button>
        </li>
      </ol>
    </div>

    <p v-if="state.error" class="bg-danger-soft px-4 py-1 text-sm text-danger" role="alert">{{ state.error }}</p>

    <div class="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2 md:px-7">
      <div class="flex min-w-0 basis-full items-center gap-3 md:basis-72 md:shrink-0">
        <AlbumCover :album-id="track.album_id" :has-cover="track.has_cover" :size="96" :box="48" />
        <div class="min-w-0">
          <div class="truncate font-medium">{{ track.title }}</div>
          <div class="truncate text-sm text-muted">{{ track.artist }}<template v-if="track.album"> · {{ track.album }}</template></div>
        </div>
      </div>

      <div class="flex items-center">
        <button class="btn-icon" title="Previous" aria-label="Previous" @click="player.prev()">
          <MdiIcon :path="mdiSkipPrevious" :size="24" />
        </button>
        <button class="btn-icon" :title="playing ? 'Pause' : 'Play'" :aria-label="playing ? 'Pause' : 'Play'" @click="player.toggle()">
          <MdiIcon :path="playing ? mdiPause : mdiPlay" :size="30" />
        </button>
        <button class="btn-icon" title="Stop" aria-label="Stop" @click="player.stop()">
          <MdiIcon :path="mdiStop" :size="24" />
        </button>
        <button class="btn-icon" title="Next" aria-label="Next" @click="player.next()">
          <MdiIcon :path="mdiSkipNext" :size="24" />
        </button>
      </div>

      <div class="flex min-w-48 flex-1 items-center gap-2 text-xs text-muted tabular-nums">
        <span class="w-10 text-right">{{ clock(state.position) }}</span>
        <input
          type="range"
          class="min-w-0 flex-1 accent-[var(--color-accent)]"
          aria-label="Position"
          min="0"
          :max="Math.max(state.duration, 1)"
          step="1"
          :value="state.position"
          :disabled="state.status === 'stopped'"
          @input="onSeek"
        />
        <span class="w-10">{{ clock(state.duration) }}</span>
      </div>

      <div class="flex items-center">
        <button
          class="btn-icon"
          :class="state.shuffle ? 'text-accent' : ''"
          title="Shuffle"
          aria-label="Shuffle"
          :aria-pressed="state.shuffle"
          @click="player.toggleShuffle()"
        >
          <MdiIcon :path="mdiShuffleVariant" :size="22" />
        </button>
        <button
          class="btn-icon"
          :class="state.repeat !== 'off' ? 'text-accent' : ''"
          :title="`Repeat: ${state.repeat}`"
          :aria-label="`Repeat: ${state.repeat}`"
          @click="player.cycleRepeat()"
        >
          <MdiIcon :path="state.repeat === 'one' ? mdiRepeatOnce : mdiRepeat" :size="22" />
        </button>
        <MdiIcon :path="mdiVolumeHigh" :size="20" class="ml-1 hidden text-muted md:block" />
        <input
          type="range"
          class="ml-1 hidden w-20 accent-[var(--color-accent)] md:block"
          aria-label="Volume"
          min="0"
          max="1"
          step="0.05"
          :value="state.volume"
          @input="onVolume"
        />
        <button class="btn-icon" :class="showQueue ? 'text-accent' : ''" title="Queue" aria-label="Queue" @click="showQueue = !showQueue">
          <MdiIcon :path="mdiPlaylistMusic" :size="22" />
        </button>
      </div>
    </div>
    <PlaylistPickerDialog
      v-if="saving"
      :selection="{ track_ids: state.queue.slice(0, QUEUE_SAVE_MAX).map((t) => t.id) }"
      :what="`The queue (${Math.min(state.queue.length, QUEUE_SAVE_MAX)} tracks)`"
      @close="saving = false"
    />
  </section>
</template>
