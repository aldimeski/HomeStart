// Builds public/mdi-icons.json from @mdi/svg so the icon picker and menu can show any
// Material Design icon without a CDN and without putting all paths in the main bundle.
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)
const svgPackageDir = dirname(require.resolve('@mdi/svg/package.json'))
const meta = JSON.parse(readFileSync(join(svgPackageDir, 'meta.json'), 'utf8'))
const outFile = join(dirname(fileURLToPath(import.meta.url)), '..', 'public', 'mdi-icons.json')

const icons = []
for (const icon of meta) {
  if (icon.deprecated) continue
  const svg = readFileSync(join(svgPackageDir, 'svg', `${icon.name}.svg`), 'utf8')
  const path = svg.match(/ d="([^"]+)"/)?.[1]
  if (!path) continue
  const keywords = [...icon.aliases, ...icon.tags].join(' ').toLowerCase()
  icons.push([icon.name, path, keywords])
}

mkdirSync(dirname(outFile), { recursive: true })
writeFileSync(outFile, JSON.stringify(icons))
console.log(`mdi-icons.json: ${icons.length} icons`)
