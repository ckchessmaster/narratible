import { useState, useEffect, useRef } from 'react'
import { getProject, updateProject, getChapters, saveChapters, uploadCover, getDebugChapters, getDebugPrompt } from '../api'

export default function Step2Editor({ projectId, isActive, onNext, onBack, toast, debugMode = false }) {
  const [meta, setMeta] = useState({ title: '', author: '', cover_image: null })
  const [chapters, setChapters] = useState([])
  const [selectedIdx, setSelectedIdx] = useState(0)
  const [saving, setSaving] = useState(false)
  const [loading, setLoading] = useState(true)
  const [debugComparison, setDebugComparison] = useState(null)
  const [showHeuristic, setShowHeuristic] = useState(false)
  const [debugPrompt, setDebugPrompt] = useState(null)
  const [showPromptModal, setShowPromptModal] = useState(false)
  const coverRef = useRef()
  const textareaRef = useRef()

  useEffect(() => {
    if (!projectId) {
      // Resetting all state when the project is cleared — batched by React 18
      /* eslint-disable react-hooks/set-state-in-effect */
      setMeta({ title: '', author: '', cover_image: null })
      setChapters([])
      setSelectedIdx(0)
      setLoading(true)
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
    ])
      .then(([p, chs, dbg, prompt]) => {
        setMeta({ title: p.title, author: p.author, cover_image: p.cover_image })
        setChapters(chs)
        setDebugComparison(dbg ?? null)
        setDebugPrompt(prompt ?? null)
        if (!dbg) setShowHeuristic(false)
      })
      .catch(e => toast(e.message, 'error'))
      .finally(() => setLoading(false))
  }, [projectId, isActive, toast, debugMode])

  const updateChapter = (idx, field, value) => {
    setChapters(prev => prev.map((ch, i) => i === idx ? { ...ch, [field]: value } : ch))
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
    setChapters(updated)
    toast('Chapter split at cursor.', 'success')
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      await Promise.all([
        saveChapters(projectId, chapters),
        updateProject(projectId, { title: meta.title, author: meta.author }),
      ])
      toast('Saved!', 'success')
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  const handleCoverUpload = async (e) => {
    const f = e.target.files[0]
    if (!f) return
    try {
      const res = await uploadCover(projectId, f)
      setMeta(m => ({ ...m, cover_image: res.cover_image }))
      toast('Cover uploaded!', 'success')
    } catch (e) {
      toast(e.message, 'error')
    }
  }

  const handleNext = async () => {
    await handleSave()
    onNext()
  }

  if (loading) return <div className="step-card"><div className="text-secondary">Loading…</div></div>

  const ch = chapters[selectedIdx]

  return (
    <div className="step-card" style={{ padding: 0, overflow: 'hidden' }}>
      {/* Toolbar */}
      <div className="flex items-center justify-between p-4" style={{ borderBottom: '1px solid var(--glass-border)' }}>
        <div>
          <div className="step-title">Edit Chapters</div>
          <div className="step-desc">{chapters.length} chapter{chapters.length !== 1 ? 's' : ''} · Click a chapter to edit</div>
        </div>
        <div className="flex gap-2">
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
                    {ch.warnings?.length > 0 && <span style={{ fontSize: 10, marginRight: 3 }}>⚠️</span>}
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
                  {ch.warnings?.length > 0 && (
                    <span title="Verify boundaries" style={{ fontSize: 10 }}>⚠️</span>
                  )}
                </div>
                <div className="text-xs text-muted">{ch.text?.length ?? 0} chars</div>
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
              {ch.warnings?.length > 0 && (
                <div style={{
                  padding: '8px 12px',
                  background: 'rgba(234, 179, 8, 0.1)',
                  borderBottom: '1px solid rgba(234, 179, 8, 0.2)',
                  color: 'rgb(202, 138, 4)',
                  fontSize: 12,
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: 8
                }}>
                  <span style={{ fontSize: 16 }}>⚠️</span>
                  <div>
                    <div style={{ fontWeight: 600 }}>Chapter Warnings</div>
                    {ch.warnings.map((w, i) => <div key={i}>{w}</div>)}
                  </div>
                </div>
              )}
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
          <div className="section-title">Book Metadata</div>

          <div className="field">
            <label>Title</label>
            <input type="text" value={meta.title} onChange={e => setMeta(m => ({ ...m, title: e.target.value }))} autoComplete="off" />
          </div>
          <div className="field">
            <label>Author</label>
            <input type="text" value={meta.author} onChange={e => setMeta(m => ({ ...m, author: e.target.value }))} autoComplete="off" />
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
    </div>
  )
}
