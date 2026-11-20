export function GameGridSkeleton({ count = 12, layout = 'tile' }: LooseProps) {
  const placeholders = Array.from({ length: Math.max(count, 1) }, (_, index) => index)

  return (
    <div
      className="game-library-container"
      data-library-grid
      data-library-skeleton
      data-layout={layout}
      role="status"
      aria-busy="true"
      aria-label="Loading games"
    >
      {placeholders.map((index) => (
        <div key={index} className="game-card-skeleton" aria-hidden="true">
          <div className="game-card-skeleton__cover" />
        </div>
      ))}
    </div>
  )
}
