<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { mdiOpenInNew } from '@mdi/js'
import { api, ApiError, type SkodaAccount, type SkodaOverview } from '../api'
import MdiIcon from './mdi-icon.vue'

const account = ref<SkodaAccount | null>(null)
const form = reactive({ username: '', password: '' })
const error = ref('')
// A Škoda page (new terms or consent) that has to be answered before the login works.
const actionUrl = ref<string | null>(null)
const busy = ref(false)
const confirmingSignOut = ref(false)

onMounted(async () => {
  try {
    account.value = (await api<SkodaOverview>('GET', '/api/skoda/vehicles')).account
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Could not load the Škoda account'
  }
})

async function connect() {
  error.value = ''
  actionUrl.value = null
  busy.value = true
  try {
    account.value = (await api<SkodaOverview>('PUT', '/api/skoda/account', form)).account
    form.password = ''
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Could not connect the account'
    const url = e instanceof ApiError ? (e.data as { action_url?: unknown } | null)?.action_url : null
    actionUrl.value = typeof url === 'string' && url.startsWith('https://') ? url : null
  } finally {
    busy.value = false
  }
}

async function signOut() {
  error.value = ''
  try {
    await api('DELETE', '/api/skoda/account')
    account.value = { connected: false }
    confirmingSignOut.value = false
    form.username = form.password = ''
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Could not sign out'
  }
}
</script>

<template>
  <section class="card p-5">
    <h2 class="mb-1 text-lg font-semibold">Škoda account</h2>
    <p v-if="!account" class="text-sm text-muted">Loading…</p>

    <template v-else-if="account.connected">
      <p class="mb-4 text-sm text-muted">
        Connected as <span class="font-medium text-ink">{{ account.username }}</span>.
        <template v-if="account.last_sync">Last update {{ new Date(`${account.last_sync}Z`).toLocaleString() }}.</template>
      </p>
      <p class="mb-4 text-sm text-muted">
        HomeStart only reads vehicle information. It never locks, unlocks or controls a vehicle.
      </p>
      <p v-if="error" class="error-box mb-4" role="alert">{{ error }}</p>
      <button v-if="!confirmingSignOut" type="button" class="btn btn-danger" @click="confirmingSignOut = true">
        Sign out of Škoda account
      </button>
      <div v-else class="rounded-lg border border-line p-3 text-sm">
        <p class="mb-2 font-medium">Sign out? The stored login and vehicle data are deleted.</p>
        <div class="flex gap-2">
          <button type="button" class="btn" @click="confirmingSignOut = false">Keep</button>
          <button type="button" class="btn btn-danger" @click="signOut">Sign out</button>
        </div>
      </div>
    </template>

    <template v-else>
      <p class="mb-4 text-sm text-muted">
        Connect your MyŠkoda account to see your vehicles on the Škoda page. The login is stored encrypted and is
        only used to read vehicle information.
      </p>
      <form class="space-y-4" @submit.prevent="connect">
        <div>
          <label class="label" for="skoda-username">MyŠkoda email</label>
          <input id="skoda-username" v-model="form.username" class="input" type="email" autocomplete="off" required maxlength="254" />
        </div>
        <div>
          <label class="label" for="skoda-password">MyŠkoda password</label>
          <input
            id="skoda-password"
            v-model="form.password"
            class="input"
            type="password"
            autocomplete="new-password"
            required
            maxlength="256"
          />
        </div>
        <div v-if="error" class="error-box space-y-2" role="alert">
          <p>{{ error }}</p>
          <a v-if="actionUrl" :href="actionUrl" target="_blank" rel="noopener noreferrer" class="btn btn-danger bg-surface">
            Open the Škoda page
            <MdiIcon :path="mdiOpenInNew" :size="16" />
          </a>
        </div>
        <button type="submit" class="btn btn-primary" :disabled="busy">
          {{ busy ? 'Connecting to Škoda…' : 'Connect account' }}
        </button>
      </form>
    </template>
  </section>
</template>
