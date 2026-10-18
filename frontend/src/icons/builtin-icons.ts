/** HomeStart's own link icons for devices that Material Design Icons does not cover. */
import { mdiFlashOutline } from '@mdi/js'

export interface BuiltinIcon {
  name: string
  label: string
  keywords: string
  /** Either a single filled path (MDI style) or SVG markup for a 24×24 viewBox. */
  path?: string
  body?: string
}

const STROKE = 'fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"'

export const BUILTIN_ICONS: BuiltinIcon[] = [
  {
    name: 'tasmota',
    label: 'Tasmota',
    keywords: 'tasmota tasmosiz firmware relay switch device',
    // Same symbol as the TasmoSiz module in the menu.
    path: mdiFlashOutline,
  },
  {
    name: 'sonoff',
    label: 'Sonoff',
    keywords: 'sonoff itead smart switch relay basic device',
    // Sonoff Basic style: switch module with power symbol, status LED and cable ends.
    body: `
      <rect x="2.5" y="6.5" width="19" height="11" rx="2.5" ${STROKE} stroke-width="1.6"/>
      <path d="M1 10.5v3M23 10.5v3" ${STROKE} stroke-width="1.6"/>
      <path d="M12 9.3v2.6" ${STROKE} stroke-width="1.5"/>
      <path d="M9.9 10.3a3 3 0 1 0 4.2 0" ${STROKE} stroke-width="1.5"/>
      <circle cx="5.6" cy="9.4" r="0.95" fill="currentColor"/>`,
  },
  {
    name: 'esp32',
    label: 'ESP32',
    keywords: 'esp32 esp8266 espressif microcontroller module chip wifi board',
    // ESP32 module: PCB antenna meander on top, metal shield below, pins on both sides.
    body: `
      <rect x="5.5" y="2" width="13" height="20" rx="1.2" ${STROKE} stroke-width="1.5"/>
      <path d="M7.8 6.5V4.3h2.1v2.2H12V4.3h2.1v2.2h2.1" ${STROKE} stroke-width="1.2"/>
      <rect x="7.8" y="9.5" width="8.4" height="10" rx="0.6" ${STROKE} stroke-width="1.3"/>
      <path d="M3 11h2.5M3 14h2.5M3 17h2.5M3 20h2.5M18.5 11H21M18.5 14H21M18.5 17H21M18.5 20H21" ${STROKE} stroke-width="1.3"/>`,
  },
]

const byName = new Map(BUILTIN_ICONS.map((icon) => [icon.name, icon]))

export function builtinIcon(name: string): BuiltinIcon | undefined {
  return byName.get(name)
}

export function searchBuiltin(query: string): BuiltinIcon[] {
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
  if (!terms.length) return BUILTIN_ICONS
  return BUILTIN_ICONS.filter((icon) => terms.every((term) => icon.keywords.includes(term)))
}
