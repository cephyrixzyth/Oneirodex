import type { SVGProps } from 'react'
import { RailIcon } from '@oneirodex/ui'

// Preserve the existing top-bar viewport and size. Destination glyphs belong
// to the shared rail; only the two live top-bar control adapters remain here.
const base = {
  viewBox: '0 0 24 24',
  width: 18,
  height: 18,
} as const

export function IconMenu(props: SVGProps<SVGSVGElement>) {
  return <RailIcon name="menu" era={null} {...base} {...props} />
}

export function IconUser(props: SVGProps<SVGSVGElement>) {
  return <RailIcon name="user" era={null} {...base} {...props} />
}
