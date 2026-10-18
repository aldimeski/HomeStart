import { ref } from 'vue'
import type { Theme } from './api'

const media = window.matchMedia('(prefers-color-scheme: dark)')
let current: Theme = 'system'

/** Whether the dark palette is currently shown (after resolving "system"). */
export const isDark = ref(false)

function render() {
  isDark.value = current === 'dark' || (current === 'system' && media.matches)
  document.documentElement.classList.toggle('dark', isDark.value)
}

export function applyTheme(theme: Theme) {
  current = theme
  render()
}

media.addEventListener('change', render)
render()
