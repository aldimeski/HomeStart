<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { session } from '../stores/session'

const route = useRoute()
const router = useRouter()

const username = ref('')
const password = ref('')
const error = ref('')
const busy = ref(false)

async function submit() {
  error.value = ''
  busy.value = true
  try {
    await session.login(username.value, password.value)
    const redirect = typeof route.query.redirect === 'string' && route.query.redirect.startsWith('/') ? route.query.redirect : '/'
    router.replace(redirect)
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Login failed'
    password.value = ''
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="flex min-h-full items-center justify-center p-4">
    <form class="card w-full max-w-sm p-7 shadow-sm" @submit.prevent="submit">
      <div class="mb-6 flex items-center gap-3">
        <img src="/favicon.svg" alt="" width="36" height="36" />
        <div>
          <h1 class="text-xl font-bold">HomeStart</h1>
          <p class="text-sm text-muted">Sign in to continue</p>
        </div>
      </div>

      <label class="label" for="username">Username</label>
      <input id="username" v-model="username" class="input mb-4" autocomplete="username" autofocus required />

      <label class="label" for="password">Password</label>
      <input
        id="password"
        v-model="password"
        class="input mb-4"
        type="password"
        autocomplete="current-password"
        required
      />

      <p v-if="error" class="error-box mb-4" role="alert">{{ error }}</p>

      <button class="btn btn-primary w-full" type="submit" :disabled="busy">
        {{ busy ? 'Signing in…' : 'Sign in' }}
      </button>
    </form>
  </div>
</template>
