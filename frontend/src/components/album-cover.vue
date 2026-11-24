<script setup lang="ts">
import { ref, watch } from 'vue'
import { mdiMusicBox } from '@mdi/js'
import MdiIcon from './mdi-icon.vue'

const props = defineProps<{ albumId: number | null; hasCover: boolean; size: 96 | 300 | 600; box: number }>()

// A picture that fails to load (e.g. the cache was cleared) falls back to the icon.
const failed = ref(false)
watch(() => [props.albumId, props.hasCover], () => (failed.value = false))
</script>

<template>
  <img
    v-if="albumId !== null && hasCover && !failed"
    :src="`/api/player/cover/${albumId}?size=${size}`"
    :width="box"
    :height="box"
    alt=""
    loading="lazy"
    class="shrink-0 rounded-md bg-surface-2 object-cover"
    :style="{ width: `${box}px`, height: `${box}px` }"
    @error="failed = true"
  />
  <span
    v-else
    class="flex shrink-0 items-center justify-center rounded-md bg-surface-2 text-muted"
    :style="{ width: `${box}px`, height: `${box}px` }"
  >
    <MdiIcon :path="mdiMusicBox" :size="Math.round(box * 0.6)" />
  </span>
</template>
