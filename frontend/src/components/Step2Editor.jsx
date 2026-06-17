import { useState, useEffect, useRef, useCallback } from 'react'
import { getProject, updateProject, getChapters, saveChapters, uploadCover, getDebugChapters, getDebugPrompt, getCleaningEval, saveCleaningEval, getCleaningProfiles, redoCleaningChunk, applyCleaningVariant, batchRedoCleaning, getCleaningReport } from '../api'

export default function Step2Editor({ projectId, isActive, onNext, onBack, toast, debugMode = false }) {
  const [meta, setMeta] = useState({ title: '', author: '', cover_image: null })
  const [chapters, setChapters] = useState([])
  const [selectedIdx, setSelectedIdx] = useState(0)
  const [saving, setSaving] = useState(false)
  const [saveStatus, setSaveStatus] = useState('saved')
  const [loading, setLoading] = useState(true)
  const [debugComparison, setDebugComparison] = useState(null)
  const [showHeuristic, setShowHeuristic] = useState(false)
  const [debugPrompt, setDebugPrompt] = useState(null)
  const [cleaningEval, setCleaningEval] = useState(null)
  const [cleaningProfiles, setCleaningProfiles] = useState([])
  const [retryProfile, setRetryProfile] = useState('balanced')
  const [retryingChunk, setRetryingChunk] = useState(null)
  const [batchRetrying, setBatchRetrying] = useState(false)
  const [reviewFilter, setReviewFilter] = useState('all')
  const [comparison, setComparison] = useState(null)
  const [cleaningReport, setCleaningReport] = useState(null)
  const [showPromptModal, setShowPromptModal] = useState(false)
  const coverRef = useRef()
  const textareaRef = useRef()
  const dirtyRef = useRef(false)
  const dirtyVersionRef = useRef(0)

  useEffect(() => {
    if (!projectId) {
      // Resetting all state when the project is cleared — batched by React 18
      /* eslint-disable react-hooks/set-state-in-effect */
      setMeta({ title: '', author: '', cover_image: null })
      setChapters([])
      setSelectedIdx(0)
      setLoading(true)
      setCleaningEval(null)
      setComparison(null)
      setCleaningReport(null)
      setSaveStatus('saved')
      dirtyRef.current = false
      dirtyVersionRef.current = 0
      /* eslint-enable react-hooks/set-state-in-effect */
      return
    }
    if (!isActive) return // Don't fetch if not active
    
    setLoading(true)
    Promise.all([
      getProject(projectId),
      getChapters(projectId),
      debugMode ? getDebugChapters(projectId).catch(() => null) : Promise.resolve(null),
      debugMode ? getDebugPrompt(projectId).catch(() => null) : Promise.resolve(null),
      getCleaningEval(projectId).catch(() => null),
      getCleaningProfiles().catch(() => []),
    ])
      .then(([p, chs, dbg, prompt, evalReport, profiles]) => {
        setMeta({ title: p.title, author: p.author, cover_image: p.cover_image })
        setChapters(chs)
        setDebugComparison(dbg ?? null)
        setDebugPrompt(prompt ?? null)
        setCleaningEval(evalReport ?? null)
        setCleaningProfiles(profiles ?? [])
        setSaveStatus('saved')
        dirtyRef.current = false
        dirtyVersionRef.current = 0
        if (!dbg) setShowHeuristic(false)
      })
      .catch(e => toast(e.message, 'error'))
      .finally(() => setLoading(false))
  }, [projectId, isActive, toast, debugMode])

  const markDirty = useCallback(() => {
    dirtyRef.current = true
    dirtyVersionRef.current += 1
    setSaveStatus('dirty')
  }, [])

  const updateChapter = (idx, field, value) => {
    markDirty()
    setChapters(prev => prev.map((ch, i) => i === idx ? { ...ch, [field]: value } : ch))
  }

  const updateMeta = (updates) => {
    markDirty()
    setMeta(prev => ({ ...prev, ...updates }))
  }

  const reindexChapterEvals = (chapterEvals) => chapterEvals
    .slice()
    .sort((a, b) => (a.chapter_index ?? 0) - (b.chapter_index ?? 0))
    .map((chapterEval, index) => ({ ...chapterEval, chapter_index: index }))

  const reindexChunkIds = (chunks) => (chunks || []).map((chunk, index) => ({ ...chunk, chunk_id: index }))

  const mergeChapterEvals = (targetEval, deletedEval, deletedBeforeTarget) => {
    if (!targetEval) return null
    if (!deletedEval) return targetEval

    const targetChunks = targetEval.chunks || []
    const deletedChunks = deletedEval.chunks || []
    const chunks = reindexChunkIds(deletedBeforeTarget
      ? [...deletedChunks, ...targetChunks]
      : [...targetChunks, ...deletedChunks])
    const fallbackCount = chunks.filter(chunk => chunk.status === 'fallback').length

    return {
      ...targetEval,
      chunk_count: chunks.length,
      accepted_count: chunks.length - fallbackCount,
      fallback_count: fallbackCount,
      chunks,
    }
  }

  const syncCleaningEvalAfterDelete = (deletedIndex) => {
    markDirty()
    setCleaningEval(prev => {
      if (!prev?.chapters?.length) return prev
      const targetIndex = deletedIndex === 0 ? 1 : deletedIndex - 1
      const deletedEval = prev.chapters.find(chapterEval => chapterEval.chapter_index === deletedIndex)
      const updatedChapters = prev.chapters
        .filter(chapterEval => chapterEval.chapter_index !== deletedIndex)
        .map(chapterEval => {
          if (chapterEval.chapter_index !== targetIndex) return chapterEval
          return mergeChapterEvals(chapterEval, deletedEval, deletedIndex === 0) || chapterEval
        })
      return { ...prev, chapters: reindexChapterEvals(updatedChapters) }
    })
    setComparison(null)
    setCleaningReport(null)
  }

  const syncCleaningEvalAfterMove = (idx, next) => {
    markDirty()
    setCleaningEval(prev => {
      if (!prev?.chapters?.length) return prev
      return {
        ...prev,
        chapters: prev.chapters.map(chapterEval => {
          if (chapterEval.chapter_index === idx) return { ...chapterEval, chapter_index: next }
          if (chapterEval.chapter_index === next) return { ...chapterEval, chapter_index: idx }
          return chapterEval
        }).sort((a, b) => (a.chapter_index ?? 0) - (b.chapter_index ?? 0)),
      }
    })
    setComparison(null)
    setCleaningReport(null)
  }

  const syncCleaningEvalAfterSplit = (splitIndex) => {
    markDirty()
    setCleaningEval(prev => {
      if (!prev?.chapters?.length) return prev
      return {
        ...prev,
        chapters: prev.chapters
          .filter(chapterEval => chapterEval.chapter_index !== splitIndex)
          .map(chapterEval => (
            chapterEval.chapter_index > splitIndex
              ? { ...chapterEval, chapter_index: chapterEval.chapter_index + 1 }
              : chapterEval
          )),
      }
    })
    setComparison(null)
    setCleaningReport(null)
  }

  const deleteChapter = (idx) => {
    if (chapters.length <= 1) { toast('Cannot delete the last chapter.', 'error'); return }
    
    setChapters(prev => {
      const updated = [...prev]
      const toDelete = updated[idx]
      
      if (idx === 0) {
        // Merge to the top of next chapter
        updated[1].text = `${toDelete.text}\n\n${updated[1].text}`.trim()
      } else {
        // Merge to the bottom of previous chapter
        updated[idx - 1].text = `${updated[idx - 1].text}\n\n${toDelete.text}`.trim()
      }
      
      return updated.filter((_, i) => i !== idx)
    })
    syncCleaningEvalAfterDelete(idx)
    setSelectedIdx(i => Math.min(i, chapters.length - 2))
  }

  const moveChapter = (idx, dir) => {
    const next = idx + dir
    if (next < 0 || next >= chapters.length) return
    setChapters(prev => {
      const a = [...prev]
      ;[a[idx], a[next]] = [a[next], a[idx]]
      return a
    })
    syncCleaningEvalAfterMove(idx, next)
    setSelectedIdx(next)
  }

  const splitAtCursor = () => {
    const textarea = textareaRef.current
    if (!textarea) return
    const pos = textarea.selectionStart
    const ch = chapters[selectedIdx]
    const before = ch.text.slice(0, pos).trim()
    const after = ch.text.slice(pos).trim()
    if (!after) { toast('No text after cursor to split.', 'error'); return }
    const updated = [...chapters]
    updated[selectedIdx] = { ...ch, text: before }
    updated.splice(selectedIdx + 1, 0, { title: `${ch.title} (cont.)`, text: after, audio_path: null })
    markDirty()
    setChapters(updated)
    syncCleaningEvalAfterSplit(selectedIdx)
    toast('Chapter split at cursor.', 'success')
  }

  const handleSave = useCallback(async (showToast = true) => {
    const saveVersion = dirtyVersionRef.current
    setSaving(true)
    setSaveStatus('saving')
    try {
      await Promise.all([
        saveChapters(projectId, chapters),
        updateProject(projectId, { title: meta.title, author: meta.author }),
        cleaningEval ? saveCleaningEval(projectId, cleaningEval) : Promise.resolve(),
      ])
      if (dirtyVersionRef.current === saveVersion) {
        dirtyRef.current = false
        setSaveStatus('saved')
      } else {
        setSaveStatus('dirty')
      }
      if (showToast) toast('Saved!', 'success')
    } catch (e) {
      setSaveStatus('failed')
      toast(e.message, 'error')
    } finally {
      setSaving(false)
    }
  }, [projectId, chapters, meta.title, meta.author, cleaningEval, toast])

  useEffect(() => {
    if (!projectId || !isActive || !dirtyRef.current || saveStatus !== 'dirty') return
    const timer = setTimeout(() => {
      if (dirtyRef.current) handleSave(false)
    }, 1200)
    return () => clearTimeout(timer)
  }, [projectId, isActive, saveStatus, chapters, meta, cleaningEval, handleSave])

  const handleCoverUpload = async (e) => {
    const f = e.target.files[0]
    if (!f) return
    try {
      const res = await uploadCover(projectId, f)
      setMeta(m => ({ ...m, cover_image: res.cover_image }))
      setSaveStatus('saved')
      toast('Cover uploaded!', 'success')
    } catch (e) {
      toast(e.message, 'error')
    }
  }

  const handleNext = async () => {
    await handleSave()
    onNext()
  }

  const handleRedoChunk = async (chunk) => {
    const chapterIndex = chunk.chapter_index ?? selectedIdx
    const retryKey = `${chapterIndex}:${chunk.chunk_id}`
    setRetryingChunk(retryKey)
    try {
      const res = await redoCleaningChunk(projectId, chapterIndex, chunk.chunk_id, retryProfile)
      setCleaningEval(res.evaluation)
      markDirty()
      setComparison({ chapter_index: chapterIndex, chunk: { ...res.chunk, chapter_index: chapterIndex }, variant: res.variant })
      toast('Chunk retry complete.', 'success')
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setRetryingChunk(null)
    }
  }

  const chunkNeedsReview = (chunk) => (
    chunk.status === 'fallback' ||
    chunk.risk_level === 'high' ||
    chunk.integrity_issues?.length > 0 ||
    (chunk.metrics?.anchor_required && chunk.metrics.anchor_matches < chunk.metrics.anchor_required)
  )

  const chunkMatchesFilter = (chunk) => {
    if (reviewFilter === 'fallbacks') return chunk.status === 'fallback'
    if (reviewFilter === 'warnings') return chunkNeedsReview(chunk)
    if (reviewFilter === 'large_delta') return Math.abs((chunk.metrics?.word_count_ratio ?? 1) - 1) > 0.15
    if (reviewFilter === 'missing_anchors') return (chunk.metrics?.anchor_required ?? 0) > (chunk.metrics?.anchor_matches ?? 0)
    if (reviewFilter === 'variants') return (chunk.variants?.length ?? 0) > 0
    return true
  }

  const handleBatchRedoVisible = async (chunks) => {
    if (!chunks.length) return
    setBatchRetrying(true)
    try {
      const payload = chunks.map(chunk => ({ chapter_index: chunk.chapter_index ?? selectedIdx, chunk_id: chunk.chunk_id }))
      const res = await batchRedoCleaning(projectId, payload, retryProfile)
      setCleaningEval(res.evaluation)
      markDirty()
      const failed = res.results?.filter(result => !result.ok)?.length ?? 0
      toast(failed ? `Batch retry finished with ${failed} issue(s).` : `Retried ${payload.length} chunk(s).`, failed ? 'warning' : 'success')
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setBatchRetrying(false)
    }
  }

  const applyComparisonVariant = async () => {
    if (!comparison?.chunk || !comparison?.variant) return
    const chapterIndex = comparison.chapter_index ?? comparison.chunk.chapter_index ?? selectedIdx
    let applyResult
    try {
      applyResult = await applyCleaningVariant(
        projectId,
        chapterIndex,
        comparison.chunk.chunk_id,
        comparison.variant.variant_id,
        false,
      )
      setCleaningEval(applyResult.evaluation)
      markDirty()
    } catch (e) {
      toast(e.message, 'error')
      return
    }
    const currentChunkText = applyResult.previous_text || comparison.chunk.accepted_text || comparison.chunk.source_text || ''
    const candidateText = applyResult.replacement_text || comparison.variant.accepted_text || comparison.variant.candidate_text || ''
    if (!candidateText.trim()) {
      toast('The selected candidate is empty.', 'error')
      return
    }
    setChapters(prev => prev.map((chapter, i) => {
      if (i !== chapterIndex) return chapter
      const currentText = chapter.text || ''
      if (currentChunkText && currentText.includes(currentChunkText)) {
        return { ...chapter, text: currentText.replace(currentChunkText, candidateText) }
      }
      return { ...chapter, text: `${currentText.trim()}\n\n${candidateText}`.trim() }
    }))
    setComparison(null)
    toast('Candidate applied to the chapter editor. Save to keep it.', 'success')
  }

  const handleApplyLowRiskCandidates = async (chunks) => {
    const chapterIndex = chunks[0]?.chapter_index ?? selectedIdx
    const lowRisk = chunks
      .map(chunk => ({ chunk, variant: (chunk.variants || []).slice().reverse().find(variant => variant.risk_level === 'low' && !(variant.integrity_issues?.length)) }))
      .filter(item => item.variant && !item.variant.is_applied)
    if (!lowRisk.length) return

    try {
      let latestEval = cleaningEval
      let updatedChapterText = chapters[chapterIndex]?.text || ''
      for (const item of lowRisk) {
        const res = await applyCleaningVariant(projectId, item.chunk.chapter_index ?? chapterIndex, item.chunk.chunk_id, item.variant.variant_id, false)
        latestEval = res.evaluation
        const previousText = res.previous_text || item.chunk.accepted_text || item.chunk.source_text || ''
        const replacementText = res.replacement_text || item.variant.accepted_text || item.variant.candidate_text || ''
        if (previousText && updatedChapterText.includes(previousText)) {
          updatedChapterText = updatedChapterText.replace(previousText, replacementText)
        }
      }
      setCleaningEval(latestEval)
      updateChapter(chapterIndex, 'text', updatedChapterText)
      markDirty()
      toast(`Applied ${lowRisk.length} low-risk candidate(s). Save to keep them.`, 'success')
    } catch (e) {
      toast(e.message, 'error')
    }
  }

  const handleLoadCleaningReport = async () => {
    try {
      const report = await getCleaningReport(projectId)
      setCleaningReport(report)
    } catch (e) {
      toast(e.message, 'error')
    }
  }

  if (loading) return <div className="step-card"><div className="text-secondary">Loading…</div></div>

  const ch = chapters[selectedIdx]
  const getChapterEval = (chapterIndex) => cleaningEval?.chapters?.find(chEval => chEval.chapter_index === chapterIndex)
  const selectedEval = getChapterEval(selectedIdx)
  const hasCleaningEval = cleaningEval?.chapters?.length > 0
  const formatRatio = (value) => `${Math.round((value ?? 1) * 100)}%`
  const visibleReviewChunks = selectedEval?.chunks?.map(chunk => ({
    ...chunk,
    chapter_index: selectedEval.chapter_index,
  })).filter(chunkMatchesFilter) ?? []
  const fallbackVisibleChunks = visibleReviewChunks.filter(chunk => chunk.status === 'fallback')
  const lowRiskVisibleChunks = visibleReviewChunks.filter(chunk => (chunk.variants || []).some(variant => variant.risk_level === 'low' && !(variant.integrity_issues?.length) && !variant.is_applied))
  const filterOptions = [
    ['all', 'All'],
    ['fallbacks', 'Fallbacks'],
    ['warnings', 'Warnings'],
    ['large_delta', 'Delta'],
    ['missing_anchors', 'Anchors'],
    ['variants', 'Variants'],
  ]
  const riskColor = (risk) => risk === 'low' ? 'var(--success)' : risk === 'high' ? 'var(--danger)' : 'var(--warning, #f59e0b)'

  return (
    <div className="step-card" style={{ padding: 0, overflow: 'hidden' }}>
      {/* Toolbar */}
      <div className="flex items-center justify-between p-4" style={{ borderBottom: '1px solid var(--glass-border)' }}>
        <div>
          <div className="step-title">Edit Chapters</div>
          <div className="step-desc">{chapters.length} chapter{chapters.length !== 1 ? 's' : ''} · Click a chapter to edit</div>
        </div>
        <div className="flex gap-2">
          <span className={`save-status save-status-${saveStatus}`}>
            {saving ? 'Saving...' : saveStatus === 'dirty' ? 'Unsaved changes' : saveStatus === 'failed' ? 'Save failed' : 'Saved'}
          </span>
          {debugPrompt && (
            <button className="btn btn-ghost btn-sm" onClick={() => setShowPromptModal(true)} title="View prompt sent to LLM">
              🔬 View Prompt
            </button>
          )}
          <button className="btn btn-ghost btn-sm" data-tip-anchor="split-button" onClick={splitAtCursor} title="Split chapter at cursor position">
            ✂ Split Here
          </button>
        </div>
      </div>

      <div className="flex" style={{ height: 'calc(100vh - 360px)', minHeight: 420 }}>
        {/* Chapter list */}
        <div style={{
          width: 240, flexShrink: 0,
          borderRight: '1px solid var(--glass-border)',
          overflowY: 'auto', padding: '12px 0',
        }} data-tip-anchor="chapter-list">
          {/* Debug comparison tab toggle */}
          {debugComparison && (
            <div className="flex" style={{ borderBottom: '1px solid var(--glass-border)', marginBottom: 8, padding: '0 12px 8px' }}>
              <button
                className={`btn btn-sm ${!showHeuristic ? 'btn-primary' : 'btn-ghost'}`}
                style={{ flex: 1, fontSize: 11, padding: '3px 6px' }}
                onClick={() => setShowHeuristic(false)}
              >LLM Reviewed</button>
              <button
                className={`btn btn-sm ${showHeuristic ? 'btn-primary' : 'btn-ghost'}`}
                style={{ flex: 1, fontSize: 11, padding: '3px 6px', marginLeft: 4 }}
                onClick={() => setShowHeuristic(true)}
              >Heuristic</button>
            </div>
          )}

          {showHeuristic && debugComparison ? (
            // Read-only heuristic snapshot
            <>
              <div className="text-xs text-muted" style={{ padding: '0 12px 6px', fontStyle: 'italic' }}>
                {debugComparison.method === 'toc' ? '📑 Embedded TOC' : '🔍 Layout heuristic'} · {debugComparison.chapters.length} chapters
              </div>
              {debugComparison.chapters.map((ch, i) => (
                <div key={i} style={{ padding: '8px 12px', borderLeft: '2px solid transparent' }}>
                  <div className="text-sm truncate" style={{ fontWeight: 500 }}>
                    {ch.title || `Chapter ${i + 1}`}
                  </div>
                  <div className="text-xs text-muted">{ch.char_count?.toLocaleString()} chars · {Math.round((ch.confidence ?? 1) * 100)}% conf</div>
                  {ch.snippet && (
                    <div className="text-xs text-muted" style={{ marginTop: 2, fontStyle: 'italic', overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
                      {ch.snippet}
                    </div>
                  )}
                </div>
              ))}
            </>
          ) : (
          <>
          {chapters.map((ch, i) => (
            <div
              key={i}
              className="flex items-center gap-2"
              style={{
                padding: '8px 12px',
                background: i === selectedIdx ? 'rgba(99,102,241,0.12)' : 'transparent',
                borderLeft: i === selectedIdx ? '2px solid var(--accent-primary)' : '2px solid transparent',
                cursor: 'pointer',
              }}
              onClick={() => setSelectedIdx(i)}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="truncate text-sm flex items-center gap-1" style={{ fontWeight: i === selectedIdx ? 600 : 400 }}>
                  {ch.title || `Chapter ${i + 1}`}
                </div>
                <div className="text-xs text-muted">{ch.text?.length ?? 0} chars</div>
                {(getChapterEval(i)?.fallback_count ?? 0) > 0 && (
                  <div className="text-xs" style={{ color: 'var(--warning, #f59e0b)', marginTop: 2 }}>
                    {getChapterEval(i).fallback_count} fallback chunk{getChapterEval(i).fallback_count === 1 ? '' : 's'}
                  </div>
                )}
              </div>
              <div className="flex flex-col gap-1">
                <button className="btn btn-ghost btn-icon" style={{ padding: '2px 4px', fontSize: 10 }}
                  onClick={e => { e.stopPropagation(); moveChapter(i, -1) }}>▲</button>
                <button className="btn btn-ghost btn-icon" style={{ padding: '2px 4px', fontSize: 10 }}
                  onClick={e => { e.stopPropagation(); moveChapter(i, 1) }}>▼</button>
              </div>
              <button
                className="btn btn-ghost btn-icon"
                style={{ padding: '2px 5px', fontSize: 11, color: 'var(--danger)' }}
                onClick={e => { e.stopPropagation(); deleteChapter(i) }}
              >✕</button>
            </div>
          ))}
          </>
          )}
        </div>

        {/* Editor panel */}
        <div className="flex flex-col" style={{ flex: 1, overflow: 'hidden' }}>
          {ch ? (
            <>
              <div className="p-3" style={{ borderBottom: '1px solid var(--glass-border)' }}>
                <input
                  type="text"
                  value={ch.title}
                  onChange={e => updateChapter(selectedIdx, 'title', e.target.value)}
                  placeholder="Chapter title"
                  autoComplete="off"
                  style={{ fontWeight: 600, fontSize: 15 }}
                />
              </div>
              <textarea
                ref={textareaRef}
                value={ch.text}
                onChange={e => updateChapter(selectedIdx, 'text', e.target.value)}
                placeholder="Chapter text…"
                style={{
                  flex: 1, resize: 'none', border: 'none', borderRadius: 0,
                  background: 'transparent', padding: '16px',
                  fontFamily: 'var(--font-mono)', fontSize: 13, lineHeight: 1.7,
                }}
              />
            </>
          ) : (
            <div className="text-center text-muted p-6">Select a chapter to edit</div>
          )}
        </div>

        {/* Metadata sidebar */}
        <div style={{
          width: 220, flexShrink: 0,
          borderLeft: '1px solid var(--glass-border)',
          padding: 16, overflowY: 'auto',
        }} data-tip-anchor="metadata-sidebar">
          {hasCleaningEval && (
            <div data-tip-anchor="cleaning-review" style={{ marginBottom: 18, paddingBottom: 16, borderBottom: '1px solid var(--glass-border)' }}>
              <div className="section-title">Cleaning Review</div>
              <div className="text-xs text-muted mb-2">
                {cleaningEval.provider || 'heuristic'} · {cleaningEval.profile || 'heuristic'} · {selectedEval?.title || ch?.title || `Chapter ${selectedIdx + 1}`}
              </div>
              {cleaningProfiles.length > 0 && (
                <div className="field" style={{ marginBottom: 10 }}>
                  <label style={{ fontSize: 11 }}>Retry Profile</label>
                  <select value={retryProfile} onChange={e => setRetryProfile(e.target.value)} style={{ fontSize: 12 }}>
                    {cleaningProfiles.map(profile => (
                      <option key={profile.id} value={profile.id}>{profile.label}</option>
                    ))}
                  </select>
                </div>
              )}
              {selectedEval ? (
                <>
                  <div className="flex gap-2" style={{ marginBottom: 10 }}>
                    <div className="glass" style={{ flex: 1, padding: 8, borderRadius: 'var(--radius-sm)' }}>
                      <div className="text-xs text-muted">Accepted</div>
                      <div style={{ fontWeight: 700 }}>{selectedEval.accepted_count}</div>
                    </div>
                    <div className="glass" style={{ flex: 1, padding: 8, borderRadius: 'var(--radius-sm)' }}>
                      <div className="text-xs text-muted">Fallback</div>
                      <div style={{ fontWeight: 700, color: selectedEval.fallback_count ? 'var(--warning, #f59e0b)' : 'inherit' }}>{selectedEval.fallback_count}</div>
                    </div>
                  </div>
                  <div className="flex gap-1" style={{ flexWrap: 'wrap', marginBottom: 8 }}>
                    {filterOptions.map(([value, label]) => (
                      <button
                        key={value}
                        type="button"
                        className={`btn btn-sm ${reviewFilter === value ? 'btn-primary' : 'btn-ghost'}`}
                        style={{ fontSize: 10, padding: '3px 6px' }}
                        onClick={() => setReviewFilter(value)}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                  <div className="flex gap-2" style={{ marginBottom: 10 }}>
                    <button
                      className="btn btn-ghost btn-sm"
                      style={{ flex: 1, fontSize: 11, padding: '4px 6px' }}
                      disabled={!fallbackVisibleChunks.length || batchRetrying}
                      onClick={() => handleBatchRedoVisible(fallbackVisibleChunks)}
                      title="Retry visible fallback chunks with the selected profile"
                    >
                      {batchRetrying ? 'Retrying…' : `Redo Visible (${fallbackVisibleChunks.length})`}
                    </button>
                    <button
                      className="btn btn-ghost btn-sm"
                      style={{ flex: 1, fontSize: 11, padding: '4px 6px' }}
                      disabled={!lowRiskVisibleChunks.length}
                      onClick={() => handleApplyLowRiskCandidates(visibleReviewChunks)}
                      title="Apply visible low-risk candidates to the editor"
                    >
                      Apply Safe ({lowRiskVisibleChunks.length})
                    </button>
                  </div>
                  <div style={{ maxHeight: 240, overflowY: 'auto', paddingRight: 4 }}>
                    {visibleReviewChunks.map(chunk => (
                      <div key={chunk.chunk_id} className="glass" style={{ padding: 8, borderRadius: 'var(--radius-sm)', marginBottom: 8 }}>
                        <div className="flex justify-between items-center gap-2">
                          <div className="text-xs" style={{ fontWeight: 700 }}>Chunk {chunk.chunk_id + 1}</div>
                          <div className="flex gap-1">
                            <span className="text-xs" style={{ color: riskColor(chunk.risk_level) }}>{chunk.risk_level || 'medium'}</span>
                            <span className="text-xs" style={{ color: chunk.status === 'fallback' ? 'var(--warning, #f59e0b)' : 'var(--success)' }}>
                              {chunk.status}
                            </span>
                          </div>
                        </div>
                        <div className="text-xs text-muted mt-1">
                          Words {chunk.metrics?.source_word_count ?? 0} → {chunk.metrics?.output_word_count ?? 0} · {formatRatio(chunk.metrics?.word_count_ratio)}
                        </div>
                        {chunk.integrity_issues?.length > 0 && (
                          <div className="text-xs mt-1" style={{ color: 'var(--warning, #f59e0b)' }}>
                            {chunk.integrity_issues.join('; ')}
                          </div>
                        )}
                        {chunk.applied_variant_id && (
                          <div className="text-xs mt-1" style={{ color: 'var(--success)' }}>Applied {chunk.applied_variant_id}</div>
                        )}
                        <div className="flex gap-2 mt-2">
                          <button
                            className="btn btn-ghost btn-sm"
                            style={{ flex: 1, fontSize: 11, padding: '4px 6px' }}
                            onClick={() => handleRedoChunk(chunk)}
                            disabled={retryingChunk === `${chunk.chapter_index}:${chunk.chunk_id}`}
                            title="Retry this chunk with the selected profile"
                          >
                            {retryingChunk === `${chunk.chapter_index}:${chunk.chunk_id}` ? 'Retrying…' : 'Redo'}
                          </button>
                          {chunk.variants?.length > 0 && (
                            <button
                              className="btn btn-ghost btn-sm"
                              style={{ flex: 1, fontSize: 11, padding: '4px 6px' }}
                              onClick={() => setComparison({ chapter_index: chunk.chapter_index, chunk, variant: chunk.variants[chunk.variants.length - 1] })}
                            >
                              Compare
                            </button>
                          )}
                        </div>
                      </div>
                    ))}
                    {!visibleReviewChunks.length && (
                      <div className="text-xs text-muted">No chunks match this filter.</div>
                    )}
                  </div>
                  <button className="btn btn-ghost btn-sm w-full mt-2" onClick={handleLoadCleaningReport}>
                    View Cleaning Report
                  </button>
                </>
              ) : (
                <div className="text-xs text-muted">No LLM cleaning data for this chapter.</div>
              )}
            </div>
          )}

          <div className="section-title">Book Metadata</div>

          <div className="field">
            <label>Title</label>
            <input type="text" value={meta.title} onChange={e => updateMeta({ title: e.target.value })} autoComplete="off" />
          </div>
          <div className="field">
            <label>Author</label>
            <input type="text" value={meta.author} onChange={e => updateMeta({ author: e.target.value })} autoComplete="off" />
          </div>

          <div className="field">
            <label>Cover Image</label>
            <input type="file" ref={coverRef} style={{ display: 'none' }} accept=".jpg,.jpeg,.png" onChange={handleCoverUpload} />
            <button className="btn btn-ghost btn-sm w-full" onClick={() => coverRef.current.click()}>
              {meta.cover_image ? '🖼 Change Cover' : '+ Upload Cover'}
            </button>
            {meta.cover_image && (
              <div className="text-xs text-success mt-1 truncate">{meta.cover_image}</div>
            )}
          </div>
        </div>
      </div>

      <div className="step-nav" style={{ padding: '16px 24px' }}>
        <button className="btn btn-ghost" onClick={onBack}>← Back</button>
        <button className="btn btn-primary btn-lg" onClick={handleNext} disabled={saving}>
          Continue to Voice →
        </button>
      </div>

      {/* Debug prompt viewer modal */}
      {showPromptModal && debugPrompt && (
        <div
          style={{
            position: 'fixed', inset: 0, zIndex: 1000,
            background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
          onClick={() => setShowPromptModal(false)}
        >
          <div
            className="glass"
            style={{ width: '80vw', maxWidth: 860, maxHeight: '80vh', display: 'flex', flexDirection: 'column', borderRadius: 'var(--radius)', overflow: 'hidden' }}
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center justify-between p-4" style={{ borderBottom: '1px solid var(--glass-border)', flexShrink: 0 }}>
              <div>
                <div style={{ fontWeight: 600, fontSize: 15 }}>LLM Chapter Review Prompt</div>
                <div className="text-xs text-muted mt-0.5">Provider: <code>{debugPrompt.provider}</code> · {debugPrompt.chapter_count} chapters</div>
              </div>
              <button className="btn btn-ghost btn-sm" onClick={() => setShowPromptModal(false)}>✕</button>
            </div>
            <div style={{ overflowY: 'auto', padding: 16, flex: 1 }}>
              <div className="section-title" style={{ marginBottom: 6 }}>System Prompt</div>
              <pre style={{ fontFamily: 'var(--font-mono)', fontSize: 12, lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word', background: 'rgba(0,0,0,0.2)', borderRadius: 'var(--radius-sm)', padding: 12, marginBottom: 16 }}>{debugPrompt.system_prompt}</pre>
              <div className="section-title" style={{ marginBottom: 6 }}>User Prompt (sent to model)</div>
              <pre style={{ fontFamily: 'var(--font-mono)', fontSize: 12, lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word', background: 'rgba(0,0,0,0.2)', borderRadius: 'var(--radius-sm)', padding: 12 }}>{debugPrompt.user_prompt}</pre>
            </div>
          </div>
        </div>
      )}

      {comparison && (
        <div
          style={{
            position: 'fixed', inset: 0, zIndex: 1000,
            background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
          onClick={() => setComparison(null)}
        >
          <div
            className="glass"
            style={{ width: '86vw', maxWidth: 980, maxHeight: '82vh', display: 'flex', flexDirection: 'column', borderRadius: 'var(--radius)', overflow: 'hidden' }}
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center justify-between p-4" style={{ borderBottom: '1px solid var(--glass-border)', flexShrink: 0 }}>
              <div>
                <div style={{ fontWeight: 600, fontSize: 15 }}>Compare Cleaning Candidate</div>
                <div className="text-xs text-muted mt-0.5">
                  Chunk {(comparison.chunk?.chunk_id ?? 0) + 1} · {comparison.variant?.profile} · {comparison.variant?.status} · {comparison.variant?.risk_level || 'medium'} risk
                </div>
              </div>
              <button className="btn btn-ghost btn-sm" onClick={() => setComparison(null)}>✕</button>
            </div>
            <div className="flex gap-3" style={{ padding: 16, overflow: 'hidden', flex: 1 }}>
              <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
                <div className="section-title" style={{ marginBottom: 6 }}>Current / Heuristic</div>
                <pre style={{ flex: 1, overflow: 'auto', fontFamily: 'var(--font-mono)', fontSize: 12, lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word', background: 'rgba(0,0,0,0.2)', borderRadius: 'var(--radius-sm)', padding: 12 }}>
                  {comparison.chunk?.accepted_text || comparison.chunk?.source_text || ''}
                </pre>
              </div>
              <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
                <div className="section-title" style={{ marginBottom: 6 }}>Retry Candidate</div>
                <pre style={{ flex: 1, overflow: 'auto', fontFamily: 'var(--font-mono)', fontSize: 12, lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word', background: 'rgba(0,0,0,0.2)', borderRadius: 'var(--radius-sm)', padding: 12 }}>
                  {comparison.variant?.accepted_text || comparison.variant?.candidate_text || ''}
                </pre>
              </div>
            </div>
            {comparison.variant?.integrity_issues?.length > 0 && (
              <div className="text-xs" style={{ color: 'var(--warning, #f59e0b)', padding: '0 16px 12px' }}>
                {comparison.variant.integrity_issues.join('; ')}
              </div>
            )}
            <div className="flex justify-end gap-2 p-4" style={{ borderTop: '1px solid var(--glass-border)' }}>
              <button className="btn btn-ghost" onClick={() => setComparison(null)}>Keep Current</button>
              <button className="btn btn-primary" onClick={applyComparisonVariant}>Use Candidate</button>
            </div>
          </div>
        </div>
      )}

      {cleaningReport && (
        <div
          style={{
            position: 'fixed', inset: 0, zIndex: 1000,
            background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
          onClick={() => setCleaningReport(null)}
        >
          <div
            style={{
              width: '76vw', maxWidth: 760, maxHeight: '82vh', display: 'flex', flexDirection: 'column',
              borderRadius: 'var(--radius)', overflow: 'hidden', background: 'var(--surface, #111827)',
              border: '1px solid var(--glass-border)', boxShadow: '0 24px 80px rgba(0,0,0,0.45)',
            }}
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center justify-between p-4" style={{ borderBottom: '1px solid var(--glass-border)', flexShrink: 0 }}>
              <div>
                <div style={{ fontWeight: 600, fontSize: 15 }}>Cleaning Report</div>
                <div className="text-xs text-muted mt-0.5">{cleaningReport.project?.title} · {cleaningReport.provider || 'heuristic'} · {cleaningReport.profile}</div>
              </div>
              <button className="btn btn-ghost btn-sm" onClick={() => setCleaningReport(null)}>✕</button>
            </div>
            <div style={{ overflow: 'auto', padding: 16 }}>
              <div className="flex gap-2" style={{ marginBottom: 12 }}>
                <div style={{ flex: 1, padding: 10, borderRadius: 'var(--radius-sm)', background: 'var(--surface-elevated, rgba(255,255,255,0.06))', border: '1px solid var(--glass-border)' }}>
                  <div className="text-xs text-muted">Chunks</div>
                  <div style={{ fontWeight: 700 }}>{cleaningReport.total_chunks}</div>
                </div>
                <div style={{ flex: 1, padding: 10, borderRadius: 'var(--radius-sm)', background: 'var(--surface-elevated, rgba(255,255,255,0.06))', border: '1px solid var(--glass-border)' }}>
                  <div className="text-xs text-muted">Fallbacks</div>
                  <div style={{ fontWeight: 700 }}>{cleaningReport.total_fallbacks}</div>
                </div>
                <div style={{ flex: 1, padding: 10, borderRadius: 'var(--radius-sm)', background: 'var(--surface-elevated, rgba(255,255,255,0.06))', border: '1px solid var(--glass-border)' }}>
                  <div className="text-xs text-muted">Applied</div>
                  <div style={{ fontWeight: 700 }}>{cleaningReport.applied_variants}</div>
                </div>
              </div>
              <div className="section-title">Risk</div>
              <div className="text-sm text-secondary mb-3">
                Low {cleaningReport.risk_counts?.low ?? 0} · Medium {cleaningReport.risk_counts?.medium ?? 0} · High {cleaningReport.risk_counts?.high ?? 0}
              </div>
              <div className="section-title">Chapters</div>
              {cleaningReport.chapters?.map(chapter => (
                <div key={chapter.chapter_index} style={{ padding: 10, borderRadius: 'var(--radius-sm)', marginBottom: 8, background: 'var(--surface-elevated, rgba(255,255,255,0.06))', border: '1px solid var(--glass-border)' }}>
                  <div className="text-sm" style={{ fontWeight: 600 }}>{chapter.title || `Chapter ${chapter.chapter_index + 1}`}</div>
                  <div className="text-xs text-muted mt-1">
                    {chapter.chunk_count} chunks · {chapter.fallback_count} fallbacks · high risk {chapter.risk_counts?.high ?? 0}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
