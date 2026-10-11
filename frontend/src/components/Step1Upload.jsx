import { useState, useRef, useEffect } from 'react'
import {
  createProject,
  uploadPdf,
  parsePdf,
  cancelTask,
  pollTask,
  getProject,
  updateProject,
} from '../api'

export default function Step1Upload({
  projectId,
  setProjectId,
  onNext,
  toast,
  onProjectChanged,
}) {
  const [title, setTitle] = useState('')
  const [author, setAuthor] = useState('')
  const [file, setFile] = useState(null)
  const [existingPdf, setExistingPdf] = useState(null)
  const [dragOver, setDragOver] = useState(false)
  const [status, setStatus] = useState(null) // null | creating | uploading | parsing | done | error | cancelled
  const [progress, setProgress] = useState(0)
  const [progressMsg, setProgressMsg] = useState('')
  const [progressStage, setProgressStage] = useState('')
  const [taskError, setTaskError] = useState(null)
  const [currentProjId, setCurrentProjId] = useState(null)
  const [timeElapsed, setTimeElapsed] = useState(0)
  const [finalTime, setFinalTime] = useState(null)

  const inputRef = useRef()
  const timerRef = useRef()

  useEffect(() => {
    if (!projectId) {
      // Reset all form state when no active project is selected.
      setTitle('')
      setAuthor('')
      setFile(null)
      setExistingPdf(null)
      setStatus(null)
      setProgress(0)
      setProgressMsg('')
      setProgressStage('')
      setTaskError(null)
      setCurrentProjId(null)
      setTimeElapsed(0)
      setFinalTime(null)
    }
  }, [projectId])

  useEffect(() => {
    if (!projectId) return
    let cancelled = false

    getProject(projectId)
      .then(meta => {
        if (cancelled) return
        setTitle(meta.title || '')
        setAuthor(meta.author || '')
        setExistingPdf(meta.source_pdf || null)
        setFile(null)
        const parseStatus = meta.last_parse_status || null
        if (parseStatus && ['running', 'done', 'error', 'cancelled'].includes(parseStatus.status)) {
          setStatus(parseStatus.status)
          setProgress(Number.isFinite(parseStatus.progress) ? parseStatus.progress : 0)
          setProgressMsg(parseStatus.message || '')
          setProgressStage(parseStatus.stage || '')
          setTaskError(parseStatus.status === 'error' ? (parseStatus.error || parseStatus.message || null) : null)
          if (typeof parseStatus.duration_seconds === 'number') {
            const rounded = Math.max(0, Math.round(parseStatus.duration_seconds))
            setTimeElapsed(rounded)
            setFinalTime(parseStatus.status === 'running' ? null : rounded)
          } else {
            setTimeElapsed(0)
            setFinalTime(null)
          }
        } else {
          setStatus(null)
          setProgress(0)
          setProgressMsg('')
          setProgressStage('')
          setTaskError(null)
          setTimeElapsed(0)
          setFinalTime(null)
        }
        setCurrentProjId(projectId)
      })
      .catch(e => {
        if (!cancelled) {
          console.warn('Failed to load project details', e)
        }
      })

    return () => { cancelled = true }
  }, [projectId])

  useEffect(() => {
    if (status === 'uploading' || status === 'parsing' || status === 'creating') {
      timerRef.current = setInterval(() => {
        setTimeElapsed(prev => prev + 1)
      }, 1000)
    } else if (timerRef.current) {
      clearInterval(timerRef.current)
    }

    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [status])

  const handleDrop = (e) => {
    e.preventDefault()
    setDragOver(false)
    const f = e.dataTransfer.files?.[0]
    if (f && f.name.toLowerCase().endsWith('.pdf')) {
      setFile(f)
    } else {
      toast('Please drop a PDF file.', 'error')
    }
  }

  const handleFile = (e) => {
    const f = e.target.files?.[0]
    if (!f) return
    if (!f.name.toLowerCase().endsWith('.pdf')) {
      toast('Please select a PDF file.', 'error')
      return
    }
    setFile(f)
  }

  const handleSubmit = async () => {
    if (!title.trim()) { toast('Please enter a book title.', 'error'); return }
    if (!file && !existingPdf) { toast('Please select a PDF file.', 'error'); return }

    try {
      setStatus('creating')
      setTaskError(null)
      setProgress(5)
      setProgressStage('Creating project')
      setProgressMsg('Creating project...')
      setTimeElapsed(0)
      setFinalTime(null)

      let activeProjectId = projectId
      if (activeProjectId) {
        await updateProject(activeProjectId, { title: title.trim(), author: author.trim() })
      } else {
        const proj = await createProject(title.trim(), author.trim())
        activeProjectId = proj.id
        setProjectId(proj.id)
      }
      setCurrentProjId(activeProjectId)
      onProjectChanged?.()

      setStatus('uploading')
      setProgress(15)
      setProgressStage('Uploading PDF')
      if (file) {
        setProgressMsg('Uploading PDF...')
        await uploadPdf(activeProjectId, file)
        setExistingPdf({ filename: file.name, stored_path: 'source/original.pdf' })
      } else {
        setProgressMsg('Using existing uploaded PDF...')
      }

      setStatus('parsing')
      setProgress(25)
      setProgressStage('Parsing text')
      setProgressMsg('Reading PDF chapters & pages...')
      // Fast heuristic parsing with prose reflow enabled by default.
      const { task_id } = await parsePdf(activeProjectId, 'regex', ['prose_reflow'], 'safe', 'standard_modern')

      const finalTask = await pollTask(task_id, (t) => {
        setProgress(t.progress)
        setProgressStage(t.stage || '')
        setProgressMsg(t.message || '')
      })

      setStatus('done')
      setProgress(100)
      const durationSeconds = typeof finalTask.duration_seconds === 'number' ? Math.max(0, Math.round(finalTask.duration_seconds)) : timeElapsed
      setFinalTime(durationSeconds)
      toast('PDF parsed successfully! Ready for Chapter Studio.', 'success')
      onProjectChanged?.()
    } catch (e) {
      if (e.cancelled) {
        setStatus('cancelled')
        setTaskError(e.message || 'Processing cancelled.')
      } else {
        setStatus('error')
        toast(e.message, 'error')
        setTaskError(e.message)
      }
      setFinalTime(timeElapsed)
    }
  }

  const handleCancel = async () => {
    if (currentProjId) {
      try {
        await cancelTask(currentProjId)
        setStatus('cancelled')
        setFinalTime(timeElapsed)
        setProgressMsg('Processing cancelled.')
        setTaskError('Processing cancelled.')
      } catch (err) {
        toast('Failed to cancel: ' + err.message, 'error')
      }
    }
  }

  const busy = ['creating', 'uploading', 'parsing'].includes(status)

  const formatTime = (s) => {
    const mins = Math.floor(s / 60)
    const secs = s % 60
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

  return (
    <div style={{ maxWidth: 840, margin: '0 auto' }}>
      <div className="step-card">
        <div className="step-header">
          <div>
            <div className="step-title">Upload PDF</div>
            <div className="step-desc">Create a project and select your source PDF to extract chapters.</div>
          </div>
        </div>

        <div className="field-row" data-tip-anchor="upload-meta">
          <div className="field">
            <label>Book Title *</label>
            <input
              type="text"
              placeholder="e.g. The Great Gatsby"
              value={title}
              onChange={e => setTitle(e.target.value)}
              disabled={busy}
              autoComplete="off"
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
              autoComplete="off"
            />
          </div>
        </div>

        <div
          className={`drop-zone ${dragOver ? 'drag-over' : ''}`}
          onClick={() => !busy && inputRef.current?.click()}
          onDragOver={e => { e.preventDefault(); setDragOver(true) }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
        >
          <input
            ref={inputRef}
            type="file"
            accept="application/pdf"
            style={{ display: 'none' }}
            onChange={handleFile}
          />
          {file ? (
            <>
              <div style={{ fontSize: 36 }}>📄</div>
              <div className="mt-2" style={{ fontWeight: 600, fontSize: 16 }}>{file.name}</div>
              <div className="text-sm text-muted mt-1">{(file.size / 1024 / 1024).toFixed(2)} MB</div>
            </>
          ) : existingPdf?.filename ? (
            <>
              <div style={{ fontSize: 36 }}>📄</div>
              <div className="mt-2" style={{ fontWeight: 600, fontSize: 16 }}>{existingPdf.filename}</div>
              <div className="text-sm text-muted mt-1">Using saved PDF. Click or drop a new file to replace it.</div>
            </>
          ) : (
            <>
              <div style={{ fontSize: 40 }}>📂</div>
              <div className="mt-2" style={{ fontWeight: 600, fontSize: 16 }}>Drop PDF here or click to browse</div>
              <div className="text-sm text-muted mt-1">Standard PDF files supported</div>
            </>
          )}
        </div>

        {(busy || status === 'done' || status === 'error' || status === 'cancelled') && (
          <div className="mt-4">
            <div className="flex justify-between text-sm text-secondary mb-1">
              <span style={{ fontWeight: 600 }}>
                {status === 'done'
                  ? 'Parsing complete!'
                  : status === 'error'
                    ? 'Parsing failed'
                    : status === 'cancelled'
                      ? 'Parsing cancelled'
                      : (progressStage || progressMsg)}
              </span>
              <span>{formatTime(finalTime ?? timeElapsed)} {status !== 'done' && `- ${progress}%`}</span>
            </div>
            {status !== 'done' && progressStage && progressMsg && progressMsg !== progressStage && (
              <div className="text-xs text-muted mb-2">{progressMsg}</div>
            )}
            <div className="progress-bar">
              <div
                className="progress-bar-fill"
                style={{
                  width: `${progress}%`,
                  backgroundColor:
                    status === 'done'
                      ? 'var(--success)'
                      : status === 'error'
                        ? 'var(--danger)'
                        : status === 'cancelled'
                          ? 'rgb(245,158,11)'
                          : 'var(--accent-primary)',
                }}
              />
            </div>
          </div>
        )}

        {taskError && (
          <div className="glass mt-4 p-4" style={{ borderColor: 'var(--danger)', backgroundColor: 'var(--danger-bg)' }}>
            <div className="text-danger" style={{ fontWeight: 600 }}>Error / Aborted</div>
            <div className="text-sm mt-1 mb-2 text-secondary">{taskError}</div>
            <button className="btn btn-ghost btn-sm" onClick={() => setTaskError(null)}>Dismiss</button>
          </div>
        )}

        <div className="step-nav mt-4">
          <div />
          <div className="flex gap-2">
            {busy && (
              <button className="btn btn-danger btn-lg" onClick={handleCancel}>
                Abort
              </button>
            )}
            {status === 'done' ? (
              <>
                <button className="btn btn-secondary btn-lg" onClick={handleSubmit} title="Re-parse PDF with current settings">
                  Re-parse PDF
                </button>
                <button className="btn btn-primary btn-lg" onClick={onNext}>
                  Open Chapter Studio →
                </button>
              </>
            ) : (
              <>
                {projectId && !busy && (
                  <button className="btn btn-secondary btn-lg" onClick={onNext}>
                    Continue →
                  </button>
                )}
                <button className="btn btn-primary btn-lg" data-tip-anchor="parse-button" onClick={handleSubmit} disabled={busy}>
                  {busy ? 'Processing...' : 'Parse PDF →'}
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
