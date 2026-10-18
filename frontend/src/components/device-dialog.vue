<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import type { TasmotaDevice } from '../api'
import { tasmota } from '../stores/tasmota'
import BaseDialog from './base-dialog.vue'

/** Edits a device, or adds one manually when no device is given. */
const props = defineProps<{ device?: TasmotaDevice; groups: string[] }>()
const emit = defineEmits<{ close: [] }>()

const form = reactive({
  name: props.device?.name ?? '',
  group_name: props.device?.group_name ?? '',
  host: '',
  port: 80,
})
const error = ref('')
const saving = ref(false)
const confirmingRemove = ref(false)

const adding = computed(() => !props.device)

async function save() {
  error.value = ''
  saving.value = true
  const name = form.name.trim() || null
  const group_name = form.group_name.trim() || null
  try {
    if (props.device) await tasmota.update(props.device.id, { name, group_name })
    else await tasmota.add({ name, group_name, host: form.host.trim(), port: form.port })
    emit('close')
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Could not save the device'
  } finally {
    saving.value = false
  }
}

async function remove() {
  if (!props.device) return
  error.value = ''
  try {
    await tasmota.remove(props.device.id)
    emit('close')
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Could not remove the device'
  }
}
</script>

<template>
  <BaseDialog :title="adding ? 'Add device manually' : `Edit ${device?.display_name}`" @close="emit('close')">
    <form id="device-form" class="space-y-4" @submit.prevent="save">
      <p v-if="adding" class="text-sm text-muted">
        Devices on MQTT are found automatically. Add a device here only if it does not appear in the list.
        The connection is tested before the device is saved.
      </p>
      <div v-if="adding" class="grid grid-cols-[1fr_6rem] gap-3">
        <div>
          <label class="label" for="device-host">IP address or hostname</label>
          <input id="device-host" v-model="form.host" class="input" required maxlength="253" placeholder="192.168.x.x" />
        </div>
        <div>
          <label class="label" for="device-port">Port</label>
          <input id="device-port" v-model.number="form.port" class="input" type="number" min="1" max="65535" required />
        </div>
      </div>
      <div>
        <label class="label" for="device-name">Name</label>
        <input
          id="device-name"
          v-model="form.name"
          class="input"
          maxlength="64"
          :placeholder="device?.topic ?? 'Shown instead of the MQTT topic'"
        />
      </div>
      <div>
        <label class="label" for="device-group">Group / room</label>
        <input id="device-group" v-model="form.group_name" class="input" maxlength="64" list="device-groups" />
        <datalist id="device-groups">
          <option v-for="group in groups" :key="group" :value="group" />
        </datalist>
      </div>
      <p v-if="error" class="error-box" role="alert">{{ error }}</p>

      <div v-if="device" class="rounded-lg border border-line p-3 text-sm">
        <template v-if="!confirmingRemove">
          <p class="mb-2 text-muted">
            Removing hides the device. If it publishes on MQTT again later, it reappears in the list.
          </p>
          <button type="button" class="btn btn-danger" @click="confirmingRemove = true">Remove device</button>
        </template>
        <template v-else>
          <p class="mb-2 font-medium">Remove {{ device.display_name }}?</p>
          <div class="flex gap-2">
            <button type="button" class="btn" @click="confirmingRemove = false">Keep</button>
            <button type="button" class="btn btn-danger" @click="remove">Remove</button>
          </div>
        </template>
      </div>
    </form>
    <template #footer>
      <button type="button" class="btn" @click="emit('close')">Cancel</button>
      <button type="submit" form="device-form" class="btn btn-primary" :disabled="saving">
        {{ saving ? (adding ? 'Testing connection…' : 'Saving…') : adding ? 'Add device' : 'Save' }}
      </button>
    </template>
  </BaseDialog>
</template>
