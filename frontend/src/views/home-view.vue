<script setup lang="ts">
import { mdiOpenInNew } from '@mdi/js'
import PageHeader from '../components/page-header.vue'
import LinkIcon from '../components/link-icon.vue'
import MdiIcon from '../components/mdi-icon.vue'
import { links } from '../stores/links'
import { session } from '../stores/session'
</script>

<template>
  <div class="flex h-full flex-col">
    <PageHeader title="HomeStart" />
    <div class="flex-1 overflow-y-auto p-4 md:p-7">
      <p class="mb-5 text-muted">Welcome, {{ session.state.user?.username }}. Choose an application:</p>

      <div class="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-4">
        <component
          :is="link.open_in_new_tab ? 'a' : 'RouterLink'"
          v-for="link in links.state.items"
          :key="link.id"
          v-bind="
            link.open_in_new_tab
              ? { href: link.url, target: '_blank', rel: 'noopener noreferrer' }
              : { to: `/link/${link.id}` }
          "
          class="card flex items-center gap-3 p-4 transition-colors hover:border-accent"
        >
          <span class="flex h-10 w-10 items-center justify-center rounded-lg bg-accent-soft text-accent">
            <LinkIcon :icon="link.icon" :size="24" />
          </span>
          <span class="min-w-0 flex-1 truncate font-semibold">{{ link.title }}</span>
          <MdiIcon v-if="link.open_in_new_tab" :path="mdiOpenInNew" :size="16" class="text-muted" />
        </component>
      </div>

      <div v-if="links.state.loaded && !links.state.items.length" class="card p-6 text-center text-muted">
        No links have been added yet.
        <RouterLink v-if="session.isAdmin.value" to="/config/links" class="text-accent underline">
          Add the first link
        </RouterLink>
      </div>
    </div>
  </div>
</template>
