import { useState, useEffect, useRef } from 'react'
import { getProject, updateProject, getChapters, saveChapters, uploadCover } from '../api'

export default function Step2Editor({ projectId, onNext, onBack, toast }) {
  const [meta, setMeta] = useState({ title: '', author: '', cover_image: null })
  const [chapters, setChapters] = useState([])
  const [selectedIdx, setSelectedIdx] = useState(0)
  const [saving, setSaving] = useState(false)
  const [loading, setLoading] = useState(true)
  const coverRef = useRef()
  const textareaRef = useRef()

  useEffect(() => {
    if (!projectId) return
    Promise.all([getProject(projectId), getChapters(projectId)])
      .then(([p, chs]) => {
        setMeta({ title: p.title, author: p.author, cover_image: p.cover_image })
        setChapters(chs)
      })
      .catch(e => toast(e.message, 'error'))
      .finally(() => setLoading(false))
  }, [projectId])

  const updateChapter = (idx, field, value) => {
    setChapters(prev => prev.map((ch, i) => i === idx ? { ...ch, [field]: value } : ch))
  }

  const addChapter = () => {
    const newCh = { title: `Chapter ${chapters.length + 1}`, text: '', audio_path: null }
    setChapters(prev => [...prev, newCh])
    setSelectedIdx(chapters.length)
  }

  const deleteChapter = (idx) => {
    if (chapters.length <= 1) { toast('Cannot delete the last chapter.', 'error'); return }
    setChapters(prev => prev.filter((_, i) => i !== idx))
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
          <button className="btn btn-ghost btn-sm" onClick={splitAtCursor} title="Split chapter at cursor position">
            ✂ Split Here
          </button>
          <button className="btn btn-ghost btn-sm" onClick={addChapter}>+ Add Chapter</button>
          <button className="btn btn-secondary btn-sm" onClick={handleSave} disabled={saving}>
            {saving ? 'Saving…' : '💾 Save'}
          </button>
        </div>
      </div>

      <div className="flex" style={{ height: 'calc(100vh - 360px)', minHeight: 420 }}>
        {/* Chapter list */}
        <div style={{
          width: 240, flexShrink: 0,
          borderRight: '1px solid var(--glass-border)',
          overflowY: 'auto', padding: '12px 0',
        }}>
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
                <div className="truncate text-sm" style={{ fontWeight: i === selectedIdx ? 600 : 400 }}>
                  {ch.title || `Chapter ${i + 1}`}
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
        }}>
          <div className="section-title">Book Metadata</div>

          <div className="field">
            <label>Title</label>
            <input type="text" value={meta.title} onChange={e => setMeta(m => ({ ...m, title: e.target.value }))} />
          </div>
          <div className="field">
            <label>Author</label>
            <input type="text" value={meta.author} onChange={e => setMeta(m => ({ ...m, author: e.target.value }))} />
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
    </div>
  )
}
