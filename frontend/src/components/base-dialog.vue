<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { mdiClose } from '@mdi/js'
import MdiIcon from './mdi-icon.vue'

withDefaults(defineProps<{ title: string; wide?: boolean }>(), { wide: false })
const emit = defineEmits<{ close: [] }>()

const dialog = ref<HTMLDialogElement>()

onMounted(() => dialog.value?.showModal())
</script>

<template>
  <dialog
    ref="dialog"
    class="m-auto w-[calc(100%-2rem)] rounded-xl border border-line bg-surface p-0 text-ink shadow-2xl backdrop:bg-black/50"
    :class="wide ? 'max-w-3xl' : 'max-w-lg'"
    @cancel.prevent="emit('close')"
  >
    <div class="flex items-center justify-between border-b border-line px-5 py-3">
      <h2 class="text-lg font-semibold">{{ title }}</h2>
      <button class="btn-icon" type="button" aria-label="Close" @click="emit('close')">
        <MdiIcon :path="mdiClose" />
      </button>
    </div>
    <div class="max-h-[75vh] overflow-y-auto p-5">
      <slot />
    </div>
    <div v-if="$slots.footer" class="flex justify-end gap-2 border-t border-line px-5 py-3">
      <slot name="footer" />
    </div>
  </dialog>
</template>
