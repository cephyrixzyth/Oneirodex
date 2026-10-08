import { useEffect, useRef, useState } from 'react'
import { buildEmbedSrc, loadYouTubeApi } from './trailersHelpers'

/* TrailerPlayer moved out of TrailersPage (v11 cycle, H-D.2) — unchanged. */

export function TrailerPlayer({
  videoId,
  skipFirst,
  settingsRef,
  onAdvance,
  title,
  gameUuid,
}: LooseProps) {
  const frameRef = useRef<any>(null)
  const advanceRef = useRef(onAdvance)
  const [src] = useState(() => buildEmbedSrc(videoId, skipFirst))

  useEffect(() => {
    advanceRef.current = onAdvance
  }, [onAdvance])

  useEffect(() => {
    let cancelled = false
    let player: any = null
    let timer: any = null
    let playedSeconds = 0
    let isPlaying = false

    function stopTimer() {
      if (timer) {
        clearInterval(timer)
        timer = null
      }
      playedSeconds = 0
      isPlaying = false
    }

    function startTimer() {
      if (timer) {
        return
      }
      timer = setInterval(() => {
        if (!isPlaying) {
          return
        }
        playedSeconds += 1
        const { skipAfter } = settingsRef.current
        if (skipAfter > 0 && playedSeconds >= skipAfter) {
          stopTimer()
          advanceRef.current?.()
        }
      }, 1000)
    }

    loadYouTubeApi().then((YT: any) => {
      if (cancelled || !YT?.Player || !frameRef.current) {
        return
      }

      player = new YT.Player(frameRef.current, {
        events: {
          onStateChange: (event: any) => {
            if (event.data === YT.PlayerState.PLAYING) {
              isPlaying = true
              startTimer()
            } else if (event.data === YT.PlayerState.PAUSED) {
              isPlaying = false
            } else if (event.data === YT.PlayerState.ENDED) {
              stopTimer()
              if (settingsRef.current.enabled) {
                advanceRef.current?.()
              }
            }
          },
        },
      })
    })

    return () => {
      cancelled = true
      stopTimer()
      try {
        player?.destroy?.()
      } catch {
        // The frame is already gone when React unmounted it first.
      }
    }
  }, [videoId, settingsRef])

  return (
    /* The CRT bezel is a generated transparent overlay in TrailersPage.css.
       The frame is decorative; the iframe remains the accessible video. */
    <div className="od-trailers__set">
      {/* The title leads the set.
          It sat under the cabinet, below the bezel and the knobs, so on a tall
          player you were watching something for several seconds before the page
          told you what it was — and on a short window it fell below the fold
          entirely. Above the frame it is the first thing read, which is the
          order a title and its video belong in. Still a link, because "what am
          I watching" and "take me to it" are the same question. */}
      {title ? (
        <p className="od-trailers__caption">
          <a className="od-trailers__title-link" href={`/game_details/${gameUuid}`}>
            {title}
          </a>
        </p>
      ) : null}
      <div className="od-trailers__video">
        <iframe
          ref={frameRef}
          title={title ? `Trailer — ${title}` : 'Game trailer'}
          src={src}
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; fullscreen"
          allowFullScreen
        />
        <span className="od-trailers__scanlines" aria-hidden="true" />
        <span className="od-trailers__glare" aria-hidden="true" />
      </div>
    </div>
  )
}
