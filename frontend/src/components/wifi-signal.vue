<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ rssi?: number; signal?: number; muted?: boolean }>()

// Tasmota reports RSSI as a 0–100 % quality value.
const bars = computed(() => {
  const quality = props.rssi ?? 0
  if (props.muted || !quality) return 0
  if (quality >= 75) return 4
  if (quality >= 50) return 3
  if (quality >= 25) return 2
  return 1
})

const description = computed(() => {
  if (props.rssi === undefined) return 'WiFi signal unknown'
  const dbm = props.signal !== undefined ? ` (${props.signal} dBm)` : ''
  return `WiFi signal ${props.rssi}%${dbm}`
})
</script>

<template>
  <span class="inline-flex items-center gap-1.5 text-sm text-muted" :title="description" :aria-label="description">
    <span class="flex h-3.5 items-end gap-[2px]" aria-hidden="true">
      <span
        v-for="level in 4"
        :key="level"
        class="w-[3px] rounded-sm"
        :class="level <= bars ? 'bg-accent' : 'bg-line'"
        :style="{ height: `${level * 25}%` }"
      />
    </span>
    <span>WiFi</span>
    <span v-if="rssi !== undefined && !muted">{{ rssi }}%</span>
  </span>
</template>
