import { X, Sparkles, Check, ArrowRight } from 'lucide-react'

export default function VisionDiffModal({
  isOpen,
  onClose,
  pageNumber,
  localBlocks = [],
  visionBlocks = [],
  onAcceptVision,
}) {
  if (!isOpen) return null

  const groupBlocks = (blocks) => {
    return {
      body: blocks.filter(b => b.type === 'body' || b.type === 'callout'),
      marginalia: blocks.filter(b => b.type === 'marginalia'),
      footnotes: blocks.filter(b => b.type === 'footnote'),
    }
  }

  const localGroups = groupBlocks(localBlocks)
  const visionGroups = groupBlocks(visionBlocks)

  return (
    <div className="modal-backdrop">
      <div className="modal-card" style={{ maxWidth: '840px', width: '90vw' }}>
        <div className="modal-header">
          <div className="flex items-center gap-2">
            <Sparkles size={18} className="text-accent" />
            <span className="font-semibold text-base">AI Vision Layout Comparison: Page {pageNumber}</span>
          </div>
          <button type="button" className="btn-icon btn-sm" onClick={onClose}>
            <X size={16} />
          </button>
        </div>

        <div className="modal-body" style={{ maxHeight: '65vh', overflowY: 'auto', padding: '16px' }}>
          <p className="text-xs text-muted mb-4">
            Compare local OCR extraction with Gemini Vision multimodal recognition. Accepting vision results will update the page layout and synchronize with the chapter editor.
          </p>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
            {/* Local Column */}
            <div className="p-3 bg-surface border border-border rounded-lg">
              <div className="text-xs font-bold text-muted uppercase tracking-wider mb-2 flex items-center justify-between">
                <span>Local OCR Blocks</span>
                <span className="text-[10px] text-dim">{localBlocks.length} blocks</span>
              </div>

              <div className="space-y-3">
                <div>
                  <span className="text-[11px] font-semibold text-blue-400 block mb-1">Body Text ({localGroups.body.length})</span>
                  {localGroups.body.map((b, i) => (
                    <div key={b.id || i} className="p-2 bg-base/60 rounded text-xs text-gray-200 mb-1 border border-border/40">
                      {b.text.slice(0, 160)}{b.text.length > 160 ? '…' : ''}
                    </div>
                  ))}
                  {localGroups.body.length === 0 && <span className="text-xs text-dim italic">None detected</span>}
                </div>

                <div>
                  <span className="text-[11px] font-semibold text-purple-400 block mb-1">Marginalia ({localGroups.marginalia.length})</span>
                  {localGroups.marginalia.map((b, i) => (
                    <div key={b.id || i} className="p-2 bg-purple-950/20 border border-purple-800/40 rounded text-xs text-purple-200 mb-1">
                      {b.text}
                    </div>
                  ))}
                  {localGroups.marginalia.length === 0 && <span className="text-xs text-dim italic">None detected</span>}
                </div>

                <div>
                  <span className="text-[11px] font-semibold text-amber-400 block mb-1">Footnotes ({localGroups.footnotes.length})</span>
                  {localGroups.footnotes.map((b, i) => (
                    <div key={b.id || i} className="p-2 bg-amber-950/20 border border-amber-800/40 rounded text-xs text-amber-200 mb-1">
                      {b.text}
                    </div>
                  ))}
                  {localGroups.footnotes.length === 0 && <span className="text-xs text-dim italic">None detected</span>}
                </div>
              </div>
            </div>

            {/* Vision Column */}
            <div className="p-3 bg-surface border border-accent/40 rounded-lg">
              <div className="text-xs font-bold text-accent uppercase tracking-wider mb-2 flex items-center justify-between">
                <span>AI Vision Extraction</span>
                <span className="text-[10px] text-accent/80">{visionBlocks.length} blocks</span>
              </div>

              <div className="space-y-3">
                <div>
                  <span className="text-[11px] font-semibold text-blue-400 block mb-1">Body Text ({visionGroups.body.length})</span>
                  {visionGroups.body.map((b, i) => (
                    <div key={b.id || i} className="p-2 bg-base/80 rounded text-xs text-gray-100 mb-1 border border-blue-900/40">
                      {b.text.slice(0, 160)}{b.text.length > 160 ? '…' : ''}
                    </div>
                  ))}
                  {visionGroups.body.length === 0 && <span className="text-xs text-dim italic">None detected</span>}
                </div>

                <div>
                  <span className="text-[11px] font-semibold text-purple-400 block mb-1">Marginalia ({visionGroups.marginalia.length})</span>
                  {visionGroups.marginalia.map((b, i) => (
                    <div key={b.id || i} className="p-2 bg-purple-950/30 border border-purple-600/50 rounded text-xs text-purple-200 mb-1">
                      {b.text}
                    </div>
                  ))}
                  {visionGroups.marginalia.length === 0 && <span className="text-xs text-dim italic">None detected</span>}
                </div>

                <div>
                  <span className="text-[11px] font-semibold text-amber-400 block mb-1">Footnotes ({visionGroups.footnotes.length})</span>
                  {visionGroups.footnotes.map((b, i) => (
                    <div key={b.id || i} className="p-2 bg-amber-950/30 border border-amber-600/50 rounded text-xs text-amber-200 mb-1">
                      {b.text}
                    </div>
                  ))}
                  {visionGroups.footnotes.length === 0 && <span className="text-xs text-dim italic">None detected</span>}
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="modal-footer" style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', padding: '12px 16px' }}>
          <button type="button" className="btn-secondary btn-sm" onClick={onClose}>
            Discard &amp; Keep Local
          </button>
          <button
            type="button"
            className="btn-primary btn-sm flex items-center gap-2"
            onClick={() => {
              onAcceptVision(visionBlocks)
              onClose()
            }}
          >
            <Check size={14} />
            <span>Accept AI Vision Results</span>
          </button>
        </div>
      </div>
    </div>
  )
}
