import { useState } from 'react'
import {
  Wand2,
  Play,
  Loader2,
  Check,
  RotateCcw,
  Sparkles,
  Undo2,
  ShieldCheck,
  Zap,
  AlignLeft,
  FileText,
  Link2,
} from 'lucide-react'
import {
  cleanTextOnDemand,
  reflowProse,
  stitchParagraphs,
  resolveProposal,
  cancelTask,
} from '../api'

export default function ChapterStudioToolsPane({
  projectId,
  currentChapterIndex,
  currentChapterTitle,
  currentChapter,
  onChaptersUpdated,
  onSnapshotForUndo,
  onUndoSnapshot,
  canUndoSnapshot = false,
  onAcceptAllProposals,
  onRevertAllProposals,
  modernizationProfiles = [],
  toast,
  hasCloudKey = false,
  cudaEnabled = true,
  localLlmAvailable = false,
}) {
  // Enhancement Scope: 'clean_only' | 'clean_and_modernize'
  const [scope, setScope] = useState('clean_only')

  // Provider: 'llm' (cloud) | 'embedded' (local gpu) | 'regex' (heuristic instant)
  // `selectedProvider` is the user's explicit pick (null = auto). The effective
  // provider falls back to the best available option so it tracks hardware /
  // settings that load after mount, and never points at an unavailable engine.
  const [selectedProvider, setProvider] = useState(null)
  const localGpuAvailable = cudaEnabled && localLlmAvailable
  const isProviderAvailable = (p) =>
    p === 'regex' || (p === 'llm' && hasCloudKey) || (p === 'embedded' && localGpuAvailable)
  const defaultProvider = hasCloudKey ? 'llm' : localGpuAvailable ? 'embedded' : 'regex'
  const provider = selectedProvider && isProviderAvailable(selectedProvider) ? selectedProvider : defaultProvider

  // Profiles
  const [cleaningProfile, setCleaningProfile] = useState('safe')
  const [modernProfile, setModernProfile] = useState('standard_modern')

  // Execution state
  const [busy, setBusy] = useState(false)
  const [statusMsg, setStatusMsg] = useState('')
  const [progressPct, setProgressPct] = useState(0)

  // Calculate pending proposals for current chapter
  const pendingBlocks = currentChapter?.blocks?.filter(b => b.pending_proposal) || []
  const hasPendingProposals = pendingBlocks.length > 0 || Boolean(currentChapter?.pending_proposal)
  const pendingCount = pendingBlocks.length || (currentChapter?.pending_proposal ? 1 : 0)

  // ─── Enhancement Handlers ──────────────────────────────────────────────────
  const handleEnhanceChapter = async () => {
    if (!projectId) return

    if (provider === 'llm' && !hasCloudKey) {
      toast('Cloud LLM requires a Gemini or OpenAI key in Settings.', 'error')
      return
    }
    if (provider === 'embedded' && !localGpuAvailable) {
      toast('Local GPU enhancement is not available in this build. Use Cloud LLM or Rule-based.', 'error')
      return
    }

    onSnapshotForUndo?.()
    setBusy(true)
    setProgressPct(0)
    const isModern = scope === 'clean_and_modernize'
    setStatusMsg(`Enhancing "${currentChapterTitle}" (${isModern ? 'Clean + Modernize' : 'Clean Only'})…`)

    try {
      const res = await cleanTextOnDemand(
        projectId,
        currentChapterIndex,
        provider,
        cleaningProfile,
        isModern,
        modernProfile,
        (task) => {
          if (task) {
            if (typeof task.progress === 'number') {
              setProgressPct(task.progress)
            }
            if (task.message) {
              setStatusMsg(task.message)
            }
          }
        }
      )
      if (res?.chapters) {
        onChaptersUpdated?.(res.chapters)
      }
      toast(res?.message || 'Enhancement proposals generated for chapter.', 'success')
    } catch (err) {
      if (err?.cancelled) {
        toast('Enhancement cancelled.', 'info')
      } else {
        toast(err.message || 'Failed to enhance chapter.', 'error')
      }
    } finally {
      setBusy(false)
      setStatusMsg('')
      setProgressPct(0)
    }
  }

  const handleEnhanceAll = async () => {
    if (!projectId) return
    const isModern = scope === 'clean_and_modernize'
    const confirmMsg = `Run AI Text Enhancement (${isModern ? 'Clean + Modernize' : 'Clean Only'}) across all chapters in the book?`
    if (!window.confirm(confirmMsg)) return

    if (provider === 'llm' && !hasCloudKey) {
      toast('Cloud LLM requires a Gemini or OpenAI key in Settings.', 'error')
      return
    }
    if (provider === 'embedded' && !localGpuAvailable) {
      toast('Local GPU enhancement is not available in this build. Use Cloud LLM or Rule-based.', 'error')
      return
    }

    onSnapshotForUndo?.()
    setBusy(true)
    setProgressPct(0)
    setStatusMsg(`Enhancing whole book…`)

    try {
      const res = await cleanTextOnDemand(
        projectId,
        null,
        provider,
        cleaningProfile,
        isModern,
        modernProfile,
        (task) => {
          if (task) {
            if (typeof task.progress === 'number') {
              setProgressPct(task.progress)
            }
            if (task.message) {
              setStatusMsg(task.message)
            }
          }
        }
      )
      if (res?.chapters) {
        onChaptersUpdated?.(res.chapters)
      }
      toast(res?.message || 'Enhancement proposals generated across all chapters.', 'success')
    } catch (err) {
      if (err?.cancelled) {
        toast('Enhancement cancelled.', 'info')
      } else {
        toast(err.message || 'Failed to enhance book.', 'error')
      }
    } finally {
      setBusy(false)
      setStatusMsg('')
      setProgressPct(0)
    }
  }

  const handleCancelEnhance = async () => {
    try {
      await cancelTask(projectId)
      toast('Cancelling enhancement…', 'info')
    } catch (err) {
      toast(err.message || 'Failed to cancel', 'error')
    }
  }

  const handleReflowChapter = async () => {
    if (!projectId) return
    onSnapshotForUndo?.()
    setBusy(true)
    setStatusMsg(`Reflowing wrapped lines for "${currentChapterTitle}"…`)
    try {
      const res = await reflowProse(projectId, currentChapterIndex)
      if (res?.chapters) {
        onChaptersUpdated?.(res.chapters)
      }
      toast(res?.message || 'Prose reflowed successfully.', 'success')
    } catch (err) {
      toast(err.message || 'Failed to reflow prose.', 'error')
    } finally {
      setBusy(false)
      setStatusMsg('')
    }
  }

  const handleReflowAll = async () => {
    if (!projectId) return
    if (!window.confirm('Reflow wrapped lines and fix soft hyphens across all chapters in the book? Any verse blocks will stay untouched.')) return
    onSnapshotForUndo?.()
    setBusy(true)
    setStatusMsg('Reflowing wrapped lines across all chapters…')
    try {
      const res = await reflowProse(projectId, null)
      if (res?.chapters) {
        onChaptersUpdated?.(res.chapters)
      }
      toast(res?.message || 'Prose reflowed for whole book.', 'success')
    } catch (err) {
      toast(err.message || 'Failed to reflow prose.', 'error')
    } finally {
      setBusy(false)
      setStatusMsg('')
    }
  }

  const handleStitchChapter = async () => {
    if (!projectId) return
    if (hasPendingProposals) {
      toast('Please accept or revert pending AI proposals before stitching paragraphs.', 'error')
      return
    }
    onSnapshotForUndo?.()
    setBusy(true)
    setStatusMsg(`Stitching broken paragraphs for "${currentChapterTitle}"…`)
    try {
      const res = await stitchParagraphs(projectId, currentChapterIndex)
      if (res?.chapters) {
        onChaptersUpdated?.(res.chapters)
      }
      toast(res?.message || 'Paragraphs stitched successfully.', 'success')
    } catch (err) {
      toast(err.message || 'Failed to stitch paragraphs.', 'error')
    } finally {
      setBusy(false)
      setStatusMsg('')
    }
  }

  const handleStitchAll = async () => {
    if (!projectId) return
    if (hasPendingProposals) {
      toast('Please accept or revert pending AI proposals before stitching paragraphs.', 'error')
      return
    }
    if (!window.confirm('Stitch broken paragraphs across page breaks across all chapters in the book?')) return
    onSnapshotForUndo?.()
    setBusy(true)
    setStatusMsg('Stitching broken paragraphs across all chapters…')
    try {
      const res = await stitchParagraphs(projectId, null)
      if (res?.chapters) {
        onChaptersUpdated?.(res.chapters)
      }
      toast(res?.message || 'Paragraphs stitched for whole book.', 'success')
    } catch (err) {
      toast(err.message || 'Failed to stitch paragraphs.', 'error')
    } finally {
      setBusy(false)
      setStatusMsg('')
    }
  }

  return (
    <div className="studio-tools-pane">
      {/* Undo Banner if snapshot exists */}
      {canUndoSnapshot && onUndoSnapshot && (
        <div className="tools-undo-banner">
          <span className="flex items-center gap-1.5">
            <Sparkles size={14} className="text-accent" /> Text updated
          </span>
          <button
            type="button"
            className="btn-undo"
            onClick={onUndoSnapshot}
            title="Revert chapter to previous state"
          >
            <Undo2 size={12} /> Undo
          </button>
        </div>
      )}

      {/* CARD 1: PENDING TRACK CHANGES REVIEW CARD */}
      {hasPendingProposals && (
        <div className="tools-card" style={{ borderColor: 'rgba(99, 102, 241, 0.5)', background: 'rgba(20, 24, 40, 0.95)' }}>
          <div className="tools-card-header">
            <div className="tools-card-title">
              <Sparkles size={16} className="text-accent animate-pulse" />
              <span>Pending Review</span>
            </div>
            <span className="tools-badge amber">
              {pendingCount} proposal{pendingCount > 1 ? 's' : ''}
            </span>
          </div>
          <p className="tools-card-desc">
            You have in-text track changes waiting in this chapter. Review individual passages inline or accept/revert all below.
          </p>
          <div className="tools-actions-row" style={{ marginTop: '10px' }}>
            <button
              type="button"
              className="tools-btn-run"
              style={{ background: '#059669', borderColor: '#10b981' }}
              onClick={onAcceptAllProposals}
            >
              <Check size={14} /> Accept All
            </button>
            <button
              type="button"
              className="tools-btn-secondary"
              style={{ color: '#f87171', borderColor: 'rgba(239, 68, 68, 0.3)' }}
              onClick={onRevertAllProposals}
            >
              <RotateCcw size={14} /> Revert All
            </button>
          </div>
        </div>
      )}

      {/* CARD 2: UNIFIED AI TEXT ENHANCEMENT */}
      <div className="tools-card" data-tip-anchor="tools-ai-enhancement">
        <div className="tools-card-header">
          <div className="tools-card-title">
            <Wand2 size={16} className="text-accent" />
            <span>AI Text Enhancement</span>
          </div>
          <span className={`tools-badge ${hasCloudKey || localGpuAvailable ? 'green' : 'muted'}`}>
            {hasCloudKey ? '● Cloud LLM' : localGpuAvailable ? '● Local GPU' : '● Regex Mode'}
          </span>
        </div>

        <p className="tools-card-desc">
          Cleans OCR glitches, rejoins hyphenated breaks, and updates archaic prose into natural narration in a single pass.
        </p>

        {/* Scope Segmented Control */}
        <div className="tools-field-group">
          <div className="tools-field-label">Enhancement Scope:</div>
          <div className="tools-pills-row" style={{ width: '100%' }}>
            <button
              type="button"
              className={`tools-pill ${scope === 'clean_only' ? 'active' : ''}`}
              style={{ flex: 1, textAlign: 'center' }}
              onClick={() => setScope('clean_only')}
            >
              <ShieldCheck size={12} className="mr-1 inline" /> Clean Only
            </button>
            <button
              type="button"
              className={`tools-pill ${scope === 'clean_and_modernize' ? 'active' : ''}`}
              style={{ flex: 1, textAlign: 'center' }}
              onClick={() => setScope('clean_and_modernize')}
            >
              <Sparkles size={12} className="mr-1 inline" /> Clean + Modernize
            </button>
          </div>
        </div>

        {/* Modernization Rigor (if scope includes modernize) */}
        {scope === 'clean_and_modernize' && (
          <div className="tools-field-group" data-tip-anchor="modernization-review">
            <div className="tools-field-label">Modernization Rigor:</div>
            <div className="tools-pills-row">
              {[
                { id: 'light', label: 'Light', tip: 'Archaic pronouns & verb endings only (thou/thee, hath/doth)' },
                { id: 'standard_modern', label: 'Standard', tip: 'Pronouns + modern sentence flow and vocabulary' },
                { id: 'deep', label: 'Deep', tip: 'Full contemporary prose restructuring' },
              ].map(r => (
                <button
                  key={r.id}
                  type="button"
                  className={`tools-pill ${modernProfile === r.id ? 'active' : ''}`}
                  onClick={() => setModernProfile(r.id)}
                  title={r.tip}
                >
                  {r.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* OCR Cleaning Profile */}
        <div className="tools-field-group">
          <div className="tools-field-label">OCR Clean Level:</div>
          <div className="tools-pills-row">
            {[
              { id: 'safe', label: 'Safe', tip: 'Minimal alteration, repairs hyphens and soft breaks' },
              { id: 'balanced', label: 'Balanced', tip: 'Fixes punctuation and common OCR substitutions' },
              { id: 'aggressive', label: 'Aggressive', tip: 'Strongest repair of damaged scans' },
            ].map(p => (
              <button
                key={p.id}
                type="button"
                className={`tools-pill ${cleaningProfile === p.id ? 'active' : ''}`}
                onClick={() => setCleaningProfile(p.id)}
                title={p.tip}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        {/* Provider Selector */}
        <div className="tools-field-group">
          <div className="tools-field-label">Engine / Provider:</div>
          <div className="tools-pills-row">
            {hasCloudKey && (
              <button
                type="button"
                className={`tools-pill ${provider === 'llm' ? 'active' : ''}`}
                onClick={() => setProvider('llm')}
                title="Use configured Gemini / OpenAI cloud API key"
              >
                Cloud LLM
              </button>
            )}
            {localGpuAvailable && (
              <button
                type="button"
                className={`tools-pill ${provider === 'embedded' ? 'active' : ''}`}
                onClick={() => setProvider('embedded')}
                title="Use local GPU embedded model"
              >
                Local GPU
              </button>
            )}
            <button
              type="button"
              className={`tools-pill ${provider === 'regex' ? 'active' : ''}`}
              onClick={() => setProvider('regex')}
              title="Instant rule-based cleaning (offline, zero-GPU)"
            >
              <Zap size={11} className="mr-0.5 inline" /> Rule-based
            </button>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="tools-actions-row">
          <button
            type="button"
            className="tools-btn-run"
            onClick={handleEnhanceChapter}
            disabled={busy}
          >
            {busy ? <Loader2 size={14} className="spin" /> : <Play size={14} />}
            Enhance Chapter
          </button>
          <button
            type="button"
            className="tools-btn-secondary"
            onClick={handleEnhanceAll}
            disabled={busy}
            title="Run enhancement across all chapters in this book"
          >
            Whole Book
          </button>
        </div>

        {busy && (
          <div className="tools-progress-card">
            <div className="tools-progress-header">
              <div className="tools-progress-status">
                <Loader2 size={13} className="spin text-accent" />
                <span className="tools-progress-title truncate">{statusMsg || 'Enhancing text…'}</span>
              </div>
              <span className="tools-progress-pct">{progressPct}%</span>
            </div>

            <div className="tools-progress-track">
              <div
                className="tools-progress-fill"
                style={{ width: `${Math.max(4, Math.min(100, progressPct))}%` }}
              />
            </div>

            <div className="tools-progress-footer">
              <span className="tools-progress-meta">
                {provider === 'llm' ? '● Cloud LLM' : provider === 'embedded' ? '● Local GPU' : '● Rule-based'}
              </span>
              <button
                type="button"
                className="tools-cancel-btn"
                onClick={handleCancelEnhance}
                title="Cancel text enhancement"
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>

      {/* CARD 3: PROSE REFLOW & DEHYPHENATION */}
      <div className="tools-card" data-tip-anchor="tools-prose-reflow">
        <div className="tools-card-header">
          <div className="tools-card-title">
            <AlignLeft size={16} className="text-accent" />
            <span>Reflow Wrapped Lines & Hyphens</span>
          </div>
          <span className="tools-badge muted">1-Click Fast</span>
        </div>

        <p className="tools-card-desc">
          Unifies broken linebreaks into continuous prose sentences and repairs split hyphens (e.g. <em>fortifica- tion</em> &rarr; <em>fortification</em>). Any verse blocks stay intact.
        </p>

        <div className="tools-actions-row">
          <button
            type="button"
            className="tools-btn-run"
            onClick={handleReflowChapter}
            disabled={busy}
            title="Reflow wrapped lines in current chapter"
          >
            {busy ? <Loader2 size={14} className="spin" /> : <AlignLeft size={14} />}
            Reflow Chapter
          </button>
          <button
            type="button"
            className="tools-btn-secondary"
            onClick={handleReflowAll}
            disabled={busy}
            title="Reflow wrapped lines across all chapters in this book"
          >
            Whole Book
          </button>
        </div>
      </div>

      {/* CARD 4: STITCH SPLIT PARAGRAPHS */}
      <div className="tools-card" data-tip-anchor="tools-stitch-paragraphs">
        <div className="tools-card-header">
          <div className="tools-card-title">
            <Link2 size={16} className="text-accent" />
            <span>Stitch Split Paragraphs</span>
          </div>
          <span className="tools-badge muted">Cross-Page</span>
        </div>

        <p className="tools-card-desc">
          Detects and merges paragraphs severed across page breaks or column boundaries, healing broken sentences before AI enhancement.
        </p>

        <div className="tools-actions-row">
          <button
            type="button"
            className="tools-btn-run"
            onClick={handleStitchChapter}
            disabled={busy || hasPendingProposals}
            title={hasPendingProposals ? "Accept or revert pending proposals first" : "Stitch broken paragraphs in current chapter"}
          >
            {busy ? <Loader2 size={14} className="spin" /> : <Link2 size={14} />}
            Stitch Chapter
          </button>
          <button
            type="button"
            className="tools-btn-secondary"
            onClick={handleStitchAll}
            disabled={busy || hasPendingProposals}
            title={hasPendingProposals ? "Accept or revert pending proposals first" : "Stitch broken paragraphs across all chapters in this book"}
          >
            Whole Book
          </button>
        </div>
      </div>
    </div>
  )
}
