import { useState, useRef, useEffect } from 'react'
import {
  createProject,
  uploadPdf,
  parsePdf,
  cancelTask,
  pollTask,
  getParsingModules,
  getCleaningProfiles,
  submitTaskDecision,
  getProject,
  updateProject,
} from '../api'

export default function Step1Upload({ projectId, setProjectId, onNext, toast, cudaEnabled = true, hasCloudKey = false, debugMode = false, onProjectChanged }) {
  const [title, setTitle] = useState('')
  const [author, setAuthor] = useState('')
  const [cleaner, setCleaner] = useState('regex')
  const [cleaningProfile, setCleaningProfile] = useState('safe')
  const [cleaningProfiles, setCleaningProfiles] = useState([])
  const [parsingModules, setParsingModules] = useState([])
  const [enabledModules, setEnabledModules] = useState([])
  const [file, setFile] = useState(null)
  const [existingPdf, setExistingPdf] = useState(null)
  const [dragOver, setDragOver] = useState(false)
  const [status, setStatus] = useState(null) // null | creating | uploading | parsing | waiting_input | done | error | cancelled
  const [progress, setProgress] = useState(0)
  const [progressMsg, setProgressMsg] = useState('')
  const [progressStage, setProgressStage] = useState('')
  const [taskError, setTaskError] = useState(null)
  const [currentProjId, setCurrentProjId] = useState(null)
  const [llmOutput, setLlmOutput] = useState('')
  const [timeElapsed, setTimeElapsed] = useState(0)
  const [finalTime, setFinalTime] = useState(null)
  const [tokensPerSecond, setTokensPerSecond] = useState(0)

  const inputRef = useRef()
  const outputRef = useRef()
  const timerRef = useRef()
  const handledDecisionIdsRef = useRef(new Set())
  const tpsSampleRef = useRef({ ts: 0, chars: 0 })

  useEffect(() => {
    if (!projectId) {
      // Reset all form state when no active project is selected.
      /* eslint-disable react-hooks/set-state-in-effect */
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
      setLlmOutput('')
      setTimeElapsed(0)
      setFinalTime(null)
      setTokensPerSecond(0)
      tpsSampleRef.current = { ts: 0, chars: 0 }
      handledDecisionIdsRef.current = new Set()
      /* eslint-enable react-hooks/set-state-in-effect */
    }
  }, [projectId])

  useEffect(() => {
    if (!projectId) return
    let cancelled = false

    getProject(projectId)
      .then(meta => {
        if (cancelled) return
        // Rehydrate Step 1 controls from saved metadata when resuming.
        setTitle(meta.title || '')
        setAuthor(meta.author || '')
        setEnabledModules(meta.enabled_modules || [])
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
        setLlmOutput('')
      })
      .catch(e => {
        if (!cancelled) {
          console.warn('Failed to load project details', e)
        }
      })

    return () => { cancelled = true }
  }, [projectId])

  useEffect(() => {
    if (status === 'uploading' || status === 'parsing' || status === 'creating' || status === 'waiting_input') {
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

  useEffect(() => {
    if (outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight
    }
  }, [llmOutput])

  const updateTpsFromOutput = (nextOutput) => {
    const now = Date.now()
    const prev = tpsSampleRef.current
    const currentChars = nextOutput.length
    const deltaChars = Math.max(0, currentChars - prev.chars)
    const deltaSec = prev.ts > 0 ? (now - prev.ts) / 1000 : 0

    if (deltaSec > 0.15 && deltaChars > 0) {
      const sampleTps = (deltaChars / 4) / deltaSec
      setTokensPerSecond(prevTps => (prevTps <= 0 ? sampleTps : (prevTps * 0.7 + sampleTps * 0.3)))
    } else if (currentChars === 0) {
      setTokensPerSecond(0)
    }

    tpsSampleRef.current = { ts: now, chars: currentChars }
  }

  useEffect(() => {
    getParsingModules()
      .then(mods => setParsingModules(mods ?? []))
      .catch(e => console.warn('Failed to load parsing modules', e))

    getCleaningProfiles()
      .then(profiles => setCleaningProfiles(profiles ?? []))
      .catch(e => console.warn('Failed to load cleaning profiles', e))
  }, [])

  const toggleModule = (id) => {
    setEnabledModules(prev =>
      prev.includes(id) ? prev.filter(m => m !== id) : [...prev, id]
    )
  }

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
    if (!file && !existingPdf) { toast('Please select a PDF file.', 'error'); return }
    if (cleaner === 'embedded' && !cudaEnabled) {
      toast('Embedded Local LLM requires a CUDA GPU. Please select a different cleanup method.', 'error')
      return
    }
    if ((cleaner === 'llm' || cleaner === 'llm_chapters_only') && !hasCloudKey) {
      toast('Cloud LLM cleanup requires a Gemini or OpenAI key in Settings.', 'error')
      return
    }

    try {
      setStatus('creating')
      setTaskError(null)
      setProgress(3)
      setProgressStage('Creating project')
      setProgressMsg('Creating project...')
      setLlmOutput('')
      setTimeElapsed(0)
      setFinalTime(null)
      setTokensPerSecond(0)
      tpsSampleRef.current = { ts: Date.now(), chars: 0 }
      handledDecisionIdsRef.current = new Set()

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
      setProgress(6)
      setProgressStage('Uploading PDF')
      if (file) {
        setProgressMsg('Uploading PDF...')
        await uploadPdf(activeProjectId, file)
        setExistingPdf({ filename: file.name, stored_path: 'source/original.pdf' })
      } else {
        setProgressMsg('Using existing uploaded PDF...')
      }

      setStatus('parsing')
      setProgress(9)
      setProgressStage('Starting parse')
      setProgressMsg('Starting parse...')
      const { task_id } = await parsePdf(activeProjectId, cleaner, enabledModules, cleaningProfile)

      await pollTask(task_id, (t) => {
        if (t.status === 'waiting_input' && t.pending_decision) {
          setStatus('waiting_input')
          const decisionId = t.pending_decision.id || `${t.pending_decision.chapter_index}-${t.pending_decision.chunk_index}`
          if (!handledDecisionIdsRef.current.has(decisionId)) {
            handledDecisionIdsRef.current.add(decisionId)
            const promptMessage = `${t.pending_decision.message}\n\n${t.pending_decision.error || ''}\n\nOK = Retry Gemini (5 more attempts)\nCancel = Use heuristic for this chunk`
            const retry = window.confirm(promptMessage)
            submitTaskDecision(task_id, retry ? 'retry' : 'heuristic').catch(err => {
              toast(`Failed to submit decision: ${err.message}`, 'error')
            })
          }
        }
        setProgress(t.progress)
        setProgressStage(t.stage || '')
        setProgressMsg(t.message || '')
        const nextOutput = t.llm_output || ''
        updateTpsFromOutput(nextOutput)
        setLlmOutput(nextOutput)
      })

      setStatus('done')
      setProgress(100)
      setFinalTime(timeElapsed)
      toast('PDF parsed successfully!', 'success')
      onProjectChanged?.()
      setTimeout(onNext, 600)
    } catch (e) {
      setFinalTime(timeElapsed)
      if (e.cancelled) {
        setStatus('cancelled')
        setTaskError(e.message || 'Processing cancelled.')
      } else if (e.message.includes('Gated Model Access') || e.message.includes('HuggingFace') || e.message.includes('cancel') || e.message.includes('abort')) {
        setStatus('error')
        setTaskError(e.message)
      } else {
        setStatus('error')
        toast(e.message, 'error')
        setTaskError(e.message)
      }
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

  const busy = ['creating', 'uploading', 'parsing', 'waiting_input'].includes(status)

  const formatTime = (s) => {
    const mins = Math.floor(s / 60)
    const secs = s % 60
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

  const renderLlmOutput = (text) => {
    if (!text) return null

    let processedText = text.replace(/<think>[\s\S]*?<\/think>/g, '')
    const unclosedThinkIndex = processedText.indexOf('<think>')
    if (unclosedThinkIndex !== -1) {
      const beforeThink = processedText.substring(0, unclosedThinkIndex)
      const thinkContent = processedText.substring(unclosedThinkIndex + 7)
      return (
        <>
          {beforeThink}
          <div style={{ color: 'var(--text-muted)', opacity: 0.6, fontStyle: 'italic', marginTop: '8px', borderLeft: '2px solid var(--glass-border)', paddingLeft: '8px' }}>
            <div style={{ fontSize: '10px', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '4px' }}>Thinking...</div>
            {thinkContent}
          </div>
        </>
      )
    }

    return processedText
  }

  return (
    <div style={{ display: 'flex', gap: '20px', alignItems: 'stretch' }}>
      <div className="step-card" style={{ flex: '2', minWidth: 400 }}>
        <div className="step-header">
          <div>
            <div className="step-title">Upload PDF</div>
            <div className="step-desc">Create a project and upload the source PDF to begin parsing.</div>
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
          ) : existingPdf?.filename ? (
            <>
              <div style={{ fontSize: 32 }}>📄</div>
              <div className="mt-2" style={{ fontWeight: 500 }}>{existingPdf.filename}</div>
              <div className="text-sm text-muted mt-1">Using saved PDF. Drop a new file to replace it.</div>
            </>
          ) : (
            <>
              <div style={{ fontSize: 36 }}>📂</div>
              <div className="mt-2" style={{ fontWeight: 500 }}>Drop PDF here or click to browse</div>
              <div className="text-sm text-muted mt-1">Only PDF files are supported</div>
            </>
          )}
        </div>

        <div className="field mt-4" data-tip-anchor="cleanup-method">
          <label>Text Cleanup Method</label>
          <div className="flex gap-3 mt-1" style={{ flexWrap: 'wrap' }}>
            {[
              { value: 'regex', label: 'Heuristic (fast, offline)', desc: 'Regex rules - no API key or GPU needed', disabled: false },
              { value: 'llm', label: 'LLM (Gemini / OpenAI)', desc: hasCloudKey ? 'Best quality - uses your configured API key' : 'Requires a Gemini or OpenAI key in Settings', disabled: !hasCloudKey },
              { value: 'embedded', label: 'Embedded Local LLM', desc: cudaEnabled ? 'Runs locally - uses GPU VRAM' : 'Requires a CUDA-capable GPU', disabled: !cudaEnabled },
            ].map(opt => (
              <label
                key={opt.value}
                className="glass flex gap-3 p-3"
                style={{
                  flex: 1,
                  cursor: (busy || opt.disabled) ? 'not-allowed' : 'pointer',
                  borderRadius: 'var(--radius-sm)',
                  alignItems: 'flex-start',
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

            {debugMode && (
              <label
                className="glass flex gap-3 p-3"
                style={{
                  flexBasis: '100%',
                  cursor: busy ? 'not-allowed' : 'pointer',
                  borderRadius: 'var(--radius-sm)',
                  alignItems: 'flex-start',
                }}
              >
                <input
                  type="radio"
                  name="cleaner"
                  value="llm_chapters_only"
                  checked={cleaner === 'llm_chapters_only' || cleaner === 'llm_chapters_only_embedded'}
                  onChange={() => setCleaner('llm_chapters_only')}
                  disabled={busy}
                  style={{ marginTop: 3, width: 'auto' }}
                />
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 500, fontSize: 14 }}>
                    LLM Chapter Review Only <span style={{ fontSize: 11, color: 'var(--accent-secondary)', fontWeight: 400 }}>(Debug)</span>
                  </div>
                  <div className="text-xs text-muted mt-1">Runs LLM boundary review only - text cleanup uses regex. For testing chapter detection.</div>
                  {(cleaner === 'llm_chapters_only' || cleaner === 'llm_chapters_only_embedded') && (
                    <div className="flex gap-4 mt-2">
                      <label className="flex items-center gap-1 text-xs cursor-pointer" style={{ fontWeight: 500, opacity: hasCloudKey ? 1 : 0.45 }}>
                        <input
                          type="radio"
                          name="debug_provider"
                          checked={cleaner === 'llm_chapters_only'}
                          onChange={() => setCleaner('llm_chapters_only')}
                          disabled={busy || !hasCloudKey}
                          style={{ width: 'auto' }}
                        />
                        Cloud (Gemini / OpenAI){!hasCloudKey ? ' (no key)' : ''}
                      </label>
                      <label className="flex items-center gap-1 text-xs cursor-pointer" style={{ fontWeight: 500, opacity: cudaEnabled ? 1 : 0.45 }}>
                        <input
                          type="radio"
                          name="debug_provider"
                          checked={cleaner === 'llm_chapters_only_embedded'}
                          onChange={() => setCleaner('llm_chapters_only_embedded')}
                          disabled={busy || !cudaEnabled}
                          style={{ width: 'auto' }}
                        />
                        Local LLM{!cudaEnabled ? ' (no GPU)' : ''}
                      </label>
                    </div>
                  )}
                </div>
              </label>
            )}
          </div>
        </div>

        {cleaner !== 'regex' && cleaningProfiles.length > 0 && (
          <div className="field mt-4" data-tip-anchor="cleanup-profile">
            <label>LLM Cleaning Profile</label>
            <div className="flex gap-2 mt-1" style={{ flexWrap: 'wrap' }}>
              {cleaningProfiles.map(profile => (
                <button
                  key={profile.id}
                  type="button"
                  className={`btn btn-sm ${cleaningProfile === profile.id ? 'btn-primary' : 'btn-ghost'}`}
                  onClick={() => !busy && setCleaningProfile(profile.id)}
                  disabled={busy}
                  title={profile.description}
                  style={{ flex: 1, minWidth: 130, justifyContent: 'center' }}
                >
                  {profile.label}
                </button>
              ))}
            </div>
            <div className="text-xs text-muted mt-2">
              {cleaningProfiles.find(profile => profile.id === cleaningProfile)?.description}
            </div>
          </div>
        )}

        {parsingModules.length > 0 && (
          <div className="field mt-4" data-tip-anchor="parsing-modules">
            <label>Reading Enhancements</label>
            <div className="flex gap-3 mt-1" style={{ flexWrap: 'wrap' }}>
              {parsingModules.map(mod => (
                <label
                  key={mod.id}
                  className="glass flex gap-3 p-3"
                  style={{
                    flex: 1,
                    minWidth: 220,
                    cursor: busy ? 'not-allowed' : 'pointer',
                    borderRadius: 'var(--radius-sm)',
                    alignItems: 'flex-start',
                  }}
                >
                  <input
                    type="checkbox"
                    checked={enabledModules.includes(mod.id)}
                    onChange={() => !busy && toggleModule(mod.id)}
                    disabled={busy}
                    style={{ marginTop: 3, width: 'auto' }}
                  />
                  <div>
                    <div style={{ fontWeight: 500, fontSize: 14 }}>{mod.name}</div>
                    <div className="text-xs text-muted mt-1">{mod.description}</div>
                  </div>
                </label>
              ))}
            </div>
          </div>
        )}

        {(busy || status === 'done' || status === 'error' || status === 'cancelled') && (
          <div className="mt-4">
            <div className="flex justify-between text-sm text-secondary mb-1">
              <span style={{ fontWeight: 600 }}>
                {status === 'done' ? 'Parsing complete!' : status === 'error' ? 'Parsing failed' : status === 'cancelled' ? 'Parsing cancelled' : (progressStage || progressMsg)}
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

      {cleaner !== 'regex' && (
        <div className="glass flex flex-col" style={{ flex: '1', minWidth: 300, borderRadius: 'var(--radius)', maxHeight: '70vh' }}>
          {(() => {
            const estimatedTokens = Math.ceil((llmOutput || '').length / 4)
            return (
          <div className="p-3 text-sm text-secondary flex items-center justify-between" style={{ borderBottom: '1px solid var(--glass-border)', fontWeight: 500 }}>
            <span>Live LLM Output</span>
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              <span title="Estimated from character count; not exact model tokenizer output." style={{ textDecoration: 'underline dotted', cursor: 'help' }}>est.</span>{' '}
              ~{tokensPerSecond.toFixed(1)} tok/s · ~{estimatedTokens} tok
            </span>
          </div>
            )
          })()}
          <div ref={outputRef} style={{ flex: 1, padding: 15, overflowY: 'auto', whiteSpace: 'pre-wrap', fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--foreground)' }}>
            {llmOutput ? renderLlmOutput(llmOutput) : <span className="text-muted italic">Processing will appear here...</span>}
          </div>
        </div>
      )}
    </div>
  )
}
