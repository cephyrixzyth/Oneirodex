import { useEffect, useId, useRef, useState } from 'react'
import { Button, Modal } from '@oneirodex/ui'
import './LibraryImageCropper.css'

interface CropperInstance {
  destroy(): void
  getCroppedCanvas(options: {
    width: number
    height: number
    imageSmoothingEnabled: boolean
    imageSmoothingQuality: 'high'
  }): HTMLCanvasElement
  move(x: number, y: number): void
  reset(): void
  zoom(ratio: number): void
}

interface CropperOptions {
  aspectRatio: number
  autoCropArea: number
  background: boolean
  center: boolean
  checkCrossOrigin: boolean
  checkOrientation: boolean
  cropBoxMovable: boolean
  cropBoxResizable: boolean
  dragMode: 'move'
  guides: boolean
  highlight: boolean
  modal: boolean
  responsive: boolean
  restore: boolean
  rotatable: boolean
  scalable: boolean
  toggleDragModeOnDblclick: boolean
  viewMode: number
  zoomable: boolean
}

interface CropperConstructor {
  new (image: HTMLImageElement, options: CropperOptions): CropperInstance
}

declare global {
  interface Window {
    Cropper?: CropperConstructor
  }
}

const CROP_CSS = '/static/vendor/cropperjs/1.6.1/cropper.min.css'
const CROP_JS = '/static/vendor/cropperjs/1.6.1/cropper.min.js'

let cropperLoad: Promise<CropperConstructor> | null = null

function loadCropper(): Promise<CropperConstructor> {
  if (window.Cropper) return Promise.resolve(window.Cropper)
  if (!cropperLoad) {
    if (!document.querySelector('link[data-oneirodex-cropper]')) {
      const link = document.createElement('link')
      link.rel = 'stylesheet'
      link.href = CROP_CSS
      link.dataset.oneirodexCropper = 'true'
      document.head.append(link)
    }
    cropperLoad = new Promise((resolve, reject) => {
      const existing = document.querySelector<HTMLScriptElement>('script[data-oneirodex-cropper]')
      const script = existing || document.createElement('script')
      const cleanup = () => {
        script.removeEventListener('load', onLoad)
        script.removeEventListener('error', onError)
      }
      const onLoad = () => {
        cleanup()
        if (window.Cropper) resolve(window.Cropper)
        else {
          cropperLoad = null
          script.remove()
          reject(new Error('Image editor could not be loaded.'))
        }
      }
      const onError = () => {
        cleanup()
        cropperLoad = null
        script.remove()
        reject(new Error('Image editor could not be loaded.'))
      }
      script.addEventListener('load', onLoad, { once: true })
      script.addEventListener('error', onError, { once: true })
      if (!existing) {
        script.src = CROP_JS
        script.dataset.oneirodexCropper = 'true'
        document.head.append(script)
      }
    })
  }
  return cropperLoad
}

const cropperOptions: CropperOptions = {
  aspectRatio: 1,
  viewMode: 1,
  dragMode: 'move',
  autoCropArea: 0.8,
  restore: false,
  guides: true,
  center: true,
  highlight: false,
  cropBoxMovable: true,
  cropBoxResizable: true,
  toggleDragModeOnDblclick: false,
  modal: true,
  background: false,
  responsive: true,
  checkCrossOrigin: false,
  zoomable: true,
  scalable: false,
  rotatable: false,
  checkOrientation: false,
}

export function LibraryImageCropper({
  file,
  onSave,
  onCancel,
}: {
  file: File
  onSave: (file: File) => void
  onCancel: () => void
}) {
  const titleId = useId()
  const imageRef = useRef<HTMLImageElement | null>(null)
  const cropperRef = useRef<CropperInstance | null>(null)
  const [imageUrl, setImageUrl] = useState('')
  const [error, setError] = useState('')
  const [cropReady, setCropReady] = useState(false)

  useEffect(() => {
    const url = URL.createObjectURL(file)
    setImageUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [file])

  useEffect(() => {
    let cancelled = false
    let imageLoadHandler: (() => void) | undefined
    setCropReady(false)
    void loadCropper()
      .then((Cropper) => {
        const image = imageRef.current
        if (cancelled || !image) return
        const initialize = () => {
          if (!cancelled && imageRef.current === image && !cropperRef.current) {
            cropperRef.current = new Cropper(image, cropperOptions)
            setCropReady(true)
            setError('')
          }
        }
        if (image.complete) {
          if (image.naturalWidth > 0) initialize()
          else setError('This image could not be opened.')
        } else {
          imageLoadHandler = initialize
          image.addEventListener('load', initialize, { once: true })
          image.addEventListener('error', () => setError('This image could not be opened.'), {
            once: true,
          })
        }
      })
      .catch(() => {
        if (!cancelled) setError('Image editor could not be loaded. Try choosing the image again.')
      })
    return () => {
      cancelled = true
      const image = imageRef.current
      if (image && imageLoadHandler) image.removeEventListener('load', imageLoadHandler)
      cropperRef.current?.destroy()
      cropperRef.current = null
    }
  }, [imageUrl])

  useEffect(() => {
    const handleKeys = (event: KeyboardEvent) => {
      const cropper = cropperRef.current
      if (!cropper) return
      switch (event.key) {
        case 'ArrowLeft':
          event.preventDefault()
          cropper.move(-10, 0)
          break
        case 'ArrowRight':
          event.preventDefault()
          cropper.move(10, 0)
          break
        case 'ArrowUp':
          event.preventDefault()
          cropper.move(0, -10)
          break
        case 'ArrowDown':
          event.preventDefault()
          cropper.move(0, 10)
          break
        case '+':
        case '=':
          event.preventDefault()
          cropper.zoom(0.1)
          break
        case '-':
          event.preventDefault()
          cropper.zoom(-0.1)
          break
        case 'r':
        case 'R':
          event.preventDefault()
          cropper.reset()
          break
      }
    }
    document.addEventListener('keydown', handleKeys)
    return () => document.removeEventListener('keydown', handleKeys)
  }, [])

  function saveCrop() {
    const cropper = cropperRef.current
    if (!cropper) return
    cropper
      .getCroppedCanvas({
        width: 512,
        height: 512,
        imageSmoothingEnabled: true,
        imageSmoothingQuality: 'high',
      })
      .toBlob(
        (blob) => {
          if (!blob) {
            setError('The selected image could not be cropped. Try another image.')
            return
          }
          onSave(new File([blob], file.name, { type: 'image/png', lastModified: Date.now() }))
        },
        'image/png',
        0.9,
      )
  }

  return (
    <Modal
      open
      onClose={onCancel}
      labelledBy={titleId}
      className="od-library-image-cropper__backdrop"
      panelClassName="od-library-image-cropper"
      closeOnBackdrop={false}
      lockScroll
    >
      <header className="od-library-image-cropper__header">
        <h2 id={titleId}>Edit library image</h2>
      </header>
      <div className="od-library-image-cropper__canvas">
        {imageUrl ? <img ref={imageRef} src={imageUrl} alt="Crop library image" /> : null}
      </div>
      {error ? (
        <p className="od-library-image-cropper__error" role="alert">
          {error}
        </p>
      ) : null}
      <div className="od-library-image-cropper__controls" aria-label="Image crop controls">
        <Button
          type="button"
          className="od-btn--ghost"
          disabled={!cropReady}
          onClick={() => cropperRef.current?.zoom(0.1)}
        >
          Zoom In
        </Button>
        <Button
          type="button"
          className="od-btn--ghost"
          disabled={!cropReady}
          onClick={() => cropperRef.current?.zoom(-0.1)}
        >
          Zoom Out
        </Button>
        <Button
          type="button"
          className="od-btn--ghost"
          disabled={!cropReady}
          onClick={() => cropperRef.current?.reset()}
        >
          Reset
        </Button>
      </div>
      <footer className="od-library-image-cropper__actions">
        <Button type="button" className="od-btn--ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="button" className="od-btn--accent" onClick={saveCrop} disabled={!cropReady}>
          Save Image
        </Button>
      </footer>
    </Modal>
  )
}
