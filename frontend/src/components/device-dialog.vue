<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { mdiClose, mdiImagePlusOutline } from '@mdi/js'
import type { TasmotaDevice } from '../api'
import { tasmota } from '../stores/tasmota'
import BaseDialog from './base-dialog.vue'
import IconPicker from './icon-picker.vue'
import LinkIcon from './link-icon.vue'
import MdiIcon from './mdi-icon.vue'

/** Edits a device, or adds one manually when no device is given. */
const props = defineProps<{ device?: TasmotaDevice; groups: string[] }>()
const emit = defineEmits<{ close: [] }>()

const form = reactive({
  name: props.device?.name ?? '',
  group_name: props.device?.group_name ?? '',
  host: '',
  port: 80,
  icon: props.device?.icon ?? '',
  relay_names: props.device?.channels.map((channel) => channel.custom_label ?? '') ?? [],
  relay_icons: props.device?.channels.map((channel) => channel.icon ?? '') ?? [],
})
// 'device' or the index of the relay whose icon is being chosen.
const picking = ref<'device' | number | null>(null)

const pickerValue = computed(() =>
  picking.value === 'device' ? form.icon : picking.value === null ? '' : form.relay_icons[picking.value],
)

function setIcon(icon: string) {
  if (picking.value === 'device') form.icon = icon
  else if (picking.value !== null) form.relay_icons[picking.value] = icon
}
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
    // Relays are only known from live state; with none known, the stored names are left untouched.
    const relays = form.relay_names.length > 0
    const relay_names = relays ? form.relay_names.map((value) => value.trim() || null) : undefined
    const relay_icons = relays ? form.relay_icons.map((value) => value || null) : undefined
    const icon = form.icon || null
    if (props.device) await tasmota.update(props.device.id, { name, group_name, icon, relay_names, relay_icons })
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
      <div v-if="device">
        <span class="label">Icon</span>
        <div class="flex items-center gap-3">
          <span class="flex h-11 w-11 items-center justify-center rounded-lg border border-line bg-surface-2">
            <LinkIcon v-if="form.icon" :icon="form.icon" :size="26" />
          </span>
          <button type="button" class="btn" @click="picking = 'device'">Choose icon…</button>
          <button v-if="form.icon" type="button" class="btn" @click="form.icon = ''">Remove</button>
        </div>
        <p class="mt-1 text-xs text-muted">Shown in front of the device name.</p>
      </div>
      <fieldset v-if="device?.channels.length" class="space-y-2">
        <legend class="label">{{ device.channels.length === 1 ? 'Switch' : 'Switches' }}</legend>
        <p class="text-xs text-muted">
          The icon lights up while the switch is on. Leave the name empty to use the name reported by the device.
        </p>
        <div v-for="(channel, index) in device.channels" :key="channel.channel" class="flex items-center gap-3">
          <label class="w-16 shrink-0 text-sm text-muted" :for="`relay-name-${channel.channel}`">
            Relay {{ channel.channel }}
          </label>
          <span class="relative shrink-0">
            <button
              type="button"
              class="flex h-10 w-10 items-center justify-center rounded-lg border border-line bg-surface-2 text-muted hover:border-accent hover:text-ink"
              :title="form.relay_icons[index] ? 'Change the switch icon' : 'Choose a switch icon'"
              :aria-label="`Icon for relay ${channel.channel}`"
              @click="picking = index"
            >
              <LinkIcon v-if="form.relay_icons[index]" :icon="form.relay_icons[index]" :size="22" class="text-ink" />
              <MdiIcon v-else :path="mdiImagePlusOutline" :size="18" />
            </button>
            <button
              v-if="form.relay_icons[index]"
              type="button"
              class="absolute -top-1.5 -right-1.5 flex h-5 w-5 items-center justify-center rounded-full border border-line bg-surface text-muted hover:text-danger"
              :aria-label="`Remove the icon of relay ${channel.channel}`"
              title="Remove icon"
              @click="form.relay_icons[index] = ''"
            >
              <MdiIcon :path="mdiClose" :size="12" />
            </button>
          </span>
          <input
            :id="`relay-name-${channel.channel}`"
            v-model="form.relay_names[index]"
            class="input"
            maxlength="64"
            :placeholder="channel.device_label ?? (device.channels.length === 1 ? 'Power' : `Relay ${channel.channel}`)"
          />
        </div>
      </fieldset>
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
  <IconPicker
    v-if="picking !== null"
    :model-value="pickerValue"
    clearable
    @update:model-value="setIcon"
    @close="picking = null"
  />
</template>
