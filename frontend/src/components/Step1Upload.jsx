import React, { useState, useRef, useEffect } from 'react'
import { createProject, uploadPdf, parsePdf, cancelTask, pollTask } from '../api'

export default function Step1Upload({ projectId, setProjectId, onNext, toast, cudaEnabled = true, hasCloudKey = false }) {
  const [title, setTitle] = useState('')
  const [author, setAuthor] = useState('')
  const [cleaner, setCleaner] = useState('regex')
  const [file, setFile] = useState(null)
  const [dragOver, setDragOver] = useState(false)
  const [status, setStatus] = useState(null) // null | 'creating' | 'uploading' | 'parsing' | 'done'
  const [progress, setProgress] = useState(0)
  const [progressMsg, setProgressMsg] = useState('')
  const [taskError, setTaskError] = useState(null)
  const [currentProjId, setCurrentProjId] = useState(null)
  const [llmOutput, setLlmOutput] = useState('')
  const [timeElapsed, setTimeElapsed] = useState(0)
  const [finalTime, setFinalTime] = useState(null)
  
  const inputRef = useRef()
  const outputRef = useRef()
  const timerRef = useRef()

  useEffect(() => {
    if (!setProjectId || !projectId) {
      setTitle('')
      setAuthor('')
      setFile(null)
      setStatus(null)
      setProgress(0)
      setProgressMsg('')
      setTaskError(null)
      setCurrentProjId(null)
      setLlmOutput('')
      setTimeElapsed(0)
      setFinalTime(null)
    }
  }, [projectId, setProjectId])

  useEffect(() => {
    if (status === 'uploading' || status === 'parsing' || status === 'creating') {
      timerRef.current = setInterval(() => {
        setTimeElapsed(prev => prev + 1)
      }, 1000)
    } else {
      if (timerRef.current) clearInterval(timerRef.current)
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [status])

  useEffect(() => {
    if (outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight
    }
  }, [llmOutput])

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
    if (cleaner === 'embedded' && !cudaEnabled) {
      toast('Embedded Local LLM requires a CUDA GPU. Please select a different cleanup method.', 'error')
      return
    }

    try {
      setStatus('creating')
      setTaskError(null)
      setProgress(5)
      setProgressMsg('Creating project…')
      setLlmOutput('')
      setTimeElapsed(0)
      setFinalTime(null)

      const proj = await createProject(title.trim(), author.trim())
      setProjectId(proj.id)
      setCurrentProjId(proj.id)

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
        if (t.llm_output) setLlmOutput(t.llm_output)
      })

      setStatus('done')
      setProgress(100)
      setFinalTime(timeElapsed)
      toast('PDF parsed successfully!', 'success')
      setTimeout(onNext, 600)
    } catch (e) {
      setStatus(null)
      if (e.message.includes('Gated Model Access') || e.message.includes('HuggingFace') || e.message.includes('cancel') || e.message.includes('abort')) {
        setTaskError(e.message)
      } else {
        toast(e.message, 'error')
      }
    }
  }

  const handleCancel = async () => {
    if (currentProjId) {
      try {
        await cancelTask(currentProjId)
        setStatus(null)
        setTaskError("Processing cancelled.")
      } catch (err) {
        toast("Failed to cancel: " + err.message, "error")
      }
    }
  }

  const busy = status && status !== 'done'
  
  const formatTime = (s) => {
    const mins = Math.floor(s / 60)
    const secs = s % 60
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

  // Parses LLM output to handle <think> tags.
  // Unclosed <think> is rendered in a darker/muted color.
  // Closed <think>...</think> is completely removed so it disappears when real output is generated.
  const renderLlmOutput = (text) => {
    if (!text) return null;
    
    // First, remove fully closed think blocks completely
    let processedText = text.replace(/<think>[\s\S]*?<\/think>/g, '');
    
    // Check if there is an unclosed think block at the end
    const unclosedThinkIndex = processedText.indexOf('<think>');
    if (unclosedThinkIndex !== -1) {
      const beforeThink = processedText.substring(0, unclosedThinkIndex);
      const thinkContent = processedText.substring(unclosedThinkIndex + 7); // 7 is length of <think>
      
      return (
        <>
          {beforeThink}
          <div style={{ color: 'var(--text-muted)', opacity: 0.6, fontStyle: 'italic', marginTop: '8px', borderLeft: '2px solid var(--glass-border)', paddingLeft: '8px' }}>
            <div style={{ fontSize: '10px', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '4px' }}>Thinking...</div>
            {thinkContent}
          </div>
        </>
      );
    }
    
    return processedText;
  }

  return (
    <div style={{ display: 'flex', gap: '20px', alignItems: 'stretch' }}>
      
      {/* CENTER: Form */}
      <div className="step-card" style={{ flex: '2', minWidth: 400 }}>
        <div className="step-header">
          <div>
            <div className="step-title">Upload PDF</div>
            <div className="step-desc">Create a project and upload the source PDF to begin parsing.</div>
          </div>
        </div>

        {/* Book metadata */}
        <div className="field-row" data-tip-anchor="upload-meta">
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
        <div className="field mt-4" data-tip-anchor="cleanup-method">
          <label>Text Cleanup Method</label>
          <div className="flex gap-3 mt-1" style={{ flexWrap: 'wrap' }}>
            {[
              { value: 'regex', label: 'Heuristic (fast, offline)', desc: 'Regex rules — no API key or GPU needed', disabled: false },
              { value: 'llm', label: 'LLM (Gemini / OpenAI)', desc: hasCloudKey ? 'Best quality — uses your configured API key' : 'Requires a Gemini or OpenAI key in ⚙ Settings', disabled: false },
              { value: 'embedded', label: 'Embedded Local LLM', desc: cudaEnabled ? 'Runs locally — uses GPU VRAM' : 'Requires a CUDA-capable GPU', disabled: !cudaEnabled },
            ].map(opt => (
              <label
                key={opt.value}
                className="glass flex gap-3 p-3"
                style={{
                  flex: 1, cursor: (busy || opt.disabled) ? 'not-allowed' : 'pointer',
                  borderRadius: 'var(--radius-sm)', alignItems: 'flex-start',
                  opacity: opt.disabled ? 0.45 : 1,
                }}
              >
                <input
                  type="radio"
                  name="cleaner"
                  value={opt.value}
                  checked={cleaner === opt.value}
                  onChange={() => !opt.disabled && setCleaner(opt.value)}
                  disabled={busy || opt.disabled}
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

        {(busy || status === 'done') && (
          <div className="mt-4">
            <div className="flex justify-between text-sm text-secondary mb-2">
              <span>{status === 'done' ? 'Parsing complete!' : progressMsg}</span>
              <span>{formatTime(status === 'done' ? finalTime ?? timeElapsed : timeElapsed)} {status !== 'done' && `• ${progress}%`}</span>
            </div>
            <div className="progress-bar">
              <div className="progress-bar-fill" style={{ width: `${progress}%`, backgroundColor: status === 'done' ? 'var(--success)' : 'var(--accent-primary)' }} />
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

        <div className="step-nav">
          <div />
          <div className="flex gap-2">
            {busy && (
              <button className="btn btn-danger btn-lg" onClick={handleCancel}>
                Abort
              </button>
            )}
            {projectId && !busy && (
              <button className="btn btn-secondary btn-lg" onClick={onNext}>
                Continue →
              </button>
            )}
            <button className="btn btn-primary btn-lg" data-tip-anchor="parse-button" onClick={handleSubmit} disabled={busy}>
              {busy ? 'Processing...' : 'Parse PDF →'}
            </button>
          </div>
        </div>
      </div>

      {/* RIGHT: Output */}
      {cleaner !== 'regex' && (
        <div className="glass flex flex-col" style={{ flex: '1', minWidth: 300, borderRadius: 'var(--radius)', maxHeight: '70vh' }}>
          <div className="p-3 text-sm text-secondary" style={{ borderBottom: '1px solid var(--glass-border)', fontWeight: 500 }}>
            Live LLM Output
          </div>
          <div ref={outputRef} style={{ flex: 1, padding: 15, overflowY: 'auto', whiteSpace: 'pre-wrap', fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--foreground)' }}>
            {llmOutput ? renderLlmOutput(llmOutput) : <span className="text-muted italic">Processing will appear here...</span>}
          </div>
        </div>
      )}

    </div>
  )
}
