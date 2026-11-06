<script setup lang="ts">
import { reactive, ref } from 'vue'
import { api, type RadioStation, type RadioStationInput } from '../api'
import BaseDialog from './base-dialog.vue'

const props = defineProps<{ station?: RadioStation }>()
const emit = defineEmits<{ close: []; saved: [] }>()

const form = reactive({
  slug: props.station?.slug ?? '',
  name: props.station?.name ?? '',
  sub: props.station?.sub ?? '',
  urls: (props.station?.urls ?? []).join('\n'),
  content_type: props.station?.content_type ?? '',
})
const error = ref('')
const saving = ref(false)

async function save() {
  error.value = ''
  saving.value = true
  const body: RadioStationInput = {
    slug: form.slug.trim(),
    name: form.name.trim(),
    sub: form.sub.trim() || null,
    urls: form.urls
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean),
    content_type: form.content_type.trim() || null,
  }
  try {
    if (props.station) await api('PUT', `/api/radio/stations/${props.station.id}`, body)
    else await api('POST', '/api/radio/stations', body)
    emit('saved')
    emit('close')
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Could not save the station'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <BaseDialog :title="station ? 'Edit station' : 'Add station'" @close="emit('close')">
    <form id="station-form" class="space-y-4" @submit.prevent="save">
      <div>
        <label class="label" for="station-name">Name</label>
        <input id="station-name" v-model="form.name" class="input" maxlength="64" required />
      </div>
      <div>
        <label class="label" for="station-sub">Subtitle</label>
        <input id="station-sub" v-model="form.sub" class="input" maxlength="64" placeholder="Country · genre" />
      </div>
      <div>
        <label class="label" for="station-slug">Id</label>
        <input
          id="station-slug"
          v-model="form.slug"
          class="input"
          maxlength="40"
          pattern="[a-z0-9\-]+"
          required
          placeholder="rock-antenne"
        />
        <p class="mt-1 text-xs text-muted">Lowercase letters, digits and hyphens; used in the address /openpanel/radio/&lt;id&gt;.</p>
      </div>
      <div>
        <label class="label" for="station-urls">Stream addresses</label>
        <textarea
          id="station-urls"
          v-model="form.urls"
          class="input"
          rows="3"
          required
          placeholder="https://example.org/stream"
        />
        <p class="mt-1 text-xs text-muted">One per line, up to 5. They are tried in order until one answers.</p>
      </div>
      <div>
        <label class="label" for="station-type">Content type (optional)</label>
        <input id="station-type" v-model="form.content_type" class="input" maxlength="64" placeholder="audio/aac" />
        <p class="mt-1 text-xs text-muted">Overrides the type the station sends, for stations Safari cannot play otherwise.</p>
      </div>
      <p v-if="error" class="error-box" role="alert">{{ error }}</p>
    </form>

    <template #footer>
      <button type="button" class="btn" @click="emit('close')">Cancel</button>
      <button type="submit" form="station-form" class="btn btn-primary" :disabled="saving">
        {{ saving ? 'Saving…' : 'Save' }}
      </button>
    </template>
  </BaseDialog>
</template>
