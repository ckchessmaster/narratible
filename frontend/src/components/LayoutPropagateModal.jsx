import { useState } from 'react'
import { X, Copy, Layers, Loader2, CheckCircle2 } from 'lucide-react'
import { propagateLayout } from '../api'

export default function LayoutPropagateModal({
  isOpen,
  onClose,
  projectId,
  currentPage = 1,
  totalPages = 1,
  onPropagated,
}) {
  const [mode, setMode] = useState('alternating') // 'alternating' | 'single'
  const defaultEven = currentPage % 2 === 0 ? currentPage : Math.max(1, currentPage - 1)
  const defaultOdd = currentPage % 2 !== 0 ? currentPage : Math.min(totalPages, currentPage + 1)

  const [evenPage, setEvenPage] = useState(defaultEven)
  const [oddPage, setOddPage] = useState(defaultOdd)
  const [singlePage, setSinglePage] = useState(currentPage)
  const [startPage, setStartPage] = useState(1)
  const [endPage, setEndPage] = useState(totalPages)
  const [reextractAll, setReextractAll] = useState(true)

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [successCount, setSuccessCount] = useState(null)

  if (!isOpen) return null

  const handleApply = async () => {
    setLoading(true)
    setError(null)
    setSuccessCount(null)

    try {
      const payload = {
        mode,
        target_start_page: Number(startPage),
        target_end_page: Number(endPage),
        reextract_all: reextractAll,
      }
      if (mode === 'alternating') {
        payload.template_even_page = Number(evenPage)
        payload.template_odd_page = Number(oddPage)
      } else {
        payload.template_page = Number(singlePage)
      }

      const res = await propagateLayout(projectId, payload)
      setSuccessCount(res.updated_pages_count || 0)
      if (onPropagated) {
        onPropagated()
      }
      setTimeout(() => {
        onClose()
      }, 1200)
    } catch (err) {
      setError(err.message || 'Failed to propagate layout template')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="modal-backdrop">
      <div className="modal-card" style={{ maxWidth: '480px' }}>
        <div className="modal-header">
          <div className="flex items-center gap-2">
            <Layers size={18} className="text-accent" />
            <span className="font-semibold text-base">Propagate Layout Template</span>
          </div>
          <button type="button" className="btn-icon btn-sm" onClick={onClose} disabled={loading}>
            <X size={16} />
          </button>
        </div>

        <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '16px', padding: '16px' }}>
          {error && (
            <div className="p-3 bg-red-950/40 border border-red-800 rounded text-xs text-red-200">
              {error}
            </div>
          )}

          {successCount !== null && (
            <div className="p-3 bg-emerald-950/40 border border-emerald-800 rounded text-xs text-emerald-200 flex items-center gap-2">
              <CheckCircle2 size={16} className="text-emerald-400" />
              <span>Successfully propagated layout across {successCount} pages!</span>
            </div>
          )}

          {/* Mode Selector */}
          <div>
            <label className="text-xs font-semibold text-muted uppercase tracking-wider block mb-2">
              Propagation Mode
            </label>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
              <button
                type="button"
                className={`btn-tag ${mode === 'alternating' ? 'active' : ''}`}
                style={{ padding: '8px', textAlign: 'center', justifyContent: 'center' }}
                onClick={() => setMode('alternating')}
              >
                Alternating (Even / Odd)
              </button>
              <button
                type="button"
                className={`btn-tag ${mode === 'single' ? 'active' : ''}`}
                style={{ padding: '8px', textAlign: 'center', justifyContent: 'center' }}
                onClick={() => setMode('single')}
              >
                Single Page Clone
              </button>
            </div>
          </div>

          {/* Source Template Page(s) */}
          {mode === 'alternating' ? (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <div>
                <label className="text-xs text-muted block mb-1">Verso (Even) Template</label>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-muted">Page</span>
                  <input
                    type="number"
                    className="input-text text-sm"
                    value={evenPage}
                    min={1}
                    max={totalPages}
                    onChange={(e) => setEvenPage(e.target.value)}
                    style={{ width: '80px' }}
                  />
                </div>
              </div>
              <div>
                <label className="text-xs text-muted block mb-1">Recto (Odd) Template</label>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-muted">Page</span>
                  <input
                    type="number"
                    className="input-text text-sm"
                    value={oddPage}
                    min={1}
                    max={totalPages}
                    onChange={(e) => setOddPage(e.target.value)}
                    style={{ width: '80px' }}
                  />
                </div>
              </div>
            </div>
          ) : (
            <div>
              <label className="text-xs text-muted block mb-1">Source Template Page</label>
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted">Page</span>
                <input
                  type="number"
                  className="input-text text-sm"
                  value={singlePage}
                  min={1}
                  max={totalPages}
                  onChange={(e) => setSinglePage(e.target.value)}
                  style={{ width: '90px' }}
                />
              </div>
            </div>
          )}

          {/* Target Range */}
          <div>
            <label className="text-xs font-semibold text-muted uppercase tracking-wider block mb-2">
              Apply to Page Range
            </label>
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted">From</span>
                <input
                  type="number"
                  className="input-text text-sm"
                  value={startPage}
                  min={1}
                  max={totalPages}
                  onChange={(e) => setStartPage(e.target.value)}
                  style={{ width: '80px' }}
                />
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted">To</span>
                <input
                  type="number"
                  className="input-text text-sm"
                  value={endPage}
                  min={1}
                  max={totalPages}
                  onChange={(e) => setEndPage(e.target.value)}
                  style={{ width: '80px' }}
                />
              </div>
              <span className="text-xs text-muted">of {totalPages}</span>
            </div>
          </div>

          {/* Re-extract text toggle */}
          <label className="flex items-center gap-2 text-xs text-muted cursor-pointer mt-1">
            <input
              type="checkbox"
              checked={reextractAll}
              onChange={(e) => setReextractAll(e.target.checked)}
            />
            <span>Re-extract bounded text and synchronize chapter paragraphs</span>
          </label>
        </div>

        <div className="modal-footer" style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', padding: '12px 16px' }}>
          <button type="button" className="btn-secondary btn-sm" onClick={onClose} disabled={loading}>
            Cancel
          </button>
          <button
            type="button"
            className="btn-primary btn-sm flex items-center gap-2"
            onClick={handleApply}
            disabled={loading}
          >
            {loading && <Loader2 size={14} className="spin" />}
            <span>Apply Template</span>
          </button>
        </div>
      </div>
    </div>
  )
}
