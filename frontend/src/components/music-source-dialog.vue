<script setup lang="ts">
import { reactive, ref } from 'vue'
import { api, type MusicSource, type MusicSourceInput, type MusicSourceTest } from '../api'
import BaseDialog from './base-dialog.vue'

const props = defineProps<{ source?: MusicSource }>()
const emit = defineEmits<{ close: []; saved: [] }>()

const form = reactive({
  name: props.source?.name ?? '',
  kind: props.source?.kind ?? ('local' as 'local' | 'smb'),
  path: props.source?.path ?? '',
  network_path: props.source?.network_path ?? '',
  username: props.source?.username ?? '',
  password: '',
  enabled: props.source?.enabled ?? true,
})
const error = ref('')
const saving = ref(false)
const testing = ref(false)
const testResult = ref<MusicSourceTest | null>(null)

function body(): MusicSourceInput {
  const common = { name: form.name.trim(), kind: form.kind, enabled: form.enabled }
  if (form.kind === 'local') return { ...common, path: form.path.trim() }
  return {
    ...common,
    network_path: form.network_path.trim(),
    username: form.username.trim() || null,
    // Empty when editing: the saved password stays.
    password: form.password || null,
  }
}

async function test() {
  error.value = ''
  testResult.value = null
  testing.value = true
  try {
    testResult.value = await api<MusicSourceTest>('POST', '/api/config/player/sources/test', { ...body(), source_id: props.source?.id ?? null })
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Could not test the location'
  } finally {
    testing.value = false
  }
}

async function save() {
  error.value = ''
  saving.value = true
  try {
    if (props.source) await api('PUT', `/api/config/player/sources/${props.source.id}`, body())
    else await api('POST', '/api/config/player/sources', body())
    emit('saved')
    emit('close')
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Could not save the location'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <BaseDialog :title="source ? 'Edit location' : 'Add location'" @close="emit('close')">
    <form id="source-form" class="space-y-4" @submit.prevent="save">
      <div>
        <label class="label" for="source-name">Name</label>
        <input id="source-name" v-model="form.name" class="input" maxlength="64" required placeholder="Music" />
        <p class="mt-1 text-xs text-muted">Shown to users as the first level when browsing folders.</p>
      </div>

      <div v-if="!source">
        <label class="label" for="source-kind">Kind</label>
        <select id="source-kind" v-model="form.kind" class="input" @change="testResult = null">
          <option value="local">Folder on the server</option>
          <option value="smb">Network share (SMB)</option>
        </select>
      </div>

      <div v-if="form.kind === 'local'">
        <label class="label" for="source-path">Folder on the server</label>
        <input id="source-path" v-model="form.path" class="input" maxlength="1000" required placeholder="/srv/music" />
        <p class="mt-1 text-xs text-muted">
          The full path. HomeStart only reads the folder and its subfolders; it never changes or deletes files.
        </p>
      </div>

      <template v-else>
        <div>
          <label class="label" for="source-network">Network path</label>
          <input
            id="source-network"
            v-model="form.network_path"
            class="input"
            maxlength="1000"
            required
            placeholder="\\192.168.1.20\Music\Albums"
          />
          <p class="mt-1 text-xs text-muted">
            \\server\share or \\server\share\folder. Only servers of the local network are allowed.
          </p>
        </div>
        <div class="grid gap-4 sm:grid-cols-2">
          <div>
            <label class="label" for="source-user">User name</label>
            <input id="source-user" v-model="form.username" class="input" maxlength="128" autocomplete="off" />
          </div>
          <div>
            <label class="label" for="source-password">Password</label>
            <input
              id="source-password"
              v-model="form.password"
              class="input"
              type="password"
              maxlength="256"
              autocomplete="new-password"
              :placeholder="source?.has_password ? 'Saved – leave empty to keep it' : ''"
            />
          </div>
        </div>
        <p class="text-xs text-muted">
          Leave the user name empty to read the share as a guest. The password is stored encrypted and is never shown again.
        </p>
      </template>

      <label class="flex items-center gap-2 text-sm">
        <input v-model="form.enabled" type="checkbox" />
        Switched on (scanned and shown to listeners)
      </label>

      <div class="flex flex-wrap items-center gap-3">
        <button type="button" class="btn" :disabled="testing" @click="test">{{ testing ? 'Testing…' : 'Test connection' }}</button>
        <p
          v-if="testResult"
          class="text-sm"
          :class="testResult.ok ? 'text-accent' : 'text-danger'"
          :role="testResult.ok ? 'status' : 'alert'"
        >
          {{ testResult.message }}
        </p>
      </div>
      <p v-if="error" class="error-box" role="alert">{{ error }}</p>
    </form>

    <template #footer>
      <button type="button" class="btn" @click="emit('close')">Cancel</button>
      <button type="submit" form="source-form" class="btn btn-primary" :disabled="saving">
        {{ saving ? 'Saving…' : 'Save' }}
      </button>
    </template>
  </BaseDialog>
</template>
