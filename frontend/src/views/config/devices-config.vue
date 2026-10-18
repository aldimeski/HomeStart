<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { api } from '../../api'
import { tasmota } from '../../stores/tasmota'

const credentials = reactive({ username: '', password: '' })
const hasPassword = ref(false)
const configured = ref(false)
const message = ref('')
const error = ref('')
const saving = ref(false)

async function load() {
  const data = await api<{ username: string | null; has_password: boolean }>('GET', '/api/tasmota/credentials')
  credentials.username = data.username ?? ''
  credentials.password = ''
  hasPassword.value = data.has_password
  configured.value = data.username !== null
}

async function save() {
  error.value = message.value = ''
  saving.value = true
  try {
    await api('PUT', '/api/tasmota/credentials', {
      username: credentials.username,
      // An empty field keeps the stored password.
      password: credentials.password || (hasPassword.value ? null : ''),
    })
    await load()
    message.value = 'Credentials saved.'
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Could not save the credentials'
  } finally {
    saving.value = false
  }
}

async function clear() {
  error.value = message.value = ''
  try {
    await api('DELETE', '/api/tasmota/credentials')
    await load()
    message.value = 'Credentials removed.'
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Could not remove the credentials'
  }
}

onMounted(() => {
  load().catch((e) => (error.value = e.message))
  tasmota.connect()
})
onBeforeUnmount(() => tasmota.disconnect())
</script>

<template>
  <div class="grid max-w-5xl gap-6 lg:grid-cols-[22rem_1fr]">
    <section class="card self-start p-5">
      <h2 class="mb-1 text-lg font-semibold">Tasmota login</h2>
      <p class="mb-4 text-sm text-muted">
        Shared web login of all Tasmota devices. Needed only for the network scan and HTTP access; status and
        switching use MQTT. Stored encrypted.
      </p>
      <form class="space-y-4" @submit.prevent="save">
        <div>
          <label class="label" for="tasmota-user">Username</label>
          <input id="tasmota-user" v-model="credentials.username" class="input" required maxlength="64" autocomplete="off" />
        </div>
        <div>
          <label class="label" for="tasmota-password">Password</label>
          <input
            id="tasmota-password"
            v-model="credentials.password"
            class="input"
            type="password"
            maxlength="128"
            autocomplete="new-password"
            :placeholder="hasPassword ? 'Unchanged' : ''"
          />
        </div>
        <p v-if="error" class="error-box" role="alert">{{ error }}</p>
        <p v-if="message" class="rounded-lg bg-accent-soft px-3 py-2 text-sm text-accent">{{ message }}</p>
        <div class="flex gap-2">
          <button class="btn btn-primary" type="submit" :disabled="saving">Save</button>
          <button v-if="configured" class="btn" type="button" @click="clear">Remove</button>
        </div>
      </form>
    </section>

    <section class="card overflow-x-auto self-start">
      <h2 class="px-4 pt-4 text-lg font-semibold">Devices</h2>
      <p class="px-4 pb-3 text-sm text-muted">Rename, group or remove devices from the TasmoSiz page.</p>
      <table class="w-full text-sm">
        <thead class="text-left text-muted">
          <tr class="border-y border-line">
            <th class="px-4 py-2 font-medium">Name</th>
            <th class="px-4 py-2 font-medium">Status</th>
            <th class="hidden px-4 py-2 font-medium md:table-cell">IP address</th>
            <th class="hidden px-4 py-2 font-medium md:table-cell">Firmware</th>
            <th class="px-4 py-2 font-medium">Login</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-line">
          <tr v-for="device in tasmota.state.devices" :key="device.id">
            <td class="px-4 py-2 font-medium">
              {{ device.display_name }}
              <span v-if="device.group_name" class="block text-xs font-normal text-muted">{{ device.group_name }}</span>
            </td>
            <td class="px-4 py-2">{{ device.online ? 'Online' : device.online === false ? 'Offline' : 'Unknown' }}</td>
            <td class="hidden px-4 py-2 md:table-cell">{{ device.host ?? '–' }}</td>
            <td class="hidden px-4 py-2 md:table-cell">{{ device.firmware ?? '–' }}</td>
            <td class="px-4 py-2">{{ device.auth_required ? 'Required' : '–' }}</td>
          </tr>
          <tr v-if="tasmota.state.loaded && !tasmota.state.devices.length">
            <td colspan="5" class="px-4 py-4 text-center text-muted">No devices yet.</td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>
