<script setup lang="ts">
import { reactive, ref } from 'vue'
import { api, type Theme, type UserSettings } from '../../api'
import { session } from '../../stores/session'

const passwords = reactive({ current: '', next: '', confirm: '' })
const passwordMessage = ref('')
const passwordError = ref('')
const savingPassword = ref(false)
const settingsError = ref('')

const themes: { value: Theme; label: string }[] = [
  { value: 'system', label: 'Same as system' },
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
]

async function changePassword() {
  passwordMessage.value = passwordError.value = ''
  if (passwords.next !== passwords.confirm) {
    passwordError.value = 'The new passwords do not match'
    return
  }
  savingPassword.value = true
  try {
    await api('POST', '/api/users/me/password', {
      current_password: passwords.current,
      new_password: passwords.next,
    })
    Object.assign(passwords, { current: '', next: '', confirm: '' })
    passwordMessage.value = 'Password changed. Other sessions have been signed out.'
  } catch (e) {
    passwordError.value = e instanceof Error ? e.message : 'Could not change the password'
  } finally {
    savingPassword.value = false
  }
}

async function saveSetting(patch: Partial<UserSettings>) {
  settingsError.value = ''
  try {
    await session.updateSettings(patch)
  } catch (e) {
    settingsError.value = e instanceof Error ? e.message : 'Could not save the setting'
  }
}
</script>

<template>
  <div class="grid max-w-4xl gap-6 lg:grid-cols-2">
    <section class="card p-5">
      <h2 class="mb-1 text-lg font-semibold">Change password</h2>
      <p class="mb-4 text-sm text-muted">Signed in as {{ session.state.user?.username }}.</p>
      <form class="space-y-4" @submit.prevent="changePassword">
        <div>
          <label class="label" for="current-password">Current password</label>
          <input
            id="current-password"
            v-model="passwords.current"
            class="input"
            type="password"
            required
            autocomplete="current-password"
          />
        </div>
        <div>
          <label class="label" for="new-password">New password</label>
          <input id="new-password" v-model="passwords.next" class="input" type="password" required autocomplete="new-password" />
        </div>
        <div>
          <label class="label" for="confirm-password">Confirm new password</label>
          <input
            id="confirm-password"
            v-model="passwords.confirm"
            class="input"
            type="password"
            required
            autocomplete="new-password"
          />
        </div>
        <p v-if="passwordError" class="error-box" role="alert">{{ passwordError }}</p>
        <p v-if="passwordMessage" class="rounded-lg bg-accent-soft px-3 py-2 text-sm text-accent">{{ passwordMessage }}</p>
        <button class="btn btn-primary" type="submit" :disabled="savingPassword">Change password</button>
      </form>
    </section>

    <section class="card p-5">
      <h2 class="mb-4 text-lg font-semibold">Appearance</h2>

      <fieldset class="mb-5">
        <legend class="label">Theme</legend>
        <div class="flex flex-wrap gap-2">
          <label
            v-for="theme in themes"
            :key="theme.value"
            class="flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm"
            :class="session.state.settings.theme === theme.value ? 'border-accent bg-accent-soft text-accent' : 'border-line'"
          >
            <input
              type="radio"
              name="theme"
              class="sr-only"
              :value="theme.value"
              :checked="session.state.settings.theme === theme.value"
              @change="saveSetting({ theme: theme.value })"
            />
            {{ theme.label }}
          </label>
        </div>
      </fieldset>

      <fieldset class="space-y-3">
        <legend class="label">Menu</legend>
        <label class="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            class="h-4 w-4 accent-[var(--hs-accent)]"
            :checked="session.state.settings.sidebar_collapsed"
            @change="saveSetting({ sidebar_collapsed: ($event.target as HTMLInputElement).checked })"
          />
          Collapse the side menu to icons
        </label>
        <label class="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            class="h-4 w-4 accent-[var(--hs-accent)]"
            :checked="session.state.settings.sholink_expanded"
            @change="saveSetting({ sholink_expanded: ($event.target as HTMLInputElement).checked })"
          />
          Show ShoLink links in the menu
        </label>
      </fieldset>
      <p v-if="settingsError" class="error-box mt-4" role="alert">{{ settingsError }}</p>
    </section>
  </div>
</template>
