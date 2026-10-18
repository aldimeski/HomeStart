/** Lazily loads the full Material Design Icons set served locally as /mdi-icons.json. */

export interface MdiIcon {
  name: string
  path: string
  keywords: string
}

let loading: Promise<MdiIcon[]> | null = null
const byName = new Map<string, string>()

export function loadMdiLibrary(): Promise<MdiIcon[]> {
  loading ??= fetch('/mdi-icons.json')
    .then((response) => {
      if (!response.ok) throw new Error('Icon library could not be loaded')
      return response.json() as Promise<[string, string, string][]>
    })
    .then((rows) => {
      const icons = rows.map(([name, path, keywords]) => ({ name, path, keywords }))
      for (const icon of icons) byName.set(icon.name, icon.path)
      return icons
    })
    .catch((error) => {
      loading = null
      throw error
    })
  return loading
}

export async function mdiPath(name: string): Promise<string | undefined> {
  if (!byName.size) await loadMdiLibrary()
  return byName.get(name)
}

export function searchMdi(icons: MdiIcon[], query: string, limit = 240): MdiIcon[] {
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
  if (!terms.length) return icons.slice(0, limit)

  // "home automation" should rank the icon named "home-automation" first.
  const joined = terms.join('-')
  const scored: { icon: MdiIcon; score: number }[] = []
  for (const icon of icons) {
    let score = icon.name === joined ? 500 : icon.name.startsWith(joined) ? 200 : 0
    for (const term of terms) {
      if (icon.name === term) score += 100
      else if (icon.name.startsWith(term)) score += 20
      else if (icon.name.includes(term)) score += 10
      else if (icon.keywords.includes(term)) score += 3
      else {
        score = 0
        break
      }
    }
    if (score) scored.push({ icon, score })
  }
  scored.sort((a, b) => b.score - a.score || a.icon.name.length - b.icon.name.length)
  return scored.slice(0, limit).map((entry) => entry.icon)
}

/** Icons offered first in the picker, matching the devices and services listed in the specification. */
export const SUGGESTED_ICONS = [
  'home', 'home-automation', 'router-wireless', 'router', 'lan', 'server', 'server-network', 'wifi',
  'car', 'lightbulb', 'power-socket-eu', 'thermometer', 'television', 'camera', 'nas', 'web',
  'cloud', 'chart-line', 'cog', 'link-variant',
]
