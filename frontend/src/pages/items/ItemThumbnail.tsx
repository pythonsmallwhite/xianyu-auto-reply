import { useEffect, useRef, useState } from 'react'
import type { Item } from '@/types'

// Limit concurrent first-frame requests. Covers/images never start a video.
const frameQueue: Array<() => void> = []
let activeFrames = 0
function requestFrameSlot(start: () => void) {
  let started = false
  let released = false
  const run = () => {
    started = true
    activeFrames += 1
    start()
  }
  if (activeFrames < 2) run()
  else frameQueue.push(run)
  return () => {
    if (released) return
    released = true
    if (started) {
      activeFrames -= 1
      // Let all unmount cleanups cancel queued rows before starting another URL.
      queueMicrotask(() => {
        while (activeFrames < 2 && frameQueue.length) frameQueue.shift()?.()
      })
    } else {
      const index = frameQueue.indexOf(run)
      if (index !== -1) frameQueue.splice(index, 1)
    }
  }
}

function mediaUrl(value: unknown): string {
  if (typeof value !== 'string') return ''
  const url = value.trim()
  if (url.startsWith('/static/')) return url
  try {
    const parsed = new URL(url.startsWith('//') ? `https:${url}` : url)
    return ['https:', 'http:'].includes(parsed.protocol) && !parsed.username ? parsed.href : ''
  } catch {
    return ''
  }
}

export function ItemThumbnail({ item }: { item: Item }) {
  const cover = mediaUrl(item.item_video_cover)
  const firstImage = mediaUrl(item.item_images?.[0])
  const images = [...new Set([cover, firstImage].filter(Boolean))]
  const video = mediaUrl(item.item_video_url)
  return <ThumbnailMedia key={JSON.stringify([images, video])} images={images} video={video} />
}

function ThumbnailMedia({ images, video }: { images: string[]; video: string }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [visible, setVisible] = useState(false)
  const [imageIndex, setImageIndex] = useState(0)
  useEffect(() => {
    const element = containerRef.current
    if (!element) return
    if (typeof IntersectionObserver === 'undefined') {
      setVisible(true)
      return
    }
    const observer = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting), { rootMargin: '80px' })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  const image = images[imageIndex]
  return (
    <div ref={containerRef} className="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-md border border-slate-200 bg-slate-100 dark:border-slate-700 dark:bg-slate-800">
      {visible && image ? (
        <img
          key={image}
          src={image}
          alt="商品小图"
          width={48}
          height={48}
          loading="lazy"
          decoding="async"
          className="h-full w-full object-cover"
          onError={() => setImageIndex(index => index + 1)}
        />
      ) : visible && video ? (
        <VideoFirstFrame src={video} />
      ) : (
        <ThumbnailPlaceholder label={visible && images.length ? '加载失败' : images.length || video ? '待加载' : '无媒体'} />
      )}
    </div>
  )
}

function ThumbnailPlaceholder({ label }: { label: string }) {
  return <span className="px-1 text-center text-[10px] text-slate-400" role="img" aria-label={label} title={label}>{label}</span>
}

function VideoFirstFrame({ src }: { src: string }) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [loading, setLoading] = useState(false)
  const [ready, setReady] = useState(false)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    const element = videoRef.current
    if (!element) return
    let disposed = false
    let finished = false
    let timeout: ReturnType<typeof setTimeout> | undefined
    let release: (() => void) | undefined
    const stopDownload = () => {
      element.pause()
      element.removeAttribute('src')
      element.load()
    }
    const finish = (success: boolean) => {
      if (disposed || finished) return
      finished = true
      clearTimeout(timeout)
      element.pause()
      element.preload = 'none'
      if (success) setReady(true)
      else {
        setFailed(true)
        stopDownload()
      }
      release?.()
    }
    const onMetadata = () => {
      if (disposed || finished) return
      try {
        const duration = element.duration
        if (!Number.isFinite(duration) || duration <= 0) return finish(false)
        element.currentTime = Math.min(0.1, duration / 2)
      } catch {
        finish(false)
      }
    }
    const onSeeked = () => {
      if (element.readyState >= 2 && element.videoWidth > 0 && element.videoHeight > 0) finish(true)
    }
    const onError = () => finish(false)
    element.addEventListener('loadedmetadata', onMetadata)
    element.addEventListener('seeked', onSeeked)
    element.addEventListener('error', onError)
    release = requestFrameSlot(() => {
      if (disposed) return
      setLoading(true)
      element.preload = 'metadata'
      timeout = setTimeout(() => finish(false), 6000)
      element.src = src
      element.load()
    })
    return () => {
      disposed = true
      clearTimeout(timeout)
      element.removeEventListener('loadedmetadata', onMetadata)
      element.removeEventListener('seeked', onSeeked)
      element.removeEventListener('error', onError)
      stopDownload()
      release?.()
    }
  }, [src])

  return (
    <div className="relative flex h-full w-full items-center justify-center">
      {!ready && <ThumbnailPlaceholder label={failed ? '加载失败' : loading ? '加载中' : '待加载'} />}
      <video
        ref={videoRef}
        muted
        playsInline
        preload="none"
        width={48}
        height={48}
        aria-label="商品视频首帧"
        className={`absolute inset-0 h-full w-full object-cover ${ready ? '' : 'invisible'}`}
      />
      {ready && <span className="absolute bottom-0 right-0 rounded-tl bg-black/60 px-1 text-[9px] text-white">视频</span>}
    </div>
  )
}
