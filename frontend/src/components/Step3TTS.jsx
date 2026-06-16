import { useState, useEffect, useRef, useCallback } from 'react'
import { getVoices, ttsPreview,
         ttsDebugText, listLibraryVoices, updateProject } from '../api'

const ENGINES = [
  { value: 'edge-tts', label: 'Edge-TTS', desc: 'Free · Microsoft voices · Online', requiresCuda: false },
  { value: 'kokoro',   label: 'Kokoro-82M', desc: 'Local · Fast · GPU accelerated', requiresCuda: true },
  { value: 'f5-tts',  label: 'Voice Library', desc: 'Reusable cloned voices · GPU', requiresCuda: true },
]

export default function Step3TTS({ projectId, isActive, onNext, onBack, toast, cudaEnabled = true, onOpenVoiceLibrary, voiceLibraryRevision = 0 }) {
  const [engine, setEngine] = useState('edge-tts')
  const [voices, setVoices] = useState([])
  const [voice, setVoice] = useState('en-US-AriaNeural')
  const [speed, setSpeed] = useState(1.0)
  const [readHeadings, setReadHeadings] = useState(true)
  const [previewText, setPreviewText] = useState('Welcome to narratible. This is a preview of the selected voice.')
  const [previewing, setPreviewing] = useState(false)
  const [debuggingText, setDebuggingText] = useState(false)
  const [ttsDebug, setTtsDebug] = useState(null)
  const [libraryVoices, setLibraryVoices] = useState([])
  const [loadingVoices, setLoadingVoices] = useState(false)
  const [loadingLibraryVoices, setLoadingLibraryVoices] = useState(false)
  const audioRef = useRef()

  const refreshLibraryVoices = useCallback(async () => {
    setLoadingLibraryVoices(true)
    try {
      const res = await listLibraryVoices()
      const savedVoices = res.voices || []
      setLibraryVoices(savedVoices)
      setVoice(current => savedVoices.some(saved => saved.id === current) ? current : (savedVoices[0]?.id || ''))
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setLoadingLibraryVoices(false)
    }
  }, [toast])

  // Switch away from CUDA engines if CUDA becomes unavailable
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (!cudaEnabled) setEngine('edge-tts')
  }, [cudaEnabled])

  // Load voices when engine changes
  useEffect(() => {
    if (engine === 'f5-tts') {
      const timer = setTimeout(refreshLibraryVoices, 0)
      return () => clearTimeout(timer)
    }
    let active = true
    setTimeout(() => {
      if (active) setLoadingVoices(true)
    }, 0)
    getVoices(engine)
      .then(res => {
        if (!active) return
        setVoices(res.voices)
        if (res.voices.length > 0) setVoice(res.voices[0].id)
      })
      .catch(e => { if (active) toast(e.message, 'error') })
      .finally(() => { if (active) setLoadingVoices(false) })
    return () => { active = false }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [engine])

  useEffect(() => {
    if (!isActive || engine !== 'f5-tts') return
    const timer = setTimeout(refreshLibraryVoices, 0)
    return () => clearTimeout(timer)
  }, [engine, isActive, refreshLibraryVoices, voiceLibraryRevision])

  const handlePreview = async () => {
    if (!previewText.trim()) return
    setPreviewing(true)
    try {
      const res = await ttsPreview(projectId, previewText, engine, voice, speed)
      if (!res.ok) {
        const text = await res.text();
        try {
          const e = JSON.parse(text);
          throw new Error(e.detail || text);
        } catch {
          throw new Error(text);
        }
      }
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      audioRef.current.src = url
      audioRef.current.play()
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setPreviewing(false)
    }
  }

  const handleDebugText = async () => {
    if (!previewText.trim()) return
    setDebuggingText(true)
    try {
      const data = await ttsDebugText(projectId, previewText, engine, voice, speed)
      setTtsDebug(data)
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setDebuggingText(false)
    }
  }

  const handleNext = async () => {
    if (engine === 'f5-tts' && !voice) {
      toast('Create or select a library voice first.', 'error')
      return
    }
    try {
      await updateProject(projectId, { tts_engine: engine, tts_voice: voice, tts_speed: speed, tts_read_headings: readHeadings })
      onNext()
    } catch (e) {
      toast(e.message, 'error')
    }
  }

  // Filter voices to English by default for readability
  const filteredVoices = voices.filter(v =>
    !v.locale || v.locale.startsWith('en')
  )
  const selectedLibraryVoice = libraryVoices.find(savedVoice => savedVoice.id === voice)

  const handleLibraryVoiceChange = (voiceId) => {
    setVoice(voiceId)
    const selected = libraryVoices.find(savedVoice => savedVoice.id === voiceId)
    if (selected) setSpeed(selected.speed ?? 1.0)
  }

  useEffect(() => {
    if (engine !== 'f5-tts' || !selectedLibraryVoice) return
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSpeed(selectedLibraryVoice.speed ?? 1.0)
  }, [engine, selectedLibraryVoice])

  return (
    <div className="step-card">
      <div className="step-header">
        <div>
          <div className="step-title">Configure Voice</div>
          <div className="step-desc">Choose a TTS engine and voice, then synthesize all chapters.</div>
        </div>
      </div>

      <div className="flex gap-6">
        {/* Left: Engine + voice config */}
        <div style={{ flex: 1 }}>
          {/* Engine selector */}
          <div className="section-title">Engine</div>
          <div className="flex gap-3 mb-4" data-tip-anchor="engine-select">
            {ENGINES.map(eng => {
              const disabled = eng.requiresCuda && !cudaEnabled
              return (
                <label
                  key={eng.value}
                  className="glass flex gap-3 p-3 glass-hover"
                  style={{
                    flex: 1, cursor: disabled ? 'not-allowed' : 'pointer',
                    alignItems: 'flex-start', borderRadius: 'var(--radius-sm)',
                    opacity: disabled ? 0.45 : 1,
                  }}
                >
                  <input
                    type="radio" name="engine" value={eng.value}
                    checked={engine === eng.value}
                    onChange={() => !disabled && setEngine(eng.value)}
                    disabled={disabled}
                    style={{ marginTop: 3, width: 'auto' }}
                  />
                  <div>
                    <div style={{ fontWeight: 600, fontSize: 14 }}>{eng.label}</div>
                    <div className="text-xs text-muted mt-1">
                      {disabled ? '⚠ Requires CUDA GPU' : eng.desc}
                    </div>
                  </div>
                </label>
              )
            })}
          </div>

          {/* Voice selector */}
          {engine === 'f5-tts' && (
            <div className="glass p-3 mb-4" style={{ borderRadius: 'var(--radius-sm)' }}>
              <div className="text-sm" style={{ fontWeight: 600 }}>Voice Library mode</div>
              <div className="text-xs text-muted mt-1">
                Select a saved voice from the Voice Library panel, or create and test new voices from the library page.
              </div>
            </div>
          )}
          {engine !== 'f5-tts' && (
            <div className="field">
              <label>Voice {loadingVoices && <span className="text-muted">(loading...)</span>}</label>
              <select value={voice} onChange={e => setVoice(e.target.value)} disabled={loadingVoices}>
                {(filteredVoices.length ? filteredVoices : voices).map(v => (
                  <option key={v.id} value={v.id}>{v.name}</option>
                ))}
              </select>
            </div>
          )}

          {/* Speed */}
          <div className="field" data-tip-anchor="voice-speed">
            <label>Speed — {speed.toFixed(2)}×</label>
            <input
              type="range" min="0.5" max="2.0" step="0.05"
              value={speed} onChange={e => setSpeed(parseFloat(e.target.value))}
            />
            <div className="range-ticks text-xs text-muted">
              <span className="range-tick range-tick-start">0.5× slow</span>
              <span className="range-tick" style={{ left: '33.333%' }}>1.0× normal</span>
              <span className="range-tick range-tick-end">2.0× fast</span>
            </div>
          </div>

          {/* Read chapter headings */}
          <div className="field" data-tip-anchor="read-headings">
            <label className="flex gap-2 items-center" style={{ cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={readHeadings}
                onChange={e => setReadHeadings(e.target.checked)}
                style={{ width: 'auto' }}
              />
              <span>Read chapter headings aloud</span>
            </label>
            <div className="text-xs text-muted mt-1">
              Speaks each chapter's title before its content during synthesis.
            </div>
          </div>

          {/* Preview */}
          <div className="section-title mt-4">Preview</div>
          <div className="field">
            <textarea
              rows={2}
              value={previewText}
              onChange={e => setPreviewText(e.target.value)}
              placeholder="Type text to preview…"
            />
          </div>
          <div className="flex gap-2 items-center" data-tip-anchor="preview-section">
            <button className="btn btn-secondary" onClick={handlePreview} disabled={previewing || !voice}>
              {previewing ? '⏳ Generating…' : '▶ Play Preview'}
            </button>
            <button className="btn btn-ghost" onClick={handleDebugText} disabled={debuggingText || !previewText.trim()}>
              {debuggingText ? 'Inspecting…' : 'Debug Text'}
            </button>
            <audio ref={audioRef} style={{ flex: 1 }} controls />
          </div>
          {ttsDebug && (
            <div className="glass p-3 mt-3" style={{ borderRadius: 'var(--radius-sm)' }} data-tip-anchor="tts-debug-text">
              <div className="flex justify-between items-center mb-2">
                <div className="text-sm" style={{ fontWeight: 600 }}>TTS converted text</div>
                <div className="text-xs text-muted">
                  {ttsDebug.engine} · {(ttsDebug.enabled_modules || []).length ? ttsDebug.enabled_modules.join(', ') : 'no modules'}
                </div>
              </div>
              <textarea
                rows={6}
                readOnly
                value={ttsDebug.prepared_text || ''}
                style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace', fontSize: 12 }}
              />
              <div className="text-xs text-muted mt-2">
                {ttsDebug.segments?.length || 0} segment{ttsDebug.segments?.length === 1 ? '' : 's'}
              </div>
              {ttsDebug.segments?.length > 0 && (
                <div className="mt-2" style={{ display: 'grid', gap: 6 }}>
                  {ttsDebug.segments.map(segment => (
                    <details key={segment.index} className="glass p-2" style={{ borderRadius: 'var(--radius-sm)' }}>
                      <summary className="text-xs" style={{ cursor: 'pointer', fontWeight: 600 }}>
                        Segment {segment.index} · {segment.char_count} chars · pause {segment.pause_after_ms}ms
                      </summary>
                      <pre className="text-xs mt-2" style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{segment.text}</pre>
                    </details>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Right: Voice library summary */}
        <div style={{ width: 260, flexShrink: 0 }}>
          <div className="section-title">Voice Library</div>
          <div className="glass p-3 mb-4" style={{ borderRadius: 'var(--radius-sm)' }} data-tip-anchor="voice-library-select">
            {engine === 'f5-tts' ? (
              <>
                <label>Library voice {loadingLibraryVoices && <span className="text-muted">(loading...)</span>}</label>
                <select
                  value={voice}
                  onChange={e => handleLibraryVoiceChange(e.target.value)}
                  disabled={loadingLibraryVoices || libraryVoices.length === 0}
                >
                  {libraryVoices.length === 0 ? (
                    <option value="">No saved voices</option>
                  ) : libraryVoices.map(savedVoice => (
                    <option key={savedVoice.id} value={savedVoice.id}>{savedVoice.name}</option>
                  ))}
                </select>
                <div className="text-xs text-muted mt-1 mb-3">
                  {selectedLibraryVoice
                    ? 'This saved voice will be used for previews and full audiobook generation.'
                    : 'Create a saved voice before using Voice Library generation.'}
                </div>
                <button type="button" className="btn btn-ghost btn-sm w-full" onClick={onOpenVoiceLibrary} data-tip-anchor="voice-library-manage">
                  Open Voice Library
                </button>
              </>
            ) : (
              <div className="text-xs text-muted">
                Switch the engine to Voice Library to use reusable cloned voices created from reference clips.
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="step-nav">
        <button className="btn btn-ghost" onClick={onBack}>← Back</button>
        <button className="btn btn-primary btn-lg" onClick={handleNext} disabled={engine === 'f5-tts' && !voice}>
          Continue to Export →
        </button>
      </div>
    </div>
  )
}
