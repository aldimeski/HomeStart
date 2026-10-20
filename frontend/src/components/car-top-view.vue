<script setup lang="ts">
import type { CarSide, OpenState, SkodaVehicle } from '../api'

/** Top view of the car, front at the top. Parts are coloured by state; open doors are also drawn swung out. */
const props = defineProps<{ vehicle: SkodaVehicle }>()

const LABELS: Record<CarSide, string> = {
  front_left: 'Front left',
  front_right: 'Front right',
  rear_left: 'Rear left',
  rear_right: 'Rear right',
}

// Door panels and the window strip next to each; left doors hinge on their outer front corner.
const SIDES: { side: CarSide; door: [number, number, number, number]; window: [number, number, number, number]; hinge: [number, number]; swing: number }[] = [
  { side: 'front_left', door: [22, 112, 18, 88], window: [41, 118, 11, 76], hinge: [22, 112], swing: 32 },
  { side: 'rear_left', door: [22, 204, 18, 84], window: [41, 208, 11, 70], hinge: [22, 204], swing: 32 },
  { side: 'front_right', door: [160, 112, 18, 88], window: [148, 118, 11, 76], hinge: [178, 112], swing: -32 },
  { side: 'rear_right', door: [160, 204, 18, 84], window: [148, 208, 11, 70], hinge: [178, 204], swing: -32 },
]

function stateClass(state: OpenState | undefined) {
  if (state === 'open') return 'part-open'
  if (state === 'closed') return 'part-closed'
  return 'part-unknown'
}

function stateText(state: OpenState | undefined) {
  if (state === 'open' || state === 'closed') return state
  if (state === 'unsupported') return 'not available'
  return 'unknown'
}

function door(side: CarSide) {
  return props.vehicle.doors?.[side]
}

function windowState(side: CarSide) {
  return props.vehicle.windows?.[side]
}
</script>

<template>
  <svg viewBox="-40 0 280 400" class="car-top-view h-auto w-full max-w-[15rem]" role="img" :aria-label="`Top view of ${vehicle.title ?? 'the vehicle'}`">
    <!-- wheels, partly hidden by the body -->
    <rect x="14" y="58" width="12" height="40" rx="4" class="wheel" />
    <rect x="174" y="58" width="12" height="40" rx="4" class="wheel" />
    <rect x="14" y="300" width="12" height="40" rx="4" class="wheel" />
    <rect x="174" y="300" width="12" height="40" rx="4" class="wheel" />
    <ellipse cx="16" cy="114" rx="8" ry="5" class="body" />
    <ellipse cx="184" cy="114" rx="8" ry="5" class="body" />

    <path class="body" d="M100 10C140 10 165 18 170 40L177 110L178 300C178 360 160 388 100 390C40 388 22 360 22 300L23 110L30 40C35 18 60 10 100 10Z" />

    <path :class="stateClass(vehicle.bonnet)" d="M46 24C70 15 130 15 154 24L160 102H40Z">
      <title>Bonnet: {{ stateText(vehicle.bonnet) }}</title>
    </path>
    <path class="glass" d="M44 108H156L146 140H54Z" />
    <rect x="54" y="142" width="92" height="118" rx="6" class="roof" />
    <rect v-if="vehicle.sunroof && vehicle.sunroof !== 'unsupported'" x="70" y="160" width="60" height="52" rx="6" :class="stateClass(vehicle.sunroof)">
      <title>Sunroof: {{ stateText(vehicle.sunroof) }}</title>
    </rect>
    <path class="glass" d="M54 262H146L152 290H48Z" />
    <path :class="stateClass(vehicle.trunk)" d="M44 296H156L160 360C140 378 60 378 40 360Z">
      <title>Boot: {{ stateText(vehicle.trunk) }}</title>
    </path>

    <g v-for="part in SIDES" :key="part.side">
      <rect :x="part.window[0]" :y="part.window[1]" :width="part.window[2]" :height="part.window[3]" rx="3" :class="stateClass(windowState(part.side))">
        <title>{{ LABELS[part.side] }} window: {{ stateText(windowState(part.side)) }}</title>
      </rect>
      <rect
        :x="part.door[0]"
        :y="part.door[1]"
        :width="part.door[2]"
        :height="part.door[3]"
        rx="4"
        :class="stateClass(door(part.side))"
        :transform="door(part.side) === 'open' ? `rotate(${part.swing} ${part.hinge[0]} ${part.hinge[1]})` : undefined"
      >
        <title>{{ LABELS[part.side] }} door: {{ stateText(door(part.side)) }}</title>
      </rect>
    </g>
  </svg>
</template>

<style>
/* Not scoped: the theme class sits on <html>. */
.car-top-view {
  --closed: #16a34a;
  --open: #dc2626;
}
.dark .car-top-view {
  --closed: #4ade80;
  --open: #f87171;
}
</style>

<style scoped>
.body {
  fill: var(--hs-surface-2);
  stroke: var(--hs-muted);
  stroke-width: 2;
}
.wheel {
  fill: var(--hs-ink);
  opacity: 0.75;
}
.roof {
  fill: var(--hs-line);
}
.glass {
  fill: var(--hs-line);
  opacity: 0.7;
}
.part-closed,
.part-open,
.part-unknown {
  stroke-width: 2;
  transition: fill 0.2s, transform 0.3s;
}
.part-closed {
  fill: color-mix(in srgb, var(--closed) 28%, transparent);
  stroke: var(--closed);
}
.part-open {
  fill: color-mix(in srgb, var(--open) 55%, transparent);
  stroke: var(--open);
}
.part-unknown {
  fill: var(--hs-surface);
  stroke: var(--hs-muted);
  stroke-dasharray: 4 3;
}
</style>
