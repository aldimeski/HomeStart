<script setup lang="ts">
import { computed, ref } from 'vue'
import { mdiRefresh } from '@mdi/js'
import type { TasmotaDevice, ZigbeeMapNode } from '../api'
import { tasmota } from '../stores/tasmota'
import BaseDialog from './base-dialog.vue'
import MdiIcon from './mdi-icon.vue'

const props = defineProps<{ bridge: TasmotaDevice; canScan: boolean }>()
const emit = defineEmits<{ close: [] }>()

const SIZE = 520
const CENTER = SIZE / 2
const ROUTER_RADIUS = 115
const END_DEVICE_RADIUS = 210

const error = ref('')
const network = computed(() => props.bridge.zigbee)
const map = computed(() => network.value?.map ?? null)

/** Coordinator in the middle, routers on an inner ring, end devices outside, next to the node they hang on. */
const layout = computed(() => {
  const nodes = map.value?.nodes ?? []
  const links = map.value?.links ?? []
  const positions = new Map<string, { x: number; y: number; angle: number }>()
  positions.set('0x0000', { x: CENTER, y: CENTER, angle: 0 })

  const routers = nodes.filter((node) => node.type === 'router')
  routers.forEach((node, index) => {
    const angle = (2 * Math.PI * index) / Math.max(routers.length, 1) - Math.PI / 2
    positions.set(node.short, { x: CENTER + ROUTER_RADIUS * Math.cos(angle), y: CENTER + ROUTER_RADIUS * Math.sin(angle), angle })
  })

  const endDevices = nodes.filter((node) => node.type === 'end_device')
  const parentAngle = (short: string) => {
    const partner = links.map((l) => (l.a === short ? l.b : l.b === short ? l.a : null)).find((p) => p && p !== '0x0000' && positions.has(p))
    return partner ? positions.get(partner)!.angle : null
  }
  // Devices hanging on the bridge itself are spread around, offset by half a step so they sit between routers.
  const orphans = endDevices.filter((node) => parentAngle(node.short) === null)
  endDevices.forEach((node, index) => {
    const near = parentAngle(node.short)
    const step = (2 * Math.PI) / Math.max(orphans.length, 1)
    const spread = step * orphans.indexOf(node) - Math.PI / 2 + (routers.length ? step / 2 : 0)
    const angle = near === null ? spread : near + (index % 2 ? 0.35 : -0.35)
    positions.set(node.short, {
      x: CENTER + END_DEVICE_RADIUS * Math.cos(angle),
      y: CENTER + END_DEVICE_RADIUS * Math.sin(angle),
      angle,
    })
  })

  return {
    nodes: nodes.filter((node) => positions.has(node.short)).map((node) => ({ ...node, ...positions.get(node.short)! })),
    links: links
      .filter((link) => positions.has(link.a) && positions.has(link.b))
      .map((link) => ({ ...link, from: positions.get(link.a)!, to: positions.get(link.b)! })),
  }
})

function linkClass(quality: number | null) {
  if (quality === null) return 'link-unknown'
  if (quality >= 150) return 'link-good'
  if (quality >= 80) return 'link-fair'
  return 'link-poor'
}

function nodeClass(node: ZigbeeMapNode) {
  return [`node-${node.type}`, node.known ? '' : 'node-unknown']
}

function label(node: ZigbeeMapNode) {
  return node.name ?? `${node.short}${node.known ? '' : ' (unknown)'}`
}

const scannedAt = computed(() =>
  network.value?.map_scanned_at ? new Date(network.value.map_scanned_at * 1000).toLocaleString() : null,
)

async function scan() {
  error.value = ''
  try {
    await tasmota.zigbeeMap(props.bridge.id)
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Could not start the scan'
  }
}
</script>

<template>
  <BaseDialog :title="`Zigbee map · ${bridge.display_name}`" wide @close="emit('close')">
    <div class="mb-3 flex flex-wrap items-center gap-3 text-sm">
      <span v-if="network?.map_scanning" class="text-accent">Scanning the network… results appear as they arrive.</span>
      <span v-else-if="scannedAt" class="text-muted">Last scan {{ scannedAt }}</span>
      <span v-else class="text-muted">The network has not been scanned since HomeStart started.</span>
      <button v-if="canScan" type="button" class="btn ml-auto" :disabled="network?.map_scanning" @click="scan">
        <MdiIcon :path="mdiRefresh" :size="16" :class="network?.map_scanning ? 'animate-spin' : ''" />
        Scan network
      </button>
    </div>
    <p v-if="error" class="error-box mb-3" role="alert">{{ error }}</p>

    <svg
      v-if="map"
      :viewBox="`-60 -10 ${SIZE + 120} ${SIZE + 20}`"
      class="zigbee-map mx-auto h-auto w-full max-w-2xl"
      role="img"
      :aria-label="`Zigbee network with ${map.nodes.length} nodes`"
    >
      <g v-for="link in layout.links" :key="`${link.a}-${link.b}`">
        <line :x1="link.from.x" :y1="link.from.y" :x2="link.to.x" :y2="link.to.y" :class="linkClass(link.link_quality)" />
        <text
          v-if="link.link_quality !== null"
          :x="(link.from.x + link.to.x) / 2"
          :y="(link.from.y + link.to.y) / 2 - 4"
          class="link-label"
          text-anchor="middle"
        >{{ link.link_quality }}</text>
      </g>
      <g v-for="node in layout.nodes" :key="node.short">
        <circle :cx="node.x" :cy="node.y" :r="node.type === 'coordinator' ? 22 : node.type === 'router' ? 16 : 11" :class="nodeClass(node)">
          <title>{{ label(node) }} · {{ node.short }} · {{ node.type.replace('_', ' ') }}</title>
        </circle>
        <text :x="node.x" :y="node.y + (node.type === 'coordinator' ? 38 : node.type === 'router' ? 31 : 25)" class="node-label" text-anchor="middle">
          {{ label(node) }}
        </text>
      </g>
    </svg>
    <p v-else class="py-10 text-center text-sm text-muted">
      No map yet.
      {{ canScan ? 'Press Scan network: the bridge asks every router for its neighbours (takes up to 30 seconds).' : 'An administrator can scan the network.' }}
    </p>

    <ul v-if="map" class="mt-4 flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted">
      <li class="flex items-center gap-1.5"><span class="legend-dot node-coordinator" /> Bridge (coordinator)</li>
      <li class="flex items-center gap-1.5"><span class="legend-dot node-router" /> Router (mains powered)</li>
      <li class="flex items-center gap-1.5"><span class="legend-dot node-end_device" /> End device</li>
      <li class="flex items-center gap-1.5"><span class="legend-line link-good" /> Link quality ≥ 150</li>
      <li class="flex items-center gap-1.5"><span class="legend-line link-fair" /> 80–149</li>
      <li class="flex items-center gap-1.5"><span class="legend-line link-poor" /> &lt; 80</li>
    </ul>
  </BaseDialog>
</template>

<style scoped>
.zigbee-map line {
  stroke-width: 2.5;
}
.link-good {
  stroke: #16a34a;
  background: #16a34a;
}
.link-fair {
  stroke: #d97706;
  background: #d97706;
}
.link-poor {
  stroke: #dc2626;
  background: #dc2626;
}
.link-unknown {
  stroke: var(--hs-muted);
  stroke-dasharray: 4 4;
}
.link-label {
  fill: var(--hs-muted);
  font-size: 12px;
}
.node-label {
  fill: var(--hs-ink);
  font-size: 13px;
}
circle,
.legend-dot {
  stroke-width: 2.5;
}
.node-coordinator {
  fill: var(--hs-accent);
  stroke: var(--hs-accent-hover);
  background: var(--hs-accent);
}
.node-router {
  fill: #3b82f6;
  stroke: #1d4ed8;
  background: #3b82f6;
}
.node-end_device {
  fill: var(--hs-surface-2);
  stroke: var(--hs-muted);
  background: var(--hs-surface-2);
  border: 2px solid var(--hs-muted);
}
.node-unknown {
  stroke-dasharray: 3 3;
  opacity: 0.7;
}
.legend-dot {
  display: inline-block;
  width: 12px;
  height: 12px;
  border-radius: 9999px;
}
.legend-line {
  display: inline-block;
  width: 18px;
  height: 3px;
  border-radius: 2px;
}
</style>
