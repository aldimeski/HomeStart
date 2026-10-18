<script setup lang="ts">
defineProps<{ checked: boolean | null; disabled?: boolean; busy?: boolean; label: string }>()
const emit = defineEmits<{ toggle: [] }>()
</script>

<template>
  <button
    type="button"
    role="switch"
    :aria-checked="checked === null ? 'mixed' : checked"
    :aria-label="label"
    :title="label"
    :disabled="disabled || busy"
    class="relative inline-flex h-7 w-12 shrink-0 items-center rounded-full transition-colors disabled:cursor-not-allowed"
    :class="[
      checked ? 'bg-accent' : 'bg-line',
      disabled ? 'opacity-50' : '',
      busy ? 'animate-pulse' : '',
    ]"
    @click="emit('toggle')"
  >
    <span
      class="inline-block h-5 w-5 rounded-full bg-white shadow transition-transform"
      :class="checked ? 'translate-x-6' : 'translate-x-1'"
    />
  </button>
</template>
