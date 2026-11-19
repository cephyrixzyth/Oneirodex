import { SystemFamilyMark } from '../chrome/systemMarks'
import { SystemMotifArt, motifForPlatform } from '@oneirodex/ui/loadingMotifs'

export {
  SYSTEM_MOTIF_ARCHETYPES,
  SystemMotifArt,
  motifForPlatform,
} from '@oneirodex/ui/loadingMotifs'

/**
 * Per-system glyph, sized to whatever box it is dropped into.
 *
 * The Systems hub drew `SystemFamilyMark` — one glyph for all of Nintendo, one
 * for all of Sony — so a grid of twelve consoles showed four distinct pictures
 * between them, on coloured plates that made the tile about the plate. Every
 * system already has its own motif for the loading states; this is the same
 * drawing, doing the job it was made for on a surface that is about systems.
 *
 * Falls back to the family mark for a platform the catalogue does not know,
 * which is the honest answer for an id added to the backend enum before the
 * motifs are regenerated.
 */
export function SystemGlyph({ platformValue, family }: LooseProps) {
  const motif = motifForPlatform(platformValue)
  if (!motif) {
    return <SystemFamilyMark family={family} />
  }
  return <SystemMotifArt archetype={motif.archetype} variant={motif.variant} />
}
