<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { mdiDeleteOutline, mdiUpload } from '@mdi/js'
import { api } from '../api'
import { loadMdiLibrary, searchMdi, SUGGESTED_ICONS, type MdiIcon as MdiEntry } from '../icons/mdi-library'
import BaseDialog from './base-dialog.vue'
import LinkIcon from './link-icon.vue'
import MdiIcon from './mdi-icon.vue'

const MAX_UPLOAD_BYTES = 256 * 1024

const props = defineProps<{ modelValue: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: string]; close: [] }>()

const tab = ref<'library' | 'uploaded'>(props.modelValue.startsWith('upload:') ? 'uploaded' : 'library')
const query = ref('')
const library = ref<MdiEntry[]>([])
const libraryError = ref('')
const uploaded = ref<string[]>([])
const uploadError = ref('')
const uploading = ref(false)
const fileInput = ref<HTMLInputElement>()

const suggested = computed(() =>
  SUGGESTED_ICONS.map((name) => library.value.find((icon) => icon.name === name)).filter(
    (icon): icon is MdiEntry => !!icon,
  ),
)
const results = computed(() => (query.value.trim() ? searchMdi(library.value, query.value) : suggested.value))

onMounted(async () => {
  loadMdiLibrary()
    .then((icons) => (library.value = icons))
    .catch((e) => (libraryError.value = e.message))
  loadUploaded()
})

async function loadUploaded() {
  try {
    uploaded.value = (await api<{ icon: string }[]>('GET', '/api/icons')).map((item) => item.icon)
  } catch (e) {
    uploadError.value = e instanceof Error ? e.message : 'Could not load uploaded icons'
  }
}

function choose(icon: string) {
  emit('update:modelValue', icon)
  emit('close')
}

async function upload(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (fileInput.value) fileInput.value.value = ''
  if (!file) return
  uploadError.value = ''
  if (file.size > MAX_UPLOAD_BYTES) {
    uploadError.value = 'Icon must be 256 KB or smaller'
    return
  }
  const form = new FormData()
  form.append('file', file)
  uploading.value = true
  try {
    const { icon } = await api<{ icon: string }>('POST', '/api/icons', form)
    uploaded.value.unshift(icon)
  } catch (e) {
    uploadError.value = e instanceof Error ? e.message : 'Upload failed'
  } finally {
    uploading.value = false
  }
}

async function removeUploaded(icon: string) {
  uploadError.value = ''
  try {
    await api('DELETE', `/api/icons/${icon.slice(7)}`)
    uploaded.value = uploaded.value.filter((item) => item !== icon)
  } catch (e) {
    uploadError.value = e instanceof Error ? e.message : 'Could not delete the icon'
  }
}

function tabClass(active: boolean) {
  return [
    'rounded-lg px-3 py-1.5 text-sm font-medium',
    active ? 'bg-accent-soft text-accent' : 'text-muted hover:text-ink',
  ]
}
</script>

<template>
  <BaseDialog title="Choose icon" wide @close="emit('close')">
    <div class="mb-4 flex gap-1" role="tablist">
      <button type="button" role="tab" :aria-selected="tab === 'library'" :class="tabClass(tab === 'library')" @click="tab = 'library'">
        Icon library
      </button>
      <button type="button" role="tab" :aria-selected="tab === 'uploaded'" :class="tabClass(tab === 'uploaded')" @click="tab = 'uploaded'">
        My icons
      </button>
    </div>

    <template v-if="tab === 'library'">
      <input
        v-model="query"
        class="input mb-3"
        type="search"
        placeholder="Search icons, e.g. router, car, lightbulb"
        aria-label="Search icons"
        autofocus
      />
      <p v-if="libraryError" class="error-box">{{ libraryError }}</p>
      <p v-else-if="!library.length" class="text-sm text-muted">Loading icons…</p>
      <template v-else>
        <p class="mb-2 text-xs text-muted">
          {{ query.trim() ? `${results.length}${results.length === 240 ? '+' : ''} matching icons` : 'Suggested icons' }}
        </p>
        <div class="grid grid-cols-[repeat(auto-fill,minmax(88px,1fr))] gap-2">
          <button
            v-for="icon in results"
            :key="icon.name"
            type="button"
            class="flex flex-col items-center gap-1 rounded-lg border p-2 text-[11px] text-muted hover:border-accent hover:text-ink"
            :class="modelValue === `mdi:${icon.name}` ? 'border-accent bg-accent-soft text-accent' : 'border-line'"
            :title="icon.name"
            @click="choose(`mdi:${icon.name}`)"
          >
            <MdiIcon :path="icon.path" :size="26" class="text-ink" />
            <span class="w-full truncate text-center">{{ icon.name }}</span>
          </button>
        </div>
        <p v-if="query.trim() && !results.length" class="text-sm text-muted">No icons found.</p>
      </template>
    </template>

    <template v-else>
      <div class="mb-3 flex flex-wrap items-center gap-3">
        <button type="button" class="btn" :disabled="uploading" @click="fileInput?.click()">
          <MdiIcon :path="mdiUpload" :size="18" />
          {{ uploading ? 'Uploading…' : 'Upload icon' }}
        </button>
        <span class="text-xs text-muted">SVG, PNG, WebP or ICO, up to 256 KB. Scripts are removed from SVG files.</span>
        <input
          ref="fileInput"
          type="file"
          class="hidden"
          accept=".svg,.png,.webp,.ico,image/svg+xml,image/png,image/webp,image/x-icon"
          @change="upload"
        />
      </div>
      <p v-if="uploadError" class="error-box mb-3">{{ uploadError }}</p>
      <p v-if="!uploaded.length" class="text-sm text-muted">No uploaded icons yet.</p>
      <div class="grid grid-cols-[repeat(auto-fill,minmax(88px,1fr))] gap-2">
        <div
          v-for="icon in uploaded"
          :key="icon"
          class="group relative flex flex-col items-center rounded-lg border p-3"
          :class="modelValue === icon ? 'border-accent bg-accent-soft' : 'border-line'"
        >
          <button type="button" class="flex w-full justify-center" title="Use this icon" @click="choose(icon)">
            <LinkIcon :icon="icon" :size="36" />
          </button>
          <button
            type="button"
            class="absolute top-1 right-1 rounded p-0.5 text-muted opacity-0 group-hover:opacity-100 hover:text-danger focus:opacity-100"
            title="Delete icon"
            @click="removeUploaded(icon)"
          >
            <MdiIcon :path="mdiDeleteOutline" :size="16" />
          </button>
        </div>
      </div>
    </template>
  </BaseDialog>
</template>
