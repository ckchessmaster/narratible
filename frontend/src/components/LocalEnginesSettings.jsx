import { useEffect, useState } from 'react'
import {
  getRuntimeEngines,
  getRuntimePreflight,
  installRuntimeEngine,
  pollTask,
  removeRuntimeEngine,
  repairRuntimeEngine,
  verifyRuntimeEngine,
} from '../api'

const STATUS_LABELS = {
  failed: 'Needs repair',
  installing: 'Installing',
  needs_repair: 'Needs repair',
  needs_update: 'Update available',
  coming_soon: 'Coming soon',
  planned: 'Planned',
  not_available: 'Not available',
  not_installed: 'Not installed',
  verified: 'Ready',
}

const formatSize = value => value >= 1024
  ? `${(value / 1024).toFixed(1)} GB`
  : `${value} MB`
const operationIsBusy = operation => ['queued', 'running'].includes(operation?.status)

export default function LocalEnginesSettings() {
  const [runtime, setRuntime] = useState(null)
  const [preflight, setPreflight] = useState(null)
  const [error, setError] = useState('')
  const [operations, setOperations] = useState({})
  const [confirmRemove, setConfirmRemove] = useState('')

  const refreshRuntime = async () => {
    const [runtimeResult, preflightResult] = await Promise.all([
      getRuntimeEngines(),
      getRuntimePreflight(),
    ])
    setRuntime(runtimeResult)
    setPreflight(preflightResult)
  }

  useEffect(() => {
    let active = true
    Promise.all([getRuntimeEngines(), getRuntimePreflight()])
      .then(([runtimeResult, preflightResult]) => {
        if (!active) return
        setRuntime(runtimeResult)
        setPreflight(preflightResult)
      })
      .catch(requestError => {
        if (active) setError(requestError.message)
      })
    return () => { active = false }
  }, [])

  const runOperation = async (profile, operation) => {
    const starters = {
      install: installRuntimeEngine,
      repair: repairRuntimeEngine,
      verify: verifyRuntimeEngine,
    }
    setError('')
    setOperations(current => ({
      ...current,
      [profile.id]: { status: 'queued', progress: 0, message: `Queued ${operation}...` },
    }))
    try {
      const { task_id: taskId } = await starters[operation](profile.id)
      await pollTask(taskId, task => {
        setOperations(current => ({ ...current, [profile.id]: task }))
      }, 750)
      await refreshRuntime()
    } catch (operationError) {
      setOperations(current => ({
        ...current,
        [profile.id]: { status: 'error', progress: 0, message: operationError.message },
      }))
    }
  }

  const removeProfile = async profile => {
    setError('')
    try {
      await removeRuntimeEngine(profile.id)
      setConfirmRemove('')
      setOperations(current => {
        const next = { ...current }
        delete next[profile.id]
        return next
      })
      await refreshRuntime()
    } catch (operationError) {
      setError(operationError.message)
    }
  }

  if (error) {
    return <div className="runtime-engine-error">{error}</div>
  }
  if (!runtime || !preflight) {
    return <div className="text-sm text-muted">Loading local runtime status...</div>
  }

  return (
    <div className="runtime-engine-settings" data-tip-anchor="settings-local-engines">
      <div className="runtime-engine-summary">
        <div>
          <div className="runtime-engine-summary-title">
            {preflight.supported ? 'NVIDIA runtime available' : 'Local runtime unavailable'}
          </div>
          <div className="text-xs text-muted">
            {preflight.supported
              ? preflight.gpus.map(gpu => `${gpu.name} · ${formatSize(gpu.vram_mb)} VRAM · Driver ${gpu.driver_version}`).join(' | ')
              : preflight.reason}
          </div>
          {preflight.supported && !runtime.profiles.some(profile => profile.status === 'verified') && (
            <div className="text-xs text-muted mt-1">
              Local AI was not set up during installation. Install Kokoro below; narratible does not need to be reinstalled.
            </div>
          )}
        </div>
        <span className={`runtime-engine-state ${preflight.supported ? 'is-ready' : 'is-muted'}`}>
          {runtime.pytorch.backend.toUpperCase()}
        </span>
      </div>

      <div className="runtime-engine-list">
        {runtime.profiles.map(profile => (
          <div className="runtime-engine-row" key={profile.id}>
            <div className="runtime-engine-main">
              <div className="runtime-engine-name">{profile.label}</div>
              <div className="text-xs text-muted">
                {formatSize(profile.estimated_download_mb)} download · {formatSize(profile.estimated_disk_mb)} installed
              </div>
              {profile.last_error && <div className="runtime-engine-error text-xs">{profile.last_error}</div>}
              {operations[profile.id] && (
                <div className="runtime-engine-operation">
                  <div className="runtime-engine-progress" aria-hidden="true">
                    <span style={{ width: `${operations[profile.id].progress || 0}%` }} />
                  </div>
                  <div className="text-xs text-muted">{operations[profile.id].message}</div>
                </div>
              )}
            </div>
            <div className="runtime-engine-actions">
              <span className={`runtime-engine-state is-${profile.status}`}>
                {STATUS_LABELS[profile.status] || profile.status}
              </span>
              {profile.installable && profile.status === 'not_installed' && (
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  disabled={!preflight.supported || operationIsBusy(operations[profile.id])}
                  onClick={() => runOperation(profile, 'install')}
                >
                  Install
                </button>
              )}
              {profile.installable && ['failed', 'needs_repair'].includes(profile.status) && (
                <button type="button" className="btn btn-secondary btn-sm" disabled={operationIsBusy(operations[profile.id])} onClick={() => runOperation(profile, 'repair')}>
                  Repair
                </button>
              )}
              {profile.installable && profile.status === 'needs_update' && (
                <button type="button" className="btn btn-secondary btn-sm" disabled={operationIsBusy(operations[profile.id])} onClick={() => runOperation(profile, 'install')}>
                  Update
                </button>
              )}
              {profile.status === 'verified' && confirmRemove !== profile.id && (
                <>
                  <button type="button" className="btn btn-ghost btn-sm" disabled={operationIsBusy(operations[profile.id])} onClick={() => runOperation(profile, 'verify')}>
                    Verify
                  </button>
                  <button type="button" className="btn btn-ghost btn-sm" disabled={operationIsBusy(operations[profile.id])} onClick={() => setConfirmRemove(profile.id)}>
                    Remove
                  </button>
                </>
              )}
              {confirmRemove === profile.id && (
                <>
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => setConfirmRemove('')}>Cancel</button>
                  <button type="button" className="btn btn-danger btn-sm" onClick={() => removeProfile(profile)}>Confirm</button>
                </>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}