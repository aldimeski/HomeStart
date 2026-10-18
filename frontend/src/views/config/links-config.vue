<script setup lang="ts">
import { ref } from 'vue'
import {
  mdiArrowDown,
  mdiArrowUp,
  mdiDeleteOutline,
  mdiDragVertical,
  mdiOpenInNew,
  mdiPencilOutline,
  mdiPlus,
} from '@mdi/js'
import type { Link } from '../../api'
import { links } from '../../stores/links'
import LinkFormDialog from '../../components/link-form-dialog.vue'
import LinkIcon from '../../components/link-icon.vue'
import MdiIcon from '../../components/mdi-icon.vue'

const editing = ref<Link | null>(null)
const adding = ref(false)
const error = ref('')
const dragIndex = ref<number | null>(null)
const dropIndex = ref<number | null>(null)

async function saveOrder(ids: number[]) {
  error.value = ''
  try {
    await links.reorder(ids)
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Could not save the order'
    await links.load().catch(() => {})
  }
}

function move(index: number, delta: number) {
  const ids = links.state.items.map((link) => link.id)
  const [moved] = ids.splice(index, 1)
  ids.splice(index + delta, 0, moved)
  saveOrder(ids)
}

function onDragStart(index: number, event: DragEvent) {
  dragIndex.value = index
  event.dataTransfer?.setData('text/plain', String(index))
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'
}

function onDrop(index: number) {
  const from = dragIndex.value
  dragIndex.value = dropIndex.value = null
  if (from === null || from === index) return
  const ids = links.state.items.map((link) => link.id)
  const [moved] = ids.splice(from, 1)
  ids.splice(index, 0, moved)
  saveOrder(ids)
}

async function remove(link: Link) {
  if (!confirm(`Delete the link "${link.title}"?`)) return
  error.value = ''
  try {
    await links.remove(link.id)
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Could not delete the link'
  }
}
</script>

<template>
  <div class="max-w-4xl">
    <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 class="text-lg font-semibold">ShoLink links</h2>
        <p class="text-sm text-muted">Shared by all users. Drag to change the order in the menu.</p>
      </div>
      <button class="btn btn-primary" @click="adding = true">
        <MdiIcon :path="mdiPlus" :size="18" />
        Add link
      </button>
    </div>

    <p v-if="error" class="error-box mb-3" role="alert">{{ error }}</p>

    <ul class="card divide-y divide-line">
      <li
        v-for="(link, index) in links.state.items"
        :key="link.id"
        class="flex items-center gap-3 px-3 py-2.5"
        :class="{ 'opacity-50': dragIndex === index, 'bg-accent-soft': dropIndex === index && dragIndex !== index }"
        draggable="true"
        @dragstart="onDragStart(index, $event)"
        @dragover.prevent="dropIndex = index"
        @dragleave="dropIndex = dropIndex === index ? null : dropIndex"
        @drop.prevent="onDrop(index)"
        @dragend="dragIndex = dropIndex = null"
      >
        <MdiIcon :path="mdiDragVertical" class="cursor-grab text-muted" />
        <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-surface-2">
          <LinkIcon :icon="link.icon" :size="22" />
        </span>
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2 font-medium">
            <span class="truncate">{{ link.title }}</span>
            <span v-if="link.open_in_new_tab" class="pill shrink-0" title="Opens in a new tab">
              <MdiIcon :path="mdiOpenInNew" :size="12" class="mr-1" />new tab
            </span>
          </div>
          <div class="truncate text-sm text-muted">{{ link.url }}</div>
        </div>
        <div class="flex shrink-0 items-center">
          <button class="btn-icon" title="Move up" :disabled="index === 0" @click="move(index, -1)">
            <MdiIcon :path="mdiArrowUp" :size="18" />
          </button>
          <button
            class="btn-icon"
            title="Move down"
            :disabled="index === links.state.items.length - 1"
            @click="move(index, 1)"
          >
            <MdiIcon :path="mdiArrowDown" :size="18" />
          </button>
          <button class="btn-icon" title="Edit" @click="editing = link">
            <MdiIcon :path="mdiPencilOutline" :size="18" />
          </button>
          <button class="btn-icon hover:text-danger" title="Delete" @click="remove(link)">
            <MdiIcon :path="mdiDeleteOutline" :size="18" />
          </button>
        </div>
      </li>
      <li v-if="!links.state.items.length" class="px-4 py-6 text-center text-sm text-muted">
        No links yet. Add the first one, for example openHAB.
      </li>
    </ul>

    <LinkFormDialog v-if="adding" @close="adding = false" />
    <LinkFormDialog v-if="editing" :link="editing" @close="editing = null" />
  </div>
</template>
