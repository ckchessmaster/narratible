import { useState } from 'react'
import {
  X,
  Sparkles,
  Check,
  RotateCcw,
  SkipForward,
  Play,
  Loader2,
  AlertTriangle,
  Undo2,
} from 'lucide-react'
import {
  modernizeChapter,
  modernizeProject,
  redoModernizationChunk,
  selectModernizationVariant,
  skipModernizationChunk,
  commitModernizationSession,
  undoLastModernizationCommit,
  pollTask,
} from '../api'

export default function ModernizationDrawer({
  projectId,
  isOpen,
  onClose,
  currentChapterIndex,
  currentChapterTitle,
  modernizationEval,
  setModernizationEval,
  modernizationProfiles = [],
  toast,
  onChaptersUpdated,
}) {
  const [profile, setProfile] = useState('standard_modern')
  const [running, setRunning] = useState(false)
  const [runningMsg, setRunningMsg] = useState('')
  const [retryingChunkId, setRetryingChunkId] = useState(null)

  if (!isOpen) return null

  const chapterEval = modernizationEval?.chapters?.find(
    ch => ch.chapter_index === currentChapterIndex
  )
  const activeSession = chapterEval?.active_session
  const chunks = activeSession?.chunks || []

  const handleModernizeCurrent = async () => {
    if (!projectId) return
    setRunning(true)
    setRunningMsg(`Modernizing "${currentChapterTitle}"…`)
    try {
      const res = await modernizeChapter(projectId, currentChapterIndex, profile)
      if (res?.evaluation) {
        setModernizationEval(res.evaluation)
      }
      if (toast) toast('Modernization candidates generated for chapter.', 'success')
    } catch (err) {
      if (toast) toast(err.message || 'Failed to modernize chapter', 'error')
    } finally {
      setRunning(false)
      setRunningMsg('')
    }
  }

  const handleModernizeAll = async () => {
    if (!projectId) return
    if (!window.confirm('Run modernization across all chapters in the book?')) return
    setRunning(true)
    setRunningMsg('Queueing full-book modernization…')
    try {
      const { task_id } = await modernizeProject(projectId, profile)
      const res = await pollTask(task_id, (t) => {
        setRunningMsg(t.message || 'Processing chapters…')
      })
      if (res?.evaluation) {
        setModernizationEval(res.evaluation)
      }
      if (toast) toast('Book modernization completed.', 'success')
    } catch (err) {
      if (toast) toast(err.message || 'Failed to modernize book', 'error')
    } finally {
      setRunning(false)
      setRunningMsg('')
    }
  }

  const handleSelectVariant = async (chunkId, variantId) => {
    try {
      const res = await selectModernizationVariant(projectId, currentChapterIndex, chunkId, variantId)
      if (res?.evaluation) setModernizationEval(res.evaluation)
    } catch (err) {
      if (toast) toast(err.message || 'Failed to select variant', 'error')
    }
  }

  const handleSkipChunk = async (chunkId) => {
    try {
      const res = await skipModernizationChunk(projectId, currentChapterIndex, chunkId)
      if (res?.evaluation) setModernizationEval(res.evaluation)
    } catch (err) {
      if (toast) toast(err.message || 'Failed to skip passage', 'error')
    }
  }

  const handleRedoChunk = async (chunkId) => {
    setRetryingChunkId(chunkId)
    try {
      const res = await redoModernizationChunk(projectId, currentChapterIndex, chunkId, profile)
      if (res?.evaluation) setModernizationEval(res.evaluation)
    } catch (err) {
      if (toast) toast(err.message || 'Failed to retry passage', 'error')
    } finally {
      setRetryingChunkId(null)
    }
  }

  const handleCommit = async () => {
    try {
      const res = await commitModernizationSession(projectId, currentChapterIndex)
      if (res?.evaluation) setModernizationEval(res.evaluation)
      if (onChaptersUpdated) onChaptersUpdated()
      if (toast) toast('Modernized changes committed to chapter text.', 'success')
    } catch (err) {
      if (toast) toast(err.message || 'Failed to commit modernization', 'error')
    }
  }

  const handleUndo = async () => {
    try {
      const res = await undoLastModernizationCommit(projectId, currentChapterIndex)
      if (res?.evaluation) setModernizationEval(res.evaluation)
      if (onChaptersUpdated) onChaptersUpdated()
      if (toast) toast('Reverted chapter to pre-modernization state.', 'info')
    } catch (err) {
      if (toast) toast(err.message || 'Failed to undo modernization commit', 'error')
    }
  }

  const canCommit = chunks.some(c => c.selected_variant_id)

  return (
    <div className="drawer-overlay" onClick={onClose} role="dialog" aria-modal="true">
      <div className="drawer-panel drawer-panel-wide" onClick={e => e.stopPropagation()}>
        <div className="drawer-header">
          <div className="drawer-title-group">
            <h2 className="drawer-title flex items-center gap-2">
              <Sparkles size={18} className="text-accent" /> Text Modernization Studio
            </h2>
            <span className="drawer-subtitle">
              Intelligently update archaic vocabulary and syntax for smoother TTS reading without altering narrative meaning.
            </span>
          </div>
          <button className="btn-icon" onClick={onClose} aria-label="Close Modernization Studio">
            <X size={20} />
          </button>
        </div>

        <div className="drawer-body">
          {/* Controls Bar */}
          <div className="modernize-controls-card glass p-3 mb-4">
            <div className="flex items-center justify-between gap-3" style={{ flexWrap: 'wrap' }}>
              <div className="flex items-center gap-2">
                <label className="text-xs text-muted" htmlFor="modernize-profile-select">Profile:</label>
                <select
                  id="modernize-profile-select"
                  className="form-select form-select-sm"
                  value={profile}
                  onChange={e => setProfile(e.target.value)}
                  disabled={running}
                >
                  {modernizationProfiles.map(p => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                  {!modernizationProfiles.length && (
                    <option value="standard_modern">Standard Modernization</option>
                  )}
                </select>
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  onClick={handleModernizeCurrent}
                  disabled={running}
                >
                  {running ? <Loader2 size={14} className="spin mr-1" /> : <Play size={14} className="mr-1" />}
                  Modernize Chapter
                </button>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={handleModernizeAll}
                  disabled={running}
                >
                  Modernize All Chapters
                </button>
              </div>
            </div>

            {running && (
              <div className="mt-3 flex items-center gap-2 text-xs text-accent">
                <Loader2 size={14} className="spin" />
                <span>{runningMsg}</span>
              </div>
            )}
          </div>

          {/* Chapter Status Banner */}
          <div className="flex items-center justify-between p-2 mb-3 bg-subtle rounded text-xs">
            <span>
              Active Chapter: <strong>{currentChapterTitle}</strong>
              {chapterEval?.status === 'committed' && (
                <span className="badge badge-success ml-2">Committed</span>
              )}
            </span>
            {chapterEval?.status === 'committed' && (
              <button
                type="button"
                className="btn btn-ghost btn-sm text-danger"
                onClick={handleUndo}
              >
                <Undo2 size={13} className="mr-1" /> Undo Last Commit
              </button>
            )}
          </div>

          {/* Chunk Passages Review */}
          {!chunks.length ? (
            <div className="empty-state py-8 text-center text-muted">
              <Sparkles size={32} className="mx-auto mb-2 opacity-50" />
              <p className="text-sm">No modernization candidates generated yet for this chapter.</p>
              <p className="text-xs mt-1">Select a profile above and click "Modernize Chapter" to generate suggestions.</p>
            </div>
          ) : (
            <div className="modernize-chunks-list flex flex-col gap-3">
              {chunks.map((chunk, idx) => {
                const variant = chunk.variants?.[0]
                const isSelected = chunk.selected_variant_id === variant?.variant_id
                const isSkipped = chunk.status === 'skipped'
                const hasWarning = chunk.recommended_action === 'review' || chunk.risk_level === 'high'

                return (
                  <div
                    key={chunk.chunk_id || idx}
                    className={`modernize-chunk-card glass p-3 ${isSelected ? 'is-selected' : ''} ${hasWarning ? 'has-warning' : ''}`}
                  >
                    <div className="flex items-center justify-between text-xs text-muted mb-2">
                      <span className="font-semibold">Passage {idx + 1}</span>
                      {hasWarning && (
                        <span className="badge badge-warning flex items-center gap-1">
                          <AlertTriangle size={12} /> Needs Review
                        </span>
                      )}
                      {isSelected && (
                        <span className="badge badge-success flex items-center gap-1">
                          <Check size={12} /> Selected for Commit
                        </span>
                      )}
                      {isSkipped && (
                        <span className="badge badge-subtle">Skipped (Keep Original)</span>
                      )}
                    </div>

                    <div className="grid grid-cols-2 gap-3 text-xs mb-3">
                      <div className="source-box p-2 bg-surface rounded">
                        <div className="text-muted font-medium mb-1">Original Text:</div>
                        <div className="leading-relaxed">{chunk.source_text}</div>
                      </div>
                      <div className="candidate-box p-2 bg-accent-subtle rounded">
                        <div className="text-accent font-medium mb-1">Modernized Suggestion:</div>
                        <div className="leading-relaxed font-medium">
                          {variant?.candidate_text || 'No candidate generated'}
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center justify-end gap-2">
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm text-xs"
                        onClick={() => handleRedoChunk(chunk.chunk_id)}
                        disabled={retryingChunkId === chunk.chunk_id}
                      >
                        {retryingChunkId === chunk.chunk_id ? (
                          <Loader2 size={12} className="spin mr-1" />
                        ) : (
                          <RotateCcw size={12} className="mr-1" />
                        )}
                        Try Again
                      </button>
                      <button
                        type="button"
                        className={`btn btn-sm text-xs ${isSkipped ? 'btn-secondary' : 'btn-ghost'}`}
                        onClick={() => handleSkipChunk(chunk.chunk_id)}
                      >
                        <SkipForward size={12} className="mr-1" /> Keep Original
                      </button>
                      {variant && (
                        <button
                          type="button"
                          className={`btn btn-sm text-xs ${isSelected ? 'btn-success' : 'btn-primary'}`}
                          onClick={() => handleSelectVariant(chunk.chunk_id, variant.variant_id)}
                        >
                          <Check size={12} className="mr-1" />
                          {isSelected ? 'Selected' : 'Accept Modernized'}
                        </button>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        <div className="drawer-footer flex items-center justify-between">
          <span className="text-xs text-muted">
            {chunks.length > 0
              ? `${chunks.filter(c => c.selected_variant_id).length} of ${chunks.length} candidates selected`
              : 'On-demand tool · Does not block wizard progression'}
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={onClose}
            >
              Close
            </button>
            {chunks.length > 0 && (
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={handleCommit}
                disabled={!canCommit}
              >
                Commit Changes to Chapter
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
