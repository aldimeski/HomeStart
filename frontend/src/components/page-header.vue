<script setup lang="ts">
defineProps<{ title: string }>()
</script>

<template>
  <header
    class="flex min-h-[64px] shrink-0 flex-wrap items-center gap-3 border-b border-line bg-surface px-4 py-3 md:min-h-[78px] md:px-7"
  >
    <h1 class="text-xl font-bold">{{ title }}</h1>
    <slot name="badge" />
    <div class="ml-auto flex items-center gap-2">
      <slot name="actions" />
    </div>
  </header>
</template>
