import { computed, reactive } from 'vue'
import { api, type Me, type User, type UserSettings } from '../api'
import { applyTheme } from '../theme'

const DEFAULT_SETTINGS: UserSettings = { theme: 'system', sidebar_collapsed: false, sholink_expanded: true }

const state = reactive<{ user: User | null; settings: UserSettings; loaded: boolean }>({
  user: null,
  settings: { ...DEFAULT_SETTINGS },
  loaded: false,
})

function setMe(me: Me | null) {
  state.user = me?.user ?? null
  state.settings = me ? { ...me.settings } : { ...DEFAULT_SETTINGS }
  applyTheme(state.settings.theme)
}

export const session = {
  state,
  isAdmin: computed(() => state.user?.role === 'admin'),

  async load() {
    try {
      setMe(await api<Me>('GET', '/api/auth/me', undefined, { skipUnauthorizedHandler: true }))
    } catch {
      setMe(null)
    }
    state.loaded = true
  },

  async login(username: string, password: string) {
    setMe(await api<Me>('POST', '/api/auth/login', { username, password }, { skipUnauthorizedHandler: true }))
  },

  async logout() {
    try {
      await api('POST', '/api/auth/logout')
    } finally {
      setMe(null)
    }
  },

  clear() {
    setMe(null)
  },

  /** Applies the change immediately and saves it for the user in the background. */
  async updateSettings(patch: Partial<UserSettings>) {
    Object.assign(state.settings, patch)
    if (patch.theme) applyTheme(patch.theme)
    const saved = await api<UserSettings>('PUT', '/api/users/me/settings', patch)
    Object.assign(state.settings, saved)
  },
}
