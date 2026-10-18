<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { mdiMenu } from '@mdi/js'
import SideMenu from '../components/side-menu.vue'
import MdiIcon from '../components/mdi-icon.vue'
import { session } from '../stores/session'
import { links } from '../stores/links'

const route = useRoute()
const phoneQuery = window.matchMedia('(max-width: 767px)')
const isPhone = ref(phoneQuery.matches)
const drawerOpen = ref(false)

function onMediaChange(event: MediaQueryListEvent) {
  isPhone.value = event.matches
  if (!event.matches) drawerOpen.value = false
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') drawerOpen.value = false
}

onMounted(() => {
  phoneQuery.addEventListener('change', onMediaChange)
  window.addEventListener('keydown', onKeydown)
  if (!links.state.loaded) links.load().catch(() => {})
})

onBeforeUnmount(() => {
  phoneQuery.removeEventListener('change', onMediaChange)
  window.removeEventListener('keydown', onKeydown)
})

watch(() => route.fullPath, () => (drawerOpen.value = false))
</script>

<template>
  <div class="flex h-full">
    <aside
      v-if="!isPhone"
      class="shrink-0 border-r border-line transition-[width] duration-200"
      :class="session.state.settings.sidebar_collapsed ? 'w-[72px]' : 'w-[272px]'"
    >
      <SideMenu :collapsed="session.state.settings.sidebar_collapsed" :mobile="false" />
    </aside>

    <template v-else>
      <Transition
        enter-from-class="opacity-0"
        leave-to-class="opacity-0"
        enter-active-class="transition-opacity"
        leave-active-class="transition-opacity"
      >
        <div v-if="drawerOpen" class="fixed inset-0 z-30 bg-black/40" @click="drawerOpen = false" />
      </Transition>
      <aside
        class="fixed inset-y-0 left-0 z-40 w-[280px] max-w-[85vw] border-r border-line shadow-xl transition-transform duration-200"
        :class="drawerOpen ? 'translate-x-0' : '-translate-x-full'"
        :inert="!drawerOpen"
      >
        <SideMenu :collapsed="false" :mobile="true" @navigate="drawerOpen = false" @close="drawerOpen = false" />
      </aside>
    </template>

    <div class="flex min-w-0 flex-1 flex-col">
      <header v-if="isPhone" class="flex h-14 shrink-0 items-center gap-2 border-b border-line bg-surface px-2">
        <button class="btn-icon" aria-label="Open menu" @click="drawerOpen = true">
          <MdiIcon :path="mdiMenu" :size="24" />
        </button>
        <span class="font-bold">HomeStart</span>
      </header>
      <main class="min-h-0 flex-1 overflow-hidden">
        <RouterView />
      </main>
    </div>
  </div>
</template>
