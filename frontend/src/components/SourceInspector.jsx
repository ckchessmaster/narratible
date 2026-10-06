import { useState, useEffect, useRef, useCallback } from 'react'
import {
  ChevronLeft,
  ChevronRight,
  ZoomIn,
  ZoomOut,
  Sidebar,
  X,
  Loader2,
  FileSearch,
  MousePointer,
  SquareDashed,
  Trash2,
  Sparkles,
  RefreshCw,
  Copy,
  Layers,
  Check,
  ArrowUp,
  ArrowDown,
} from 'lucide-react'
import {
  getPageInfo,
  pageImageUrl,
  getPageLayout,
  updatePageLayout,
  reextractAllLayouts,
} from '../api'
import LayoutPropagateModal from './LayoutPropagateModal'

const BLOCK_COLORS = {
  body: {
    stroke: '#3b82f6',
    fill: 'rgba(59, 130, 246, 0.20)',
    badge: '#2563eb',
    label: 'Body',
  },
  marginalia: {
    stroke: '#a855f7',
    fill: 'rgba(168, 85, 247, 0.20)',
    badge: '#9333ea',
    label: 'Margin',
  },
  footnote: {
    stroke: '#f59e0b',
    fill: 'rgba(245, 158, 11, 0.20)',
    badge: '#d97706',
    label: 'Footnote',
  },
  callout: {
    stroke: '#10b981',
    fill: 'rgba(16, 185, 129, 0.20)',
    badge: '#059669',
    label: 'Callout',
  },
  figure_caption: {
    stroke: '#06b6d4',
    fill: 'rgba(6, 182, 212, 0.20)',
    badge: '#0891b2',
    label: 'Caption',
  },
  heading: {
    stroke: '#6366f1',
    fill: 'rgba(99, 102, 241, 0.20)',
    badge: '#4f46e5',
    label: 'Heading',
  },
  header_footer: {
    stroke: '#64748b',
    fill: 'rgba(100, 116, 139, 0.20)',
    badge: '#475569',
    label: 'Header/Footer',
  },
}

export default function SourceInspector({
  projectId,
  initialPage = 1,
  isOpen = false,
  isPinned = false,
  onClose,
  onTogglePin,
  onChapterUpdated,
  highlightBlockId = null,
}) {
  const [currentPage, setCurrentPage] = useState(initialPage)
  const [pageInput, setPageInput] = useState(String(initialPage))
  const [totalPages, setTotalPages] = useState(1)
  const [hasPdf, setHasPdf] = useState(true)
  const [loading, setLoading] = useState(false)
  const [zoom, setZoom] = useState(1.0)
  const [fitMode, setFitMode] = useState('fit')
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [isPanning, setIsPanning] = useState(false)
  const panStartRef = useRef({ x: 0, y: 0 })
  const imageContainerRef = useRef(null)
  const svgOverlayRef = useRef(null)

  // Semantic Zone State
  const [viewMode, setViewMode] = useState('scan') // 'scan' | 'zones'
  const [activeTool, setActiveTool] = useState('select') // 'select' | 'draw'
  const [layout, setLayout] = useState(null)
  const [layoutLoading, setLayoutLoading] = useState(false)
  const [selectedBlockId, setSelectedBlockId] = useState(highlightBlockId)
  const [isExtracting, setIsExtracting] = useState(false)
  const [extractSuccess, setExtractSuccess] = useState(false)
  const [isExtractingAll, setIsExtractingAll] = useState(false)
  const [extractAllSuccess, setExtractAllSuccess] = useState(false)

  // Drawing state
  const [drawingStart, setDrawingStart] = useState(null)
  const [drawingBox, setDrawingBox] = useState(null)

  // Resize / Move drag state
  const [dragState, setDragState] = useState(null) // { mode: 'move'|'nw'|'ne'|'se'|'sw', blockId, startX, startY, origBbox }

  // Modals
  const [isPropagateModalOpen, setIsPropagateModalOpen] = useState(false)
  const [templateMenuOpen, setTemplateMenuOpen] = useState(false)

  // Sync initialPage from outside
  useEffect(() => {
    if (initialPage && initialPage > 0) {
      setCurrentPage(initialPage)
      setPageInput(String(initialPage))
    }
  }, [initialPage])

  // Sync highlightBlockId
  useEffect(() => {
    if (highlightBlockId) {
      setSelectedBlockId(highlightBlockId)
      setViewMode('zones')
    }
  }, [highlightBlockId])

  // Fetch page info
  useEffect(() => {
    if (!projectId) return
    getPageInfo(projectId)
      .then(info => {
        if (info) {
          setTotalPages(info.total_pages || 1)
          setHasPdf(!!info.has_source_pdf)
        }
      })
      .catch(() => setHasPdf(false))
  }, [projectId])

  // Fetch or refresh layout for current page
  const fetchLayout = useCallback(async (page, recompute = false) => {
    if (!projectId) return
    setLayoutLoading(true)
    try {
      const data = await getPageLayout(projectId, page, recompute)
      setLayout(data)
      if (recompute && onChapterUpdated) {
        onChapterUpdated()
      }
    } catch {
      setLayout(null)
    } finally {
      setLayoutLoading(false)
    }
  }, [projectId, onChapterUpdated])

  useEffect(() => {
    if (viewMode === 'zones') {
      fetchLayout(currentPage)
    }
  }, [viewMode, currentPage, fetchLayout])

  // Adjacent page prefetch
  useEffect(() => {
    if (!projectId || !hasPdf) return
    const prefetch = (p) => {
      if (p >= 1 && p <= totalPages) {
        const img = new Image()
        img.src = pageImageUrl(projectId, p, 150)
      }
    }
    prefetch(currentPage - 1)
    prefetch(currentPage + 1)
  }, [projectId, currentPage, totalPages, hasPdf])

  const goToPage = useCallback((p) => {
    const valid = Math.max(1, Math.min(totalPages, p))
    setCurrentPage(valid)
    setPageInput(String(valid))
    setLoading(true)
    setPan({ x: 0, y: 0 })
    setSelectedBlockId(null)
  }, [totalPages])

  const handlePageInputChange = (e) => {
    setPageInput(e.target.value.replace(/[^0-9]/g, ''))
  }

  const handlePageInputSubmit = (e) => {
    if (e.key === 'Enter') {
      const parsed = parseInt(pageInput, 10)
      if (!isNaN(parsed)) goToPage(parsed)
      else setPageInput(String(currentPage))
    }
  }

  // Zoom handlers
  const handleZoomIn = () => {
    setFitMode('custom')
    setZoom(z => Math.min(3.0, Number((z + 0.25).toFixed(2))))
  }
  const handleZoomOut = () => {
    setFitMode('custom')
    setZoom(z => Math.max(0.4, Number((z - 0.25).toFixed(2))))
  }
  const handleFit = () => {
    setFitMode('fit')
    setZoom(1.0)
    setPan({ x: 0, y: 0 })
  }
  const handleActual = () => {
    setFitMode('actual')
    setZoom(1.5)
    setPan({ x: 0, y: 0 })
  }

  // Pan interactions (when not drawing or resizing)
  const handleMouseDown = (e) => {
    if (activeTool === 'draw' && viewMode === 'zones') return
    if (dragState) return
    if (zoom <= 1.0 && fitMode === 'fit') return
    setIsPanning(true)
    panStartRef.current = { x: e.clientX - pan.x, y: e.clientY - pan.y }
  }

  const handleMouseMove = (e) => {
    if (isPanning) {
      setPan({
        x: e.clientX - panStartRef.current.x,
        y: e.clientY - panStartRef.current.y,
      })
      return
    }

    if (dragState && svgOverlayRef.current) {
      const rect = svgOverlayRef.current.getBoundingClientRect()
      const curX = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
      const curY = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height))
      const dx = curX - dragState.startX
      const dy = curY - dragState.startY
      const [ox0, oy0, ox1, oy1] = dragState.origBbox

      let newBbox = [...dragState.origBbox]
      if (dragState.mode === 'move') {
        const w = ox1 - ox0
        const h = oy1 - oy0
        const nx0 = Math.max(0, Math.min(1 - w, ox0 + dx))
        const ny0 = Math.max(0, Math.min(1 - h, oy0 + dy))
        newBbox = [nx0, ny0, nx0 + w, ny0 + h]
      } else if (dragState.mode === 'nw') {
        newBbox = [Math.min(ox1 - 0.02, ox0 + dx), Math.min(oy1 - 0.02, oy0 + dy), ox1, oy1]
      } else if (dragState.mode === 'ne') {
        newBbox = [ox0, Math.min(oy1 - 0.02, oy0 + dy), Math.max(ox0 + 0.02, ox1 + dx), oy1]
      } else if (dragState.mode === 'se') {
        newBbox = [ox0, oy0, Math.max(ox0 + 0.02, ox1 + dx), Math.max(oy0 + 0.02, oy1 + dy)]
      } else if (dragState.mode === 'sw') {
        newBbox = [Math.min(ox1 - 0.02, ox0 + dx), oy0, ox1, Math.max(oy0 + 0.02, oy1 + dy)]
      }

      setLayout(prev => {
        if (!prev) return prev
        return {
          ...prev,
          blocks: prev.blocks.map(b => (b.id === dragState.blockId ? { ...b, bbox: newBbox.map(v => Number(v.toFixed(4))) } : b)),
        }
      })
      return
    }

    if (drawingStart && svgOverlayRef.current) {
      const rect = svgOverlayRef.current.getBoundingClientRect()
      const curX = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
      const curY = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height))
      setDrawingBox([
        Math.min(drawingStart.x, curX),
        Math.min(drawingStart.y, curY),
        Math.max(drawingStart.x, curX),
        Math.max(drawingStart.y, curY),
      ])
    }
  }

  const handleMouseUp = () => {
    setIsPanning(false)
    if (dragState) {
      setDragState(null)
    }
    if (drawingStart && drawingBox) {
      const [x0, y0, x1, y1] = drawingBox
      // If meaningful area drawn (width & height > 0.02)
      if (x1 - x0 > 0.02 && y1 - y0 > 0.02) {
        const newId = `blk_draw_${Date.now()}`
        const newBlock = {
          id: newId,
          type: 'body',
          order: (layout?.blocks?.filter(b => b.type === 'body').length || 0) + 1,
          audio_muted: false,
          bbox: [
            Number(x0.toFixed(4)),
            Number(y0.toFixed(4)),
            Number(x1.toFixed(4)),
            Number(y1.toFixed(4)),
          ],
          text: '',
          confidence: 1.0,
        }
        setLayout(prev => ({
          ...prev,
          blocks: [...(prev?.blocks || []), newBlock],
        }))
        setSelectedBlockId(newId)
        setActiveTool('select')
      }
      setDrawingStart(null)
      setDrawingBox(null)
    }
  }

  // Start Drawing Box
  const handleSvgMouseDown = (e) => {
    if (activeTool !== 'draw' || !svgOverlayRef.current) return
    e.stopPropagation()
    const rect = svgOverlayRef.current.getBoundingClientRect()
    const x = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
    const y = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height))
    setDrawingStart({ x, y })
    setDrawingBox([x, y, x, y])
  }

  // Block Tag Change
  const handleChangeBlockType = (blockId, newType) => {
    setLayout(prev => {
      if (!prev) return prev
      const isMuted = newType in { marginalia: 1, footnote: 1, figure_caption: 1, header_footer: 1 }
      return {
        ...prev,
        blocks: prev.blocks.map(b => (b.id === blockId ? { ...b, type: newType, audio_muted: isMuted } : b)),
      }
    })
  }

  // Delete Block
  const handleDeleteBlock = (blockId) => {
    setLayout(prev => {
      if (!prev) return prev
      return {
        ...prev,
        blocks: prev.blocks.filter(b => b.id !== blockId),
      }
    })
    if (selectedBlockId === blockId) {
      setSelectedBlockId(null)
    }
  }

  // Re-extract Page Text Action
  const handleReextractText = async () => {
    if (!layout || !projectId) return
    setIsExtracting(true)
    setExtractSuccess(false)
    try {
      const updated = await updatePageLayout(projectId, currentPage, layout.blocks, true)
      setLayout(updated)
      setExtractSuccess(true)
      if (onChapterUpdated) {
        onChapterUpdated()
      }
      setTimeout(() => setExtractSuccess(false), 2000)
    } catch (err) {
      alert(`Re-extraction failed: ${err.message}`)
    } finally {
      setIsExtracting(false)
    }
  }

  // Re-extract All Pages Action
  const handleReextractAll = async () => {
    if (!projectId) return
    setIsExtractingAll(true)
    setExtractAllSuccess(false)
    try {
      await reextractAllLayouts(projectId)
      setExtractAllSuccess(true)
      await fetchLayout(currentPage)
      if (onChapterUpdated) {
        onChapterUpdated()
      }
      setTimeout(() => setExtractAllSuccess(false), 3000)
    } catch (err) {
      alert(`Batch re-extraction failed: ${err.message}`)
    } finally {
      setIsExtractingAll(false)
    }
  }

  // Copy Layout from Previous Page
  const handleCopyFromPrevious = async () => {
    if (currentPage <= 1 || !projectId) return
    try {
      setIsExtracting(true)
      const prevLayout = await getPageLayout(projectId, currentPage - 1)
      if (prevLayout && prevLayout.blocks?.length) {
        const cloned = prevLayout.blocks.map(b => ({
          ...b,
          id: `blk_${currentPage}_${Math.random().toString(36).slice(2, 8)}`,
          text: '',
        }))
        const updated = await updatePageLayout(projectId, currentPage, cloned, true)
        setLayout(updated)
        if (onChapterUpdated) onChapterUpdated()
      }
    } catch (err) {
      alert(`Copy failed: ${err.message}`)
    } finally {
      setIsExtracting(false)
      setTemplateMenuOpen(false)
    }
  }

  if (!isOpen) return null

  const currentImageUrl = pageImageUrl(projectId, currentPage, 150)
  const selectedBlock = layout?.blocks?.find(b => b.id === selectedBlockId)

  return (
    <div className={`source-inspector ${isPinned ? 'is-pinned' : 'is-peek'}`}>
      {/* Top Inspector Bar */}
      <div className="inspector-toolbar">
        <div className="inspector-toolbar-group">
          <FileSearch size={16} className="text-accent" />
          <span className="inspector-title">Ground Truth &amp; Zones</span>

          {/* Mode Switcher: Scan vs Semantic Zones */}
          <div className="mode-segmented" style={{ display: 'inline-flex', background: '#1c202d', borderRadius: '6px', padding: '2px', border: '1px solid #2e3446' }}>
            <button
              type="button"
              className={`btn-tag btn-sm ${viewMode === 'scan' ? 'active' : ''}`}
              onClick={() => setViewMode('scan')}
              style={{ border: 'none', borderRadius: '4px', fontSize: '11px', padding: '3px 8px' }}
            >
              Scan
            </button>
            <button
              type="button"
              className={`btn-tag btn-sm ${viewMode === 'zones' ? 'active' : ''}`}
              onClick={() => setViewMode('zones')}
              style={{ border: 'none', borderRadius: '4px', fontSize: '11px', padding: '3px 8px' }}
            >
              Semantic Zones
            </button>
          </div>
        </div>

        {/* Page navigation */}
        <div className="inspector-pagination">
          <button
            type="button"
            className="btn-icon btn-sm"
            onClick={() => goToPage(currentPage - 1)}
            disabled={currentPage <= 1}
            title="Previous Page"
            aria-label="Previous Page"
          >
            <ChevronLeft size={16} />
          </button>
          <div className="page-indicator">
            <span>P.</span>
            <input
              type="text"
              className="page-input"
              value={pageInput}
              onChange={handlePageInputChange}
              onKeyDown={handlePageInputSubmit}
              onBlur={() => {
                const parsed = parseInt(pageInput, 10)
                if (!isNaN(parsed)) goToPage(parsed)
                else setPageInput(String(currentPage))
              }}
              aria-label="Page number input"
            />
            <span className="text-muted">/ {totalPages}</span>
          </div>
          <button
            type="button"
            className="btn-icon btn-sm"
            onClick={() => goToPage(currentPage + 1)}
            disabled={currentPage >= totalPages}
            title="Next Page"
            aria-label="Next Page"
          >
            <ChevronRight size={16} />
          </button>
        </div>

        {/* Zoom controls */}
        <div className="inspector-zoom-controls">
          <button type="button" className="btn-icon btn-sm" onClick={handleZoomOut} title="Zoom Out">
            <ZoomOut size={15} />
          </button>
          <span className="zoom-label">{Math.round(zoom * 100)}%</span>
          <button type="button" className="btn-icon btn-sm" onClick={handleZoomIn} title="Zoom In">
            <ZoomIn size={15} />
          </button>
          <button
            type="button"
            className={`btn-tag btn-sm ${fitMode === 'fit' ? 'active' : ''}`}
            onClick={handleFit}
          >
            Fit
          </button>
        </div>

        {/* Action icons: Pin & Close */}
        <div className="inspector-actions">
          <button
            type="button"
            className={`btn-icon btn-sm ${isPinned ? 'is-active text-accent' : ''}`}
            onClick={onTogglePin}
            title={isPinned ? 'Unpin to Peek' : 'Pin Side-by-Side'}
          >
            <Sidebar size={16} />
          </button>
          <button type="button" className="btn-icon btn-sm" onClick={onClose} title="Close Inspector">
            <X size={16} />
          </button>
        </div>
      </div>

      {/* Sub-toolbar when in Semantic Zones mode */}
      {viewMode === 'zones' && (
        <div
          className="zoning-sub-toolbar"
          style={{
            background: '#151822',
            borderBottom: '1px solid #282e40',
            padding: '6px 12px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            fontSize: '11px',
            flexWrap: 'nowrap',
            overflowX: 'auto',
            gap: '8px',
          }}
        >
          {/* Tools */}
          <div className="flex items-center gap-1.5 shrink-0">
            <button
              type="button"
              className={`btn-tag btn-xs flex items-center gap-1 ${activeTool === 'select' ? 'active' : ''}`}
              onClick={() => setActiveTool('select')}
            >
              <MousePointer size={12} />
              <span>Select</span>
            </button>
            <button
              type="button"
              className={`btn-tag btn-xs flex items-center gap-1 ${activeTool === 'draw' ? 'active' : ''}`}
              onClick={() => setActiveTool('draw')}
            >
              <SquareDashed size={12} />
              <span>Draw Box</span>
            </button>

            {/* Selected Block Quick Editor */}
            {selectedBlock && (
              <div className="flex items-center gap-1.5 pl-2 ml-1 border-l border-border/50">
                <span className="text-muted text-[10.5px]">Tag:</span>
                <select
                  className="input-text text-xs py-0.5 px-1"
                  value={selectedBlock.type}
                  onChange={(e) => handleChangeBlockType(selectedBlock.id, e.target.value)}
                  style={{ background: '#1e2230', borderColor: '#3b4258' }}
                >
                  <option value="body">Body (Flowing)</option>
                  <option value="marginalia">Marginalia (Muted)</option>
                  <option value="footnote">Footnote (Muted)</option>
                  <option value="callout">Callout Box</option>
                  <option value="header_footer">Header / Footer (Skip)</option>
                  <option value="figure_caption">Figure Caption</option>
                </select>

                <button
                  type="button"
                  className="btn-icon btn-xs text-red-400 hover:text-red-300"
                  onClick={() => handleDeleteBlock(selectedBlock.id)}
                  title="Delete Block"
                >
                  <Trash2 size={12} />
                </button>
              </div>
            )}
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-1.5 shrink-0 flex-nowrap">
            {/* Re-extract text */}
            <button
              type="button"
              className="btn-secondary btn-xs flex items-center gap-1"
              onClick={handleReextractText}
              disabled={isExtracting || isExtractingAll}
              title="Extract text strictly bounded by these zones and update chapters"
            >
              {isExtracting ? (
                <Loader2 size={12} className="spin text-accent" />
              ) : extractSuccess ? (
                <Check size={12} className="text-emerald-400" />
              ) : (
                <RefreshCw size={12} />
              )}
              <span>{extractSuccess ? 'Updated!' : 'Extract'}</span>
            </button>

            {/* Re-detect Layout */}
            <button
              type="button"
              className="btn-secondary btn-xs flex items-center gap-1"
              onClick={() => fetchLayout(currentPage, true)}
              disabled={layoutLoading || isExtractingAll}
              title="Re-run spatial layout analysis on this page to reset zones"
            >
              <RefreshCw size={12} className={layoutLoading ? 'spin' : ''} />
              <span>Detect</span>
            </button>

            {/* Apply to All Pages */}
            <button
              type="button"
              className="btn-secondary btn-xs flex items-center gap-1"
              onClick={handleReextractAll}
              disabled={isExtractingAll}
              title="Run layout analysis and update chapters across all pages in this document"
              style={{
                borderColor: extractAllSuccess ? '#10b981' : undefined,
                color: extractAllSuccess ? '#10b981' : undefined,
              }}
            >
              {isExtractingAll ? (
                <Loader2 size={12} className="spin text-accent" />
              ) : extractAllSuccess ? (
                <Check size={12} className="text-emerald-400" />
              ) : (
                <Sparkles size={12} className="text-accent" />
              )}
              <span>{extractAllSuccess ? 'Synced All!' : isExtractingAll ? 'Syncing…' : 'Apply All'}</span>
            </button>

            {/* Layout Templates Dropdown */}
            <div style={{ position: 'relative' }}>
              <button
                type="button"
                className="btn-secondary btn-xs flex items-center gap-1"
                onClick={() => setTemplateMenuOpen(!templateMenuOpen)}
                title="Layout presets and propagation options"
              >
                <Layers size={12} />
                <span>Templates ▾</span>
              </button>

              {templateMenuOpen && (
                <div
                  style={{
                    position: 'absolute',
                    right: 0,
                    top: '100%',
                    marginTop: '4px',
                    background: '#1a1d29',
                    border: '1px solid #333a4f',
                    borderRadius: '6px',
                    padding: '4px',
                    zIndex: 40,
                    width: '210px',
                    boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
                  }}
                >
                  <button
                    type="button"
                    className="w-full text-left px-2.5 py-1.5 text-xs text-gray-200 hover:bg-hover rounded flex items-center gap-2"
                    onClick={handleCopyFromPrevious}
                    disabled={currentPage <= 1}
                  >
                    <Copy size={13} className="text-muted" />
                    <span>Copy from Previous Page</span>
                  </button>
                  <button
                    type="button"
                    className="w-full text-left px-2.5 py-1.5 text-xs text-gray-200 hover:bg-hover rounded flex items-center gap-2"
                    onClick={() => {
                      setTemplateMenuOpen(false)
                      setIsPropagateModalOpen(true)
                    }}
                  >
                    <Layers size={13} className="text-accent" />
                    <span>Propagate to Range…</span>
                  </button>
                  <button
                    type="button"
                    className="w-full text-left px-2.5 py-1.5 text-xs text-gray-200 hover:bg-hover rounded flex items-center gap-2"
                    onClick={() => {
                      setTemplateMenuOpen(false)
                      handleReextractAll()
                    }}
                  >
                    <Sparkles size={13} className="text-accent" />
                    <span>Re-extract All Pages</span>
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Main Image & SVG Stage */}
      <div
        ref={imageContainerRef}
        className={`inspector-canvas ${isPanning ? 'is-panning' : ''}`}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      >
        {(loading || layoutLoading) && (
          <div className="inspector-loader">
            <Loader2 size={24} className="spin text-accent" />
            <span className="text-xs text-muted mt-2">
              {loading ? `Rendering page ${currentPage}…` : 'Analyzing spatial zones…'}
            </span>
          </div>
        )}

        {!hasPdf ? (
          <div className="inspector-empty">
            <FileSearch size={32} className="text-muted" />
            <p className="text-sm text-muted mt-2">Original PDF file not found.</p>
          </div>
        ) : (
          <div
            className="inspector-image-wrapper"
            style={{
              transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
              transformOrigin: 'top center',
              position: 'relative',
              display: 'inline-block',
            }}
          >
            {/* The PDF scan image */}
            <img
              key={`page-${currentPage}`}
              src={currentImageUrl}
              alt={`Scan page ${currentPage}`}
              className={`inspector-page-img ${fitMode === 'fit' ? 'is-fit' : ''}`}
              onLoad={() => setLoading(false)}
              onError={() => setLoading(false)}
              draggable={false}
              style={{ display: 'block' }}
            />

            {/* Interactive SVG Zoning Canvas Overlay */}
            {viewMode === 'zones' && (
              <svg
                ref={svgOverlayRef}
                viewBox="0 0 1000 1000"
                preserveAspectRatio="none"
                style={{
                  position: 'absolute',
                  inset: 0,
                  width: '100%',
                  height: '100%',
                  pointerEvents: 'auto',
                  cursor: activeTool === 'draw' ? 'crosshair' : 'default',
                }}
                onMouseDown={handleSvgMouseDown}
              >
                {/* Existing Layout Blocks */}
                {layout?.blocks?.map((block) => {
                  const [nx0, ny0, nx1, ny1] = block.bbox
                  const x = nx0 * 1000
                  const y = ny0 * 1000
                  const w = Math.max(8, (nx1 - nx0) * 1000)
                  const h = Math.max(8, (ny1 - ny0) * 1000)
                  const isSelected = block.id === selectedBlockId
                  const style = BLOCK_COLORS[block.type] || BLOCK_COLORS.body

                  return (
                    <g key={block.id} className="cursor-pointer">
                      {/* Bounding Box Rect */}
                      <rect
                        x={x}
                        y={y}
                        width={w}
                        height={h}
                        fill={isSelected ? style.fill.replace('0.20', '0.35') : style.fill}
                        stroke={style.stroke}
                        strokeWidth={isSelected ? 2.5 : 1.5}
                        strokeDasharray={block.type === 'header_footer' ? '4 2' : 'none'}
                        rx={3}
                        onClick={(e) => {
                          e.stopPropagation()
                          setSelectedBlockId(block.id)
                        }}
                        onMouseDown={(e) => {
                          if (activeTool === 'select') {
                            e.stopPropagation()
                            setSelectedBlockId(block.id)
                            const rect = svgOverlayRef.current.getBoundingClientRect()
                            setDragState({
                              mode: 'move',
                              blockId: block.id,
                              startX: (e.clientX - rect.left) / rect.width,
                              startY: (e.clientY - rect.top) / rect.height,
                              origBbox: block.bbox,
                            })
                          }
                        }}
                      />

                      {/* Header Tag / Order Badge */}
                      <g transform={`translate(${x + 2}, ${y - 14 > 0 ? y - 14 : y + 2})`}>
                        <rect
                          width={block.order ? 65 : 55}
                          height={14}
                          rx={2}
                          fill={style.badge}
                          opacity={0.9}
                        />
                        <text
                          x={4}
                          y={10.5}
                          fill="#ffffff"
                          fontSize="9"
                          fontWeight="bold"
                          fontFamily="sans-serif"
                        >
                          {block.order ? `(#${block.order}) ${style.label}` : style.label}
                        </text>
                      </g>

                      {/* Resize Handles for Selected Box */}
                      {isSelected && activeTool === 'select' && (
                        <>
                          {/* NW */}
                          <circle
                            cx={x}
                            cy={y}
                            r={5}
                            fill="#ffffff"
                            stroke={style.stroke}
                            strokeWidth={2}
                            style={{ cursor: 'nwse-resize' }}
                            onMouseDown={(e) => {
                              e.stopPropagation()
                              const rect = svgOverlayRef.current.getBoundingClientRect()
                              setDragState({
                                mode: 'nw',
                                blockId: block.id,
                                startX: (e.clientX - rect.left) / rect.width,
                                startY: (e.clientY - rect.top) / rect.height,
                                origBbox: block.bbox,
                              })
                            }}
                          />
                          {/* NE */}
                          <circle
                            cx={x + w}
                            cy={y}
                            r={5}
                            fill="#ffffff"
                            stroke={style.stroke}
                            strokeWidth={2}
                            style={{ cursor: 'nesw-resize' }}
                            onMouseDown={(e) => {
                              e.stopPropagation()
                              const rect = svgOverlayRef.current.getBoundingClientRect()
                              setDragState({
                                mode: 'ne',
                                blockId: block.id,
                                startX: (e.clientX - rect.left) / rect.width,
                                startY: (e.clientY - rect.top) / rect.height,
                                origBbox: block.bbox,
                              })
                            }}
                          />
                          {/* SE */}
                          <circle
                            cx={x + w}
                            cy={y + h}
                            r={5}
                            fill="#ffffff"
                            stroke={style.stroke}
                            strokeWidth={2}
                            style={{ cursor: 'nwse-resize' }}
                            onMouseDown={(e) => {
                              e.stopPropagation()
                              const rect = svgOverlayRef.current.getBoundingClientRect()
                              setDragState({
                                mode: 'se',
                                blockId: block.id,
                                startX: (e.clientX - rect.left) / rect.width,
                                startY: (e.clientY - rect.top) / rect.height,
                                origBbox: block.bbox,
                              })
                            }}
                          />
                          {/* SW */}
                          <circle
                            cx={x}
                            cy={y + h}
                            r={5}
                            fill="#ffffff"
                            stroke={style.stroke}
                            strokeWidth={2}
                            style={{ cursor: 'nesw-resize' }}
                            onMouseDown={(e) => {
                              e.stopPropagation()
                              const rect = svgOverlayRef.current.getBoundingClientRect()
                              setDragState({
                                mode: 'sw',
                                blockId: block.id,
                                startX: (e.clientX - rect.left) / rect.width,
                                startY: (e.clientY - rect.top) / rect.height,
                                origBbox: block.bbox,
                              })
                            }}
                          />
                        </>
                      )}
                    </g>
                  )
                })}

                {/* In-progress Drawn Box Preview */}
                {drawingBox && (
                  <rect
                    x={drawingBox[0] * 1000}
                    y={drawingBox[1] * 1000}
                    width={(drawingBox[2] - drawingBox[0]) * 1000}
                    height={(drawingBox[3] - drawingBox[1]) * 1000}
                    fill="rgba(59, 130, 246, 0.3)"
                    stroke="#3b82f6"
                    strokeWidth={2}
                    strokeDasharray="4 2"
                  />
                )}
              </svg>
            )}
          </div>
        )}
      </div>

      {/* Modals */}
      <LayoutPropagateModal
        isOpen={isPropagateModalOpen}
        onClose={() => setIsPropagateModalOpen(false)}
        projectId={projectId}
        currentPage={currentPage}
        totalPages={totalPages}
        onPropagated={() => {
          fetchLayout(currentPage)
          if (onChapterUpdated) onChapterUpdated()
        }}
      />
    </div>
  )
}
