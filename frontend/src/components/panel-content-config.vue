<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { mdiArrowDown, mdiArrowUp, mdiClose, mdiPencilOutline } from '@mdi/js'
import { api, type PanelContent, type PanelItem } from '../api'
import MdiIcon from './mdi-icon.vue'

const content = ref<PanelContent | null>(null)
const error = ref('')

const sections = [
  { key: 'favorites' as const, title: 'Favourite tracks', empty: 'None yet. Press the star on a track in the Player.' },
  {
    key: 'suggestions' as const,
    title: 'Suggestions',
    empty: 'None yet. Press "Offer on the openpanel" on an album, a folder or a panel playlist in the Player.',
  },
]

async function load() {
  content.value = await api<PanelContent>('GET', '/api/config/player/panel')
}

async function run(action: () => Promise<unknown>, fallback: string) {
  error.value = ''
  try {
    await action()
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : fallback
  }
}

function move(section: 'favorites' | 'suggestions', index: number, delta: number) {
  const ids = content.value![section].map((i) => i.id)
  const [moved] = ids.splice(index, 1)
  ids.splice(index + delta, 0, moved)
  return run(() => api('PUT', `/api/config/player/panel/${section}/order`, { ids }), 'Could not save the order')
}

function retitle(item: PanelItem) {
  const title = prompt(`Title for "${item.name}" (empty = its own name):`, item.title ?? '')
  if (title === null) return
  return run(() => api('PUT', `/api/config/player/panel/items/${item.id}`, { title }), 'Could not rename')
}

const remove = (item: PanelItem) => run(() => api('DELETE', `/api/config/player/panel/items/${item.id}`), 'Could not remove')

onMounted(() => load().catch((e) => (error.value = e instanceof Error ? e.message : 'Could not load the openpanel content')))
</script>

<template>
  <section v-if="content" class="card mt-6 p-4" aria-labelledby="panel-title">
    <h2 id="panel-title" class="text-lg font-semibold">Openpanel content</h2>
    <p class="mt-1 text-sm text-muted">
      What the openpanel (no login) offers besides the whole library. Panel playlists
      ({{ content.playlists.length }} so far) are made on the Playlists tab of the Player and are shown there to everybody.
    </p>
    <p v-if="error" class="error-box mt-3" role="alert">{{ error }}</p>

    <div v-for="section in sections" :key="section.key" class="mt-4">
      <h3 class="mb-1 text-sm font-semibold">{{ section.title }}</h3>
      <ul class="divide-y divide-line rounded-lg border border-line">
        <li v-for="(item, index) in content[section.key]" :key="item.id" class="flex items-center gap-2 px-3 py-2" :class="item.available ? '' : 'opacity-60'">
          <span class="pill shrink-0">{{ item.kind }}</span>
          <div class="min-w-0 flex-1">
            <div class="truncate font-medium">{{ item.title ?? item.name }}</div>
            <div class="truncate text-xs text-muted">
              <template v-if="item.title">{{ item.name }} · </template>
              <template v-if="!item.available">not available now</template>
            </div>
          </div>
          <button class="btn-icon shrink-0" title="Move up" :disabled="index === 0" @click="move(section.key, index, -1)">
            <MdiIcon :path="mdiArrowUp" :size="18" />
          </button>
          <button class="btn-icon shrink-0" title="Move down" :disabled="index === content[section.key].length - 1" @click="move(section.key, index, 1)">
            <MdiIcon :path="mdiArrowDown" :size="18" />
          </button>
          <button class="btn-icon shrink-0" title="Change the title" @click="retitle(item)">
            <MdiIcon :path="mdiPencilOutline" :size="18" />
          </button>
          <button class="btn-icon shrink-0 hover:text-danger" title="Take off the openpanel" @click="remove(item)">
            <MdiIcon :path="mdiClose" :size="18" />
          </button>
        </li>
        <li v-if="!content[section.key].length" class="px-3 py-3 text-sm text-muted">{{ section.empty }}</li>
      </ul>
    </div>
  </section>
</template>
