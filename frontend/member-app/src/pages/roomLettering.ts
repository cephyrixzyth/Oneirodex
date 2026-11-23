type Line = { text: string; y: number; kind: 'title' | 'body' }

/** Mounted display typography is sized by its actual canvas, not the room's large wall signs. */
export function instrumentLabelLayout(
  title: string,
  body: string,
  width: number,
  height: number,
  measure: (text: string, size: number) => number,
) {
  const titleSize = Math.min(42, height * 0.35)
  function layout(bodySize: number) {
    const lines: Line[] = []
    let clipped = false,
      y = titleSize + 8
    function wrap(text: string, size: number, kind: Line['kind'], limit: number) {
      const words = text.trim().split(/\s+/).filter(Boolean)
      for (let row = 0; row < limit && words.length; row++) {
        let line = words.shift()!
        while (words.length && measure(line + ' ' + words[0], size) < width - 60)
          line += ' ' + words.shift()
        lines.push({ text: line, y, kind })
        y += size * 1.17
      }
      if (words.length) clipped = true
    }
    wrap(title, titleSize, 'title', 1)
    y += 8
    wrap(body, bodySize, 'body', Math.max(0, Math.floor((height - 6 - y) / (bodySize * 1.17)) + 1))
    return { lines, clipped, titleSize, bodySize }
  }
  let result = layout(Math.min(26, titleSize * 0.72))
  if (result.clipped && result.bodySize > 24) result = layout(24)
  return result
}
