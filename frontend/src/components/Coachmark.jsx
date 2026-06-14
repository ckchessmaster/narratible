import { useLayoutEffect, useRef, useState } from 'react'

const CARD_WIDTH = 280
const GAP = 12

// Renders a single anchored coach-mark for the first un-dismissed tip in
// `tips` whose anchor element currently exists and is visible. Tips are
// resolved against `[data-tip-anchor="<anchor>"]` elements in the DOM.
//
// Shared by the wizard (App) and the Settings modal; callers control layering
// via `zIndex` and which tips are eligible via `tips`.
export default function Coachmark({ tips, onDismiss, onDisableAll, zIndex = 150 }) {
  const [resolved, setResolved] = useState(null) // { tip, rect } | null

  // Keep latest tips in a ref so the recompute effect can read them without
  // re-running on every render (the array is recreated each render by the
  // parent). The ref is updated in a layout effect declared *before* the
  // recompute effect so ordering is correct when `tipsKey` changes.
  const tipsRef = useRef(tips)
  const tipsKey = tips.map(t => t.id).join('|')
  useLayoutEffect(() => {
    tipsRef.current = tips
  })

  useLayoutEffect(() => {
    let raf = 0
    const recompute = () => {
      let next = null
      for (const tip of tipsRef.current) {
        const el = document.querySelector(`[data-tip-anchor="${CSS.escape(tip.anchor)}"]`)
        if (el) {
          const rect = el.getBoundingClientRect()
          if (rect.width > 0 || rect.height > 0) {
            next = { tip, rect }
            break
          }
        }
      }
      setResolved(next)
    }

    recompute()
    // Retry shortly in case anchors mount after a step/tab switch or async load.
    const t1 = setTimeout(recompute, 60)
    const t2 = setTimeout(recompute, 250)
    const onScrollResize = () => {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(recompute)
    }
    window.addEventListener('resize', onScrollResize)
    window.addEventListener('scroll', onScrollResize, true)
    return () => {
      clearTimeout(t1)
      clearTimeout(t2)
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', onScrollResize)
      window.removeEventListener('scroll', onScrollResize, true)
    }
  }, [tipsKey])

  if (!resolved) return null

  const { tip, rect } = resolved
  const placement = tip.placement || 'bottom'
  const cx = rect.left + rect.width / 2
  const cy = rect.top + rect.height / 2

  let left
  let top
  let transform
  let arrowLeftPx = CARD_WIDTH / 2 - 6

  if (placement === 'top') {
    left = cx
    top = rect.top - GAP
    transform = 'translate(-50%, -100%)'
  } else if (placement === 'left') {
    left = rect.left - GAP
    top = cy
    transform = 'translate(-100%, -50%)'
  } else if (placement === 'right') {
    left = rect.right + GAP
    top = cy
    transform = 'translate(0, -50%)'
  } else {
    left = cx
    top = rect.bottom + GAP
    transform = 'translate(-50%, 0)'
  }

  if (placement === 'top' || placement === 'bottom') {
    const half = CARD_WIDTH / 2
    const clampedLeft = Math.max(half + 8, Math.min(left, window.innerWidth - half - 8))
    arrowLeftPx = Math.max(14, Math.min(cx - (clampedLeft - half) - 6, CARD_WIDTH - 26))
    left = clampedLeft
  }

  const arrowStyle = {}
  if (placement === 'top') {
    arrowStyle.bottom = -6
    arrowStyle.left = arrowLeftPx
  } else if (placement === 'left') {
    arrowStyle.right = -6
    arrowStyle.top = '50%'
    arrowStyle.marginTop = -6
  } else if (placement === 'right') {
    arrowStyle.left = -6
    arrowStyle.top = '50%'
    arrowStyle.marginTop = -6
  } else {
    arrowStyle.top = -6
    arrowStyle.left = arrowLeftPx
  }

  return (
    <div className="coachmark" style={{ left, top, transform, zIndex }} role="dialog" aria-label={tip.title}>
      <div className="coachmark-arrow" style={arrowStyle} />
      <button className="coachmark-close" title="Dismiss" onClick={() => onDismiss(tip.id)}>✕</button>
      <div className="coachmark-title">{tip.title}</div>
      <div className="coachmark-body">{tip.body}</div>
      <div className="coachmark-actions">
        <label className="coachmark-check">
          <input
            type="checkbox"
            onChange={e => { if (e.target.checked) onDisableAll() }}
          />
          Don’t show tips
        </label>
        <button className="btn btn-primary btn-sm" onClick={() => onDismiss(tip.id)}>Got it</button>
      </div>
    </div>
  )
}
