import { useState, useEffect, useRef } from 'react'
import { getVoices, ttsPreview,
         uploadVoiceSample, listVoiceSamples, updateProject } from '../api'

const ENGINES = [
  { value: 'edge-tts', label: 'Edge-TTS', desc: 'Free · Microsoft voices · Online', requiresCuda: false },
  { value: 'kokoro',   label: 'Kokoro-82M', desc: 'Local · Fast · GPU accelerated', requiresCuda: true },
  { value: 'f5-tts',  label: 'F5-TTS Clone', desc: 'Voice cloning · Uses your uploaded sample · GPU', requiresCuda: true },
]

export default function Step3TTS({ projectId, isActive, onNext, onBack, toast, cudaEnabled = true }) {
  const [engine, setEngine] = useState('edge-tts')
  const [voices, setVoices] = useState([])
  const [voice, setVoice] = useState('en-US-AriaNeural')
  const [speed, setSpeed] = useState(1.0)
  const [previewText, setPreviewText] = useState('Welcome to narratible. This is a preview of the selected voice.')
  const [previewing, setPreviewing] = useState(false)
  const [voiceSamples, setVoiceSamples] = useState([])
  const [loadingVoices, setLoadingVoices] = useState(false)
  const audioRef = useRef()
  const sampleInputRef = useRef()

  // Switch away from CUDA engines if CUDA becomes unavailable
  useEffect(() => {
    if (!cudaEnabled) setEngine('edge-tts')
  }, [cudaEnabled])

  // Load voices when engine changes
  useEffect(() => {
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

  // Load voice samples
  useEffect(() => {
    if (!projectId || !isActive) return
    listVoiceSamples(projectId)
      .then(res => setVoiceSamples(res.voices))
      .catch(() => {})
  }, [projectId, isActive])

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

  const handleSampleUpload = async (e) => {
    const f = e.target.files[0]
    if (!f) return
    try {
      await uploadVoiceSample(projectId, f)
      const res = await listVoiceSamples(projectId)
      setVoiceSamples(res.voices)
      toast('Voice sample uploaded!', 'success')
    } catch (e) {
      toast(e.message, 'error')
    }
  }

  const handleNext = async () => {
    try {
      await updateProject(projectId, { tts_engine: engine, tts_voice: voice, tts_speed: speed })
      onNext()
    } catch (e) {
      toast(e.message, 'error')
    }
  }

  // Filter voices to English by default for readability
  const filteredVoices = voices.filter(v =>
    !v.locale || v.locale.startsWith('en')
  )

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

          {/* Voice selector — hidden for f5-tts since it uses uploaded sample */}
          {engine !== 'f5-tts' && (
            <div className="field">
              <label>Voice {loadingVoices && <span className="text-muted">(loading…)</span>}</label>
              <select value={voice} onChange={e => setVoice(e.target.value)} disabled={loadingVoices}>
                {(filteredVoices.length ? filteredVoices : voices).map(v => (
                  <option key={v.id} value={v.id}>{v.name}</option>
                ))}
              </select>
            </div>
          )}
          {engine === 'f5-tts' && (
            <div className="glass p-3 mb-4" style={{ borderRadius: 'var(--radius-sm)', borderColor: 'rgba(99,102,241,0.3)' }}>
              <div className="text-sm" style={{ fontWeight: 500 }}>🎤 Voice Cloning Mode</div>
              <div className="text-xs text-muted mt-1">
                Upload a <strong>.wav</strong> voice sample (5–15 seconds, clear speech, no music)
                in the panel on the right. F5-TTS will clone that voice for all chapters.
              </div>
            </div>
          )}

          {/* Speed */}
          <div className="field" data-tip-anchor="voice-speed">
            <label>Speed — {speed.toFixed(2)}×</label>
            <input
              type="range" min="0.5" max="2.0" step="0.05"
              value={speed} onChange={e => setSpeed(parseFloat(e.target.value))}
            />
            <div className="flex justify-between text-xs text-muted mt-1">
              <span>0.5× slow</span><span>1.0× normal</span><span>2.0× fast</span>
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
            <audio ref={audioRef} style={{ flex: 1 }} controls />
          </div>
        </div>

        {/* Right: Voice samples + synthesis */}
        <div style={{ width: 260, flexShrink: 0 }}>
          {/* Voice samples */}
          <div className="section-title">Voice Samples</div>
          <div className="glass p-3 mb-4" style={{ borderRadius: 'var(--radius-sm)' }}>
            <div className="text-xs text-muted mb-2">
              {engine === 'f5-tts'
                ? <span style={{ color: 'var(--accent-primary)' }}>⚠ Required for F5-TTS cloning. Upload a 5–15s WAV clip.</span>
                : 'Upload .wav samples for F5-TTS voice cloning (optional for other engines).'}
            </div>
            <input
              ref={sampleInputRef}
              type="file" accept=".wav,.mp3,.flac"
              style={{ display: 'none' }}
              onChange={handleSampleUpload}
            />
            <button className="btn btn-ghost btn-sm w-full" onClick={() => sampleInputRef.current.click()}>
              + Upload Sample
            </button>
            {voiceSamples.length > 0 && (
              <div className="mt-2">
                {voiceSamples.map(s => (
                  <div key={s} className="text-xs text-secondary flex items-center gap-1 mt-1">
                    🎤 <span className="truncate">{s}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="step-nav">
        <button className="btn btn-ghost" onClick={onBack}>← Back</button>
        <button className="btn btn-primary btn-lg" onClick={handleNext}>
          Continue to Export →
        </button>
      </div>
    </div>
  )
}
