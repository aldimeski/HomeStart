<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { mdiDeleteOutline, mdiKeyVariant, mdiPlus } from '@mdi/js'
import { api, type User } from '../../api'
import { session } from '../../stores/session'
import BaseDialog from '../../components/base-dialog.vue'
import MdiIcon from '../../components/mdi-icon.vue'

const users = ref<User[]>([])
const error = ref('')

const adding = ref(false)
const newUser = reactive({ username: '', password: '', role: 'user' as User['role'] })
const addError = ref('')

const resetting = ref<User | null>(null)
const resetPassword = ref('')
const resetError = ref('')
const notice = ref('')

async function load() {
  try {
    users.value = await api<User[]>('GET', '/api/users')
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Could not load users'
  }
}

onMounted(load)

function replace(updated: User) {
  users.value = users.value.map((user) => (user.id === updated.id ? updated : user))
}

async function update(user: User, patch: Partial<Pick<User, 'role' | 'is_active'>>) {
  error.value = notice.value = ''
  try {
    replace(await api<User>('PUT', `/api/users/${user.id}`, patch))
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Could not update the user'
    await load()
  }
}

async function create() {
  addError.value = ''
  try {
    const user = await api<User>('POST', '/api/users', newUser)
    users.value.push(user)
    users.value.sort((a, b) => a.username.localeCompare(b.username))
    adding.value = false
    Object.assign(newUser, { username: '', password: '', role: 'user' })
  } catch (e) {
    addError.value = e instanceof Error ? e.message : 'Could not create the user'
  }
}

async function doReset() {
  if (!resetting.value) return
  resetError.value = ''
  try {
    await api('POST', `/api/users/${resetting.value.id}/password`, { new_password: resetPassword.value })
    notice.value = `Password for ${resetting.value.username} has been reset.`
    resetting.value = null
    resetPassword.value = ''
  } catch (e) {
    resetError.value = e instanceof Error ? e.message : 'Could not reset the password'
  }
}

async function remove(user: User) {
  if (!confirm(`Delete the user "${user.username}"?`)) return
  error.value = notice.value = ''
  try {
    await api('DELETE', `/api/users/${user.id}`)
    users.value = users.value.filter((item) => item.id !== user.id)
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Could not delete the user'
  }
}

function formatDate(value: string | null) {
  return value ? new Date(`${value}Z`).toLocaleString() : 'Never'
}
</script>

<template>
  <div class="max-w-4xl">
    <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 class="text-lg font-semibold">Users</h2>
        <p class="text-sm text-muted">Administrators manage users and shared links.</p>
      </div>
      <button class="btn btn-primary" @click="adding = true">
        <MdiIcon :path="mdiPlus" :size="18" />
        Add user
      </button>
    </div>

    <p v-if="error" class="error-box mb-3" role="alert">{{ error }}</p>
    <p v-if="notice" class="mb-3 rounded-lg bg-accent-soft px-3 py-2 text-sm text-accent">{{ notice }}</p>

    <div class="card overflow-x-auto">
      <table class="w-full text-sm">
        <thead class="text-left text-muted">
          <tr class="border-b border-line">
            <th class="px-4 py-2.5 font-medium">Username</th>
            <th class="px-4 py-2.5 font-medium">Role</th>
            <th class="px-4 py-2.5 font-medium">Active</th>
            <th class="hidden px-4 py-2.5 font-medium sm:table-cell">Last login</th>
            <th class="px-4 py-2.5"><span class="sr-only">Actions</span></th>
          </tr>
        </thead>
        <tbody class="divide-y divide-line">
          <tr v-for="user in users" :key="user.id">
            <td class="px-4 py-2.5 font-medium">
              {{ user.username }}
              <span v-if="user.id === session.state.user?.id" class="pill ml-1">you</span>
            </td>
            <td class="px-4 py-2.5">
              <select
                class="input w-auto py-1"
                :value="user.role"
                :aria-label="`Role of ${user.username}`"
                @change="update(user, { role: ($event.target as HTMLSelectElement).value as User['role'] })"
              >
                <option value="admin">Administrator</option>
                <option value="user">User</option>
              </select>
            </td>
            <td class="px-4 py-2.5">
              <input
                type="checkbox"
                class="h-4 w-4 accent-[var(--hs-accent)]"
                :checked="user.is_active"
                :aria-label="`${user.username} is active`"
                @change="update(user, { is_active: ($event.target as HTMLInputElement).checked })"
              />
            </td>
            <td class="hidden px-4 py-2.5 text-muted sm:table-cell">{{ formatDate(user.last_login) }}</td>
            <td class="px-4 py-2.5 text-right whitespace-nowrap">
              <button class="btn-icon" title="Reset password" @click="resetting = user">
                <MdiIcon :path="mdiKeyVariant" :size="18" />
              </button>
              <button
                class="btn-icon hover:text-danger"
                title="Delete user"
                :disabled="user.id === session.state.user?.id"
                @click="remove(user)"
              >
                <MdiIcon :path="mdiDeleteOutline" :size="18" />
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <BaseDialog v-if="adding" title="Add user" @close="adding = false">
      <form id="add-user" class="space-y-4" @submit.prevent="create">
        <div>
          <label class="label" for="new-username">Username</label>
          <input
            id="new-username"
            v-model="newUser.username"
            class="input"
            required
            pattern="[A-Za-z0-9._\-]+"
            maxlength="64"
            autocomplete="off"
          />
          <p class="mt-1 text-xs text-muted">Letters, digits, dot, dash and underscore.</p>
        </div>
        <div>
          <label class="label" for="new-password">Password</label>
          <input id="new-password" v-model="newUser.password" class="input" type="password" required autocomplete="new-password" />
        </div>
        <div>
          <label class="label" for="new-role">Role</label>
          <select id="new-role" v-model="newUser.role" class="input">
            <option value="user">User</option>
            <option value="admin">Administrator</option>
          </select>
        </div>
        <p v-if="addError" class="error-box" role="alert">{{ addError }}</p>
      </form>
      <template #footer>
        <button class="btn" @click="adding = false">Cancel</button>
        <button class="btn btn-primary" type="submit" form="add-user">Create user</button>
      </template>
    </BaseDialog>

    <BaseDialog v-if="resetting" :title="`Reset password for ${resetting.username}`" @close="resetting = null">
      <form id="reset-password" @submit.prevent="doReset">
        <label class="label" for="reset-pw">New password</label>
        <input id="reset-pw" v-model="resetPassword" class="input" type="password" required autocomplete="new-password" />
        <p class="mt-2 text-xs text-muted">The user will be signed out of all sessions.</p>
        <p v-if="resetError" class="error-box mt-3" role="alert">{{ resetError }}</p>
      </form>
      <template #footer>
        <button class="btn" @click="resetting = null">Cancel</button>
        <button class="btn btn-primary" type="submit" form="reset-password">Reset password</button>
      </template>
    </BaseDialog>
  </div>
</template>
