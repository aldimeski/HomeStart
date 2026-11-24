<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, type MusicScanDetail } from '../api'
import BaseDialog from './base-dialog.vue'

const props = defineProps<{ scanId: number }>()
const emit = defineEmits<{ close: [] }>()

type Kind = 'added' | 'changed' | 'removed' | 'new_folders' | 'removed_folders' | 'errors'

const report = ref<MusicScanDetail | null>(null)
const error = ref('')
const kind = ref<Kind>('added')

const groups = computed(() => {
  const r = report.value
  if (!r) return []
  return [
    { key: 'added' as const, label: 'New files', count: r.added, items: r.added_files },
    { key: 'changed' as const, label: 'Changed files', count: r.changed, items: r.changed_files },
    { key: 'removed' as const, label: 'Removed files', count: r.removed, items: r.removed_files },
    { key: 'new_folders' as const, label: 'New folders', count: r.new_folders.length, items: r.new_folders },
    { key: 'removed_folders' as const, label: 'Removed folders', count: r.removed_folders.length, items: r.removed_folders },
    { key: 'errors' as const, label: 'Errors', count: r.errors, items: r.error_list },
  ]
})
const current = computed(() => groups.value.find((g) => g.key === kind.value))

function format(value: string | null) {
  return value ? new Date(value + 'Z').toLocaleString() : '–'
}

onMounted(async () => {
  try {
    report.value = await api<MusicScanDetail>('GET', `/api/config/player/scans/${props.scanId}`)
    // Open on the first kind that has anything to show.
    kind.value = groups.value.find((g) => g.count > 0)?.key ?? 'added'
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Could not load the report'
  }
})
</script>

<template>
  <BaseDialog title="Scan report" wide @close="emit('close')">
    <p v-if="error" class="error-box" role="alert">{{ error }}</p>
    <template v-if="report">
      <p class="mb-3 text-sm text-muted">
        {{ format(report.started_at) }} – {{ format(report.finished_at) }} ·
        {{ report.started_by ? `started by ${report.started_by}` : 'scheduled' }} · {{ report.status }}
      </p>
      <p v-if="report.error_message" class="error-box mb-3" role="alert">{{ report.error_message }}</p>

      <div class="mb-3 flex flex-wrap gap-2" role="tablist">
        <button
          v-for="group in groups"
          :key="group.key"
          class="btn"
          :class="kind === group.key ? 'btn-primary' : ''"
          role="tab"
          :aria-selected="kind === group.key"
          @click="kind = group.key"
        >
          {{ group.label }} ({{ group.count }})
        </button>
      </div>

      <ul v-if="current?.items.length" class="card max-h-80 divide-y divide-line overflow-y-auto text-sm">
        <li v-for="item in current.items" :key="item" class="px-3 py-1.5 break-all">{{ item }}</li>
      </ul>
      <p v-else class="text-sm text-muted">Nothing in this group.</p>
      <p v-if="current && current.key !== 'errors' && current.count > current.items.length" class="mt-2 text-xs text-muted">
        The first {{ current.items.length }} are listed; the count is exact.
      </p>
    </template>
    <template #footer>
      <button class="btn" @click="emit('close')">Close</button>
    </template>
  </BaseDialog>
</template>
