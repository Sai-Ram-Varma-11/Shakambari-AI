// Generates PNG icons from the SVG sources. Run: npm run icons
import sharp from 'sharp'
import { readFileSync } from 'node:fs'
const pub = new URL('../public/', import.meta.url)
const fav = readFileSync(new URL('favicon.svg', pub))
const logo = readFileSync(new URL('logo.svg', pub))
const jobs = [
  [fav, 32, 'favicon-32.png'],
  [logo, 180, 'apple-touch-icon.png'],
  [logo, 192, 'icon-192.png'],
  [logo, 512, 'icon-512.png'],
]
for (const [src, size, name] of jobs) await sharp(src, { density: 384 }).resize(size, size).png().toFile(new URL(name, pub).pathname)
await sharp(readFileSync(new URL('../scripts/og-card.svg', import.meta.url))).png().toFile(new URL('og-image.png', pub).pathname)
console.log('icons generated')
