import { useState, useEffect, useRef, useCallback } from 'react'
import { getProject, updateProject, getChapters, saveChapters, uploadCover, getDebugChapters, getDebugPrompt, getCleaningEval, saveCleaningEval, redoCleaningChunk, applyCleaningVariant, batchRedoCleaning, getCleaningReport, getModernizationEval, saveModernizationEval, getModernizationProfiles, modernizeChapter, modernizeProject, redoModernizationChunk, selectModernizationVariant, skipModernizationChunk, clearModernizationSelection, commitModernizationSession, undoLastModernizationCommit, discardModernizationSession, pollTask } from '../api'

const MODERNIZATION_MODULE_ID = 'modernize_text'
const REVIEW_STEP_IDS = {
  CLEANUP_METADATA: 'cleanup_metadata',
  CHAPTER_SETUP: 'chapter_setup',
  RUN_MODERNIZATION: 'run_modernization',
  REVIEW_MODERNIZATION: 'review_modernization',
  FINAL_REVIEW: 'final_review',
}

export default function Step2Editor({ projectId, isActive, onNext, onBack, toast, debugMode = false }) {
  const [meta, setMeta] = useState({
    title: '',
    author: '',
    language: 'en',
    description: '',
    publisher: '',
    subject: '',
    isbn: '',
    series: '',
    cover_image: null,
    enabled_modules: [],
  })
  const [chapters, setChapters] = useState([])
  const [selectedIdx, setSelectedIdx] = useState(0)
  const [saving, setSaving] = useState(false)
  const [saveStatus, setSaveStatus] = useState('saved')
  const [loading, setLoading] = useState(true)
  const [debugComparison, setDebugComparison] = useState(null)
  const [showHeuristic, setShowHeuristic] = useState(false)
  const [debugPrompt, setDebugPrompt] = useState(null)
  const [cleaningEval, setCleaningEval] = useState(null)
  const retryProfile = 'balanced'
  const [retryingChunk, setRetryingChunk] = useState(null)
  const [batchRetrying, setBatchRetrying] = useState(false)
  const [reviewFilter, setReviewFilter] = useState('all')
  const [comparison, setComparison] = useState(null)
  const [cleaningReport, setCleaningReport] = useState(null)
  const [modernizationEval, setModernizationEval] = useState(null)
  const [modernizationProfiles, setModernizationProfiles] = useState([])
  const [modernizationProfile, setModernizationProfile] = useState('standard_modern')
  const [modernizationRedoMode, setModernizationRedoMode] = useState('try_again')
  const [modernizationRedoInstruction, setModernizationRedoInstruction] = useState('')
  const [modernizingChapter, setModernizingChapter] = useState(false)
  const [modernizingProject, setModernizingProject] = useState(false)
  const [retryingModernizationChunk, setRetryingModernizationChunk] = useState(null)
  const [applyingModernizationChunk, setApplyingModernizationChunk] = useState(null)
  const [applyingModernizationBulk, setApplyingModernizationBulk] = useState(false)
  const [committingModernization, setCommittingModernization] = useState(false)
  const [discardingModernization, setDiscardingModernization] = useState(false)
  const [modernizationComparison, setModernizationComparison] = useState(null)
  const [showModernizationCommitPreview, setShowModernizationCommitPreview] = useState(false)
  const [reviewFlowStep, setReviewFlowStep] = useState(REVIEW_STEP_IDS.CLEANUP_METADATA)
  const [reviewFlowCompletedSteps, setReviewFlowCompletedSteps] = useState([])
  const [showPromptModal, setShowPromptModal] = useState(false)
  const coverRef = useRef()
  const textareaRef = useRef()
  const dirtyRef = useRef(false)
  const dirtyVersionRef = useRef(0)
  const cleaningEvalDirtyRef = useRef(false)
  const modernizationEvalDirtyRef = useRef(false)

  useEffect(() => {
    if (!projectId) {
      // Resetting all state when the project is cleared — batched by React 18
      /* eslint-disable react-hooks/set-state-in-effect */
      setMeta({
        title: '',
        author: '',
        language: 'en',
        description: '',
        publisher: '',
        subject: '',
        isbn: '',
        series: '',
        cover_image: null,
        enabled_modules: [],
      })
      setChapters([])
      setSelectedIdx(0)
      setLoading(true)
      setCleaningEval(null)
      setComparison(null)
      setCleaningReport(null)
      setModernizationEval(null)
      setModernizationComparison(null)
      setShowModernizationCommitPreview(false)
      setReviewFlowStep(REVIEW_STEP_IDS.CLEANUP_METADATA)
      setReviewFlowCompletedSteps([])
      setSaveStatus('saved')
      dirtyRef.current = false
      dirtyVersionRef.current = 0
      cleaningEvalDirtyRef.current = false
      modernizationEvalDirtyRef.current = false
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
      getModernizationEval(projectId).catch(() => null),
      getModernizationProfiles().catch(() => []),
    ])
      .then(([p, chs, dbg, prompt, evalReport, modernEval, modernProfiles]) => {
        setMeta({
          title: p.title || '',
          author: p.author || '',
          language: p.language || 'en',
          description: p.description || '',
          publisher: p.publisher || '',
          subject: p.subject || '',
          isbn: p.isbn || '',
          series: p.series || '',
          cover_image: p.cover_image,
          enabled_modules: p.enabled_modules || [],
        })
        setChapters(chs)
        setDebugComparison(dbg ?? null)
        setDebugPrompt(prompt ?? null)
        setCleaningEval(evalReport ?? null)
        setModernizationEval(modernEval ?? null)
        setModernizationProfiles(modernProfiles ?? [])
        setReviewFlowStep(p.review_flow_step || REVIEW_STEP_IDS.CLEANUP_METADATA)
        setReviewFlowCompletedSteps(p.review_flow_completed_steps || [])
        setSaveStatus('saved')
        dirtyRef.current = false
        dirtyVersionRef.current = 0
        cleaningEvalDirtyRef.current = false
        modernizationEvalDirtyRef.current = false
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

  const markCleaningEvalDirty = useCallback(() => {
    cleaningEvalDirtyRef.current = true
    markDirty()
  }, [markDirty])

  const markModernizationEvalDirty = useCallback(() => {
    modernizationEvalDirtyRef.current = true
    markDirty()
  }, [markDirty])

  const updateChapter = (idx, field, value) => {
    markDirty()
    setChapters(prev => prev.map((ch, i) => i === idx ? { ...ch, [field]: value } : ch))
  }

  const updateSelectedChapterTitle = (value) => {
    updateChapter(selectedIdx, 'title', value)
  }

  const updateSelectedChapterText = (value) => {
    updateChapter(selectedIdx, 'text', value)
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
    cleaningEvalDirtyRef.current = true
    modernizationEvalDirtyRef.current = true
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
    setModernizationComparison(null)
    setCleaningReport(null)

    setModernizationEval(prev => {
      if (!prev?.chapters?.length) return prev
      const targetIndex = deletedIndex === 0 ? 1 : deletedIndex - 1
      const deletedEval = prev.chapters.find(chapterEval => chapterEval.chapter_index === deletedIndex)
      const updatedChapters = prev.chapters
        .filter(chapterEval => chapterEval.chapter_index !== deletedIndex)
        .map(chapterEval => {
          if (chapterEval.chapter_index !== targetIndex || !deletedEval) return chapterEval
          return {
            ...chapterEval,
            chunks: reindexChunkIds([...(deletedIndex === 0 ? deletedEval.chunks || [] : []), ...(chapterEval.chunks || []), ...(deletedIndex !== 0 ? deletedEval.chunks || [] : [])]),
          }
        })
      return { ...prev, chapters: reindexChapterEvals(updatedChapters) }
    })
  }

  const syncCleaningEvalAfterMove = (idx, next) => {
    markDirty()
    cleaningEvalDirtyRef.current = true
    modernizationEvalDirtyRef.current = true
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
    setModernizationComparison(null)
    setCleaningReport(null)
    setModernizationEval(prev => {
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
  }

  const syncCleaningEvalAfterSplit = (splitIndex) => {
    markDirty()
    cleaningEvalDirtyRef.current = true
    modernizationEvalDirtyRef.current = true
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
    setModernizationComparison(null)
    setCleaningReport(null)
    setModernizationEval(prev => {
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
        updateProject(projectId, {
          title: meta.title,
          author: meta.author,
          language: meta.language,
          description: meta.description,
          publisher: meta.publisher,
          subject: meta.subject,
          isbn: meta.isbn,
          series: meta.series,
          cover_image: meta.cover_image,
          review_flow_step: reviewFlowStep,
          review_flow_completed_steps: reviewFlowCompletedSteps,
        }),
        cleaningEval && cleaningEvalDirtyRef.current ? saveCleaningEval(projectId, cleaningEval) : Promise.resolve(),
        modernizationEval && modernizationEvalDirtyRef.current ? saveModernizationEval(projectId, modernizationEval) : Promise.resolve(),
      ])
      if (dirtyVersionRef.current === saveVersion) {
        dirtyRef.current = false
        cleaningEvalDirtyRef.current = false
        modernizationEvalDirtyRef.current = false
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
  }, [projectId, chapters, meta.title, meta.author, meta.language, meta.description, meta.publisher, meta.subject, meta.isbn, meta.series, meta.cover_image, reviewFlowStep, reviewFlowCompletedSteps, cleaningEval, modernizationEval, toast])

  useEffect(() => {
    if (!projectId || !isActive || !dirtyRef.current || saveStatus !== 'dirty') return
    const timer = setTimeout(() => {
      if (dirtyRef.current) handleSave(false)
    }, 1200)
    return () => clearTimeout(timer)
  }, [projectId, isActive, saveStatus, chapters, meta, cleaningEval, modernizationEval, handleSave])

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

  const handleClearCover = () => {
    updateMeta({ cover_image: null })
    toast('Cover image cleared. Save to keep this change.', 'success')
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
      markCleaningEvalDirty()
      setComparison({ chapter_index: chapterIndex, chunk: { ...res.chunk, chapter_index: chapterIndex }, variant: res.variant })
      toast('Cleanup retry complete.', 'success')
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setRetryingChunk(null)
    }
  }

  const handleModernizeChapter = async () => {
    setModernizingChapter(true)
    try {
      const res = await modernizeChapter(projectId, selectedIdx, modernizationProfile, modernizationEval?.provider ?? null)
      setModernizationEval(res.evaluation)
      markModernizationEvalDirty()
      toast('Modernization candidates ready for this chapter.', 'success')
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setModernizingChapter(false)
    }
  }

  const handleModernizeProject = async () => {
    setModernizingProject(true)
    try {
      const { task_id } = await modernizeProject(projectId, modernizationProfile, modernizationEval?.provider ?? null)
      await pollTask(task_id, () => {})
      const latest = await getModernizationEval(projectId).catch(() => null)
      setModernizationEval(latest)
      markModernizationEvalDirty()
      toast('Modernization candidates ready for all chapters.', 'success')
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setModernizingProject(false)
    }
  }

  const handleRedoModernizationChunk = async (chunk) => {
    const chapterIndex = chunk.chapter_index ?? selectedIdx
    const retryKey = `${chapterIndex}:${chunk.chunk_id}`
    setRetryingModernizationChunk(retryKey)
    try {
      const redoInstruction = modernizationRedoInstruction.trim() || null
      const res = await redoModernizationChunk(projectId, chapterIndex, chunk.chunk_id, modernizationProfile, modernizationEval?.provider ?? null, modernizationRedoMode, redoInstruction)
      setModernizationEval(res.evaluation)
      markModernizationEvalDirty()
      setModernizationComparison({ chapter_index: chapterIndex, chunk: { ...res.chunk, chapter_index: chapterIndex }, variant: res.variant })
      toast('Modernization retry complete.', 'success')
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setRetryingModernizationChunk(null)
    }
  }

  const selectModernizationCandidate = async (candidate = modernizationComparison) => {
    if (!candidate?.chunk || !candidate?.variant) return
    const chapterIndex = candidate.chapter_index ?? candidate.chunk.chapter_index ?? selectedIdx
    const applyKey = `${chapterIndex}:${candidate.chunk.chunk_id}`
    setApplyingModernizationChunk(applyKey)
    try {
      const res = await selectModernizationVariant(
        projectId,
        chapterIndex,
        candidate.chunk.chunk_id,
        candidate.variant.variant_id,
      )
      setModernizationEval(res.evaluation)
      setModernizationComparison(null)
      toast('Modernization candidate selected for commit.', 'success')
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setApplyingModernizationChunk(null)
    }
  }

  const skipModernizationCandidate = async (chunk) => {
    const chapterIndex = chunk.chapter_index ?? selectedIdx
    const applyKey = `${chapterIndex}:${chunk.chunk_id}`
    setApplyingModernizationChunk(applyKey)
    try {
      const res = await skipModernizationChunk(projectId, chapterIndex, chunk.chunk_id)
      setModernizationEval(res.evaluation)
      setModernizationComparison(null)
      toast('Passage skipped for this modernization commit.', 'success')
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setApplyingModernizationChunk(null)
    }
  }

  const clearModernizationCandidate = async (chunk) => {
    const chapterIndex = chunk.chapter_index ?? selectedIdx
    const applyKey = `${chapterIndex}:${chunk.chunk_id}`
    setApplyingModernizationChunk(applyKey)
    try {
      const res = await clearModernizationSelection(projectId, chapterIndex, chunk.chunk_id)
      setModernizationEval(res.evaluation)
      setModernizationComparison(null)
      toast('Modernization selection cleared.', 'success')
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setApplyingModernizationChunk(null)
    }
  }

  const latestUnappliedModernizationVariant = (chunk) => {
    const variants = chunk?.variants || []
    const latestVariant = variants[variants.length - 1]
    if (!latestVariant) return null
    if (latestVariant.is_applied || chunk.applied_variant_id === latestVariant.variant_id) return null
    return latestVariant
  }

  const appliedModernizationVariant = (chunk) => {
    const variants = chunk?.variants || []
    return variants.find(variant => variant.is_selected) || variants.find(variant => variant.is_applied) || variants.find(variant => variant.variant_id === (chunk?.selected_variant_id || chunk?.applied_variant_id)) || null
  }

  const selectedModernizationVariant = (chunk) => {
    const variants = chunk?.variants || []
    const selectedId = chunk?.selected_variant_id || chunk?.applied_variant_id
    return variants.find(variant => variant.variant_id === selectedId) || variants.find(variant => variant.is_selected) || variants.find(variant => variant.is_applied) || null
  }

  const modernizationSourceSnapshotText = (chapterEval) => {
    if (chapterEval?.source_text) return chapterEval.source_text
    return (chapterEval?.chunks || [])
      .slice()
      .sort((a, b) => (a.chunk_id ?? 0) - (b.chunk_id ?? 0))
      .map(chunk => chunk.source_text || '')
      .join('\n\n')
      .trim()
  }

  const modernizationCommitPreviewText = (chapterEval) => (
    (chapterEval?.chunks || [])
      .slice()
      .sort((a, b) => (a.chunk_id ?? 0) - (b.chunk_id ?? 0))
      .map(chunk => {
        const variant = selectedModernizationVariant(chunk)
        return (variant?.accepted_text || variant?.candidate_text || chunk.source_text || '').trim()
      })
      .join('\n\n')
      .trim()
  )

  const handleSelectModernizationCandidates = async (items, scopeLabel) => {
    if (!items.length) return
    setApplyingModernizationBulk(true)

    let latestEval = modernizationEval
    let selectedCount = 0
    let skippedCount = 0

    try {
      for (const item of items) {
        const chapterIndex = item.chapter_index ?? item.chunk?.chapter_index ?? selectedIdx
        if (!chapters[chapterIndex]) {
          skippedCount += 1
          continue
        }
        const res = await selectModernizationVariant(
          projectId,
          chapterIndex,
          item.chunk.chunk_id,
          item.variant.variant_id,
        )
        latestEval = res.evaluation
        selectedCount += 1
      }

      if (selectedCount) {
        setModernizationEval(latestEval)
        setModernizationComparison(null)
      }
      if (selectedCount && skippedCount) {
        toast(`Selected ${selectedCount} ${scopeLabel} candidate(s); ${skippedCount} could not be selected.`, 'warning')
      } else if (selectedCount) {
        toast(`Selected ${selectedCount} ${scopeLabel} candidate(s) for commit.`, 'success')
      } else {
        toast('No modernization candidates could be selected.', 'warning')
      }
    } catch (e) {
      if (selectedCount) {
        setModernizationEval(latestEval)
        setModernizationComparison(null)
      }
      toast(e.message, 'error')
    } finally {
      setApplyingModernizationBulk(false)
    }
  }

  const handleCommitModernization = async () => {
    setCommittingModernization(true)
    try {
      if (dirtyRef.current) await handleSave(false)
      const res = await commitModernizationSession(projectId, selectedIdx)
      setModernizationEval(res.evaluation)
      setChapters(prev => prev.map((chapter, i) => (i === selectedIdx ? res.chapter : chapter)))
      setModernizationComparison(null)
      setShowModernizationCommitPreview(false)
      dirtyRef.current = false
      setSaveStatus('saved')
      toast('Selected modernization changes committed.', 'success')
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setCommittingModernization(false)
    }
  }

  const handleUndoModernizationCommit = async () => {
    setCommittingModernization(true)
    try {
      const res = await undoLastModernizationCommit(projectId, selectedIdx)
      setModernizationEval(res.evaluation)
      setChapters(prev => prev.map((chapter, i) => (i === selectedIdx ? res.chapter : chapter)))
      setModernizationComparison(null)
      setShowModernizationCommitPreview(false)
      dirtyRef.current = false
      setSaveStatus('saved')
      toast('Last modernization commit undone.', 'success')
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setCommittingModernization(false)
    }
  }

  const handleDiscardModernization = async () => {
    setDiscardingModernization(true)
    try {
      const res = await discardModernizationSession(projectId, selectedIdx)
      setModernizationEval(res.evaluation)
      setModernizationComparison(null)
      setShowModernizationCommitPreview(false)
      toast('Modernization review discarded.', 'success')
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setDiscardingModernization(false)
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

  const formatCleaningIssue = (issue) => {
    const labels = {
      'possible page header inserted mid-sentence': 'Possible page header inserted mid-sentence',
      'placeholder or summary language': 'Placeholder or summary language',
      'missing source anchor phrases': 'Missing source anchor phrases',
      'empty output': 'Empty output',
    }
    if (labels[issue]) return labels[issue]
    const readable = String(issue || '').replace(/[_-]+/g, ' ').trim()
    return readable ? readable.charAt(0).toUpperCase() + readable.slice(1) : 'Cleanup warning'
  }

  const cleanupSnippetFromText = (text, maxLength = 170) => {
    const normalized = (text || '').replace(/\s+/g, ' ').trim()
    if (!normalized) return ''
    if (normalized.length <= maxLength) return normalized
    const clipped = normalized.slice(0, maxLength).trimEnd()
    const breakAt = Math.max(clipped.lastIndexOf('. '), clipped.lastIndexOf('? '), clipped.lastIndexOf('! '), clipped.lastIndexOf('; '))
    return `${(breakAt > 80 ? clipped.slice(0, breakAt + 1) : clipped).trim()}...`
  }

  const lineLooksUnfinished = (line) => Boolean(line) && !/[.!?;:)\]"']$/.test(line.trim())
  const lineContinuesSentence = (line) => /^[a-z("']/.test((line || '').trim()) || /^(that|this|these|those|it|them|which|who)\b/i.test((line || '').trim())

  const pageHeaderSnippet = (text, maxLength) => {
    const lines = (text || '').split(/\r?\n/).map(line => line.trim()).filter(Boolean)
    for (let i = 1; i < lines.length - 1; i += 1) {
      const previous = lines[i - 1]
      const current = lines[i]
      const next = lines[i + 1]
      if (lineLooksUnfinished(previous) && current.length >= 4 && current.length <= 90 && lineContinuesSentence(next)) {
        return cleanupSnippetFromText(`${previous} ${current} ${next}`, maxLength)
      }
    }
    return ''
  }

  const cleanupSnippet = (chunk, issue = '', maxLength = 170) => {
    const sourceText = chunk?.accepted_text || chunk?.source_text || chunk?.candidate_text || ''
    if (issue === 'possible page header inserted mid-sentence') {
      const focused = pageHeaderSnippet(sourceText, maxLength)
      if (focused) return focused
    }
    return cleanupSnippetFromText(sourceText, maxLength)
  }

  const riskLabel = (risk) => risk === 'low' ? 'Low risk' : risk === 'high' ? 'Needs review' : 'Review'
  const statusLabel = (status) => status === 'fallback' ? 'Fallback used' : 'Accepted'

  const handleBatchRedoVisible = async (chunks) => {
    if (!chunks.length) return
    setBatchRetrying(true)
    try {
      const payload = chunks.map(chunk => ({ chapter_index: chunk.chapter_index ?? selectedIdx, chunk_id: chunk.chunk_id }))
      const res = await batchRedoCleaning(projectId, payload, retryProfile)
      setCleaningEval(res.evaluation)
      markCleaningEvalDirty()
      const failed = res.results?.filter(result => !result.ok)?.length ?? 0
      toast(failed ? `Batch retry finished with ${failed} issue(s).` : `Retried ${payload.length} passage(s).`, failed ? 'warning' : 'success')
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
      markCleaningEvalDirty()
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
      markCleaningEvalDirty()
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
  const getModernizationChapterEval = (chapterIndex) => modernizationEval?.chapters?.find(chEval => chEval.chapter_index === chapterIndex)
  const selectedEval = getChapterEval(selectedIdx)
  const selectedModernizationEval = getModernizationChapterEval(selectedIdx)
  const hasCleaningEval = cleaningEval?.chapters?.length > 0
  const hasModernizationModule = meta.enabled_modules?.includes(MODERNIZATION_MODULE_ID)
  const hasModernizationEval = modernizationEval?.chapters?.length > 0
  const showModernizationTools = hasModernizationModule || hasModernizationEval
  const formatRatio = (value) => `${Math.round((value ?? 1) * 100)}%`
  const visibleReviewChunks = selectedEval?.chunks?.map(chunk => ({
    ...chunk,
    chapter_index: selectedEval.chapter_index,
  })).filter(chunkMatchesFilter) ?? []
  const fallbackVisibleChunks = visibleReviewChunks.filter(chunk => chunk.status === 'fallback')
  const lowRiskVisibleChunks = visibleReviewChunks.filter(chunk => (chunk.variants || []).some(variant => variant.risk_level === 'low' && !(variant.integrity_issues?.length) && !variant.is_applied))
  const visibleModernizationChunks = selectedModernizationEval?.chunks?.map(chunk => ({
    ...chunk,
    chapter_index: selectedModernizationEval.chapter_index,
  })) ?? []
  const selectedModernizationApplyItems = visibleModernizationChunks
    .map(chunk => ({ chunk, variant: latestUnappliedModernizationVariant(chunk), chapter_index: chunk.chapter_index }))
    .filter(item => item.variant)
  const allModernizationApplyItems = (modernizationEval?.chapters || []).flatMap(chapterEval => (
    (chapterEval.chunks || []).map(chunk => {
      const chunkWithChapter = { ...chunk, chapter_index: chapterEval.chapter_index }
      return {
        chapter_index: chapterEval.chapter_index,
        chunk: chunkWithChapter,
        variant: latestUnappliedModernizationVariant(chunkWithChapter),
      }
    }).filter(item => item.variant)
  ))
  const selectedModernizationCount = visibleModernizationChunks.filter(chunk => chunk.selected_variant_id || chunk.applied_variant_id).length
  const selectedModernizationSessionStatus = selectedModernizationEval?.status || 'reviewing'
  const selectedModernizationIsCommitted = selectedModernizationSessionStatus === 'committed'
  const selectedModernizationCanUndo = selectedModernizationIsCommitted && selectedModernizationEval?.last_commit?.before_text !== undefined
  const allModernizationSessionsCommitted = Boolean(
    modernizationEval?.chapters?.length &&
    modernizationEval.chapters.every(chapterEval => chapterEval.status === 'committed'),
  )
  const modernizationSessionStale = Boolean(
    selectedModernizationEval?.source_text &&
    selectedModernizationSessionStatus === 'reviewing' &&
    (chapters[selectedIdx]?.text || '') !== selectedModernizationEval.source_text,
  )
  const selectedModernizationSourcePreview = modernizationSourceSnapshotText(selectedModernizationEval)
  const selectedModernizationCommitPreview = modernizationCommitPreviewText(selectedModernizationEval)
  const modernizationReviewCount = visibleModernizationChunks.filter(chunk => chunk.recommended_action === 'review' || chunk.risk_level === 'high' || chunk.integrity_issues?.length).length
  const reviewSteps = [
    { id: REVIEW_STEP_IDS.CLEANUP_METADATA, label: 'Cleanup + Metadata', description: 'Review cleanup and book details' },
    { id: REVIEW_STEP_IDS.CHAPTER_SETUP, label: 'Chapter Setup', description: 'Finalize chapter text and order' },
    showModernizationTools ? { id: REVIEW_STEP_IDS.RUN_MODERNIZATION, label: 'Run Modernization', description: 'Generate modernization candidates' } : null,
    showModernizationTools ? { id: REVIEW_STEP_IDS.REVIEW_MODERNIZATION, label: 'Review Modernization', description: 'Select and commit modernization changes' } : null,
    { id: REVIEW_STEP_IDS.FINAL_REVIEW, label: 'Final Review', description: 'Confirm text and metadata before Voice' },
  ].filter(Boolean)
  const activeReviewStepId = reviewSteps.some(step => step.id === reviewFlowStep) ? reviewFlowStep : reviewSteps[0].id
  const activeReviewStepIndex = Math.max(0, reviewSteps.findIndex(step => step.id === activeReviewStepId))
  const activeReviewStep = reviewSteps[activeReviewStepIndex]
  const completedReviewStepSet = new Set(reviewFlowCompletedSteps)
  const activeReviewStepLocked = completedReviewStepSet.has(activeReviewStepId)
  const canEditChapters = !activeReviewStepLocked && [REVIEW_STEP_IDS.CHAPTER_SETUP, REVIEW_STEP_IDS.FINAL_REVIEW].includes(activeReviewStepId)
  const persistReviewFlow = async (nextStep, nextCompleted, extra = {}) => {
    setReviewFlowStep(nextStep)
    setReviewFlowCompletedSteps(nextCompleted)
    try {
      await updateProject(projectId, {
        review_flow_step: nextStep,
        review_flow_completed_steps: nextCompleted,
        ...extra,
      })
    } catch (e) {
      toast(e.message, 'error')
    }
  }
  const goReviewStep = (targetStepId) => {
    const targetIndex = reviewSteps.findIndex(step => step.id === targetStepId)
    if (targetIndex < 0) return
    const canOpen = targetIndex <= activeReviewStepIndex || completedReviewStepSet.has(targetStepId)
    if (canOpen) setReviewFlowStep(targetStepId)
  }
  const resetStepsAfter = (stepId, completedSteps = reviewFlowCompletedSteps) => {
    const index = reviewSteps.findIndex(step => step.id === stepId)
    return completedSteps.filter(id => {
      const stepIndex = reviewSteps.findIndex(step => step.id === id)
      return stepIndex >= 0 && stepIndex <= index
    })
  }
  const advanceReviewFlow = async () => {
    if (activeReviewStepId === REVIEW_STEP_IDS.RUN_MODERNIZATION && !hasModernizationEval) {
      toast('Run modernization before continuing to modernization review.', 'warning')
      return
    }
    if (activeReviewStepId === REVIEW_STEP_IDS.REVIEW_MODERNIZATION && !allModernizationSessionsCommitted) {
      toast('Commit modernization changes for every chapter before final review.', 'warning')
      return
    }
    if (dirtyRef.current) await handleSave(false)
    const completed = Array.from(new Set([...reviewFlowCompletedSteps, activeReviewStepId]))
    const nextStep = reviewSteps[activeReviewStepIndex + 1]
    if (nextStep) {
      await persistReviewFlow(nextStep.id, completed)
      return
    }
    await persistReviewFlow(activeReviewStepId, completed)
    await handleNext()
  }
  const unlockReviewStep = async (stepId) => {
    const step = reviewSteps.find(item => item.id === stepId)
    if (!step || !completedReviewStepSet.has(stepId)) return
    const stepIndex = reviewSteps.findIndex(item => item.id === stepId)
    const laterCompleted = reviewFlowCompletedSteps.filter(id => {
      const index = reviewSteps.findIndex(item => item.id === id)
      return index > stepIndex
    })
    if (laterCompleted.length) {
      const ok = window.confirm(`Unlock ${step.label}? This will reset later Review steps and they will need to be completed again before Voice.`)
      if (!ok) return
    }
    const nextCompleted = resetStepsAfter(stepId).filter(id => id !== stepId)
    await persistReviewFlow(stepId, nextCompleted, { review_flow_unlocked_at: new Date().toISOString() })
  }
  const reviewPrimaryLabel = activeReviewStepIndex < reviewSteps.length - 1
    ? `Lock ${activeReviewStep.label} and continue`
    : 'Finish Review and continue to Voice'
  const filterOptions = [
    ['all', 'All'],
    ['fallbacks', 'Fallback used'],
    ['warnings', 'Warnings'],
    ['large_delta', 'Text changed'],
    ['missing_anchors', 'Missing anchors'],
    ['variants', 'Candidates'],
  ]
  const modernizationRedoModes = [
    ['try_again', 'Try again'],
    ['more_faithful', 'More faithful'],
    ['more_readable', 'More readable'],
    ['less_condensed', 'Less condensed'],
    ['preserve_key_terms', 'Preserve terms'],
    ['fix_missing_paragraphs', 'Fix missing paragraphs'],
  ]
  const riskColor = (risk) => risk === 'low' ? 'var(--success)' : risk === 'high' ? 'var(--danger)' : 'var(--warning, #f59e0b)'
  const reportWarningItems = (cleaningReport?.top_warnings || []).flatMap((warning, warningIndex) => {
    const chapterIndex = warning.chapter_index ?? 0
    const chapterEval = getChapterEval(chapterIndex)
    const reportChapter = cleaningReport?.chapters?.find(chapter => chapter.chapter_index === chapterIndex)
    const chunk = chapterEval?.chunks?.find(item => item.chunk_id === warning.chunk_id)
    return (warning.issues || []).map((issue, issueIndex) => ({
      key: `${chapterIndex}:${warning.chunk_id ?? warningIndex}:${issueIndex}:${issue}`,
      chapterTitle: reportChapter?.title || chapterEval?.title || chapters[chapterIndex]?.title || `Chapter ${chapterIndex + 1}`,
      label: formatCleaningIssue(issue),
      snippet: cleanupSnippet(chunk, issue, 220),
    }))
  })

  const renderModernizationReviewCard = (chunk) => {
    const latestVariant = (chunk.variants || [])[chunk.variants?.length - 1]
    const latestApplyVariant = latestUnappliedModernizationVariant(chunk)
    const appliedVariant = appliedModernizationVariant(chunk)
    const displayVariant = appliedVariant || latestVariant
    const retryKey = `${chunk.chapter_index}:${chunk.chunk_id}`
    const chunkStatusLabel = chunk.status === 'selected' || chunk.selected_variant_id ? 'Selected' : chunk.status === 'skipped' ? 'Skipped' : 'Not selected'
    const sourceText = chunk.source_text || ''
    const candidateText = displayVariant?.accepted_text || displayVariant?.candidate_text || ''

    return (
      <div key={chunk.chunk_id} className="glass" style={{ padding: 14, borderRadius: 'var(--radius-sm)', marginBottom: 12 }}>
        <div className="flex justify-between items-start gap-3" style={{ marginBottom: 10 }}>
          <div style={{ minWidth: 0 }}>
            <div className="text-sm" style={{ fontWeight: 700 }}>Passage {chunk.chunk_id + 1}</div>
            <div className="text-xs text-muted mt-1">
              Words {chunk.metrics?.source_word_count ?? 0} -&gt; {chunk.metrics?.output_word_count ?? 0} · {formatRatio(chunk.metrics?.word_count_ratio)}
            </div>
          </div>
          <div className="flex gap-1" style={{ flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            <span className="text-xs" style={{ color: riskColor(chunk.risk_level), fontWeight: 700 }}>{riskLabel(chunk.risk_level)}</span>
            <span className="text-xs" style={{ color: chunkStatusLabel === 'Selected' ? 'var(--success)' : chunkStatusLabel === 'Skipped' ? 'var(--warning, #f59e0b)' : 'var(--text-muted)', fontWeight: 700 }}>{chunkStatusLabel}</span>
          </div>
        </div>

        {(chunk.integrity_issues?.length > 0 || latestVariant?.similarity_to_previous >= 0.94) && (
          <div className="text-xs" style={{ color: 'var(--warning, #f59e0b)', lineHeight: 1.45, marginBottom: 10 }}>
            {[...(chunk.integrity_issues || []), latestVariant?.similarity_to_previous >= 0.94 ? 'Very similar to previous candidate' : null].filter(Boolean).join('; ')}
          </div>
        )}

        {chunk.variants?.length > 1 && (
          <div className="field" style={{ maxWidth: 220, marginBottom: 10 }}>
            <label style={{ fontSize: 11 }}>Variant</label>
            <select
              value={(appliedVariant || latestVariant)?.variant_id || ''}
              onChange={e => {
                const variant = chunk.variants.find(item => item.variant_id === e.target.value)
                if (variant) setModernizationComparison({ chapter_index: chunk.chapter_index, chunk, variant })
              }}
              style={{ fontSize: 12 }}
            >
              {chunk.variants.map((variant, variantIndex) => (
                <option key={variant.variant_id} value={variant.variant_id}>Variant {variantIndex + 1}</option>
              ))}
            </select>
          </div>
        )}

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 12, marginBottom: 12 }}>
          <div style={{ minWidth: 0 }}>
            <div className="section-title" style={{ marginBottom: 6 }}>Source</div>
            <pre style={{ maxHeight: 220, overflow: 'auto', fontFamily: 'var(--font-mono)', fontSize: 12, lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word', background: 'rgba(0,0,0,0.18)', borderRadius: 'var(--radius-sm)', padding: 10 }}>
              {sourceText || 'No source text available.'}
            </pre>
          </div>
          <div style={{ minWidth: 0 }}>
            <div className="section-title" style={{ marginBottom: 6 }}>Candidate</div>
            <pre style={{ maxHeight: 220, overflow: 'auto', fontFamily: 'var(--font-mono)', fontSize: 12, lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word', background: 'rgba(0,0,0,0.18)', borderRadius: 'var(--radius-sm)', padding: 10 }}>
              {candidateText || 'No candidate text available.'}
            </pre>
          </div>
        </div>

        <div className="flex gap-2" style={{ flexWrap: 'wrap' }}>
          {latestApplyVariant && (
            <button
              className="btn btn-primary btn-sm"
              onClick={() => selectModernizationCandidate({ chapter_index: chunk.chapter_index, chunk, variant: latestApplyVariant })}
              disabled={applyingModernizationChunk === retryKey || applyingModernizationBulk || selectedModernizationIsCommitted}
              title="Select this modernized candidate for commit"
            >
              {applyingModernizationChunk === retryKey ? 'Selecting...' : 'Use This'}
            </button>
          )}
          {appliedVariant && (
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => clearModernizationCandidate(chunk)}
              disabled={applyingModernizationBulk || selectedModernizationIsCommitted}
              title="Clear this modernization selection"
            >
              Unuse
            </button>
          )}
          {latestVariant && (
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => setModernizationComparison({ chapter_index: chunk.chapter_index, chunk, variant: latestVariant })}
            >
              Compare
            </button>
          )}
          <button
            className="btn btn-ghost btn-sm"
            onClick={() => handleRedoModernizationChunk(chunk)}
            disabled={retryingModernizationChunk === retryKey || selectedModernizationIsCommitted}
            title="Retry this passage with the selected modernization profile"
          >
            {retryingModernizationChunk === retryKey ? 'Retrying...' : 'Redo'}
          </button>
          <button
            className="btn btn-ghost btn-sm"
            onClick={() => skipModernizationCandidate(chunk)}
            disabled={applyingModernizationChunk === retryKey || selectedModernizationIsCommitted}
            title="Keep the source text for this passage when committing"
          >
            Skip
          </button>
        </div>
      </div>
    )
  }

  const renderModernizationControls = () => (
    <div className="glass" style={{ padding: 14, borderRadius: 'var(--radius-sm)', marginBottom: 14 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: 12, alignItems: 'end' }}>
        {modernizationProfiles.length > 0 && (
          <div className="field" style={{ marginBottom: 0 }}>
            <label style={{ fontSize: 11 }}>Profile</label>
            <select value={modernizationProfile} onChange={e => setModernizationProfile(e.target.value)} style={{ fontSize: 12 }}>
              {modernizationProfiles.map(profile => (
                <option key={profile.id} value={profile.id}>{profile.label}</option>
              ))}
            </select>
          </div>
        )}
        <div className="field" style={{ marginBottom: 0 }}>
          <label style={{ fontSize: 11 }}>Redo Mode</label>
          <select value={modernizationRedoMode} onChange={e => setModernizationRedoMode(e.target.value)} style={{ fontSize: 12 }}>
            {modernizationRedoModes.map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </div>
        <div className="field" style={{ marginBottom: 0 }}>
          <label style={{ fontSize: 11 }}>Redo Instruction</label>
          <input
            type="text"
            value={modernizationRedoInstruction}
            onChange={e => setModernizationRedoInstruction(e.target.value)}
            placeholder="Keep Saviour unchanged"
            style={{ fontSize: 12 }}
          />
        </div>
        <div className="flex gap-2" style={{ flexWrap: 'wrap' }}>
          <button className="btn btn-ghost btn-sm" disabled={activeReviewStepLocked || modernizingChapter || modernizingProject} onClick={handleModernizeChapter}>
            {modernizingChapter ? 'Running...' : selectedModernizationEval ? 'Regenerate chapter' : 'Modernize chapter'}
          </button>
          <button className="btn btn-ghost btn-sm" disabled={activeReviewStepLocked || modernizingChapter || modernizingProject} onClick={handleModernizeProject}>
            {modernizingProject ? 'Running...' : hasModernizationEval ? 'Regenerate all' : 'Modernize all'}
          </button>
        </div>
      </div>

      {selectedModernizationEval && (
        <>
          <div className="flex gap-2" style={{ flexWrap: 'wrap', marginTop: 12 }}>
            <button
              className="btn btn-primary btn-sm"
              disabled={activeReviewStepLocked || !selectedModernizationApplyItems.length || applyingModernizationBulk || selectedModernizationIsCommitted}
              onClick={() => handleSelectModernizationCandidates(selectedModernizationApplyItems, 'chapter')}
            >
              {applyingModernizationBulk ? 'Selecting...' : `Select chapter (${selectedModernizationApplyItems.length})`}
            </button>
            <button
              className="btn btn-primary btn-sm"
              disabled={activeReviewStepLocked || !allModernizationApplyItems.length || applyingModernizationBulk || selectedModernizationIsCommitted}
              onClick={() => handleSelectModernizationCandidates(allModernizationApplyItems, 'book')}
            >
              {applyingModernizationBulk ? 'Selecting...' : `Select all (${allModernizationApplyItems.length})`}
            </button>
            <button
              className="btn btn-primary btn-sm"
              disabled={activeReviewStepLocked || !selectedModernizationCount || committingModernization || selectedModernizationIsCommitted}
              onClick={handleCommitModernization}
            >
              {committingModernization ? 'Committing...' : 'Commit selected changes'}
            </button>
            <button
              className="btn btn-ghost btn-sm"
              disabled={!visibleModernizationChunks.length}
              onClick={() => setShowModernizationCommitPreview(true)}
            >
              Preview commit
            </button>
            <button
              className="btn btn-ghost btn-sm"
              disabled={activeReviewStepLocked || discardingModernization || selectedModernizationIsCommitted}
              onClick={handleDiscardModernization}
            >
              {discardingModernization ? 'Discarding...' : 'Discard session'}
            </button>
            {selectedModernizationCanUndo && (
              <button className="btn btn-ghost btn-sm" disabled={committingModernization} onClick={handleUndoModernizationCommit}>
                Undo last commit
              </button>
            )}
          </div>
          <div className="flex gap-2" style={{ flexWrap: 'wrap', marginTop: 10 }}>
            <span className="badge">{visibleModernizationChunks.length} passages</span>
            <span className="badge" style={{ color: selectedModernizationCount ? 'var(--success)' : 'var(--text-secondary)' }}>{selectedModernizationCount} selected</span>
            {modernizationReviewCount > 0 && <span className="badge" style={{ color: 'var(--warning, #f59e0b)' }}>{modernizationReviewCount} need review</span>}
          </div>
        </>
      )}
    </div>
  )

  const renderMetadataForm = (compact = false) => (
    <div className="glass" style={{ padding: 14, borderRadius: 'var(--radius-sm)' }} data-tip-anchor="metadata-sidebar">
      <div className="section-title">Book Metadata</div>
      <div className="field">
        <label>Title</label>
        <input type="text" value={meta.title} onChange={e => updateMeta({ title: e.target.value })} disabled={activeReviewStepLocked} autoComplete="off" />
      </div>
      <div className="field">
        <label>Author</label>
        <input type="text" value={meta.author} onChange={e => updateMeta({ author: e.target.value })} disabled={activeReviewStepLocked} autoComplete="off" />
      </div>
      <div className={compact ? 'field-row' : ''}>
        <div className="field" data-tip-anchor="metadata-language">
          <label>Language</label>
          <input type="text" value={meta.language || ''} onChange={e => updateMeta({ language: e.target.value })} disabled={activeReviewStepLocked} placeholder="en" autoComplete="off" />
        </div>
        <div className="field" data-tip-anchor="metadata-isbn">
          <label>ISBN</label>
          <input type="text" value={meta.isbn || ''} onChange={e => updateMeta({ isbn: e.target.value })} disabled={activeReviewStepLocked} autoComplete="off" />
        </div>
      </div>
      <div className="field" data-tip-anchor="metadata-description">
        <label>Description</label>
        <textarea
          value={meta.description || ''}
          onChange={e => updateMeta({ description: e.target.value })}
          disabled={!canEditChapters}
          rows={compact ? 4 : 3}
          placeholder="Short summary used in EPUB metadata"
          style={{ resize: 'vertical' }}
        />
      </div>
      <div className={compact ? 'field-row' : ''}>
        <div className="field" data-tip-anchor="metadata-publisher">
          <label>Publisher</label>
          <input type="text" value={meta.publisher || ''} onChange={e => updateMeta({ publisher: e.target.value })} disabled={activeReviewStepLocked} autoComplete="off" />
        </div>
        <div className="field" data-tip-anchor="metadata-subject">
          <label>Subject</label>
          <input type="text" value={meta.subject || ''} onChange={e => updateMeta({ subject: e.target.value })} disabled={activeReviewStepLocked} autoComplete="off" />
        </div>
      </div>
      <div className="field" data-tip-anchor="metadata-series">
        <label>Series</label>
        <input type="text" value={meta.series || ''} onChange={e => updateMeta({ series: e.target.value })} disabled={activeReviewStepLocked} autoComplete="off" />
      </div>
      <div className="field">
        <label>Cover Image</label>
        <input type="file" ref={coverRef} style={{ display: 'none' }} accept=".jpg,.jpeg,.png" onChange={handleCoverUpload} />
        <div className="flex gap-2" style={{ flexWrap: 'wrap' }}>
          <button className="btn btn-ghost btn-sm" disabled={activeReviewStepLocked} onClick={() => coverRef.current.click()}>
            {meta.cover_image ? 'Change Cover' : '+ Upload Cover'}
          </button>
          {meta.cover_image && (
            <button className="btn btn-ghost btn-sm" disabled={activeReviewStepLocked} onClick={handleClearCover} style={{ color: 'var(--danger)' }}>
              Clear Cover
            </button>
          )}
        </div>
        {meta.cover_image && <div className="text-xs text-success mt-1 truncate">{meta.cover_image}</div>}
      </div>
    </div>
  )

  const renderCleanupReviewPanel = () => (
    <div className="glass" style={{ padding: 14, borderRadius: 'var(--radius-sm)' }} data-tip-anchor="cleaning-review">
      <div className="flex items-start justify-between gap-3" style={{ marginBottom: 10 }}>
        <div>
          <div className="section-title">Cleanup Review</div>
          <div className="text-xs text-muted">{selectedEval?.title || ch?.title || `Chapter ${selectedIdx + 1}`}</div>
        </div>
        {selectedEval && (
          <div className="flex gap-2" style={{ flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            <span className="badge">{selectedEval.accepted_count ?? 0} accepted</span>
            <span className="badge" style={{ color: selectedEval.fallback_count ? 'var(--warning, #f59e0b)' : 'var(--text-secondary)' }}>{selectedEval.fallback_count ?? 0} fallback</span>
          </div>
        )}
      </div>
      {selectedEval ? (
        <>
          <div className="flex gap-1" style={{ flexWrap: 'wrap', marginBottom: 10 }}>
            {filterOptions.map(([value, label]) => (
              <button
                key={value}
                type="button"
                className={`btn btn-sm ${reviewFilter === value ? 'btn-primary' : 'btn-ghost'}`}
                style={{ fontSize: 11, padding: '4px 8px' }}
                onClick={() => setReviewFilter(value)}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="flex gap-2" style={{ flexWrap: 'wrap', marginBottom: 10 }}>
            <button
              className="btn btn-ghost btn-sm"
              disabled={!fallbackVisibleChunks.length || batchRetrying || activeReviewStepLocked}
              onClick={() => handleBatchRedoVisible(fallbackVisibleChunks)}
            >
              {batchRetrying ? 'Retrying...' : `Redo fallback (${fallbackVisibleChunks.length})`}
            </button>
            <button
              className="btn btn-ghost btn-sm"
              disabled={!lowRiskVisibleChunks.length || activeReviewStepLocked}
              onClick={() => handleApplyLowRiskCandidates(visibleReviewChunks)}
            >
              Apply low-risk ({lowRiskVisibleChunks.length})
            </button>
          </div>
          <div style={{ display: 'grid', gap: 10 }}>
            {visibleReviewChunks.map(chunk => (
              <div key={chunk.chunk_id} className="glass" style={{ padding: 10, borderRadius: 'var(--radius-sm)' }}>
                <div className="flex justify-between items-start gap-2">
                  <div className="text-sm" style={{ fontWeight: 700 }}>Passage {chunk.chunk_id + 1}</div>
                  <div className="flex gap-1" style={{ flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                    <span className="text-xs" style={{ color: riskColor(chunk.risk_level), fontWeight: 700 }}>{riskLabel(chunk.risk_level)}</span>
                    <span className="text-xs" style={{ color: chunk.status === 'fallback' ? 'var(--warning, #f59e0b)' : 'var(--success)', fontWeight: 700 }}>{statusLabel(chunk.status)}</span>
                  </div>
                </div>
                <div className="text-xs text-muted mt-1">
                  Words {chunk.metrics?.source_word_count ?? 0} -&gt; {chunk.metrics?.output_word_count ?? 0} · {formatRatio(chunk.metrics?.word_count_ratio)}
                </div>
                {chunk.integrity_issues?.length > 0 && (
                  <div className="text-xs mt-1" style={{ color: 'var(--warning, #f59e0b)', lineHeight: 1.45 }}>
                    {chunk.integrity_issues.map(formatCleaningIssue).join('; ')}
                  </div>
                )}
                <div className="flex gap-2 mt-2" style={{ flexWrap: 'wrap' }}>
                  <button
                    className="btn btn-ghost btn-sm"
                    onClick={() => handleRedoChunk(chunk)}
                    disabled={retryingChunk === `${chunk.chapter_index}:${chunk.chunk_id}` || activeReviewStepLocked}
                  >
                    {retryingChunk === `${chunk.chapter_index}:${chunk.chunk_id}` ? 'Retrying...' : 'Redo'}
                  </button>
                  {chunk.variants?.length > 0 && (
                    <button
                      className="btn btn-ghost btn-sm"
                      onClick={() => setComparison({ chapter_index: chunk.chapter_index, chunk, variant: chunk.variants[chunk.variants.length - 1] })}
                    >
                      Compare
                    </button>
                  )}
                </div>
              </div>
            ))}
            {!visibleReviewChunks.length && <div className="text-sm text-muted">No cleanup passages match this filter.</div>}
          </div>
        </>
      ) : (
        <div className="text-sm text-muted">No LLM cleaning data for this chapter.</div>
      )}
    </div>
  )

  const renderChapterEditor = (includeMetadata = false) => (
    <div style={{ flex: 1, overflow: 'hidden', display: 'grid', gridTemplateColumns: includeMetadata ? 'minmax(0, 1.6fr) minmax(280px, 0.9fr)' : 'minmax(0, 1fr)', gap: includeMetadata ? 12 : 0, padding: includeMetadata ? 12 : 0 }}>
      <div className="flex flex-col" style={{ minWidth: 0, overflow: 'hidden', border: includeMetadata ? '1px solid var(--glass-border)' : 'none', borderRadius: includeMetadata ? 'var(--radius-sm)' : 0 }}>
        <div className="p-3" style={{ borderBottom: '1px solid var(--glass-border)' }}>
          <input
            type="text"
            value={ch.title}
            onChange={e => updateSelectedChapterTitle(e.target.value)}
            disabled={!canEditChapters}
            placeholder="Chapter title"
            autoComplete="off"
            style={{ fontWeight: 600, fontSize: 15 }}
          />
        </div>
        <textarea
          ref={textareaRef}
          value={ch.text}
          onChange={e => updateSelectedChapterText(e.target.value)}
          disabled={activeReviewStepLocked}
          placeholder="Chapter text..."
          style={{
            flex: 1, resize: 'none', border: 'none', borderRadius: 0,
            background: 'transparent', padding: '16px', minHeight: includeMetadata ? 360 : 'auto',
            fontFamily: 'var(--font-mono)', fontSize: 13, lineHeight: 1.7,
          }}
        />
      </div>
      {includeMetadata && <div style={{ overflow: 'auto', minWidth: 0 }}>{renderMetadataForm(true)}</div>}
    </div>
  )

  return (
    <div className="step-card" style={{ padding: 0, overflow: 'hidden' }}>
      {/* Toolbar */}
      <div className="flex items-center justify-between p-4" style={{ borderBottom: '1px solid var(--glass-border)' }}>
        <div>
          <div className="step-title">Review Chapters</div>
          <div className="step-desc">{chapters.length} chapter{chapters.length !== 1 ? 's' : ''} · {activeReviewStep?.description || 'Step through the review flow'}</div>
        </div>
        <div className="flex gap-2">
          <span className={`save-status save-status-${saveStatus}`}>
            {saving ? 'Saving...' : saveStatus === 'dirty' ? 'Unsaved changes' : saveStatus === 'failed' ? 'Save failed' : 'Saved'}
          </span>
          {hasCleaningEval && (
            <button className="btn btn-ghost btn-sm" onClick={handleLoadCleaningReport}>
              Book Cleanup Report
            </button>
          )}
          {debugPrompt && (
            <button className="btn btn-ghost btn-sm" onClick={() => setShowPromptModal(true)} title="View prompt sent to LLM">
              🔬 View Prompt
            </button>
          )}
          <button className="btn btn-ghost btn-sm" data-tip-anchor="split-button" disabled={!canEditChapters} onClick={splitAtCursor} title="Split chapter at cursor position">
            ✂ Split Here
          </button>
        </div>
      </div>

      <div className="flex items-center justify-between" style={{ padding: '10px 16px', borderBottom: '1px solid var(--glass-border)', gap: 12 }}>
        <div className="flex gap-2" style={{ flexWrap: 'wrap' }}>
          {reviewSteps.map((step, index) => {
            const isActive = step.id === activeReviewStepId
            const isCompleted = completedReviewStepSet.has(step.id)
            const isLocked = !isActive && !isCompleted
            return (
              <div key={step.id} className="flex gap-1" style={{ alignItems: 'center' }}>
                <button
                  type="button"
                  className={`btn btn-sm ${isActive ? 'btn-primary' : 'btn-ghost'}`}
                  style={{ padding: '6px 10px', opacity: isLocked ? 0.55 : 1 }}
                  disabled={isLocked}
                  onClick={() => isCompleted ? goReviewStep(step.id) : undefined}
                  title={isLocked ? 'Complete earlier Review steps first' : step.description}
                >
                  <span style={{ opacity: 0.75 }}>{isCompleted ? '✓' : index + 1}</span>
                  {step.label}
                </button>
                {isCompleted && (
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    style={{ padding: '6px 8px' }}
                    onClick={() => unlockReviewStep(step.id)}
                    title="Unlock this step and reset later Review steps"
                  >
                    Unlock
                  </button>
                )}
              </div>
            )
          })}
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
                    {getChapterEval(i).fallback_count} fallback used
                  </div>
                )}
              </div>
              <div className="flex flex-col gap-1">
                <button className="btn btn-ghost btn-icon" style={{ padding: '2px 4px', fontSize: 10 }}
                  disabled={!canEditChapters}
                  onClick={e => { e.stopPropagation(); moveChapter(i, -1) }}>▲</button>
                <button className="btn btn-ghost btn-icon" style={{ padding: '2px 4px', fontSize: 10 }}
                  disabled={!canEditChapters}
                  onClick={e => { e.stopPropagation(); moveChapter(i, 1) }}>▼</button>
              </div>
              <button
                className="btn btn-ghost btn-icon"
                style={{ padding: '2px 5px', fontSize: 11, color: 'var(--danger)' }}
                disabled={!canEditChapters}
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
            activeReviewStepId === REVIEW_STEP_IDS.CLEANUP_METADATA ? (
              <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 14 }}>
                  {renderCleanupReviewPanel()}
                  {renderMetadataForm(true)}
                </div>
              </div>
            ) : [REVIEW_STEP_IDS.RUN_MODERNIZATION, REVIEW_STEP_IDS.REVIEW_MODERNIZATION].includes(activeReviewStepId) && showModernizationTools ? (
              <div className="flex flex-col" style={{ flex: 1, overflow: 'hidden' }} data-tip-anchor="modernization-review">
                <div className="p-4" style={{ borderBottom: '1px solid var(--glass-border)', flexShrink: 0 }}>
                  <div className="flex items-start justify-between gap-3">
                    <div style={{ minWidth: 0 }}>
                      <div className="text-sm text-muted">Modernization Review</div>
                      <div className="step-title truncate" style={{ fontSize: 18 }}>{selectedModernizationEval?.title || ch.title || `Chapter ${selectedIdx + 1}`}</div>
                    </div>
                    {selectedModernizationEval && (
                      <div className="flex gap-2" style={{ flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                        <span className="badge">{visibleModernizationChunks.length} passages</span>
                        <span className="badge" style={{ color: selectedModernizationCount ? 'var(--success)' : 'var(--text-secondary)' }}>{selectedModernizationCount} selected</span>
                        {modernizationReviewCount > 0 && <span className="badge" style={{ color: 'var(--warning, #f59e0b)' }}>{modernizationReviewCount} review</span>}
                      </div>
                    )}
                  </div>
                  {modernizationSessionStale && (
                    <div className="text-xs" style={{ color: 'var(--warning, #f59e0b)', lineHeight: 1.45, marginTop: 10 }}>
                      This modernization review was generated from an earlier version of the chapter. Regenerate modernization to use the latest edits.
                    </div>
                  )}
                </div>
                <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
                  {renderModernizationControls()}
                  {activeReviewStepId === REVIEW_STEP_IDS.RUN_MODERNIZATION ? (
                    <div className="glass" style={{ padding: 18, borderRadius: 'var(--radius-sm)' }}>
                      <div className="section-title" style={{ marginBottom: 10 }}>Modernization Pass</div>
                      <div className="text-sm text-muted">Generate or regenerate modernization candidates before moving to candidate review.</div>
                    </div>
                  ) : selectedModernizationEval ? (
                    visibleModernizationChunks.length ? (
                      visibleModernizationChunks.map(renderModernizationReviewCard)
                    ) : (
                      <div className="text-center text-muted p-6">No modernization candidates for this chapter yet.</div>
                    )
                  ) : (
                    <div className="glass" style={{ padding: 18, borderRadius: 'var(--radius-sm)' }}>
                      <div className="section-title" style={{ marginBottom: 10 }}>No Modernization Session</div>
                      <div className="text-sm text-muted">Use the controls above to generate reviewable modernization candidates.</div>
                    </div>
                  )}
                </div>
              </div>
            ) : activeReviewStepId === REVIEW_STEP_IDS.FINAL_REVIEW ? (
              renderChapterEditor(true)
            ) : (
              renderChapterEditor(false)
            )
          ) : (
            <div className="text-center text-muted p-6">Select a chapter to edit</div>
          )}
        </div>
      </div>

      <div className="step-nav" style={{ padding: '16px 24px' }}>
        <button className="btn btn-ghost" onClick={activeReviewStepIndex > 0 ? () => goReviewStep(reviewSteps[activeReviewStepIndex - 1].id) : onBack}>
          {activeReviewStepIndex > 0 ? '← Previous review step' : '← Back'}
        </button>
        <button
          className="btn btn-primary btn-lg"
          onClick={advanceReviewFlow}
          disabled={saving}
        >
          {reviewPrimaryLabel} →
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
                  Passage {(comparison.chunk?.chunk_id ?? 0) + 1} · {comparison.variant?.profile} · {statusLabel(comparison.variant?.status)} · {riskLabel(comparison.variant?.risk_level)}
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

      {showModernizationCommitPreview && selectedModernizationEval && (
        <div
          style={{
            position: 'fixed', inset: 0, zIndex: 1000,
            background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
          onClick={() => setShowModernizationCommitPreview(false)}
        >
          <div
            className="glass"
            style={{ width: '88vw', maxWidth: 1080, maxHeight: '84vh', display: 'flex', flexDirection: 'column', borderRadius: 'var(--radius)', overflow: 'hidden' }}
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center justify-between p-4" style={{ borderBottom: '1px solid var(--glass-border)', flexShrink: 0 }}>
              <div>
                <div style={{ fontWeight: 600, fontSize: 15 }}>Modernization Commit Preview</div>
                <div className="text-xs text-muted mt-0.5">
                  {selectedModernizationEval.title || ch?.title || `Chapter ${selectedIdx + 1}`} · {selectedModernizationCount} selected
                </div>
              </div>
              <button className="btn btn-ghost btn-sm" onClick={() => setShowModernizationCommitPreview(false)}>✕</button>
            </div>
            {modernizationSessionStale && (
              <div className="text-xs" style={{ color: 'var(--warning, #f59e0b)', padding: '10px 16px 0', lineHeight: 1.45 }}>
                This preview is built from the modernization source snapshot, not the current edited chapter text.
              </div>
            )}
            <div className="flex gap-3" style={{ padding: 16, overflow: 'hidden', flex: 1 }}>
              <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
                <div className="section-title" style={{ marginBottom: 6 }}>Source Snapshot</div>
                <pre style={{ flex: 1, overflow: 'auto', fontFamily: 'var(--font-mono)', fontSize: 12, lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word', background: 'rgba(0,0,0,0.2)', borderRadius: 'var(--radius-sm)', padding: 12 }}>
                  {selectedModernizationSourcePreview || 'No source snapshot available.'}
                </pre>
              </div>
              <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
                <div className="section-title" style={{ marginBottom: 6 }}>After Commit</div>
                <pre style={{ flex: 1, overflow: 'auto', fontFamily: 'var(--font-mono)', fontSize: 12, lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word', background: 'rgba(0,0,0,0.2)', borderRadius: 'var(--radius-sm)', padding: 12 }}>
                  {selectedModernizationCommitPreview || selectedModernizationSourcePreview || 'No commit text available.'}
                </pre>
              </div>
            </div>
            <div className="flex justify-end gap-2 p-4" style={{ borderTop: '1px solid var(--glass-border)' }}>
              <button className="btn btn-ghost" onClick={() => setShowModernizationCommitPreview(false)}>Close</button>
              <button
                className="btn btn-primary"
                disabled={!selectedModernizationCount || committingModernization || selectedModernizationIsCommitted}
                onClick={handleCommitModernization}
              >
                {committingModernization ? 'Committing…' : 'Commit selected changes'}
              </button>
            </div>
          </div>
        </div>
      )}

      {modernizationComparison && (
        <div
          style={{
            position: 'fixed', inset: 0, zIndex: 1000,
            background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
          onClick={() => setModernizationComparison(null)}
        >
          <div
            className="glass"
            style={{ width: '86vw', maxWidth: 980, maxHeight: '82vh', display: 'flex', flexDirection: 'column', borderRadius: 'var(--radius)', overflow: 'hidden' }}
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center justify-between p-4" style={{ borderBottom: '1px solid var(--glass-border)', flexShrink: 0 }}>
              <div>
                <div style={{ fontWeight: 600, fontSize: 15 }}>Compare Modernized Candidate</div>
                <div className="text-xs text-muted mt-0.5">
                  Passage {(modernizationComparison.chunk?.chunk_id ?? 0) + 1} · {modernizationComparison.variant?.profile} · {riskLabel(modernizationComparison.variant?.risk_level)}
                </div>
              </div>
              <button className="btn btn-ghost btn-sm" onClick={() => setModernizationComparison(null)}>✕</button>
            </div>
            <div className="flex gap-3" style={{ padding: 16, overflow: 'hidden', flex: 1 }}>
              <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
                <div className="section-title" style={{ marginBottom: 6 }}>Current Text</div>
                <pre style={{ flex: 1, overflow: 'auto', fontFamily: 'var(--font-mono)', fontSize: 12, lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word', background: 'rgba(0,0,0,0.2)', borderRadius: 'var(--radius-sm)', padding: 12 }}>
                  {modernizationComparison.chunk?.accepted_text || modernizationComparison.chunk?.source_text || ''}
                </pre>
              </div>
              <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
                <div className="section-title" style={{ marginBottom: 6 }}>Modernized Candidate</div>
                <pre style={{ flex: 1, overflow: 'auto', fontFamily: 'var(--font-mono)', fontSize: 12, lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word', background: 'rgba(0,0,0,0.2)', borderRadius: 'var(--radius-sm)', padding: 12 }}>
                  {modernizationComparison.variant?.accepted_text || modernizationComparison.variant?.candidate_text || ''}
                </pre>
              </div>
            </div>
            {modernizationComparison.variant?.integrity_issues?.length > 0 && (
              <div className="text-xs" style={{ color: 'var(--warning, #f59e0b)', padding: '0 16px 12px' }}>
                {modernizationComparison.variant.integrity_issues.join('; ')}
              </div>
            )}
            <div className="flex justify-end gap-2 p-4" style={{ borderTop: '1px solid var(--glass-border)' }}>
              <button className="btn btn-ghost" onClick={() => setModernizationComparison(null)}>Keep Current</button>
              {appliedModernizationVariant(modernizationComparison.chunk) && (
                <button className="btn btn-ghost" onClick={() => clearModernizationCandidate(modernizationComparison.chunk)}>
                  Unuse
                </button>
              )}
              <button
                className="btn btn-primary"
                disabled={selectedModernizationIsCommitted}
                onClick={() => selectModernizationCandidate()}
              >
                Use This
              </button>
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
                <div style={{ fontWeight: 600, fontSize: 15 }}>Book Cleanup Report</div>
                <div className="text-xs text-muted mt-0.5">{cleaningReport.project?.title} · {cleaningReport.provider || 'heuristic'} · {cleaningReport.profile}</div>
              </div>
              <button className="btn btn-ghost btn-sm" onClick={() => setCleaningReport(null)}>✕</button>
            </div>
            <div style={{ overflow: 'auto', padding: 16 }}>
              <div className="section-title">Cleanup Warnings</div>
              <div style={{ marginBottom: 14 }}>
                {reportWarningItems.map(item => (
                  <div key={item.key} style={{ padding: 10, borderRadius: 'var(--radius-sm)', marginBottom: 8, background: 'var(--surface-elevated, rgba(255,255,255,0.06))', border: '1px solid var(--glass-border)' }}>
                    <div className="text-sm" style={{ color: 'var(--warning, #f59e0b)', fontWeight: 600 }}>{item.label}</div>
                    <div className="text-xs text-muted mt-1">{item.chapterTitle}</div>
                    {item.snippet && (
                      <div className="text-xs mt-1" style={{ lineHeight: 1.5 }}>
                        <span className="text-muted">Context: </span>{item.snippet}
                      </div>
                    )}
                  </div>
                ))}
                {!reportWarningItems.length && (
                  <div className="text-sm text-secondary mb-3">No cleanup warnings were reported.</div>
                )}
              </div>
              <div className="flex gap-2" style={{ marginBottom: 12 }}>
                <div style={{ flex: 1, padding: 10, borderRadius: 'var(--radius-sm)', background: 'var(--surface-elevated, rgba(255,255,255,0.06))', border: '1px solid var(--glass-border)' }}>
                  <div className="text-xs text-muted">Passages checked</div>
                  <div style={{ fontWeight: 700 }}>{cleaningReport.total_chunks}</div>
                </div>
                <div style={{ flex: 1, padding: 10, borderRadius: 'var(--radius-sm)', background: 'var(--surface-elevated, rgba(255,255,255,0.06))', border: '1px solid var(--glass-border)' }}>
                  <div className="text-xs text-muted">Fallbacks used</div>
                  <div style={{ fontWeight: 700 }}>{cleaningReport.total_fallbacks}</div>
                </div>
                <div style={{ flex: 1, padding: 10, borderRadius: 'var(--radius-sm)', background: 'var(--surface-elevated, rgba(255,255,255,0.06))', border: '1px solid var(--glass-border)' }}>
                  <div className="text-xs text-muted">Candidates applied</div>
                  <div style={{ fontWeight: 700 }}>{cleaningReport.applied_variants}</div>
                </div>
              </div>
              <div className="section-title">Advanced Summary</div>
              <div className="text-sm text-secondary mb-3">
                Low risk {cleaningReport.risk_counts?.low ?? 0} · Review {cleaningReport.risk_counts?.medium ?? 0} · Needs review {cleaningReport.risk_counts?.high ?? 0}
              </div>
              <div className="section-title">Chapters</div>
              {cleaningReport.chapters?.map(chapter => (
                <div key={chapter.chapter_index} style={{ padding: 10, borderRadius: 'var(--radius-sm)', marginBottom: 8, background: 'var(--surface-elevated, rgba(255,255,255,0.06))', border: '1px solid var(--glass-border)' }}>
                  <div className="text-sm" style={{ fontWeight: 600 }}>{chapter.title || `Chapter ${chapter.chapter_index + 1}`}</div>
                  <div className="text-xs text-muted mt-1">
                    {chapter.chunk_count} passages checked · {chapter.fallback_count} fallbacks used · needs review {chapter.risk_counts?.high ?? 0}
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
