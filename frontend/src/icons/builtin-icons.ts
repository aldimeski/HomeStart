/**
 * HomeStart's own icons for devices that Material Design Icons does not cover.
 * Elements with class "lit", "lit-line" or "flame" change colour while the switch they stand for is on.
 */
import { mdiFlash, mdiFlashOutline } from '@mdi/js'

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
    // Same symbol as the TasmoSiz module in the menu; the bolt fills in while on.
    body: `
      <path class="lit" fill="none" d="${mdiFlash}"/>
      <path fill="currentColor" d="${mdiFlashOutline}"/>`,
  },
  {
    name: 'sonoff',
    label: 'Sonoff',
    keywords: 'sonoff itead smart switch relay basic device',
    // Sonoff Basic style: switch module with power symbol, status LED and cable ends.
    body: `
      <rect x="2.5" y="6.5" width="19" height="11" rx="2.5" ${STROKE} stroke-width="1.6"/>
      <path d="M1 10.5v3M23 10.5v3" ${STROKE} stroke-width="1.6"/>
      <path class="lit-line" d="M12 9.3v2.6" ${STROKE} stroke-width="1.5"/>
      <path class="lit-line" d="M9.9 10.3a3 3 0 1 0 4.2 0" ${STROKE} stroke-width="1.5"/>
      <circle class="lit" cx="5.6" cy="9.4" r="0.95" fill="currentColor"/>`,
  },
  {
    name: 'esp32',
    label: 'ESP32',
    keywords: 'esp32 esp8266 espressif microcontroller module chip wifi board',
    // ESP32 module: PCB antenna meander on top, metal shield below, pins on both sides.
    body: `
      <rect x="5.5" y="2" width="13" height="20" rx="1.2" ${STROKE} stroke-width="1.5"/>
      <path d="M7.8 6.5V4.3h2.1v2.2H12V4.3h2.1v2.2h2.1" ${STROKE} stroke-width="1.2"/>
      <rect class="lit" x="7.8" y="9.5" width="8.4" height="10" rx="0.6" ${STROKE} stroke-width="1.3"/>
      <path d="M3 11h2.5M3 14h2.5M3 17h2.5M3 20h2.5M18.5 11H21M18.5 14H21M18.5 17H21M18.5 20H21" ${STROKE} stroke-width="1.3"/>`,
  },
  {
    name: 'gas-boiler',
    label: 'Gas boiler',
    keywords: 'gas boiler heater heating combi furnace flame fire water hot',
    // Wall-mounted combi boiler: casing with display and knob, burner flame, pipes below; the flame burns while on.
    body: `
      <rect x="4.5" y="2" width="15" height="16.5" rx="2" ${STROKE} stroke-width="1.6"/>
      <path d="M7.5 5.3h4.5" ${STROKE} stroke-width="1.5"/>
      <circle cx="16" cy="5.3" r="1.1" fill="currentColor"/>
      <path class="flame" d="M12 8.4c2 1.8 3.1 3.4 3.1 5.1a3.1 3.1 0 0 1-6.2 0c0-1.05.45-2 1.2-2.7.1.95.55 1.55 1.2 1.8-.25-1.5.15-2.85.7-4.2z" ${STROKE} stroke-width="1.4"/>
      <path d="M8 18.5V22M12 18.5V22M16 18.5V22" ${STROKE} stroke-width="1.6"/>`,
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
