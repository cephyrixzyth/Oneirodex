export type Choice = { id: number; name: string }
export type Options = {
  libraries: Array<{ uuid: string; name: string; platform_name: string }>
  taxonomies: Record<string, Choice[]>
  categories: Array<{ value: string; label: string }>
  statuses: Array<{ value: string; label: string }>
}
export type Candidate = Record<string, any> & { id: number; name: string }

export const TAXONOMIES = [
  ['genres', 'Genres', 'genre_ids'],
  ['game_modes', 'Game modes', 'game_mode_ids'],
  ['themes', 'Themes', 'theme_ids'],
  ['platforms', 'Platforms', 'platform_ids'],
  ['player_perspectives', 'Player perspectives', 'player_perspective_ids'],
] as const
