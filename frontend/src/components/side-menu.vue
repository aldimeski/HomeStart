<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  mdiCarOutline,
  mdiChevronDown,
  mdiChevronLeft,
  mdiChevronRight,
  mdiClose,
  mdiCogOutline,
  mdiFlashOutline,
  mdiLinkVariant,
  mdiLogout,
  mdiOpenInNew,
  mdiRadio,
  mdiWeatherNight,
  mdiWhiteBalanceSunny,
} from '@mdi/js'
import MdiIcon from './mdi-icon.vue'
import LinkIcon from './link-icon.vue'
import { session } from '../stores/session'
import { links } from '../stores/links'
import { isDark } from '../theme'

const props = defineProps<{ collapsed: boolean; mobile: boolean }>()
const emit = defineEmits<{ navigate: []; close: [] }>()

const route = useRoute()
const router = useRouter()

// The drawer on phones always shows labels, regardless of the desktop collapse setting.
const compact = computed(() => props.collapsed && !props.mobile)
const expanded = computed(() => session.state.settings.sholink_expanded)

const modules = [
  { to: '/tasmosiz', label: 'TasmoSiz', icon: mdiFlashOutline },
  { to: '/skoda', label: 'Škoda', icon: mdiCarOutline },
  { to: '/radiopanel', label: 'Radiopanel', icon: mdiRadio },
]

function itemClass(active: boolean) {
  return [
    'group flex w-full items-center gap-3 rounded-lg py-2 text-[15px] transition-colors',
    compact.value ? 'justify-center px-0' : 'px-3',
    active ? 'bg-accent-soft font-semibold text-accent' : 'text-ink/80 hover:bg-surface-2 hover:text-ink',
  ]
}

function isActive(path: string) {
  return route.path === path || route.path.startsWith(`${path}/`)
}

function toggleCollapsed() {
  session.updateSettings({ sidebar_collapsed: !props.collapsed }).catch(() => {})
}

function toggleShoLink() {
  session.updateSettings({ sholink_expanded: !expanded.value }).catch(() => {})
}

function toggleTheme() {
  session.updateSettings({ theme: isDark.value ? 'light' : 'dark' }).catch(() => {})
}

async function logout() {
  await session.logout().catch(() => {})
  router.replace('/login')
}
</script>

<template>
  <nav class="flex h-full flex-col bg-surface px-3 py-4" aria-label="Main menu">
    <div v-if="mobile" class="mb-2 flex items-center justify-between px-3">
      <span class="text-lg font-bold">HomeStart</span>
      <button class="btn-icon" title="Close menu" @click="emit('close')">
        <MdiIcon :path="mdiClose" />
      </button>
    </div>
    <button
      v-else
      :class="itemClass(false)"
      :title="compact ? 'Expand menu' : 'Collapse menu'"
      :aria-label="compact ? 'Expand menu' : 'Collapse menu'"
      @click="toggleCollapsed"
    >
      <MdiIcon :path="compact ? mdiChevronRight : mdiChevronLeft" />
      <span v-if="!compact">Collapse menu</span>
    </button>

    <div class="mt-2 flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto overflow-x-hidden">
      <button
        :class="itemClass(false)"
        :title="compact ? (expanded ? 'ShoLink – hide links' : 'ShoLink – show links') : undefined"
        :aria-expanded="expanded"
        aria-controls="sholink-links"
        @click="toggleShoLink"
      >
        <span class="relative">
          <MdiIcon :path="mdiLinkVariant" />
          <MdiIcon
            v-if="compact"
            :path="expanded ? mdiChevronDown : mdiChevronRight"
            :size="12"
            class="absolute -right-2.5 -bottom-1"
          />
        </span>
        <template v-if="!compact">
          <span class="flex-1 text-left">ShoLink</span>
          <MdiIcon :path="expanded ? mdiChevronDown : mdiChevronRight" :size="18" class="text-muted" />
        </template>
      </button>

      <div v-show="expanded" id="sholink-links" class="flex flex-col gap-1" :class="compact ? '' : 'pl-5'">
        <template v-for="link in links.state.items" :key="link.id">
          <a
            v-if="link.open_in_new_tab"
            :href="link.url"
            target="_blank"
            rel="noopener noreferrer"
            :class="itemClass(false)"
            :title="compact ? `${link.title} (opens in new tab)` : 'Opens in a new tab'"
            @click="emit('navigate')"
          >
            <LinkIcon :icon="link.icon" />
            <template v-if="!compact">
              <span class="flex-1 truncate">{{ link.title }}</span>
              <MdiIcon :path="mdiOpenInNew" :size="14" class="text-muted opacity-0 group-hover:opacity-100" />
            </template>
          </a>
          <RouterLink
            v-else
            :to="`/link/${link.id}`"
            :class="itemClass(route.path === `/link/${link.id}`)"
            :title="compact ? link.title : undefined"
            @click="emit('navigate')"
          >
            <LinkIcon :icon="link.icon" />
            <span v-if="!compact" class="truncate">{{ link.title }}</span>
          </RouterLink>
        </template>
        <p v-if="links.state.loaded && !links.state.items.length && !compact" class="px-3 py-1 text-sm text-muted">
          No links yet.
          <RouterLink v-if="session.isAdmin.value" to="/config/links" class="text-accent underline" @click="emit('navigate')">
            Add one
          </RouterLink>
        </p>
      </div>

      <RouterLink
        v-for="item in modules"
        :key="item.to"
        :to="item.to"
        :class="itemClass(isActive(item.to))"
        :title="compact ? item.label : undefined"
        @click="emit('navigate')"
      >
        <MdiIcon :path="item.icon" />
        <span v-if="!compact">{{ item.label }}</span>
      </RouterLink>
    </div>

    <RouterLink
      to="/config"
      :class="itemClass(isActive('/config'))"
      :title="compact ? 'Configuration' : undefined"
      @click="emit('navigate')"
    >
      <MdiIcon :path="mdiCogOutline" />
      <span v-if="!compact">Configuration</span>
    </RouterLink>

    <div
      class="mt-3 flex items-center border-t border-line pt-3"
      :class="compact ? 'flex-col gap-1' : 'gap-1 pl-3'"
    >
      <span v-if="!compact" class="flex-1 truncate text-[15px]" :title="session.state.user?.username">
        {{ session.state.user?.username }}
      </span>
      <button
        class="btn-icon"
        :title="isDark ? 'Switch to light theme' : 'Switch to dark theme'"
        :aria-label="isDark ? 'Switch to light theme' : 'Switch to dark theme'"
        @click="toggleTheme"
      >
        <MdiIcon :path="isDark ? mdiWhiteBalanceSunny : mdiWeatherNight" />
      </button>
      <button
        class="btn-icon"
        :title="compact ? `Log out ${session.state.user?.username ?? ''}` : 'Log out'"
        aria-label="Log out"
        @click="logout"
      >
        <MdiIcon :path="mdiLogout" />
      </button>
    </div>
  </nav>
</template>
