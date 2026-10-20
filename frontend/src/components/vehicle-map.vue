<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { mdiCar } from '@mdi/js'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

const props = defineProps<{ latitude: number; longitude: number; label: string }>()

const ZOOM = 16
const element = ref<HTMLElement>()
let map: L.Map | null = null
let marker: L.Marker | null = null

// A drawn pin instead of Leaflet's default marker images.
const pin = L.divIcon({
  className: 'vehicle-pin',
  html: `<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path fill="currentColor" d="${mdiCar}"/></svg>`,
  iconSize: [38, 38],
  iconAnchor: [19, 19],
})

onMounted(() => {
  if (!element.value) return
  map = L.map(element.value, { scrollWheelZoom: false }).setView([props.latitude, props.longitude], ZOOM)
  // Tiles come through HomeStart, which caches them; the browser never contacts the tile server.
  L.tileLayer('/api/map/tiles/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors',
  }).addTo(map)
  marker = L.marker([props.latitude, props.longitude], { icon: pin, title: props.label, keyboard: false }).addTo(map)
})

watch(
  () => [props.latitude, props.longitude],
  ([latitude, longitude]) => {
    marker?.setLatLng([latitude, longitude])
    map?.setView([latitude, longitude], map.getZoom())
  },
)

onBeforeUnmount(() => {
  map?.remove()
  map = null
})
</script>

<template>
  <!-- isolate keeps Leaflet's high z-indexes below dialogs and the mobile menu -->
  <div ref="element" class="vehicle-map isolate h-72 w-full overflow-hidden rounded-lg border border-line" />
</template>

<style scoped>
.vehicle-map :deep(.vehicle-pin) {
  display: flex;
  align-items: center;
  justify-content: center;
  border: 3px solid #fff;
  border-radius: 9999px;
  background: var(--hs-accent);
  color: var(--hs-on-accent);
  box-shadow: 0 2px 6px rgb(0 0 0 / 0.35);
}
</style>

<style>
/* Not scoped: the theme class sits on <html>. OpenStreetMap tiles are light; in dark mode they are inverted
   so the map does not glare. */
.dark .vehicle-map .leaflet-tile-pane {
  filter: invert(1) hue-rotate(180deg) brightness(0.95) contrast(0.9);
}
</style>
