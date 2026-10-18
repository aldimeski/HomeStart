<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import PageHeader from '../../components/page-header.vue'
import { session } from '../../stores/session'

const route = useRoute()

const tabs = computed(() => [
  ...(session.isAdmin.value
    ? [
        { to: '/config/links', label: 'Links' },
        { to: '/config/users', label: 'Users' },
        { to: '/config/devices', label: 'Devices' },
      ]
    : []),
  { to: '/config/account', label: 'My account' },
])
</script>

<template>
  <div class="flex h-full flex-col">
    <PageHeader title="Configuration" />
    <nav class="flex gap-1 overflow-x-auto border-b border-line bg-surface px-4 md:px-7" aria-label="Configuration sections">
      <RouterLink
        v-for="tab in tabs"
        :key="tab.to"
        :to="tab.to"
        class="-mb-px border-b-2 px-3 py-2.5 text-sm font-medium whitespace-nowrap"
        :class="route.path === tab.to ? 'border-accent text-accent' : 'border-transparent text-muted hover:text-ink'"
      >
        {{ tab.label }}
      </RouterLink>
    </nav>
    <div class="flex-1 overflow-y-auto p-4 md:p-7">
      <RouterView />
    </div>
  </div>
</template>
