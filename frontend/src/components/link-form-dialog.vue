<script setup lang="ts">
import { reactive, ref } from 'vue'
import type { Link, LinkInput } from '../api'
import { links } from '../stores/links'
import BaseDialog from './base-dialog.vue'
import IconPicker from './icon-picker.vue'
import LinkIcon from './link-icon.vue'

const props = defineProps<{ link?: Link }>()
const emit = defineEmits<{ close: [] }>()

const form = reactive<LinkInput>({
  title: props.link?.title ?? '',
  url: props.link?.url ?? 'http://',
  icon: props.link?.icon ?? 'mdi:link-variant',
  open_in_new_tab: props.link?.open_in_new_tab ?? false,
})
const error = ref('')
const saving = ref(false)
const pickerOpen = ref(false)

async function save() {
  error.value = ''
  saving.value = true
  try {
    if (props.link) await links.update(props.link.id, { ...form })
    else await links.create({ ...form })
    emit('close')
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Could not save the link'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <BaseDialog :title="link ? 'Edit link' : 'Add link'" @close="emit('close')">
    <form id="link-form" class="space-y-4" @submit.prevent="save">
      <div>
        <label class="label" for="link-title">Name</label>
        <input id="link-title" v-model="form.title" class="input" maxlength="64" required placeholder="openHAB" />
      </div>
      <div>
        <label class="label" for="link-url">URL</label>
        <input
          id="link-url"
          v-model="form.url"
          class="input"
          type="url"
          required
          placeholder="http://server-address:8080"
        />
        <p class="mt-1 text-xs text-muted">
          Use an address the browser can reach (the server's IP address, not localhost).
        </p>
      </div>
      <div>
        <span class="label">Icon</span>
        <div class="flex items-center gap-3">
          <span class="flex h-11 w-11 items-center justify-center rounded-lg border border-line bg-surface-2">
            <LinkIcon :icon="form.icon" :size="26" />
          </span>
          <button type="button" class="btn" @click="pickerOpen = true">Choose icon…</button>
          <span class="truncate text-xs text-muted">{{ form.icon.startsWith('mdi:') ? form.icon.slice(4) : 'Uploaded icon' }}</span>
        </div>
      </div>
      <label class="flex items-start gap-2 text-sm">
        <input v-model="form.open_in_new_tab" type="checkbox" class="mt-0.5 h-4 w-4 accent-[var(--hs-accent)]" />
        <span>
          <span class="font-medium">Open in new tab</span>
          <span class="block text-xs text-muted">
            By default the page opens inside HomeStart. Enable this only for sites that cannot be embedded.
          </span>
        </span>
      </label>
      <p v-if="error" class="error-box" role="alert">{{ error }}</p>
    </form>

    <template #footer>
      <button type="button" class="btn" @click="emit('close')">Cancel</button>
      <button type="submit" form="link-form" class="btn btn-primary" :disabled="saving">
        {{ saving ? 'Saving…' : 'Save' }}
      </button>
    </template>
  </BaseDialog>

  <IconPicker v-if="pickerOpen" v-model="form.icon" @close="pickerOpen = false" />
</template>
