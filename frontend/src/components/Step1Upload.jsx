import { useState, useRef } from 'react'
import { createProject, uploadPdf, parsePdf, pollTask } from '../api'

export default function Step1Upload({ setProjectId, onNext, toast }) {
  const [title, setTitle] = useState('')
  const [author, setAuthor] = useState('')
  const [cleaner, setCleaner] = useState('regex')
  const [file, setFile] = useState(null)
  const [dragOver, setDragOver] = useState(false)
  const [status, setStatus] = useState(null) // null | 'creating' | 'uploading' | 'parsing' | 'done'
  const [progress, setProgress] = useState(0)
  const [progressMsg, setProgressMsg] = useState('')
  const inputRef = useRef()

  const handleDrop = (e) => {
    e.preventDefault()
    setDragOver(false)
    const f = e.dataTransfer.files[0]
    if (f && f.name.endsWith('.pdf')) setFile(f)
    else toast('Please drop a PDF file.', 'error')
  }

  const handleFile = (e) => {
    const f = e.target.files[0]
    if (f) setFile(f)
  }

  const handleSubmit = async () => {
    if (!title.trim()) { toast('Please enter a book title.', 'error'); return }
    if (!file) { toast('Please select a PDF file.', 'error'); return }

    try {
      setStatus('creating')
      setProgress(5)
      setProgressMsg('Creating project…')

      const proj = await createProject(title.trim(), author.trim())
      setProjectId(proj.id)

      setStatus('uploading')
      setProgress(20)
      setProgressMsg('Uploading PDF…')
      await uploadPdf(proj.id, file)

      setStatus('parsing')
      setProgress(30)
      setProgressMsg('Starting parse…')
      const { task_id } = await parsePdf(proj.id, cleaner)

      await pollTask(task_id, (t) => {
        setProgress(30 + Math.round(t.progress * 0.7))
        setProgressMsg(t.message)
      })

      setStatus('done')
      setProgress(100)
      toast('PDF parsed successfully!', 'success')
      setTimeout(onNext, 600)
    } catch (e) {
      setStatus(null)
      toast(e.message, 'error')
    }
  }

  const busy = status && status !== 'done'

  return (
    <div className="step-card">
      <div className="step-header">
        <div>
          <div className="step-title">Upload PDF</div>
          <div className="step-desc">Create a project and upload the source PDF to begin parsing.</div>
        </div>
      </div>

      {/* Book metadata */}
      <div className="field-row">
        <div className="field">
          <label>Book Title *</label>
          <input
            type="text"
            placeholder="e.g. The Great Gatsby"
            value={title}
            onChange={e => setTitle(e.target.value)}
            disabled={busy}
          />
        </div>
        <div className="field">
          <label>Author</label>
          <input
            type="text"
            placeholder="e.g. F. Scott Fitzgerald"
            value={author}
            onChange={e => setAuthor(e.target.value)}
            disabled={busy}
          />
        </div>
      </div>

      {/* Drop zone */}
      <div
        className={`drop-zone ${dragOver ? 'drag-over' : ''}`}
        onClick={() => !busy && inputRef.current.click()}
        onDragOver={e => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
      >
        <input ref={inputRef} type="file" accept=".pdf" style={{ display: 'none' }} onChange={handleFile} />
        {file ? (
          <>
            <div style={{ fontSize: 32 }}>📄</div>
            <div className="mt-2" style={{ fontWeight: 500 }}>{file.name}</div>
            <div className="text-sm text-muted mt-1">{(file.size / 1024 / 1024).toFixed(2)} MB</div>
          </>
        ) : (
          <>
            <div style={{ fontSize: 36 }}>📂</div>
            <div className="mt-2" style={{ fontWeight: 500 }}>Drop PDF here or click to browse</div>
            <div className="text-sm text-muted mt-1">Only PDF files are supported</div>
          </>
        )}
      </div>

      {/* Cleaner option */}
      <div className="field mt-4">
        <label>Text Cleanup Method</label>
        <div className="flex gap-3 mt-1" style={{ flexWrap: 'wrap' }}>
          {[
            { value: 'regex', label: 'Heuristic (fast, offline)', desc: 'Regex rules — no API key needed' },
            { value: 'llm', label: 'LLM (Gemini / OpenAI)', desc: 'Best quality — requires API key in Settings' },
            { value: 'embedded', label: 'Embedded Local LLM', desc: 'Runs locally — uses GPU VRAM' },
          ].map(opt => (
            <label
              key={opt.value}
              className="glass flex gap-3 p-3"
              style={{ flex: 1, cursor: 'pointer', borderRadius: 'var(--radius-sm)', alignItems: 'flex-start' }}
            >
              <input
                type="radio"
                name="cleaner"
                value={opt.value}
                checked={cleaner === opt.value}
                onChange={() => setCleaner(opt.value)}
                disabled={busy}
                style={{ marginTop: 3, width: 'auto' }}
              />
              <div>
                <div style={{ fontWeight: 500, fontSize: 14 }}>{opt.label}</div>
                <div className="text-xs text-muted mt-1">{opt.desc}</div>
              </div>
            </label>
          ))}
        </div>
      </div>

      {/* Progress */}
      {busy && (
        <div className="mt-4">
          <div className="flex justify-between text-sm text-secondary mb-2">
            <span>{progressMsg}</span>
            <span>{progress}%</span>
          </div>
          <div className="progress-bar">
            <div className="progress-bar-fill" style={{ width: `${progress}%` }} />
          </div>
        </div>
      )}

      <div className="step-nav">
        <div />
        <button className="btn btn-primary btn-lg" onClick={handleSubmit} disabled={busy}>
          {busy ? progressMsg : 'Parse PDF →'}
        </button>
      </div>
    </div>
  )
}
