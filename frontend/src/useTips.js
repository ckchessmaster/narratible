import { useCallback, useEffect, useState } from 'react'
import {
  TIPS,
  getDismissedTips,
  isTipsDisabled,
  dismissTip as persistDismiss,
  disableAllTips as persistDisableAll,
  resetTips as persistReset,
} from './tips'

// Manages first-time-user tip state backed by localStorage.
//
// Multiple instances stay in sync via the `tips:reset` window event, so a
// reset triggered from Settings also restores the wizard tips rendered by App.
export default function useTips() {
  const [dismissed, setDismissed] = useState(() => getDismissedTips())
  const [disabled, setDisabled] = useState(() => isTipsDisabled())

  useEffect(() => {
    const sync = () => {
      setDismissed(getDismissedTips())
      setDisabled(isTipsDisabled())
    }
    window.addEventListener('tips:reset', sync)
    return () => window.removeEventListener('tips:reset', sync)
  }, [])

  const dismiss = useCallback((id) => {
    persistDismiss(id)
    setDismissed(prev => new Set(prev).add(id))
  }, [])

  const disableAll = useCallback(() => {
    persistDisableAll()
    setDisabled(true)
  }, [])

  const reset = useCallback(() => {
    // Dispatches `tips:reset`, which the effect above uses to refresh state.
    persistReset()
  }, [])

  // Returns the still-active tips (not dismissed, not globally disabled)
  // matching the supplied predicate, in definition order.
  const getActiveTips = useCallback((predicate) => {
    if (disabled) return []
    return TIPS.filter(t => !dismissed.has(t.id) && predicate(t))
  }, [disabled, dismissed])

  return { disabled, dismiss, disableAll, reset, getActiveTips }
}
