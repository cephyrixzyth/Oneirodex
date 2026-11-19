import { CanvasTexture, SRGBColorSpace } from 'three'

export function wrapReadingText(text: string, width: number, measure: (text: string) => number) {
  const lines: string[] = []
  let current = ''
  for (const word of text.trim().split(/\s+/)) {
    const candidate = current ? current + ' ' + word : word
    if (current && measure(candidate) > width) {
      lines.push(current)
      current = ''
    }
    if (measure(word) > width) {
      for (const glyph of Array.from(word)) {
        if (current && measure(current + glyph) > width) {
          lines.push(current)
          current = ''
        }
        current += glyph
      }
    } else current = current ? current + ' ' + word : word
  }
  if (current) lines.push(current)
  return lines
}

export function readingTexture(
  title: string,
  text: string,
  index: number,
  accent: string,
  large = false,
) {
  const canvas = document.createElement('canvas')
  canvas.width = 1080
  canvas.height = 416
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('The reading desk requires a canvas.')
  ctx.fillStyle = '#152124'
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  ctx.fillStyle = accent
  ctx.fillRect(0, 0, 8, canvas.height)
  ctx.font = 'bold 52px sans-serif'
  const headings = wrapReadingText(title, 1004, (s) => ctx.measureText(s).width)
  const headRows = Math.min(2, headings.length)
  ctx.fillStyle = '#f5f5eb'
  headings
    .slice(0, headRows)
    .forEach((line, i) =>
      ctx.fillText(line + (i === 1 && headings.length > 2 ? '…' : ''), 38, 65 + i * 56, 1004),
    )
  const bodySize = large ? 46 : 34
  const lineHeight = large ? 55 : 43
  ctx.font = bodySize + 'px sans-serif'
  ctx.fillStyle = '#d5ded7'
  const lines = wrapReadingText(text, 1004, (s) => ctx.measureText(s).width)
  const firstY = 72 + headRows * 56
  const perPage = Math.floor((359 - firstY) / lineHeight) + 1
  const pages = Math.max(1, Math.ceil(lines.length / perPage))
  const page = Math.min(Math.max(0, index), pages - 1)
  lines
    .slice(page * perPage, (page + 1) * perPage)
    .forEach((line, i) => ctx.fillText(line, 38, firstY + i * lineHeight))
  if (pages > 1) {
    ctx.font = '26px sans-serif'
    ctx.fillStyle = accent
    ctx.fillText(`Page ${page + 1} of ${pages}`, 38, 396)
  }
  const texture = new CanvasTexture(canvas)
  texture.colorSpace = SRGBColorSpace
  return { texture, pages, page }
}
