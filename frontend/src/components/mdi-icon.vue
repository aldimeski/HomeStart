<script setup lang="ts">
// body is only ever set from the static BUILTIN_ICONS table, never from user input.
withDefaults(defineProps<{ path?: string; body?: string; size?: number }>(), { size: 20 })
</script>

<template>
  <svg v-if="body" :width="size" :height="size" viewBox="0 0 24 24" aria-hidden="true" class="shrink-0" v-html="body" />
  <svg v-else :width="size" :height="size" viewBox="0 0 24 24" aria-hidden="true" class="shrink-0">
    <path v-if="path" :d="path" fill="currentColor" />
  </svg>
</template>
