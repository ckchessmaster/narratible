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
  X,
  PanelLeftClose,
  PanelLeftOpen,
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
  const [activeNotesPopoverBlockId, setActiveNotesPopoverBlockId] = useState(null)
  const [splitConfirmIdx, setSplitConfirmIdx] = useState(null)

  // Layout & Resizer state
  const [outlineCollapsed, setOutlineCollapsed] = useState(false)
  const [inspectorWidth, setInspectorWidth] = useState(() => {
    try {
      const saved = localStorage.getItem('echo_scribe_inspector_width')
      return saved ? Math.max(380, Math.min(parseInt(saved, 10), 900)) : 620
    } catch {
      return 620
    }
  })
  const [isResizing, setIsResizing] = useState(false)
  const resizeStartXRef = useRef(0)
  const resizeStartWidthRef = useRef(620)

  // Auto-collapse outline when inspector is pinned to give maximum reading & inspection space
  useEffect(() => {
    if (inspectorOpen && inspectorPinned) {
      setOutlineCollapsed(true)
    }
  }, [inspectorPinned, inspectorOpen])

  const handleResizerMouseDown = useCallback((e) => {
    e.preventDefault()
    setIsResizing(true)
    resizeStartXRef.current = e.clientX
    resizeStartWidthRef.current = inspectorWidth
  }, [inspectorWidth])

  useEffect(() => {
    if (!isResizing) return

    const handleMouseMove = (e) => {
      const delta = resizeStartXRef.current - e.clientX
      const maxW = Math.max(400, Math.floor(window.innerWidth * 0.65))
      const newWidth = Math.max(380, Math.min(resizeStartWidthRef.current + delta, maxW))
      setInspectorWidth(newWidth)
    }

    const handleMouseUp = () => {
      setIsResizing(false)
      try {
        localStorage.setItem('echo_scribe_inspector_width', String(inspectorWidth))
      } catch {}
    }

    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)
    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
    }
  }, [isResizing, inspectorWidth])

  // Close popovers on Escape key
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        setActiveNotesPopoverBlockId(null)
        setSplitConfirmIdx(null)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

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

  // Memoized blocks & apparatus lookup maps for linear O(1) performance
  const {
    allBlocks,
    bodyBlocks,
    apparatusFootnotes,
    apparatusMarginalia,
    apparatusCallouts,
    blockIndexMap,
    associatedNotesMap,
    hasApparatus,
  } = useMemo(() => {
    const blocks = currentChapter?.blocks || []
    const body = []
    const footnotes = []
    const marginalia = []
    const callouts = []
    const bIndexMap = new Map()
    const notesByPara = new Map()
    const notesByPage = new Map()

    for (let i = 0; i < blocks.length; i++) {
      const b = blocks[i]
      bIndexMap.set(b.id, i)
      if (b.type === 'footnote') {
        footnotes.push(b)
      } else if (b.type === 'marginalia') {
        marginalia.push(b)
      } else if (b.type === 'callout') {
        callouts.push(b)
      } else {
        body.push(b)
      }

      if (b.type === 'footnote' || b.type === 'marginalia') {
        if (b.associated_para_id) {
          if (!notesByPara.has(b.associated_para_id)) notesByPara.set(b.associated_para_id, [])
          notesByPara.get(b.associated_para_id).push(b)
        }
        if (b.source_page) {
          if (!notesByPage.has(b.source_page)) notesByPage.set(b.source_page, [])
          notesByPage.get(b.source_page).push(b)
        }
      }
    }

    const assocMap = new Map()
    for (const b of body) {
      const direct = notesByPara.get(b.id) || []
      const byPage = b.source_page ? (notesByPage.get(b.source_page) || []) : []
      const seen = new Set()
      const combined = []
      for (const n of [...direct, ...byPage]) {
        if (!seen.has(n.id)) {
          seen.add(n.id)
          combined.push(n)
        }
      }
      assocMap.set(b.id, combined)
    }

    return {
      allBlocks: blocks,
      bodyBlocks: body,
      apparatusFootnotes: footnotes,
      apparatusMarginalia: marginalia,
      apparatusCallouts: callouts,
      blockIndexMap: bIndexMap,
      associatedNotesMap: assocMap,
      hasApparatus: footnotes.length > 0 || marginalia.length > 0 || callouts.length > 0,
    }
  }, [currentChapter?.blocks])

  // Progressive rendering limit for large chapters to avoid DOM thrashing
  const [visibleLimit, setVisibleLimit] = useState(60)
  const sentinelRef = useRef(null)

  useEffect(() => {
    setVisibleLimit(60)
  }, [selectedIdx])

  const displayedBodyBlocks = useMemo(() => {
    return bodyBlocks.slice(0, visibleLimit)
  }, [bodyBlocks, visibleLimit])

  useEffect(() => {
    if (visibleLimit >= bodyBlocks.length) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          setVisibleLimit((prev) => Math.min(prev + 60, bodyBlocks.length))
        }
      },
      { rootMargin: '350px' }
    )
    const el = sentinelRef.current
    if (el) observer.observe(el)
    return () => {
      if (el) observer.unobserve(el)
    }
  }, [visibleLimit, bodyBlocks.length])

  // Fallback textarea height adjustment for older browser engines without field-sizing support
  useEffect(() => {
    if (typeof CSS !== 'undefined' && CSS.supports && CSS.supports('field-sizing', 'content')) return
    const timer = setTimeout(() => {
      displayedBodyBlocks.forEach(b => {
        const el = blockRefs.current[b.id]
        if (el) {
          el.style.height = 'auto'
          el.style.height = `${Math.max(el.scrollHeight, 28)}px`
        }
      })
    }, 50)
    return () => clearTimeout(timer)
  }, [selectedIdx, displayedBodyBlocks])

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
      <div
        className={`studio-workspace-grid ${inspectorOpen && inspectorPinned ? 'with-pinned-inspector' : ''}`}
        style={{
          gridTemplateColumns: inspectorOpen && inspectorPinned
            ? `${outlineCollapsed ? '52px' : '280px'} 1fr 6px ${inspectorWidth}px`
            : `${outlineCollapsed ? '52px' : '320px'} 1fr`,
          userSelect: isResizing ? 'none' : 'auto',
        }}
      >
        {/* Left Rail: Chapter Outline */}
        <aside className={`outline-pane ${outlineCollapsed ? 'is-collapsed' : ''}`}>
          {outlineCollapsed ? (
            <div className="outline-collapsed-rail">
              <button
                type="button"
                className="btn-icon p-2 text-muted hover:text-accent w-full flex justify-center"
                onClick={() => setOutlineCollapsed(false)}
                title="Expand Chapter Outline"
              >
                <PanelLeftOpen size={18} />
              </button>
              <div className="outline-collapsed-list">
                {chapters.map((ch, i) => (
                  <button
                    key={ch.id}
                    type="button"
                    className={`outline-collapsed-chip ${i === selectedIdx ? 'active' : ''}`}
                    onClick={() => setSelectedIdx(i)}
                    title={`${ch.order}. ${ch.title || 'Untitled'}`}
                  >
                    {ch.order}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <>
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
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm text-xs"
                    onClick={handleAddChapter}
                    title="Add a new chapter"
                  >
                    <Plus size={14} className="mr-1" /> New
                  </button>
                  <button
                    type="button"
                    className="btn-icon btn-sm text-muted hover:text-gray-200"
                    onClick={() => setOutlineCollapsed(true)}
                    title="Collapse Outline"
                  >
                    <PanelLeftClose size={15} />
                  </button>
                </div>
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
            </>
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
                    <>
                      {displayedBodyBlocks.map((block) => {
                        const realIdx = blockIndexMap.get(block.id) ?? allBlocks.findIndex(b => b.id === block.id)
                        const isMuted = !!block.audio_muted
                        const hasWarning = block.warning && block.warning.status !== 'resolved'
                        const isDiffOpen = !diffClosedBlockIds.has(block.id)
                        const associatedNotes = associatedNotesMap.get(block.id) || []
                        const isNotesActive = activeNotesPopoverBlockId === block.id

                        return (
                          <div
                            key={block.id || realIdx}
                            className={`continuous-paragraph-item ${isMuted ? 'is-muted' : ''} ${hasWarning ? 'has-warning' : ''} ${isNotesActive ? 'is-active-notes' : ''}`}
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
                                      <div style={{ position: 'relative' }}>
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
                                          onClick={(e) => {
                                            e.stopPropagation()
                                            setActiveNotesPopoverBlockId(activeNotesPopoverBlockId === block.id ? null : block.id)
                                          }}
                                          title={`${associatedNotes.length} apparatus note(s) associated with this passage. Click to view notes.`}
                                        >
                                          {associatedNotes.length} note{associatedNotes.length > 1 ? 's' : ''}
                                        </button>

                                        {activeNotesPopoverBlockId === block.id && (
                                          <div className="notes-inline-popover" onClick={(e) => e.stopPropagation()}>
                                            <div className="flex items-center justify-between pb-2 mb-2 border-b border-border/50">
                                              <span className="text-xs font-semibold text-gray-200 flex items-center gap-1.5">
                                                <BookOpen size={13} className="text-amber-400" />
                                                Passage Notes ({associatedNotes.length})
                                              </span>
                                              <button
                                                type="button"
                                                className="btn-icon btn-xs text-muted hover:text-gray-200"
                                                onClick={() => setActiveNotesPopoverBlockId(null)}
                                                title="Close"
                                              >
                                                <X size={13} />
                                              </button>
                                            </div>

                                            <div className="space-y-2.5 max-h-[280px] overflow-y-auto pr-1">
                                              {associatedNotes.map((note) => {
                                                const realNoteIdx = blockIndexMap.get(note.id) ?? -1
                                                const isMuted = note.audio_muted !== false
                                                const typeColor =
                                                  note.type === 'marginalia'
                                                    ? { bg: 'rgba(168, 85, 247, 0.15)', text: '#c084fc', border: 'rgba(168, 85, 247, 0.3)' }
                                                    : note.type === 'callout'
                                                    ? { bg: 'rgba(16, 185, 129, 0.15)', text: '#34d399', border: 'rgba(16, 185, 129, 0.3)' }
                                                    : { bg: 'rgba(245, 158, 11, 0.15)', text: '#fbbf24', border: 'rgba(245, 158, 11, 0.3)' }

                                                return (
                                                  <div key={note.id} className="p-2.5 rounded bg-surface border border-border/60">
                                                    <div className="flex items-center justify-between mb-1.5 text-[11px]">
                                                      <span
                                                        style={{
                                                          background: typeColor.bg,
                                                          color: typeColor.text,
                                                          border: `1px solid ${typeColor.border}`,
                                                          padding: '1px 6px',
                                                          borderRadius: '4px',
                                                          fontWeight: 600,
                                                          textTransform: 'capitalize',
                                                          fontSize: '10px',
                                                        }}
                                                      >
                                                        {note.type}
                                                      </span>
                                                      <div className="flex items-center gap-1.5">
                                                        <button
                                                          type="button"
                                                          className="text-[10px] text-muted hover:text-accent flex items-center gap-1 px-1.5 py-0.5 rounded hover:bg-hover"
                                                          onClick={() => inspectPage(note.source_page || block.source_page || 1, note.id)}
                                                          title="Inspect note on original scan"
                                                        >
                                                          <FileSearch size={11} /> P. {note.source_page || block.source_page || '—'} ↗
                                                        </button>
                                                        {realNoteIdx !== -1 && (
                                                          <button
                                                            type="button"
                                                            className={`btn-tag btn-xs ${isMuted ? '' : 'active'}`}
                                                            style={{ fontSize: '10px', padding: '1px 5px' }}
                                                            onClick={() => handleToggleBlockMute(realNoteIdx)}
                                                            title="Toggle TTS audio narration for this note"
                                                          >
                                                            {isMuted ? '🔇 Muted' : '🔊 Narrated'}
                                                          </button>
                                                        )}
                                                      </div>
                                                    </div>
                                                    {realNoteIdx !== -1 ? (
                                                      <textarea
                                                        className="input-text w-full text-xs p-1.5 rounded"
                                                        style={{ background: '#12141c', borderColor: '#2b3144', minHeight: '52px', resize: 'vertical' }}
                                                        value={note.text || ''}
                                                        onChange={(e) => handleBlockTextChange(realNoteIdx, e.target.value)}
                                                        placeholder="Note text..."
                                                        rows={2}
                                                      />
                                                    ) : (
                                                      <p className="text-xs text-gray-300 whitespace-pre-wrap">{note.text}</p>
                                                    )}
                                                  </div>
                                                )
                                              })}
                                            </div>
                                          </div>
                                        )}
                                      </div>
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
                                  <div className={`inter-block-split-divider ${splitConfirmIdx === realIdx ? 'is-active' : ''}`}>
                                    <div className="split-line" />
                                    <button
                                      type="button"
                                      className="split-badge flex items-center gap-1"
                                      onClick={(e) => {
                                        e.stopPropagation()
                                        setSplitConfirmIdx(splitConfirmIdx === realIdx ? null : realIdx)
                                      }}
                                      title="Split chapter into two at this paragraph boundary"
                                    >
                                      <Scissors size={11} /> Split Chapter
                                    </button>

                                    {splitConfirmIdx === realIdx && (
                                      <div className="split-confirm-popover" onClick={(e) => e.stopPropagation()}>
                                        <div className="flex items-center gap-1.5 mb-1.5 font-semibold text-xs text-gray-200">
                                          <Scissors size={13} className="text-accent" />
                                          <span>Split Chapter Here?</span>
                                        </div>
                                        <p className="text-[11.5px] text-muted mb-3 leading-relaxed">
                                          This will divide <strong>&ldquo;{currentChapter.title}&rdquo;</strong> into two separate chapters right after this paragraph.
                                        </p>
                                        <div className="flex items-center justify-end gap-2">
                                          <button
                                            type="button"
                                            className="btn-secondary btn-xs"
                                            onClick={() => setSplitConfirmIdx(null)}
                                          >
                                            Cancel
                                          </button>
                                          <button
                                            type="button"
                                            className="btn-primary btn-xs flex items-center gap-1"
                                            onClick={() => {
                                              handleSplitChapterAt(realIdx)
                                              setSplitConfirmIdx(null)
                                            }}
                                          >
                                            <Check size={12} />
                                            <span>Split Chapter</span>
                                          </button>
                                        </div>
                                      </div>
                                    )}
                                  </div>
                                )}
                              </div>
                            )
                          })}

                          {visibleLimit < bodyBlocks.length && (
                            <div ref={sentinelRef} className="py-6 flex flex-col items-center justify-center gap-2 border-t border-border/30 mt-4">
                              <span className="text-xs text-muted">
                                Showing {displayedBodyBlocks.length} of {bodyBlocks.length} paragraphs
                              </span>
                              <button
                                type="button"
                                className="btn btn-secondary btn-sm text-xs"
                                onClick={() => setVisibleLimit((prev) => Math.min(prev + 100, bodyBlocks.length))}
                              >
                                Load more paragraphs
                              </button>
                            </div>
                          )}

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
                                        const realIdx = blockIndexMap.get(note.id) ?? -1
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
                                        const realIdx = blockIndexMap.get(note.id) ?? -1
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
                                        const realIdx = blockIndexMap.get(note.id) ?? -1
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
                      )}
                    </div>
              )}
            </>
          )}
        </main>

        {/* Resizer Handle between Editor and Pinned Inspector */}
        {inspectorOpen && inspectorPinned && (
          <div
            className={`workspace-resizer-handle ${isResizing ? 'is-resizing' : ''}`}
            onMouseDown={handleResizerMouseDown}
            title="Drag to resize inspector pane"
          />
        )}

        {/* Pinned Inspector (Side-by-Side) */}
        {inspectorOpen && inspectorPinned && (
          <aside className="inspector-pane" style={{ width: `${inspectorWidth}px`, minWidth: '360px' }}>
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
