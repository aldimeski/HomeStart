<script setup lang="ts">
import { computed, ref, watchEffect } from 'vue'
import { builtinIcon } from '../icons/builtin-icons'
import { mdiPath } from '../icons/mdi-library'
import MdiIcon from './mdi-icon.vue'

const props = withDefaults(defineProps<{ icon: string; size?: number }>(), { size: 20 })

const builtin = computed(() => (props.icon.startsWith('builtin:') ? builtinIcon(props.icon.slice(8)) : undefined))

const path = ref<string>()

watchEffect(async () => {
  path.value = undefined
  if (props.icon.startsWith('mdi:')) {
    const name = props.icon.slice(4)
    const resolved = await mdiPath(name).catch(() => undefined)
    if (props.icon === `mdi:${name}`) path.value = resolved
  }
})
</script>

<template>
  <img
    v-if="icon.startsWith('upload:')"
    :src="`/api/icons/${icon.slice(7)}`"
    :width="size"
    :height="size"
    alt=""
    class="shrink-0 object-contain"
    :style="{ width: `${size}px`, height: `${size}px` }"
  />
  <MdiIcon v-else-if="builtin" :path="builtin.path" :body="builtin.body" :size="size" />
  <MdiIcon v-else :path="path" :size="size" />
</template>
