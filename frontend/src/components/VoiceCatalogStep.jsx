import { useEffect, useMemo, useRef, useState } from 'react'
import {
  getProject,
  getVoices,
  listLibraryVoices,
  ttsDebugText,
  ttsPreview,
  updateProject,
} from '../api'

const RECOMMENDED_VOICES = [
  { engine: 'edge-tts', id: 'en-US-AriaNeural' },
  { engine: 'edge-tts', id: 'en-US-GuyNeural' },
  { engine: 'kokoro', id: 'af_heart' },
  { engine: 'kokoro', id: 'am_adam' },
]

const ENGINE_LABELS = {
  'edge-tts': 'Edge-TTS',
  kokoro: 'Kokoro',
  'f5-tts': 'F5-TTS',
  chatterbox: 'Chatterbox',
}

const engineNeedsCuda = engine => engine === 'kokoro' || engine === 'f5-tts'
const voiceKey = item => `${item.engine}:${item.id}`
const normalizeBuiltIn = (item, engine) => ({ ...item, engine, kind: 'built-in', engine_configured: true })
const normalizeCustom = item => ({ ...item, kind: 'custom', locale: 'Custom voice' })

function VoiceCard({ item, selected, disabled, onSelect }) {
  const engineLabel = ENGINE_LABELS[item.engine] || item.engine
  return (
    <button
      type="button"
      className={`voice-catalog-card glass glass-hover${selected ? ' is-selected' : ''}`}
      disabled={disabled}
      onClick={() => onSelect(item)}
      title={disabled ? `${engineLabel} is unavailable on the selected hardware.` : item.name}
    >
      <span className="voice-catalog-card-main">
        <span className="voice-catalog-name">{item.name}</span>
        <span className="text-xs text-muted">{item.locale || 'Voice'}</span>
      </span>
      <span className="voice-engine-badge">{engineLabel}</span>
    </button>
  )
}

export default function VoiceCatalogStep({
  projectId,
  isActive,
  onNext,
  onBack,
  toast,
  cudaEnabled = true,
  onOpenVoiceLibrary,
  voiceLibraryRevision = 0,
}) {
  const [engine, setEngine] = useState('edge-tts')
  const [voice, setVoice] = useState('en-US-AriaNeural')
  const [edgeVoices, setEdgeVoices] = useState([])
  const [kokoroVoices, setKokoroVoices] = useState([])
  const [libraryVoices, setLibraryVoices] = useState([])
  const [providerErrors, setProviderErrors] = useState({})
  const [loadingCatalog, setLoadingCatalog] = useState(false)
  const [browseOpen, setBrowseOpen] = useState(false)
  const [browseEngine, setBrowseEngine] = useState('all')
  const [voiceSearch, setVoiceSearch] = useState('')
  const [speed, setSpeed] = useState(1.0)
  const [exaggeration, setExaggeration] = useState(0.5)
  const [cfgWeight, setCfgWeight] = useState(0.3)
  const [readHeadings, setReadHeadings] = useState(true)
  const [previewText, setPreviewText] = useState('Welcome to narratible. This is a preview of the selected voice.')
  const [previewing, setPreviewing] = useState(false)
  const [debuggingText, setDebuggingText] = useState(false)
  const [ttsDebug, setTtsDebug] = useState(null)
  const audioRef = useRef(null)

  useEffect(() => {
    if (!projectId || !isActive) return
    let active = true
    const loadingTimer = setTimeout(() => {
      if (active) setLoadingCatalog(true)
    }, 0)
    Promise.allSettled([
      getProject(projectId),
      getVoices('edge-tts'),
      getVoices('kokoro'),
      listLibraryVoices(),
    ]).then(([projectResult, edgeResult, kokoroResult, libraryResult]) => {
      if (!active) return
      if (projectResult.status === 'fulfilled') {
        const project = projectResult.value
        setEngine(project.tts_engine || 'edge-tts')
        setVoice(project.tts_voice || 'en-US-AriaNeural')
        setSpeed(project.tts_speed ?? 1.0)
        setExaggeration(project.tts_exaggeration ?? 0.5)
        setCfgWeight(project.tts_cfg_weight ?? 0.3)
        setReadHeadings(project.tts_read_headings ?? true)
      } else {
        toast(projectResult.reason?.message || 'Could not load project voice settings.', 'error')
      }

      const errors = {}
      if (edgeResult.status === 'fulfilled') {
        setEdgeVoices((edgeResult.value.voices || []).map(item => normalizeBuiltIn(item, 'edge-tts')))
      } else {
        setEdgeVoices([])
        errors['edge-tts'] = edgeResult.reason?.message || 'Edge-TTS voices are unavailable.'
      }
      if (kokoroResult.status === 'fulfilled') {
        setKokoroVoices((kokoroResult.value.voices || []).map(item => normalizeBuiltIn(item, 'kokoro')))
      } else {
        setKokoroVoices([])
        errors.kokoro = kokoroResult.reason?.message || 'Kokoro voices are unavailable.'
      }
      if (libraryResult.status === 'fulfilled') {
        setLibraryVoices((libraryResult.value.voices || []).map(normalizeCustom))
      } else {
        setLibraryVoices([])
        errors.library = libraryResult.reason?.message || 'Custom voices are unavailable.'
      }
      setProviderErrors(errors)
    }).finally(() => {
      if (active) setLoadingCatalog(false)
    })
    return () => {
      active = false
      clearTimeout(loadingTimer)
    }
  }, [isActive, projectId, toast])

  useEffect(() => {
    if (!isActive || voiceLibraryRevision === 0) return
    let active = true
    listLibraryVoices()
      .then(result => { if (active) setLibraryVoices((result.voices || []).map(normalizeCustom)) })
      .catch(error => { if (active) toast(error.message, 'error') })
    return () => { active = false }
  }, [isActive, toast, voiceLibraryRevision])

  const builtInVoices = useMemo(() => [...edgeVoices, ...kokoroVoices], [edgeVoices, kokoroVoices])
  const allVoices = useMemo(() => [...builtInVoices, ...libraryVoices], [builtInVoices, libraryVoices])
  const selectedVoice = allVoices.find(item => item.engine === engine && item.id === voice) || null
  const selectedUnavailable = selectedVoice && engineNeedsCuda(selectedVoice.engine) && !cudaEnabled
  const recommended = RECOMMENDED_VOICES
    .map(recommendation => builtInVoices.find(item => item.engine === recommendation.engine && item.id === recommendation.id))
    .filter(Boolean)
  const normalizedSearch = voiceSearch.trim().toLocaleLowerCase()
  const browsedVoices = builtInVoices.filter(item => {
    if (browseEngine !== 'all' && item.engine !== browseEngine) return false
    if (!normalizedSearch) return true
    return `${item.name} ${item.locale || ''}`.toLocaleLowerCase().includes(normalizedSearch)
  })

  const selectCatalogVoice = item => {
    if (!item.engine_configured) {
      toast('Confirm this voice\'s engine in Manage Voices before selecting it.', 'error')
      onOpenVoiceLibrary()
      return
    }
    if (engineNeedsCuda(item.engine) && !cudaEnabled) return
    setEngine(item.engine)
    setVoice(item.id)
    setTtsDebug(null)
    if (item.kind === 'custom') {
      setSpeed(item.speed ?? 1.0)
      setExaggeration(item.exaggeration ?? 0.5)
      setCfgWeight(item.cfg_weight ?? 0.3)
    }
  }

  const handlePreview = async () => {
    if (!previewText.trim() || !selectedVoice) return
    setPreviewing(true)
    try {
      const response = await ttsPreview(
        projectId,
        previewText,
        engine,
        voice,
        speed,
        engine === 'chatterbox' ? { exaggeration, cfg_weight: cfgWeight } : {},
      )
      if (!response.ok) {
        const text = await response.text()
        let detail = text
        try { detail = JSON.parse(text).detail || text } catch { /* use response text */ }
        throw new Error(detail)
      }
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      if (audioRef.current?.src?.startsWith('blob:')) URL.revokeObjectURL(audioRef.current.src)
      if (audioRef.current) {
        audioRef.current.src = url
        audioRef.current.play()
      }
    } catch (error) {
      toast(error.message, 'error')
    } finally {
      setPreviewing(false)
    }
  }

  const handleDebugText = async () => {
    if (!previewText.trim() || !selectedVoice) return
    setDebuggingText(true)
    try {
      setTtsDebug(await ttsDebugText(projectId, previewText, engine, voice, speed))
    } catch (error) {
      toast(error.message, 'error')
    } finally {
      setDebuggingText(false)
    }
  }

  const handleNext = async () => {
    if (!selectedVoice || !selectedVoice.engine_configured) {
      toast('Choose an available voice before continuing.', 'error')
      return
    }
    if (selectedUnavailable) {
      toast('The selected voice is unavailable on the selected hardware.', 'error')
      return
    }
    try {
      await updateProject(projectId, {
        tts_engine: engine,
        tts_voice: voice,
        tts_speed: speed,
        tts_exaggeration: exaggeration,
        tts_cfg_weight: cfgWeight,
        tts_read_headings: readHeadings,
      })
      onNext()
    } catch (error) {
      toast(error.message, 'error')
    }
  }

  return (
    <div className="step-card voice-catalog-page">
      <div className="step-header">
        <div>
          <div className="step-title">Voice Library</div>
          <div className="step-desc">Choose a narrator, tune it for this project, then preview the result.</div>
        </div>
        <button type="button" className="btn btn-secondary btn-sm" onClick={onOpenVoiceLibrary}>Manage Voices</button>
      </div>

      <div className="voice-catalog-layout">
        <section className="voice-catalog-browser" data-tip-anchor="voice-catalog">
          <div className="flex justify-between items-center gap-3 mb-3">
            <div className="section-title" style={{ margin: 0 }}>Recommended</div>
            {loadingCatalog && <span className="text-xs text-muted">Loading voices...</span>}
          </div>
          <div className="voice-catalog-grid">
            {recommended.map(item => (
              <VoiceCard
                key={voiceKey(item)} item={item}
                selected={item.engine === engine && item.id === voice}
                disabled={engineNeedsCuda(item.engine) && !cudaEnabled}
                onSelect={selectCatalogVoice}
              />
            ))}
          </div>
          {recommended.length === 0 && !loadingCatalog && (
            <div className="glass p-3 text-sm text-muted">Recommended built-in voices are unavailable.</div>
          )}

          <div className="voice-catalog-section" data-tip-anchor="custom-voices">
            <div className="flex justify-between items-center gap-3 mb-3">
              <div className="section-title" style={{ margin: 0 }}>My Voices</div>
              <button type="button" className="btn btn-ghost btn-sm" onClick={onOpenVoiceLibrary}>Manage</button>
            </div>
            {libraryVoices.length ? (
              <div className="voice-catalog-grid">
                {libraryVoices.map(item => (
                  <VoiceCard
                    key={voiceKey(item)}
                    item={{ ...item, name: item.engine_configured ? item.name : `${item.name} (confirm engine)` }}
                    selected={item.engine === engine && item.id === voice}
                    disabled={item.engine_configured && engineNeedsCuda(item.engine) && !cudaEnabled}
                    onSelect={selectCatalogVoice}
                  />
                ))}
              </div>
            ) : (
              <div className="glass p-3 text-sm text-muted">No custom voices yet. Create one from Manage Voices.</div>
            )}
          </div>

          <div className="voice-catalog-section" data-tip-anchor="browse-voices">
            <button
              type="button" className="voice-browse-toggle" aria-expanded={browseOpen}
              onClick={() => setBrowseOpen(open => !open)}
            >
              <span>Browse built-in voices</span>
              <span aria-hidden="true">{browseOpen ? '-' : '+'}</span>
            </button>
            {browseOpen && (
              <div className="voice-browse-panel">
                <div className="voice-browse-tools">
                  <input
                    id="voice-catalog-search" name="voice-catalog-search" type="search" value={voiceSearch}
                    onChange={event => setVoiceSearch(event.target.value)}
                    placeholder="Search name or locale" aria-label="Search built-in voices"
                  />
                  <div className="segmented" role="group" aria-label="Filter voice engine">
                    {[
                      ['all', 'All'], ['edge-tts', 'Edge'], ['kokoro', 'Kokoro'],
                    ].map(([value, label]) => (
                      <button
                        type="button" key={value}
                        className={`segmented-btn${browseEngine === value ? ' is-active' : ''}`}
                        onClick={() => setBrowseEngine(value)}
                      >{label}</button>
                    ))}
                  </div>
                </div>
                <div className="voice-catalog-grid voice-catalog-scroll">
                  {browsedVoices.map(item => (
                    <VoiceCard
                      key={voiceKey(item)} item={item}
                      selected={item.engine === engine && item.id === voice}
                      disabled={engineNeedsCuda(item.engine) && !cudaEnabled}
                      onSelect={selectCatalogVoice}
                    />
                  ))}
                </div>
                {browsedVoices.length === 0 && <div className="text-sm text-muted">No voices match this filter.</div>}
              </div>
            )}
          </div>

          {Object.keys(providerErrors).length > 0 && (
            <div className="voice-provider-errors text-xs text-muted">
              {Object.entries(providerErrors).map(([provider, message]) => <div key={provider}>{message}</div>)}
            </div>
          )}
        </section>

        <aside className="voice-project-settings" data-tip-anchor="voice-project-settings">
          <div className="section-title">Project Voice</div>
          <div className="voice-selected-summary glass">
            {selectedVoice ? (
              <>
                <div className="voice-catalog-name">{selectedVoice.name}</div>
                <div className="text-xs text-muted">{ENGINE_LABELS[selectedVoice.engine]} · {selectedVoice.locale || 'Custom voice'}</div>
              </>
            ) : (
              <div className="text-sm text-muted">Choose an available voice from the catalog.</div>
            )}
          </div>

          <div className="field" data-tip-anchor="voice-speed">
            <label htmlFor="project-voice-speed">Speed - {speed.toFixed(2)}x</label>
            <input id="project-voice-speed" name="project-voice-speed" type="range" min="0.5" max="2" step="0.05" value={speed} onChange={event => setSpeed(parseFloat(event.target.value))} />
            <div className="range-ticks text-xs text-muted">
              <span className="range-tick range-tick-start">0.5x</span>
              <span className="range-tick" style={{ left: '33.333%' }}>1.0x</span>
              <span className="range-tick range-tick-end">2.0x</span>
            </div>
          </div>

          {engine === 'chatterbox' && (
            <div className="voice-engine-controls glass">
              <div className="field">
                <label htmlFor="project-voice-expression">Expression - {exaggeration.toFixed(2)}</label>
                <input id="project-voice-expression" name="project-voice-expression" type="range" min="0.25" max="1" step="0.05" value={exaggeration} onChange={event => setExaggeration(parseFloat(event.target.value))} />
              </div>
              <div className="field" style={{ marginBottom: 0 }}>
                <label htmlFor="project-voice-cfg">CFG Weight - {cfgWeight.toFixed(2)}</label>
                <input id="project-voice-cfg" name="project-voice-cfg" type="range" min="0" max="1" step="0.05" value={cfgWeight} onChange={event => setCfgWeight(parseFloat(event.target.value))} />
              </div>
            </div>
          )}

          <div className="field" data-tip-anchor="read-headings">
            <label className="flex gap-2 items-center" style={{ cursor: 'pointer' }}>
              <input name="project-read-headings" type="checkbox" checked={readHeadings} onChange={event => setReadHeadings(event.target.checked)} style={{ width: 'auto' }} />
              <span>Read chapter headings aloud</span>
            </label>
          </div>

          <div className="section-title">Preview</div>
          <div className="field">
            <textarea name="voice-preview-text" aria-label="Voice preview text" rows={3} value={previewText} onChange={event => setPreviewText(event.target.value)} placeholder="Type text to preview" />
          </div>
          <div className="voice-preview-actions" data-tip-anchor="preview-section">
            <button type="button" className="btn btn-secondary" onClick={handlePreview} disabled={previewing || !selectedVoice || selectedUnavailable}>
              {previewing ? 'Generating...' : 'Play Preview'}
            </button>
            <button type="button" className="btn btn-ghost" onClick={handleDebugText} disabled={debuggingText || !previewText.trim() || !selectedVoice}>
              {debuggingText ? 'Inspecting...' : 'Debug Text'}
            </button>
          </div>
          <audio ref={audioRef} className="voice-preview-audio" controls />
        </aside>
      </div>

      {ttsDebug && (
        <div className="glass p-3 mt-4" style={{ borderRadius: 'var(--radius-sm)' }} data-tip-anchor="tts-debug-text">
          <div className="flex justify-between items-center mb-2">
            <div className="text-sm" style={{ fontWeight: 600 }}>TTS converted text</div>
            <div className="text-xs text-muted">{ttsDebug.engine} · {(ttsDebug.enabled_modules || []).length ? ttsDebug.enabled_modules.join(', ') : 'no modules'}</div>
          </div>
          <textarea rows={6} readOnly value={ttsDebug.prepared_text || ''} style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace', fontSize: 12 }} />
          <div className="text-xs text-muted mt-2">{ttsDebug.segments?.length || 0} segment{ttsDebug.segments?.length === 1 ? '' : 's'}</div>
        </div>
      )}

      <div className="step-nav">
        <button className="btn btn-ghost" onClick={onBack}>Back</button>
        <button className="btn btn-primary btn-lg" onClick={handleNext} disabled={!selectedVoice || selectedUnavailable}>Continue to Export</button>
      </div>
    </div>
  )
}