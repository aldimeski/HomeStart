<script setup lang="ts">
import { computed, ref, watchEffect } from 'vue'
import { builtinIcon } from '../icons/builtin-icons'
import { mdiPath } from '../icons/mdi-library'
import { switchIconLayers, type IconLayer } from '../icons/switch-icons'
import MdiIcon from './mdi-icon.vue'

/** state is set for switch icons only: "on" lights the icon up, "off" shows it plain. */
const props = withDefaults(defineProps<{ icon: string; size?: number; state?: 'on' | 'off' }>(), { size: 20 })

const builtin = computed(() => (props.icon.startsWith('builtin:') ? builtinIcon(props.icon.slice(8)) : undefined))
const stateClass = computed(() => (props.state === 'on' ? 'icon-on' : undefined))

const path = ref<string>()
const layers = ref<IconLayer[]>()

watchEffect(async () => {
  path.value = undefined
  layers.value = undefined
  if (!props.icon.startsWith('mdi:')) return
  const icon = props.icon
  const name = icon.slice(4)
  const resolved = await mdiPath(name).catch(() => undefined)
  const resolvedLayers = resolved && props.state ? await switchIconLayers(name, resolved).catch(() => undefined) : undefined
  if (props.icon !== icon) return
  path.value = resolved
  layers.value = resolvedLayers
})
</script>

<template>
  <img
    v-if="icon.startsWith('upload:')"
    :src="`/api/icons/${icon.slice(7)}`"
    :width="size"
    :height="size"
    alt=""
    class="shrink-0 object-contain transition"
    :class="state === 'off' ? 'opacity-45 grayscale' : ''"
    :style="{ width: `${size}px`, height: `${size}px` }"
  />
  <MdiIcon v-else-if="builtin" :path="builtin.path" :body="builtin.body" :size="size" :class="stateClass" />
  <MdiIcon v-else-if="layers" :layers="layers" :size="size" :class="stateClass" />
  <MdiIcon v-else :path="path" :size="size" />
</template>
