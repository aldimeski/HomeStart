<script setup lang="ts">
import MdiIcon from '../components/mdi-icon.vue'
import PageHeader from '../components/page-header.vue'

defineProps<{ title: string; icon: string }>()
</script>

<template>
  <div class="flex h-full flex-col">
    <PageHeader :title="title" />
    <div class="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center text-muted">
      <MdiIcon :path="icon" :size="48" class="text-accent" />
      <p class="text-lg font-semibold text-ink">Coming soon</p>
      <p class="max-w-sm text-sm">This module is planned for a later version of HomeStart.</p>
    </div>
  </div>
</template>
