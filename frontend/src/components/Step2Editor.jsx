import { useState, useEffect, useLayoutEffect, useRef, useCallback, useMemo } from 'react'
import {
  BookOpen,
  Volume2,
  VolumeX,
  Plus,
  Trash2,
  Check,
  FileSearch,
  Sparkles,
  GripVertical,
  Scissors,
  ArrowRight,
  ArrowLeft,
  AlertTriangle,
  AlignLeft,
  Layers,
  Undo2,
  ChevronDown,
  ChevronUp,
  RotateCcw,
  Pencil,
} from 'lucide-react'
import {
  getProject,
  getChapters,
  saveChapters,
  getModernizationEval,
  getModernizationProfiles,
} from '../api'
import BookDetailsModal from './BookDetailsModal'
import SourceInspector from './SourceInspector'
import ModernizationDrawer from './ModernizationDrawer'

export default function Step2Editor({
  projectId,
  isActive,
  onNext,
  onBack,
  toast,
}) {
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
  })
  const [coverImgErr, setCoverImgErr] = useState(false)
  const [chapters, setChapters] = useState([])
  const [selectedIdx, setSelectedIdx] = useState(0)
  const [selectedChapterIds, setSelectedChapterIds] = useState(new Set())
  const [lastClickedIdx, setLastClickedIdx] = useState(null)
  const [editorMode, setEditorMode] = useState('blocks') // 'blocks' | 'raw'
  const [filterQuery, setFilterQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [saveStatus, setSaveStatus] = useState('saved') // 'saved' | 'saving' | 'unsaved'

  // Modals / Drawers state
  const [showBookDetails, setShowBookDetails] = useState(false)
  const [showModernize, setShowModernize] = useState(false)
  const [inspectorOpen, setInspectorOpen] = useState(false)
  const [inspectorPinned, setInspectorPinned] = useState(false)
  const [inspectorPage, setInspectorPage] = useState(1)
  const [inspectorHighlightBlockId, setInspectorHighlightBlockId] = useState(null)
  const [apparatusTab, setApparatusTab] = useState('footnotes') // 'footnotes' | 'marginalia' | 'callouts'
  const [apparatusCollapsed, setApparatusCollapsed] = useState(false)

  // Modernization
  const [modernizationEval, setModernizationEval] = useState(null)
  const [modernizationProfiles, setModernizationProfiles] = useState([])

  // Undo history for destructive operations (merge, split, bulk delete)
  const [undoSnapshot, setUndoSnapshot] = useState(null)

  // Drag and drop state
  const [draggedIdx, setDraggedIdx] = useState(null)
  const [dragOverIdx, setDragOverIdx] = useState(null)

  // Warning diff accordion state (default open for review)
  const [diffClosedBlockIds, setDiffClosedBlockIds] = useState(new Set())
  const toggleDiff = (blockId) => {
    setDiffClosedBlockIds(prev => {
      const next = new Set(prev)
      if (next.has(blockId)) next.delete(blockId)
      else next.add(blockId)
      return next
    })
  }

  // Focus management for block splitting/merging
  const blockRefs = useRef({})
  const focusTargetRef = useRef(null) // { blockId, cursorPosition }

  const saveTimerRef = useRef(null)
  const dirtyRef = useRef(false)

  // Initial load
  useEffect(() => {
    if (!projectId || !isActive) return

    /* eslint-disable react-hooks/set-state-in-effect */
    setLoading(true)
    /* eslint-enable react-hooks/set-state-in-effect */
    Promise.all([
      getProject(projectId),
      getChapters(projectId),
      getModernizationEval(projectId).catch(() => null),
      getModernizationProfiles().catch(() => []),
    ])
      .then(([p, chs, modernEval, modernProfiles]) => {
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
        })
        setChapters(chs || [])
        setModernizationEval(modernEval || null)
        setModernizationProfiles(modernProfiles || [])
        setSelectedIdx(0)
        setSaveStatus('saved')
        dirtyRef.current = false
      })
      .catch(e => {
        if (toast) toast(e.message || 'Failed to load project', 'error')
      })
      .finally(() => setLoading(false))
  }, [projectId, isActive, toast])

  // Debounced auto-save for chapters
  const scheduleAutoSave = useCallback((newChapters) => {
    dirtyRef.current = true
    setSaveStatus('unsaved')
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current)

    saveTimerRef.current = setTimeout(async () => {
      if (!projectId || !dirtyRef.current) return
      setSaveStatus('saving')
      try {
        await saveChapters(projectId, newChapters)
        dirtyRef.current = false
        setSaveStatus('saved')
      } catch (err) {
        setSaveStatus('unsaved')
        if (toast) toast(err.message || 'Auto-save failed', 'error')
      }
    }, 600)
  }, [projectId, toast])

  // Immediate save helper
  const saveNow = useCallback(async (newChapters) => {
    if (!projectId) return
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
    setSaveStatus('saving')
    try {
      await saveChapters(projectId, newChapters)
      dirtyRef.current = false
      setSaveStatus('saved')
    } catch (err) {
      setSaveStatus('unsaved')
      if (toast) toast(err.message || 'Failed to save chapters', 'error')
    }
  }, [projectId, toast])

  // Apply focus target after block split/merge
  useEffect(() => {
    if (focusTargetRef.current) {
      const { blockId, cursorPosition } = focusTargetRef.current
      const el = blockRefs.current[blockId]
      if (el) {
        el.focus()
        if (typeof cursorPosition === 'number') {
          el.setSelectionRange(cursorPosition, cursorPosition)
        }
      }
      focusTargetRef.current = null
    }
  }, [chapters])

  const currentChapter = chapters[selectedIdx] || null

  // Word count & narration estimates
  const currentChapterStats = useMemo(() => {
    if (!currentChapter) return { words: 0, minutes: 0 }
    const text = currentChapter.blocks?.length
      ? currentChapter.blocks.filter(b => !b.audio_muted).map(b => b.text).join(' ')
      : (currentChapter.text || '')
    const words = text.split(/\s+/).filter(Boolean).length
    const minutes = Math.max(1, Math.round(words / 150))
    return { words, minutes }
  }, [currentChapter])

  const bookTotalStats = useMemo(() => {
    let totalWords = 0
    chapters.forEach(ch => {
      if (ch.include_in_audio !== false) {
        const text = ch.blocks?.length
          ? ch.blocks.filter(b => !b.audio_muted).map(b => b.text).join(' ')
          : (ch.text || '')
        totalWords += text.split(/\s+/).filter(Boolean).length
      }
    })
    const totalMinutes = Math.max(1, Math.round(totalWords / 150))
    return { totalWords, totalMinutes }
  }, [chapters])

  // Open PDF Inspector to specific page
  const inspectPage = useCallback((pageNum, blockId = null) => {
    if (pageNum && pageNum > 0) {
      setInspectorPage(pageNum)
    }
    if (blockId) {
      setInspectorHighlightBlockId(blockId)
    }
    setInspectorOpen(true)
  }, [])

  // ── Outline & Chapter Management ──────────────────────────────────────────

  const handleAddChapter = () => {
    const newId = `ch_${Date.now()}`
    const newChapter = {
      id: newId,
      order: chapters.length + 1,
      title: `Chapter ${chapters.length + 1}`,
      include_in_audio: true,
      text: '',
      blocks: [
        {
          id: `${newId}_b1`,
          source_page: null,
          text: '',
          audio_muted: false,
          warning: null,
        },
      ],
    }
    const updated = [...chapters, newChapter]
    setChapters(updated)
    setSelectedIdx(updated.length - 1)
    saveNow(updated)
  }

  const handleDeleteChapter = (idx, e) => {
    if (e) e.stopPropagation()
    const target = chapters[idx]
    if (!window.confirm(`Delete "${target?.title || 'Chapter'}"?`)) return

    setUndoSnapshot([...chapters])
    const updated = chapters.filter((_, i) => i !== idx).map((ch, i) => ({
      ...ch,
      order: i + 1,
    }))
    setChapters(updated)
    setSelectedIdx(prev => Math.max(0, Math.min(prev, updated.length - 1)))
    saveNow(updated)
    if (toast) toast('Chapter deleted. Undo available in toolbar.', 'info')
  }

  const handleToggleChapterAudio = (idx, e) => {
    if (e) e.stopPropagation()
    const updated = [...chapters]
    const currentMuted = updated[idx].include_in_audio === false
    updated[idx] = { ...updated[idx], include_in_audio: currentMuted }
    setChapters(updated)
    scheduleAutoSave(updated)
  }

  const handleTitleChange = (newTitle) => {
    if (!currentChapter) return
    const updated = [...chapters]
    updated[selectedIdx] = { ...updated[selectedIdx], title: newTitle }
    setChapters(updated)
    scheduleAutoSave(updated)
  }

  // Multi-select for bulk actions
  const handleCheckboxClick = (idx, e) => {
    e.stopPropagation()
    const targetId = chapters[idx].id
    const nextSet = new Set(selectedChapterIds)

    if (e.shiftKey && lastClickedIdx !== null) {
      const start = Math.min(lastClickedIdx, idx)
      const end = Math.max(lastClickedIdx, idx)
      for (let i = start; i <= end; i++) {
        nextSet.add(chapters[i].id)
      }
    } else {
      if (nextSet.has(targetId)) {
        nextSet.delete(targetId)
      } else {
        nextSet.add(targetId)
      }
    }

    setLastClickedIdx(idx)
    setSelectedChapterIds(nextSet)
  }

  // Bulk Merge
  const handleBulkMerge = () => {
    if (selectedChapterIds.size < 2) return
    const selectedIndices = chapters
      .map((ch, i) => (selectedChapterIds.has(ch.id) ? i : -1))
      .filter(i => i !== -1)
      .sort((a, b) => a - b)

    const firstIdx = selectedIndices[0]
    const firstChapter = chapters[firstIdx]

    // Create undo snapshot
    setUndoSnapshot([...chapters])

    // Merge blocks sequentially into first chapter
    const mergedBlocks = []
    selectedIndices.forEach(idx => {
      const ch = chapters[idx]
      if (ch.blocks && ch.blocks.length) {
        mergedBlocks.push(...ch.blocks)
      } else if (ch.text) {
        mergedBlocks.push({
          id: `${ch.id}_b1`,
          source_page: null,
          text: ch.text,
          audio_muted: false,
          warning: null,
        })
      }
    })

    const mergedChapter = {
      ...firstChapter,
      blocks: mergedBlocks,
      text: mergedBlocks.map(b => b.text).join('\n\n'),
    }

    const updated = chapters
      .filter((_, i) => i === firstIdx || !selectedChapterIds.has(chapters[i].id))
      .map((ch, i) => (ch.id === firstChapter.id ? mergedChapter : { ...ch, order: i + 1 }))

    setChapters(updated)
    setSelectedIdx(updated.findIndex(ch => ch.id === firstChapter.id))
    setSelectedChapterIds(new Set())
    saveNow(updated)

    if (toast) {
      toast(`Merged ${selectedIndices.length} chapters into "${firstChapter.title}".`, 'success')
    }
  }

  // Bulk Delete
  const handleBulkDelete = () => {
    if (!selectedChapterIds.size) return
    if (!window.confirm(`Delete ${selectedChapterIds.size} selected chapter(s)?`)) return

    setUndoSnapshot([...chapters])
    const updated = chapters
      .filter(ch => !selectedChapterIds.has(ch.id))
      .map((ch, i) => ({ ...ch, order: i + 1 }))

    setChapters(updated)
    setSelectedIdx(0)
    setSelectedChapterIds(new Set())
    saveNow(updated)

    if (toast) toast(`Deleted ${selectedChapterIds.size} chapters.`, 'info')
  }

  // Undo Snapshot
  const handleUndo = () => {
    if (!undoSnapshot) return
    setChapters(undoSnapshot)
    saveNow(undoSnapshot)
    setUndoSnapshot(null)
    if (toast) toast('Action undone.', 'success')
  }

  // Drag and Drop reordering
  const handleDragStart = (idx, e) => {
    setDraggedIdx(idx)
    e.dataTransfer.effectAllowed = 'move'
  }

  const handleDragOver = (idx, e) => {
    e.preventDefault()
    if (draggedIdx === null || draggedIdx === idx) return
    setDragOverIdx(idx)
  }

  const handleDrop = (idx) => {
    if (draggedIdx === null || draggedIdx === idx) {
      setDraggedIdx(null)
      setDragOverIdx(null)
      return
    }

    const updated = [...chapters]
    const [moved] = updated.splice(draggedIdx, 1)
    updated.splice(idx, 0, moved)

    const reordered = updated.map((ch, i) => ({ ...ch, order: i + 1 }))
    setChapters(reordered)
    setSelectedIdx(idx)
    setDraggedIdx(null)
    setDragOverIdx(null)
    saveNow(reordered)
  }

  // ── Fluid Block Editor Interactions ───────────────────────────────────────

  // Auto-resize all active block textareas to prevent vertical clipping/cutoff
  useLayoutEffect(() => {
    if (!currentChapter?.blocks) return
    currentChapter.blocks.forEach(b => {
      const el = blockRefs.current[b.id]
      if (el) {
        el.style.height = 'auto'
        el.style.height = `${Math.max(el.scrollHeight, 28)}px`
      }
    })
  }, [currentChapter?.id, currentChapter?.blocks?.length])

  const handleBlockTextChange = (bIdx, newText) => {
    if (!currentChapter) return
    const block = currentChapter.blocks[bIdx]
    const updatedBlocks = [...(currentChapter.blocks || [])]
    updatedBlocks[bIdx] = { ...updatedBlocks[bIdx], text: newText }

    const updatedChapters = [...chapters]
    updatedChapters[selectedIdx] = {
      ...currentChapter,
      blocks: updatedBlocks,
      text: updatedBlocks.map(b => b.text).join('\n\n'),
    }
    setChapters(updatedChapters)
    scheduleAutoSave(updatedChapters)

    const el = blockRefs.current[block.id]
    if (el) {
      el.style.height = 'auto'
      el.style.height = `${Math.max(el.scrollHeight, 28)}px`
    }
  }

  const handleToggleBlockMute = (bIdx) => {
    if (!currentChapter) return
    const updatedBlocks = [...(currentChapter.blocks || [])]
    const currentMuted = !!updatedBlocks[bIdx].audio_muted
    updatedBlocks[bIdx] = { ...updatedBlocks[bIdx], audio_muted: !currentMuted }

    const updatedChapters = [...chapters]
    updatedChapters[selectedIdx] = {
      ...currentChapter,
      blocks: updatedBlocks,
    }
    setChapters(updatedChapters)
    scheduleAutoSave(updatedChapters)
  }

  // Keyboard ergonomics: Enter to split, Backspace to merge
  const handleBlockKeyDown = (bIdx, e) => {
    const el = e.currentTarget
    const selStart = el.selectionStart
    const selEnd = el.selectionEnd
    const val = el.value
    const block = currentChapter.blocks[bIdx]

    // Enter without Shift -> Split block into two blocks
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      const textBefore = val.slice(0, selStart)
      const textAfter = val.slice(selEnd)

      const newBlockId = `blk_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`
      const newBlock = {
        id: newBlockId,
        source_page: block.source_page || null,
        text: textAfter,
        audio_muted: false,
        warning: null,
      }

      const updatedBlocks = [...currentChapter.blocks]
      updatedBlocks[bIdx] = { ...block, text: textBefore }
      updatedBlocks.splice(bIdx + 1, 0, newBlock)

      focusTargetRef.current = { blockId: newBlockId, cursorPosition: 0 }

      const updatedChapters = [...chapters]
      updatedChapters[selectedIdx] = {
        ...currentChapter,
        blocks: updatedBlocks,
        text: updatedBlocks.map(b => b.text).join('\n\n'),
      }
      setChapters(updatedChapters)
      scheduleAutoSave(updatedChapters)
      return
    }

    // Backspace at start of block -> Merge with previous block
    if (e.key === 'Backspace' && selStart === 0 && selEnd === 0 && bIdx > 0) {
      e.preventDefault()
      const prevBlock = currentChapter.blocks[bIdx - 1]
      const prevTextLen = prevBlock.text.length
      const mergedText = prevBlock.text + val

      const updatedBlocks = [...currentChapter.blocks]
      updatedBlocks[bIdx - 1] = { ...prevBlock, text: mergedText }
      updatedBlocks.splice(bIdx, 1)

      focusTargetRef.current = { blockId: prevBlock.id, cursorPosition: prevTextLen }

      const updatedChapters = [...chapters]
      updatedChapters[selectedIdx] = {
        ...currentChapter,
        blocks: updatedBlocks,
        text: updatedBlocks.map(b => b.text).join('\n\n'),
      }
      setChapters(updatedChapters)
      scheduleAutoSave(updatedChapters)
      return
    }

    // Up arrow at start -> focus previous block
    if (e.key === 'ArrowUp' && selStart === 0 && bIdx > 0) {
      e.preventDefault()
      const prevBlock = currentChapter.blocks[bIdx - 1]
      const prevEl = blockRefs.current[prevBlock.id]
      if (prevEl) {
        prevEl.focus()
        prevEl.setSelectionRange(prevEl.value.length, prevEl.value.length)
      }
      return
    }

    // Down arrow at end -> focus next block
    if (e.key === 'ArrowDown' && selStart === val.length && bIdx < currentChapter.blocks.length - 1) {
      e.preventDefault()
      const nextBlock = currentChapter.blocks[bIdx + 1]
      const nextEl = blockRefs.current[nextBlock.id]
      if (nextEl) {
        nextEl.focus()
        nextEl.setSelectionRange(0, 0)
      }
      return
    }
  }

  // Inter-paragraph split: splits chapter at this paragraph boundary
  const handleSplitChapterAt = (splitAfterBIdx) => {
    if (!currentChapter) return
    const blocks1 = currentChapter.blocks.slice(0, splitAfterBIdx + 1)
    const blocks2 = currentChapter.blocks.slice(splitAfterBIdx + 1)

    if (!blocks2.length) return

    setUndoSnapshot([...chapters])

    const ch1 = {
      ...currentChapter,
      blocks: blocks1,
      text: blocks1.map(b => b.text).join('\n\n'),
    }

    const newId = `ch_${Date.now()}`
    const ch2 = {
      id: newId,
      order: currentChapter.order + 1,
      title: `${currentChapter.title} (Part 2)`,
      include_in_audio: currentChapter.include_in_audio,
      blocks: blocks2,
      text: blocks2.map(b => b.text).join('\n\n'),
    }

    const updated = [...chapters]
    updated.splice(selectedIdx, 1, ch1, ch2)
    const reordered = updated.map((ch, i) => ({ ...ch, order: i + 1 }))

    setChapters(reordered)
    setSelectedIdx(selectedIdx + 1)
    saveNow(reordered)

    if (toast) toast(`Chapter split into two chapters. Undo available.`, 'success')
  }

  // Resolve / Revert Warning
  const handleAcceptWarning = (bIdx) => {
    if (!currentChapter) return
    const updatedBlocks = [...currentChapter.blocks]
    const block = updatedBlocks[bIdx]
    updatedBlocks[bIdx] = {
      ...block,
      warning: { ...(block.warning || {}), status: 'resolved' },
    }

    const updatedChapters = [...chapters]
    updatedChapters[selectedIdx] = { ...currentChapter, blocks: updatedBlocks }
    setChapters(updatedChapters)
    scheduleAutoSave(updatedChapters)
    if (toast) toast('Cleaned AI passage accepted.', 'success')
  }

  const handleRevertWarning = (bIdx) => {
    if (!currentChapter) return
    const updatedBlocks = [...currentChapter.blocks]
    const block = updatedBlocks[bIdx]
    const rawText = block.warning?.raw_text || block.text
    updatedBlocks[bIdx] = {
      ...block,
      text: rawText,
      warning: { ...(block.warning || {}), status: 'resolved' },
    }

    const updatedChapters = [...chapters]
    updatedChapters[selectedIdx] = {
      ...currentChapter,
      blocks: updatedBlocks,
      text: updatedBlocks.map(b => b.text).join('\n\n'),
    }
    setChapters(updatedChapters)
    scheduleAutoSave(updatedChapters)

    setTimeout(() => {
      const el = blockRefs.current[block.id]
      if (el) {
        el.style.height = 'auto'
        el.style.height = `${Math.max(el.scrollHeight, 28)}px`
      }
    }, 25)

    if (toast) toast('Reverted to original OCR raw text.', 'info')
  }

  // Raw text change
  const handleRawTextChange = (newText) => {
    if (!currentChapter) return
    const updatedChapters = [...chapters]
    updatedChapters[selectedIdx] = { ...currentChapter, text: newText }
    setChapters(updatedChapters)
    scheduleAutoSave(updatedChapters)
  }

  // Filtered chapters for outline
  const filteredChapters = useMemo(() => {
    const q = filterQuery.trim().toLowerCase()
    if (!q) return chapters
    return chapters.filter(ch => (ch.title || '').toLowerCase().includes(q))
  }, [chapters, filterQuery])

  if (loading) {
    return (
      <div className="empty-state py-16 text-center text-muted">
        <div className="spin mb-3">◓</div>
        <p>Loading Chapter Studio…</p>
      </div>
    )
  }

  return (
    <div className="chapter-studio">
      {/* ── Top Workspace Header ─────────────────────────────────────────── */}
      <div className="chapter-studio-header">
        <div className="flex items-center gap-3">
          <button
            type="button"
            className="studio-project-title-btn"
            onClick={() => setShowBookDetails(true)}
            title="Edit book title, author, cover, and metadata"
          >
            <BookOpen size={16} className="text-accent" />
            <span>
              <strong>{meta.title || 'Untitled Book'}</strong>
              {meta.author && <span className="text-muted"> · {meta.author}</span>}
            </span>
            <span className="text-xs text-accent ml-1">[ ✎ Book Details ]</span>
          </button>

          <span className="text-xs text-muted">
            {chapters.length} chapters · ~{bookTotalStats.totalMinutes} min audio
          </span>
        </div>

        <div className="flex items-center gap-2">
          {undoSnapshot && (
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={handleUndo}
              title="Undo last merge, split, or delete"
            >
              <Undo2 size={14} className="mr-1" /> Undo Last Action
            </button>
          )}

          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => setShowBookDetails(true)}
            title="Edit book title, author, cover image, and metadata"
          >
            <BookOpen size={14} className="mr-1 text-accent" />
            Book Details
          </button>

          <button
            type="button"
            className={`btn btn-secondary btn-sm ${inspectorOpen ? 'btn-primary' : ''}`}
            onClick={() => setInspectorOpen(v => !v)}
            title="Toggle PDF Scan Ground Truth Inspector"
          >
            <FileSearch size={14} className="mr-1" />
            {inspectorOpen ? 'Hide Scan' : 'Inspect Scan'}
          </button>

          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => setShowModernize(true)}
            title="Open Text Modernization Studio"
          >
            <Sparkles size={14} className="mr-1" />
            Modernize Text
          </button>

          <div className="flex items-center gap-2 ml-2 pl-2 border-l border-glass">
            <span className="text-xs text-muted mr-1">
              {saveStatus === 'saving' ? (
                'Saving…'
              ) : saveStatus === 'unsaved' ? (
                'Unsaved changes'
              ) : (
                <span className="text-success flex items-center gap-1">
                  <Check size={12} /> Auto-saved
                </span>
              )}
            </span>

            {onBack && (
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={onBack}
              >
                <ArrowLeft size={14} className="mr-1" /> Back
              </button>
            )}

            {onNext && (
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={onNext}
              >
                Continue to Voice <ArrowRight size={14} className="ml-1" />
              </button>
            )}
          </div>
        </div>
      </div>

      {/* ── Main Workspace Grid ──────────────────────────────────────────── */}
      <div className={`studio-workspace-grid ${inspectorOpen && inspectorPinned ? 'with-pinned-inspector' : ''}`}>
        {/* Left Rail: Chapter Outline */}
        <aside className="outline-pane">
          {/* Book Details Summary Card */}
          <div
            className="outline-book-card"
            onClick={() => setShowBookDetails(true)}
            title="Click to view and edit book metadata and cover"
          >
            <div className="outline-book-thumb">
              {meta.cover_image && !coverImgErr ? (
                <img
                  src={meta.cover_image}
                  alt="Cover"
                  className="outline-book-thumb-img"
                  onError={() => setCoverImgErr(true)}
                />
              ) : (
                <BookOpen size={18} className="text-accent" />
              )}
            </div>
            <div className="outline-book-info">
              <span className="outline-book-title">{meta.title || 'Untitled Book'}</span>
              <span className="outline-book-author">{meta.author || 'Unknown Author'}</span>
              <span className="outline-book-edit-hint">
                <Pencil size={11} className="mr-1" /> Edit Book Details
              </span>
            </div>
          </div>

          <div className="outline-header">
            <span className="text-xs font-semibold uppercase tracking-wider text-muted">
              Chapter Outline ({chapters.length})
            </span>
            <button
              type="button"
              className="btn btn-ghost btn-sm text-xs"
              onClick={handleAddChapter}
              title="Add a new chapter"
            >
              <Plus size={14} className="mr-1" /> New
            </button>
          </div>

          <div className="outline-search-box">
            <input
              type="text"
              className="outline-search-input"
              value={filterQuery}
              onChange={e => setFilterQuery(e.target.value)}
              placeholder="Filter chapters…"
            />
          </div>

          <div className="outline-list">
            {filteredChapters.map((ch) => {
              const actualIdx = chapters.findIndex(c => c.id === ch.id)
              const isActiveRow = actualIdx === selectedIdx
              const isSelected = selectedChapterIds.has(ch.id)
              const isDragging = draggedIdx === actualIdx
              const isDragOver = dragOverIdx === actualIdx

              const isMuted = ch.include_in_audio === false
              const warnCount = (ch.blocks || []).filter(
                b => b.warning && b.warning.status !== 'resolved'
              ).length

              const chWords = (ch.text || '').split(/\s+/).filter(Boolean).length
              const chMin = Math.max(1, Math.round(chWords / 150))

              return (
                <div
                  key={ch.id}
                  className={`chapter-row ${isActiveRow ? 'is-active' : ''} ${isDragOver ? 'is-drag-over' : ''}`}
                  style={{ opacity: isDragging ? 0.4 : 1 }}
                  draggable
                  onDragStart={e => handleDragStart(actualIdx, e)}
                  onDragOver={e => handleDragOver(actualIdx, e)}
                  onDrop={() => handleDrop(actualIdx)}
                >
                  <div className="chapter-drag-handle" title="Drag to reorder">
                    <GripVertical size={14} />
                  </div>

                  <input
                    type="checkbox"
                    className="chapter-checkbox"
                    checked={isSelected}
                    onChange={e => handleCheckboxClick(actualIdx, e)}
                    onClick={e => e.stopPropagation()}
                    aria-label={`Select ${ch.title}`}
                  />

                  <button
                    type="button"
                    className="chapter-info-btn"
                    onClick={() => setSelectedIdx(actualIdx)}
                  >
                    <span className="chapter-title-text">
                      {ch.order}. {ch.title || 'Untitled'}
                    </span>
                    <span className="chapter-meta-line">
                      {isMuted ? (
                        <span className="badge badge-subtle">Muted</span>
                      ) : (
                        <span>~{chMin} min</span>
                      )}
                      {warnCount > 0 && (
                        <span className="badge badge-warning" title={`${warnCount} check(s) pending`}>
                          ⚠️ {warnCount}
                        </span>
                      )}
                    </span>
                  </button>

                  <div className="chapter-row-actions">
                    <button
                      type="button"
                      className={`btn-icon ${isMuted ? 'text-danger' : 'text-muted'}`}
                      onClick={e => handleToggleChapterAudio(actualIdx, e)}
                      title={isMuted ? 'Muted: Excluded from audio. Click to include.' : 'Included in audiobook narration. Click to mute.'}
                      aria-label="Toggle Chapter Audio"
                    >
                      {isMuted ? <VolumeX size={15} /> : <Volume2 size={15} />}
                    </button>

                    <button
                      type="button"
                      className="btn-icon text-muted hover:text-danger"
                      onClick={e => handleDeleteChapter(actualIdx, e)}
                      title="Delete Chapter"
                      aria-label="Delete Chapter"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              )
            })}
          </div>

          {/* Floating Bulk Actions Toolbar */}
          {selectedChapterIds.size > 0 && (
            <div className="floating-bulk-toolbar">
              <span className="text-xs font-semibold text-primary">
                {selectedChapterIds.size} selected
              </span>

              {selectedChapterIds.size >= 2 && (
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={handleBulkMerge}
                  title="Merge selected chapters sequentially into first chapter"
                >
                  Merge Selected
                </button>
              )}

              <button
                type="button"
                className="btn btn-danger-ghost btn-sm"
                onClick={handleBulkDelete}
                title="Delete all selected chapters"
              >
                <Trash2 size={14} className="mr-1" /> Delete
              </button>

              <button
                type="button"
                className="btn-icon btn-sm"
                onClick={() => setSelectedChapterIds(new Set())}
                title="Clear selection"
              >
                ✕
              </button>
            </div>
          )}
        </aside>

        {/* Center Pane: Fluid Document Editor */}
        <main className="editor-pane">
          {!currentChapter ? (
            <div className="empty-state py-16 text-center text-muted">
              <p>No chapters available. Click "New" to create one.</p>
            </div>
          ) : (
            <>
              {/* Chapter Header */}
              <div className="chapter-editor-header">
                <input
                  type="text"
                  className="chapter-title-input"
                  value={currentChapter.title || ''}
                  onChange={e => handleTitleChange(e.target.value)}
                  placeholder="Chapter Title…"
                  aria-label="Chapter Title"
                />

                <div className="chapter-editor-toolbar">
                  <div className="flex items-center gap-3">
                    <button
                      type="button"
                      className={`btn-tag ${currentChapter.include_in_audio !== false ? 'active' : ''}`}
                      onClick={() => handleToggleChapterAudio(selectedIdx)}
                    >
                      {currentChapter.include_in_audio !== false ? (
                        <span className="flex items-center gap-1">
                          <Volume2 size={13} /> Included in Narration
                        </span>
                      ) : (
                        <span className="flex items-center gap-1 text-danger">
                          <VolumeX size={13} /> Muted for TTS (EPUB Only)
                        </span>
                      )}
                    </button>

                    <span className="text-xs text-muted">
                      {currentChapterStats.words} words · ~{currentChapterStats.minutes} min audio
                    </span>
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm text-xs"
                      onClick={() => {
                        const firstBlockPage = currentChapter.blocks?.[0]?.source_page || 1
                        inspectPage(firstBlockPage)
                      }}
                      title="Inspect scan for this chapter"
                    >
                      <FileSearch size={13} className="mr-1" />
                      Inspect Scan ↗
                    </button>

                    <div className="flex items-center gap-1 bg-subtle p-1 rounded">
                      <button
                        type="button"
                        className={`btn-tag btn-sm ${editorMode === 'blocks' ? 'active' : ''}`}
                        onClick={() => setEditorMode('blocks')}
                        title="Continuous fluid blocks layout"
                      >
                        <Layers size={13} className="mr-1" /> Blocks Flow
                      </button>
                      <button
                        type="button"
                        className={`btn-tag btn-sm ${editorMode === 'raw' ? 'active' : ''}`}
                        onClick={() => setEditorMode('raw')}
                        title="Raw text markdown editor"
                      >
                        <AlignLeft size={13} className="mr-1" /> Raw Text
                      </button>
                    </div>
                  </div>
                </div>
              </div>

              {/* Editor Workspace */}
              {editorMode === 'raw' ? (
                <div className="document-sheet">
                  <textarea
                    className="form-textarea"
                    style={{ minHeight: '600px', lineHeight: '1.8' }}
                    value={currentChapter.text || ''}
                    onChange={e => handleRawTextChange(e.target.value)}
                    placeholder="Enter chapter text here..."
                  />
                </div>
              ) : (
                <div className="document-sheet">
                  {(!currentChapter.blocks || !currentChapter.blocks.length) ? (
                    <div className="empty-state py-8 text-center text-muted">
                      <p>No paragraph blocks found.</p>
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm mt-3"
                        onClick={() => {
                          const newBlocks = [
                            {
                              id: `blk_${Date.now()}`,
                              source_page: null,
                              text: currentChapter.text || '',
                              audio_muted: false,
                              warning: null,
                            },
                          ]
                          const updated = [...chapters]
                          updated[selectedIdx] = { ...currentChapter, blocks: newBlocks }
                          setChapters(updated)
                        }}
                      >
                        Create Paragraph Block
                      </button>
                    </div>
                  ) : (
                    (() => {
                      const allBlocks = currentChapter.blocks || []
                      const bodyBlocks = allBlocks.filter(b => b.type !== 'marginalia' && b.type !== 'footnote')
                      const apparatusFootnotes = allBlocks.filter(b => b.type === 'footnote')
                      const apparatusMarginalia = allBlocks.filter(b => b.type === 'marginalia')
                      const apparatusCallouts = allBlocks.filter(b => b.type === 'callout')
                      const hasApparatus = apparatusFootnotes.length > 0 || apparatusMarginalia.length > 0 || apparatusCallouts.length > 0

                      return (
                        <>
                          {bodyBlocks.map((block) => {
                            const realIdx = allBlocks.findIndex(b => b.id === block.id)
                            const isMuted = !!block.audio_muted
                            const hasWarning = block.warning && block.warning.status !== 'resolved'
                            const isDiffOpen = !diffClosedBlockIds.has(block.id)
                            const associatedNotes = allBlocks.filter(
                              n => (n.type === 'marginalia' || n.type === 'footnote') &&
                                   (n.associated_para_id === block.id || (n.source_page && n.source_page === block.source_page))
                            )

                            return (
                              <div
                                key={block.id || realIdx}
                                className={`continuous-paragraph-item ${isMuted ? 'is-muted' : ''} ${hasWarning ? 'has-warning' : ''}`}
                              >
                                {/* Inline Diff Accordion for AI Cleaning Warnings */}
                                {hasWarning && (
                                  <div className="warning-accordion">
                                    <div className="warning-accordion-header">
                                      <div className="flex items-center gap-2">
                                        <AlertTriangle size={15} className="text-warning flex-shrink-0" />
                                        <span className="warning-accordion-title">
                                          {block.warning.message || 'Passage flagged during cleaning evaluation'}
                                        </span>
                                      </div>

                                      <div className="warning-accordion-actions">
                                        <button
                                          type="button"
                                          className="btn btn-ghost btn-xs text-xs"
                                          onClick={() => toggleDiff(block.id)}
                                          title={isDiffOpen ? 'Collapse comparison' : 'Expand comparison'}
                                        >
                                          {isDiffOpen ? (
                                            <span className="flex items-center gap-1"><ChevronUp size={12} /> Hide Diff</span>
                                          ) : (
                                            <span className="flex items-center gap-1"><ChevronDown size={12} /> View Diff</span>
                                          )}
                                        </button>

                                        <button
                                          type="button"
                                          className="btn btn-ghost btn-xs text-xs"
                                          onClick={() => inspectPage(block.source_page || 1)}
                                          title="Open original scan page in inspector"
                                        >
                                          <FileSearch size={12} className="mr-1" /> Inspect Scan ↗
                                        </button>

                                        <button
                                          type="button"
                                          className="btn btn-primary btn-xs text-xs"
                                          onClick={() => handleAcceptWarning(realIdx)}
                                          title="Keep cleaned AI version and mark reviewed"
                                        >
                                          <Check size={12} className="mr-1" /> Accept Cleaned
                                        </button>

                                        <button
                                          type="button"
                                          className="btn btn-secondary btn-xs text-xs text-danger"
                                          onClick={() => handleRevertWarning(realIdx)}
                                          title="Revert paragraph text back to original OCR scan text"
                                        >
                                          <RotateCcw size={12} className="mr-1" /> Revert to OCR
                                        </button>
                                      </div>
                                    </div>

                                    {isDiffOpen && (
                                      <div className="warning-diff-body">
                                        <div className="diff-column diff-column-ocr">
                                          <div className="diff-column-header">
                                            <span className="diff-badge diff-badge-ocr">Original OCR Scan</span>
                                            <span className="text-xs text-muted">Page {block.source_page || '—'}</span>
                                          </div>
                                          <div className="diff-content">
                                            {block.warning.raw_text || <em>(No prior raw text recorded)</em>}
                                          </div>
                                        </div>

                                        <div className="diff-column diff-column-cleaned">
                                          <div className="diff-column-header">
                                            <span className="diff-badge diff-badge-cleaned">Cleaned AI Output</span>
                                            <span className="text-xs text-muted">Current Editor Text</span>
                                          </div>
                                          <div className="diff-content">
                                            {block.text}
                                          </div>
                                        </div>
                                      </div>
                                    )}
                                  </div>
                                )}

                                <div className="continuous-paragraph-row">
                                  {/* Gutter Controls */}
                                  <div className="continuous-gutter">
                                    <button
                                      type="button"
                                      className={`gutter-btn ${isMuted ? 'is-muted-active' : ''}`}
                                      onClick={() => handleToggleBlockMute(realIdx)}
                                      title={isMuted ? 'Muted from audio generation. Click to unmute.' : 'Mute this paragraph for TTS audio'}
                                      aria-label="Toggle Paragraph Audio"
                                    >
                                      {isMuted ? <VolumeX size={15} /> : <Volume2 size={15} />}
                                    </button>

                                    <button
                                      type="button"
                                      className="gutter-page-chip"
                                      onClick={() => inspectPage(block.source_page || 1)}
                                      title={`Original scan page ${block.source_page || '—'}. Click to inspect scan.`}
                                    >
                                      P. {block.source_page || '—'}
                                    </button>

                                    {associatedNotes.length > 0 && (
                                      <button
                                        type="button"
                                        className="gutter-notes-pill"
                                        style={{
                                          fontSize: '9.5px',
                                          padding: '1px 5px',
                                          borderRadius: '8px',
                                          background: 'rgba(245, 158, 11, 0.15)',
                                          color: '#fcd34d',
                                          border: '1px solid rgba(245, 158, 11, 0.3)',
                                          cursor: 'pointer',
                                          marginTop: '2px',
                                          whiteSpace: 'nowrap',
                                        }}
                                        onClick={() => {
                                          setApparatusCollapsed(false)
                                          const firstNote = associatedNotes[0]
                                          if (firstNote.type === 'marginalia') setApparatusTab('marginalia')
                                          else setApparatusTab('footnotes')
                                        }}
                                        title={`${associatedNotes.length} apparatus note(s) associated with this passage. Click to view below.`}
                                      >
                                        {associatedNotes.length} note{associatedNotes.length > 1 ? 's' : ''}
                                      </button>
                                    )}
                                  </div>

                                  {/* Continuous Paragraph Text Body */}
                                  <div className="continuous-text-wrap">
                                    {isMuted && (
                                      <div className="muted-paragraph-badge">
                                        <VolumeX size={11} className="mr-1" /> Excluded from TTS Audio
                                      </div>
                                    )}
                                    <textarea
                                      ref={el => {
                                        blockRefs.current[block.id] = el
                                        if (el) {
                                          el.style.height = 'auto'
                                          el.style.height = `${Math.max(el.scrollHeight, 28)}px`
                                        }
                                      }}
                                      className="continuous-textarea"
                                      value={block.text}
                                      onChange={e => handleBlockTextChange(realIdx, e.target.value)}
                                      onInput={e => {
                                        e.target.style.height = 'auto'
                                        e.target.style.height = `${Math.max(e.target.scrollHeight, 28)}px`
                                      }}
                                      onKeyDown={e => handleBlockKeyDown(realIdx, e)}
                                      placeholder="Type paragraph text here... (Enter to split, Backspace to merge)"
                                      rows={1}
                                    />
                                  </div>
                                </div>

                                {/* Hover Split Divider */}
                                {realIdx < allBlocks.length - 1 && (
                                  <div
                                    className="inter-block-split-divider"
                                    onClick={() => handleSplitChapterAt(realIdx)}
                                    title="Split chapter into two at this point"
                                  >
                                    <div className="split-line" />
                                    <div className="split-badge flex items-center gap-1">
                                      <Scissors size={11} /> Split Chapter Here
                                    </div>
                                  </div>
                                )}
                              </div>
                            )
                          })}

                          {/* Scholarly Apparatus Pane (Option 2) */}
                          {hasApparatus && (
                            <div className="scholarly-apparatus-pane">
                              <div className="scholarly-apparatus-header">
                                <div className="flex items-center gap-2">
                                  <BookOpen size={16} className="text-amber-400" />
                                  <span className="font-semibold text-xs tracking-wider uppercase text-gray-200">
                                    Scholarly Apparatus &amp; Notes
                                  </span>
                                  <span className="text-[11px] text-muted">
                                    ({apparatusFootnotes.length} footnotes · {apparatusMarginalia.length} marginalia · {apparatusCallouts.length} callouts)
                                  </span>
                                </div>

                                <div className="apparatus-category-tabs">
                                  <button
                                    type="button"
                                    className={`app-tab-btn ${apparatusTab === 'footnotes' ? 'active text-amber-300' : ''}`}
                                    onClick={() => {
                                      setApparatusTab('footnotes')
                                      setApparatusCollapsed(false)
                                    }}
                                  >
                                    Footnotes ({apparatusFootnotes.length})
                                  </button>
                                  <button
                                    type="button"
                                    className={`app-tab-btn ${apparatusTab === 'marginalia' ? 'active text-purple-300' : ''}`}
                                    onClick={() => {
                                      setApparatusTab('marginalia')
                                      setApparatusCollapsed(false)
                                    }}
                                  >
                                    Marginalia ({apparatusMarginalia.length})
                                  </button>
                                  <button
                                    type="button"
                                    className={`app-tab-btn ${apparatusTab === 'callouts' ? 'active text-emerald-300' : ''}`}
                                    onClick={() => {
                                      setApparatusTab('callouts')
                                      setApparatusCollapsed(false)
                                    }}
                                  >
                                    Callouts ({apparatusCallouts.length})
                                  </button>
                                </div>

                                <button
                                  type="button"
                                  className="btn-icon btn-xs text-muted hover:text-gray-200"
                                  onClick={() => setApparatusCollapsed(!apparatusCollapsed)}
                                  title={apparatusCollapsed ? 'Expand apparatus' : 'Collapse apparatus'}
                                >
                                  {apparatusCollapsed ? <ChevronDown size={15} /> : <ChevronUp size={15} />}
                                </button>
                              </div>

                              {!apparatusCollapsed && (
                                <div className="scholarly-apparatus-body">
                                  {apparatusTab === 'footnotes' && (
                                    <div className="apparatus-cards-grid">
                                      {apparatusFootnotes.map((note, fnIdx) => {
                                        const realIdx = allBlocks.findIndex(b => b.id === note.id)
                                        return (
                                          <div key={note.id || fnIdx} className="apparatus-card is-footnote">
                                            <div className="apparatus-card-top">
                                              <span className="font-semibold text-amber-400">
                                                Footnote #{fnIdx + 1}
                                              </span>
                                              <div className="flex items-center gap-2">
                                                <button
                                                  type="button"
                                                  className="text-xs text-muted hover:text-accent flex items-center gap-1"
                                                  onClick={() => inspectPage(note.source_page || 1, note.id)}
                                                >
                                                  <FileSearch size={12} /> P. {note.source_page || '—'} ↗
                                                </button>
                                                <button
                                                  type="button"
                                                  className={`btn-tag btn-xs ${note.audio_muted ? '' : 'active'}`}
                                                  onClick={() => handleToggleBlockMute(realIdx)}
                                                  title="Toggle TTS Audio Narration for this footnote"
                                                >
                                                  {note.audio_muted ? '🔇 Muted' : '🔊 Narrated'}
                                                </button>
                                              </div>
                                            </div>
                                            <textarea
                                              className="apparatus-textarea"
                                              value={note.text}
                                              onChange={(e) => handleBlockTextChange(realIdx, e.target.value)}
                                              placeholder="Footnote text..."
                                              rows={2}
                                            />
                                          </div>
                                        )
                                      })}
                                      {apparatusFootnotes.length === 0 && (
                                        <p className="text-xs text-muted italic">No footnotes detected in this chapter.</p>
                                      )}
                                    </div>
                                  )}

                                  {apparatusTab === 'marginalia' && (
                                    <div className="apparatus-cards-grid">
                                      {apparatusMarginalia.map((note, mgIdx) => {
                                        const realIdx = allBlocks.findIndex(b => b.id === note.id)
                                        return (
                                          <div key={note.id || mgIdx} className="apparatus-card is-marginalia">
                                            <div className="apparatus-card-top">
                                              <span className="font-semibold text-purple-400 font-mono">
                                                Margin Ref #{mgIdx + 1}
                                              </span>
                                              <div className="flex items-center gap-2">
                                                <button
                                                  type="button"
                                                  className="text-xs text-muted hover:text-accent flex items-center gap-1"
                                                  onClick={() => inspectPage(note.source_page || 1, note.id)}
                                                >
                                                  <FileSearch size={12} /> P. {note.source_page || '—'} ↗
                                                </button>
                                                <button
                                                  type="button"
                                                  className={`btn-tag btn-xs ${note.audio_muted ? '' : 'active'}`}
                                                  onClick={() => handleToggleBlockMute(realIdx)}
                                                  title="Toggle TTS Audio Narration for this margin citation"
                                                >
                                                  {note.audio_muted ? '🔇 Muted' : '🔊 Narrated'}
                                                </button>
                                              </div>
                                            </div>
                                            <textarea
                                              className="apparatus-textarea"
                                              value={note.text}
                                              onChange={(e) => handleBlockTextChange(realIdx, e.target.value)}
                                              placeholder="Margin citation..."
                                              rows={2}
                                            />
                                          </div>
                                        )
                                      })}
                                      {apparatusMarginalia.length === 0 && (
                                        <p className="text-xs text-muted italic">No marginal references detected in this chapter.</p>
                                      )}
                                    </div>
                                  )}

                                  {apparatusTab === 'callouts' && (
                                    <div className="apparatus-cards-grid">
                                      {apparatusCallouts.map((note, clIdx) => {
                                        const realIdx = allBlocks.findIndex(b => b.id === note.id)
                                        return (
                                          <div key={note.id || clIdx} className="apparatus-card is-callout">
                                            <div className="apparatus-card-top">
                                              <span className="font-semibold text-emerald-400">
                                                Callout Box #{clIdx + 1}
                                              </span>
                                              <div className="flex items-center gap-2">
                                                <button
                                                  type="button"
                                                  className="text-xs text-muted hover:text-accent flex items-center gap-1"
                                                  onClick={() => inspectPage(note.source_page || 1, note.id)}
                                                >
                                                  <FileSearch size={12} /> P. {note.source_page || '—'} ↗
                                                </button>
                                                <button
                                                  type="button"
                                                  className={`btn-tag btn-xs ${note.audio_muted ? '' : 'active'}`}
                                                  onClick={() => handleToggleBlockMute(realIdx)}
                                                >
                                                  {note.audio_muted ? '🔇 Muted' : '🔊 Narrated'}
                                                </button>
                                              </div>
                                            </div>
                                            <textarea
                                              className="apparatus-textarea"
                                              value={note.text}
                                              onChange={(e) => handleBlockTextChange(realIdx, e.target.value)}
                                              placeholder="Callout text..."
                                              rows={2}
                                            />
                                          </div>
                                        )
                                      })}
                                      {apparatusCallouts.length === 0 && (
                                        <p className="text-xs text-muted italic">No callout cards in this chapter.</p>
                                      )}
                                    </div>
                                  )}
                                </div>
                              )}
                            </div>
                          )}
                        </>
                      )
                    })()
                  )}
                </div>
              )}
            </>
          )}
        </main>

        {/* Pinned Inspector (Side-by-Side) */}
        {inspectorOpen && inspectorPinned && (
          <aside className="inspector-pane">
            <SourceInspector
              projectId={projectId}
              initialPage={inspectorPage}
              highlightBlockId={inspectorHighlightBlockId}
              isOpen={inspectorOpen}
              isPinned={true}
              onClose={() => setInspectorOpen(false)}
              onTogglePin={() => setInspectorPinned(false)}
              onChapterUpdated={() => {
                getChapters(projectId).then(chs => setChapters(chs || []))
              }}
            />
          </aside>
        )}
      </div>

      {/* Floating Peek Inspector (when not pinned) */}
      {inspectorOpen && !inspectorPinned && (
        <SourceInspector
          projectId={projectId}
          initialPage={inspectorPage}
          highlightBlockId={inspectorHighlightBlockId}
          isOpen={inspectorOpen}
          isPinned={false}
          onClose={() => setInspectorOpen(false)}
          onTogglePin={() => setInspectorPinned(true)}
          onChapterUpdated={() => {
            getChapters(projectId).then(chs => setChapters(chs || []))
          }}
        />
      )}

      {/* Book Details Modal */}
      <BookDetailsModal
        projectId={projectId}
        meta={meta}
        isOpen={showBookDetails}
        onClose={() => setShowBookDetails(false)}
        onUpdateMeta={(newMeta) => setMeta(prev => ({ ...prev, ...newMeta }))}
        toast={toast}
      />

      {/* Modernization Drawer */}
      <ModernizationDrawer
        projectId={projectId}
        isOpen={showModernize}
        onClose={() => setShowModernize(false)}
        currentChapterIndex={selectedIdx}
        currentChapterTitle={currentChapter?.title || 'Current Chapter'}
        modernizationEval={modernizationEval}
        setModernizationEval={setModernizationEval}
        modernizationProfiles={modernizationProfiles}
        toast={toast}
        onChaptersUpdated={() => {
          getChapters(projectId).then(chs => setChapters(chs || []))
        }}
      />
    </div>
  )
}
