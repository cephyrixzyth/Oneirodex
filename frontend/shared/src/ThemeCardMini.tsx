/**
 * A miniature of the theme for the picker: its room behind a glass bar with the
 * theme's avatar and icons, and three cover tiles in its frame — so a member
 * chooses a look, not a colour chip. Purely decorative (the button carries the
 * name and description).
 */
const PREVIEW_ICONS = ['library', 'discover', 'favorites'] as const

export function ThemeCardMini({ slug, iconPack }: { slug: string; iconPack?: string }) {
  const themeRoot = `/static/library/themes/${encodeURIComponent(slug)}`
  const pack = iconPack && iconPack !== 'outline' ? encodeURIComponent(iconPack) : ''
  return (
    <span className="theme-card-mini" aria-hidden="true">
      <span className="theme-card-mini__bar">
        <img
          className="theme-card-mini__avatar"
          src={`${themeRoot}/avatars/fox.svg`}
          alt=""
          loading="lazy"
          onError={(event) => event.currentTarget.remove()}
        />
        {pack
          ? PREVIEW_ICONS.map((name) => (
              <span
                key={name}
                className="theme-card-mini__icon"
                style={{
                  WebkitMaskImage: `url(/static/library/icon-themes/${pack}/icons/${name}.svg)`,
                  maskImage: `url(/static/library/icon-themes/${pack}/icons/${name}.svg)`,
                }}
              />
            ))
          : null}
      </span>
      <span className="theme-card-mini__tiles">
        <span className="theme-card-mini__tile" />
        <span className="theme-card-mini__tile" />
        <span className="theme-card-mini__tile" />
      </span>
    </span>
  )
}
