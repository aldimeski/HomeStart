<script setup lang="ts">
import type { IconLayer } from '../icons/switch-icons'

// body is only ever set from the static BUILTIN_ICONS table, never from user input.
withDefaults(defineProps<{ path?: string; body?: string; layers?: IconLayer[]; size?: number }>(), { size: 20 })
</script>

<template>
  <svg v-if="body" :width="size" :height="size" viewBox="0 0 24 24" aria-hidden="true" class="shrink-0" v-html="body" />
  <svg v-else-if="layers" :width="size" :height="size" viewBox="0 0 24 24" aria-hidden="true" class="shrink-0">
    <path v-for="(layer, index) in layers" :key="index" :d="layer.d" :fill="layer.fill" :class="layer.lit ? 'lit' : undefined" />
  </svg>
  <svg v-else :width="size" :height="size" viewBox="0 0 24 24" aria-hidden="true" class="shrink-0">
    <path v-if="path" :d="path" fill="currentColor" />
  </svg>
</template>
