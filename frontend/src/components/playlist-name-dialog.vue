<script setup lang="ts">
import { ref } from 'vue'
import { api, type Playlist } from '../api'
import { session } from '../stores/session'
import BaseDialog from './base-dialog.vue'

const props = defineProps<{ playlist?: Playlist }>()
const emit = defineEmits<{ close: []; saved: [playlist: Playlist] }>()

const name = ref(props.playlist?.name ?? '')
const panel = ref(false)
const error = ref('')
const saving = ref(false)

async function save() {
  error.value = ''
  saving.value = true
  try {
    const saved = props.playlist
      ? await api<Playlist>('PUT', `/api/player/playlists/${props.playlist.id}`, { name: name.value })
      : await api<Playlist>('POST', '/api/player/playlists', { name: name.value, panel: panel.value })
    emit('saved', saved)
    emit('close')
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Could not save the playlist'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <BaseDialog :title="playlist ? 'Rename playlist' : 'New playlist'" @close="emit('close')">
    <form id="playlist-name-form" class="space-y-4" @submit.prevent="save">
      <div>
        <label class="label" for="playlist-name">Name</label>
        <input id="playlist-name" v-model="name" class="input" maxlength="64" required autofocus />
      </div>
      <label v-if="!playlist && session.isAdmin.value" class="flex items-start gap-2 text-sm">
        <input v-model="panel" type="checkbox" class="mt-1" />
        <span>
          A panel playlist
          <span class="block text-xs text-muted">Shown to everybody, also on the openpanel; only administrators can change it.</span>
        </span>
      </label>
      <p v-if="error" class="error-box" role="alert">{{ error }}</p>
    </form>
    <template #footer>
      <button type="button" class="btn" @click="emit('close')">Cancel</button>
      <button type="submit" form="playlist-name-form" class="btn btn-primary" :disabled="saving">Save</button>
    </template>
  </BaseDialog>
</template>
