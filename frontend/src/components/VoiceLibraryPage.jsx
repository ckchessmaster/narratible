import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  addLibraryVoiceSample,
  createLibraryVoice,
  deleteLibraryVoice,
  deleteLibraryVoiceSample,
  enhanceLibraryVoiceSample,
  getVoices,
  listLibraryVoices,
  setLibraryVoiceSample,
  testDraftLibraryVoice,
  testLibraryVoice,
  updateLibraryVoice,
} from '../api'

const DEFAULT_TEST_TEXT = 'Welcome to narratible. This is a quick test of the saved library voice.'
const NEW_DRAFT = {
  name: '', engine: 'edge-tts', engine_configured: true, provider_voice_id: '', notes: '', speed: 1.0,
  temperature: 0.7, exaggeration: 0.5, cfg_weight: 0.3, file: null,
}

const ENGINE_LABELS = {
  'edge-tts': 'Edge-TTS',
  kokoro: 'Kokoro',
  'f5-tts': 'F5-TTS',
  chatterbox: 'Chatterbox',
}

const isCloneEngine = engine => engine === 'f5-tts' || engine === 'chatterbox'

async function responseError(response) {
  const text = await response.text()
  try {
    const data = JSON.parse(text)
    return new Error(data.detail || data.message || text || response.statusText)
  } catch {
    return new Error(text || response.statusText)
  }
}

function draftFromVoice(voice) {
  return {
    name: voice?.name || '',
    engine: voice?.engine || 'f5-tts',
    engine_configured: voice?.engine_configured ?? false,
    provider_voice_id: voice?.provider_voice_id || '',
    notes: voice?.notes || '',
    speed: voice?.speed ?? 1.0,
    temperature: voice?.temperature ?? 0.7,
    exaggeration: voice?.exaggeration ?? 0.5,
    cfg_weight: voice?.cfg_weight ?? 0.3,
    file: null,
  }
}

export default function VoiceLibraryPage({ onBack, toast, onChanged }) {
  const [voices, setVoices] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [draft, setDraft] = useState(NEW_DRAFT)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [sampleBusy, setSampleBusy] = useState('')
  const [enhancementDevice, setEnhancementDevice] = useState('auto')
  const [testText, setTestText] = useState(DEFAULT_TEST_TEXT)
  const [previewUrl, setPreviewUrl] = useState('')
  const [providerVoices, setProviderVoices] = useState([])
  const [loadingProviderVoices, setLoadingProviderVoices] = useState(false)
  const audioRef = useRef(null)
  const formRef = useRef(null)
  const sampleInputRef = useRef(null)

  const selectedVoice = useMemo(
    () => voices.find(voice => voice.id === selectedId) || null,
    [voices, selectedId]
  )
  const selectedSampleFilenames = useMemo(() => {
    if (!selectedVoice) return []
    const filenames = [selectedVoice.sample_filename, ...(selectedVoice.sample_filenames || [])]
      .filter(Boolean)
    return [...new Set(filenames)]
  }, [selectedVoice])
  const isNew = !selectedVoice
  const draftUsesCloneEngine = isCloneEngine(draft.engine)

  useEffect(() => {
    if (isCloneEngine(draft.engine)) {
      setTimeout(() => setProviderVoices([]), 0)
      return
    }
    let active = true
    setTimeout(() => {
      if (active) setLoadingProviderVoices(true)
    }, 0)
    getVoices(draft.engine)
      .then(result => {
        if (!active) return
        const available = result.voices || []
        setProviderVoices(available)
        setDraft(current => {
          if (current.engine !== draft.engine) return current
          const currentIsAvailable = available.some(item => item.id === current.provider_voice_id)
          return currentIsAvailable
            ? current
            : { ...current, provider_voice_id: available[0]?.id || '' }
        })
      })
      .catch(error => { if (active) toast(error.message, 'error') })
      .finally(() => { if (active) setLoadingProviderVoices(false) })
    return () => { active = false }
  }, [draft.engine, toast])

  const refresh = useCallback(async (nextSelectedId) => {
    setLoading(true)
    try {
      const res = await listLibraryVoices()
      const nextVoices = res.voices || []
      setVoices(nextVoices)
      if (nextSelectedId !== undefined) {
        setSelectedId(nextSelectedId)
      } else if (selectedId && !nextVoices.some(voice => voice.id === selectedId)) {
        setSelectedId(null)
        setDraft(NEW_DRAFT)
      }
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setLoading(false)
    }
  }, [selectedId, toast])

  useEffect(() => {
    const timer = setTimeout(() => refresh(), 0)
    return () => clearTimeout(timer)
  }, [refresh])

  useEffect(() => () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl)
  }, [previewUrl])

  const notifyChanged = () => {
    if (onChanged) onChanged()
  }

  const startNew = () => {
    setSelectedId(null)
    setDraft(NEW_DRAFT)
    if (formRef.current) formRef.current.reset()
  }

  const selectVoice = (voice) => {
    setSelectedId(voice.id)
    setDraft(draftFromVoice(voice))
    if (formRef.current) formRef.current.reset()
  }

  const updateDraft = (updates) => setDraft(current => ({ ...current, ...updates }))

  const handleSave = async (event) => {
    event.preventDefault()
    if (!draft.name.trim()) {
      toast('Name the voice first.', 'error')
      return
    }
    if (isNew && draftUsesCloneEngine && !draft.file) {
      toast('Add a reference audio file first.', 'error')
      return
    }
    if (!draftUsesCloneEngine && !draft.provider_voice_id) {
      toast('Choose a provider voice first.', 'error')
      return
    }

    setSaving(true)
    try {
      if (isNew) {
        const created = await createLibraryVoice(draft)
        await refresh(created.id)
        setDraft(draftFromVoice(created))
        notifyChanged()
        toast('Voice saved to the library.', 'success')
      } else {
        const updated = await updateLibraryVoice(selectedVoice.id, {
          name: draft.name,
          engine: selectedVoice.engine_configured ? undefined : draft.engine,
          provider_voice_id: selectedVoice.engine_configured ? undefined : draft.provider_voice_id,
          notes: draft.notes,
          speed: draft.speed,
          temperature: draft.temperature,
          exaggeration: draft.exaggeration,
          cfg_weight: draft.cfg_weight,
        })
        setDraft(draftFromVoice(updated))
        await refresh(updated.id)
        notifyChanged()
        toast('Voice updated.', 'success')
      }
      if (formRef.current) formRef.current.reset()
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!selectedVoice) return
    if (!window.confirm(`Delete "${selectedVoice.name}" from the voice library?`)) return
    try {
      await deleteLibraryVoice(selectedVoice.id)
      await refresh(null)
      setDraft(NEW_DRAFT)
      notifyChanged()
      toast('Voice removed.', 'success')
    } catch (e) {
      toast(e.message, 'error')
    }
  }

  const handleSampleUpload = async (event) => {
    const file = event.target.files?.[0]
    if (!selectedVoice || !file) return
    setSampleBusy('upload')
    try {
      const updated = await addLibraryVoiceSample(selectedVoice.id, file, true)
      await refresh(updated.id)
      setDraft(draftFromVoice(updated))
      notifyChanged()
      toast('Reference audio uploaded and set active.', 'success')
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setSampleBusy('')
      event.target.value = ''
    }
  }

  const handleSetActiveSample = async (sampleFilename) => {
    if (!selectedVoice || sampleFilename === selectedVoice.sample_filename) return
    setSampleBusy(`activate:${sampleFilename}`)
    try {
      const updated = await setLibraryVoiceSample(selectedVoice.id, sampleFilename)
      await refresh(updated.id)
      setDraft(draftFromVoice(updated))
      notifyChanged()
      toast('Active reference audio updated.', 'success')
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setSampleBusy('')
    }
  }

  const handleDeleteSample = async (sampleFilename) => {
    if (!selectedVoice) return
    if (!window.confirm(`Remove "${sampleFilename}" from this voice?`)) return
    setSampleBusy(`delete:${sampleFilename}`)
    try {
      const updated = await deleteLibraryVoiceSample(selectedVoice.id, sampleFilename)
      await refresh(updated.id)
      setDraft(draftFromVoice(updated))
      notifyChanged()
      toast('Reference audio removed.', 'success')
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setSampleBusy('')
    }
  }

  const handleEnhanceSample = async () => {
    if (!selectedVoice) return
    setSampleBusy('enhance')
    try {
      const result = await enhanceLibraryVoiceSample(selectedVoice.id, {
        device: enhancementDevice,
        nfe: 32,
        activate: true,
      })
      await refresh(result.voice.id)
      setDraft(draftFromVoice(result.voice))
      notifyChanged()
      toast(`Enhanced reference created on ${result.device.toUpperCase()} and set active.`, 'success')
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setSampleBusy('')
    }
  }

  const handleTest = async () => {
    if (isNew && draftUsesCloneEngine && !draft.file) {
      toast('Add a reference audio file first.', 'error')
      return
    }
    if (!draftUsesCloneEngine && !draft.provider_voice_id) {
      toast('Choose a provider voice first.', 'error')
      return
    }
    if (!testText.trim()) {
      toast('Add some test text first.', 'error')
      return
    }
    setTesting(true)
    try {
      const testOptions = {
        engine: draft.engine,
        provider_voice_id: draft.provider_voice_id,
        speed: draft.speed,
        temperature: draft.temperature,
        exaggeration: draft.exaggeration,
        cfg_weight: draft.cfg_weight,
      }
      const response = isNew
        ? await testDraftLibraryVoice({ text: testText, file: draft.file, ...testOptions })
        : await testLibraryVoice(selectedVoice.id, testText, testOptions)
      if (!response.ok) throw await responseError(response)
      const blob = await response.blob()
      if (previewUrl) URL.revokeObjectURL(previewUrl)
      const url = URL.createObjectURL(blob)
      setPreviewUrl(url)
      if (audioRef.current) {
        audioRef.current.src = url
        audioRef.current.play()
      }
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setTesting(false)
    }
  }

  return (
    <div className="step-card voice-library-page">
      <div className="step-header">
        <div>
          <div className="step-title">Voice Library</div>
          <div className="step-desc">Save built-in or cloned voices with reusable defaults for your projects.</div>
        </div>
        <button className="btn btn-ghost btn-sm" onClick={onBack}>Back to Wizard</button>
      </div>

      <div className="voice-library-layout">
        <aside className="voice-library-sidebar" data-tip-anchor="voice-library-list">
          <div className="flex justify-between items-center mb-3">
            <div className="section-title" style={{ margin: 0 }}>Saved Voices</div>
            <button className="btn btn-secondary btn-sm" onClick={startNew}>+ New</button>
          </div>
          {loading ? (
            <div className="text-sm text-muted">Loading voices...</div>
          ) : voices.length === 0 ? (
            <div className="glass p-3 text-sm text-muted" style={{ borderRadius: 'var(--radius-sm)' }}>
              No saved voices yet.
            </div>
          ) : (
            <div className="voice-list">
              {voices.map(voice => (
                <button
                  type="button"
                  key={voice.id}
                  className={`voice-list-item glass glass-hover${selectedId === voice.id ? ' is-selected' : ''}`}
                  onClick={() => selectVoice(voice)}
                >
                  <span className="voice-name truncate" title={voice.name}>{voice.name}</span>
                  <span className="text-xs text-muted truncate" title={voice.sample_filename || voice.provider_voice_id}>
                    {voice.sample_filename || voice.provider_voice_id}
                  </span>
                  <span className="text-xs text-secondary">
                    {voice.engine_configured ? (ENGINE_LABELS[voice.engine] || voice.engine) : 'Engine confirmation needed'} · {(voice.speed ?? 1).toFixed(2)}x
                  </span>
                </button>
              ))}
            </div>
          )}
        </aside>

        <form ref={formRef} className="voice-editor" onSubmit={handleSave} data-tip-anchor="voice-library-create">
          <div className="flex justify-between items-start gap-3 mb-4">
            <div>
              <div className="section-title" style={{ marginBottom: 4 }}>{isNew ? 'New Voice' : 'Edit Voice'}</div>
              <div className="text-xs text-muted">
                {isNew
                  ? 'Choose an engine and save the voice before using it in a project.'
                  : selectedVoice?.sample_filename || selectedVoice?.provider_voice_id}
              </div>
            </div>
            {!isNew && (
              <button type="button" className="btn btn-danger btn-sm" onClick={handleDelete}>Delete</button>
            )}
          </div>

          <div className="voice-editor-grid">
            <div>
              <div className="field">
                <label htmlFor="library-voice-name">Name</label>
                <input
                  id="library-voice-name"
                  name="library-voice-name"
                  type="text"
                  value={draft.name}
                  onChange={event => updateDraft({ name: event.target.value })}
                  placeholder="Warm narrator"
                />
              </div>
              <div className="field">
                <label>Engine</label>
                {isNew || !selectedVoice?.engine_configured ? (
                  <div className="segmented" role="group" aria-label="Voice cloning engine">
                    {Object.entries(ENGINE_LABELS).map(([value, label]) => (
                      <button
                        type="button"
                        key={value}
                        className={`segmented-btn${draft.engine === value ? ' is-active' : ''}`}
                        onClick={() => updateDraft({ engine: value, provider_voice_id: '' })}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                ) : (
                  <div className="glass p-3 text-sm" style={{ borderRadius: 'var(--radius-sm)' }}>
                    {ENGINE_LABELS[draft.engine] || draft.engine}
                  </div>
                )}
                <div className="text-xs text-muted mt-1">
                  {selectedVoice?.engine_configured
                    ? 'The engine is fixed after this voice is saved.'
                    : isNew
                      ? 'This voice will always use the selected engine.'
                      : 'This older voice needs a one-time engine confirmation.'}
                </div>
              </div>
              {!draftUsesCloneEngine && (
                <div className="field">
                  <label htmlFor="library-provider-voice">Provider voice</label>
                  <select
                    id="library-provider-voice"
                    name="library-provider-voice"
                    value={draft.provider_voice_id}
                    disabled={loadingProviderVoices || (!isNew && selectedVoice?.engine_configured)}
                    onChange={event => updateDraft({ provider_voice_id: event.target.value })}
                  >
                    {providerVoices.length === 0 ? (
                      <option value="">{loadingProviderVoices ? 'Loading voices...' : 'No voices available'}</option>
                    ) : providerVoices.map(item => (
                      <option key={item.id} value={item.id}>{item.name}</option>
                    ))}
                  </select>
                  <div className="text-xs text-muted mt-1">
                    Save a built-in voice with your preferred name, speed, and notes.
                  </div>
                </div>
              )}
              {isNew && draftUsesCloneEngine && (
                <div className="field">
                  <label htmlFor="library-voice-reference">Reference audio</label>
                  <input
                    id="library-voice-reference"
                    name="library-voice-reference"
                    type="file"
                    accept=".wav,.mp3,.flac"
                    onChange={event => updateDraft({ file: event.target.files?.[0] || null })}
                  />
                  <div className="text-xs text-muted mt-1">Use a clean single-speaker clip with no music. F5-TTS transcribes the usable reference automatically; Chatterbox conditions directly on the same clip.</div>
                </div>
              )}
              {!isNew && draftUsesCloneEngine && (
                <div className="field">
                  <label>Reference audio files</label>
                  <input
                    ref={sampleInputRef}
                    name="library-voice-add-reference"
                    aria-label="Add reference audio"
                    type="file"
                    accept=".wav,.mp3,.flac"
                    style={{ display: 'none' }}
                    onChange={handleSampleUpload}
                  />
                  <div className="flex flex-col gap-2">
                    {selectedSampleFilenames.map(sampleFilename => {
                      const isActive = sampleFilename === selectedVoice.sample_filename
                      return (
                        <div key={sampleFilename} className="glass" style={{ padding: 8, borderRadius: 'var(--radius-sm)' }}>
                          <div className="flex justify-between items-start gap-2">
                            <div style={{ minWidth: 0 }}>
                              <div className="text-xs truncate" style={{ fontWeight: 700 }} title={sampleFilename}>{sampleFilename}</div>
                              {isActive && <div className="text-xs" style={{ color: 'var(--success)' }}>Active reference</div>}
                            </div>
                            <div className="flex gap-1" style={{ flexShrink: 0 }}>
                              <button
                                type="button"
                                className="btn btn-ghost btn-sm"
                                style={{ fontSize: 11, padding: '3px 6px' }}
                                disabled={isActive || Boolean(sampleBusy)}
                                onClick={() => handleSetActiveSample(sampleFilename)}
                              >
                                {sampleBusy === `activate:${sampleFilename}` ? 'Using...' : 'Use'}
                              </button>
                              <button
                                type="button"
                                className="btn btn-ghost btn-sm"
                                style={{ fontSize: 11, padding: '3px 6px', color: 'var(--danger)' }}
                                disabled={selectedSampleFilenames.length <= 1 || Boolean(sampleBusy)}
                                onClick={() => handleDeleteSample(sampleFilename)}
                              >
                                {sampleBusy === `delete:${sampleFilename}` ? 'Removing...' : 'Remove'}
                              </button>
                            </div>
                          </div>
                        </div>
                      )
                    })}
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm w-full"
                      disabled={Boolean(sampleBusy)}
                      onClick={() => sampleInputRef.current?.click()}
                    >
                      {sampleBusy === 'upload' ? 'Uploading...' : '+ Add reference audio'}
                    </button>
                    <div className="glass" style={{ padding: 10, borderRadius: 'var(--radius-sm)' }}>
                      <div className="text-xs" style={{ fontWeight: 700 }}>Optional AI cleanup</div>
                      <div className="text-xs text-muted mt-1">
                        Creates a denoised, bandwidth-restored copy. The original is kept.
                      </div>
                      <div className="flex gap-2 mt-2">
                        <select
                          aria-label="Voice enhancement device"
                          value={enhancementDevice}
                          disabled={Boolean(sampleBusy)}
                          onChange={event => setEnhancementDevice(event.target.value)}
                          style={{ flex: 1 }}
                        >
                          <option value="auto">Auto device</option>
                          <option value="cuda">CUDA</option>
                          <option value="mps">Apple Metal</option>
                          <option value="cpu">CPU</option>
                        </select>
                        <button
                          type="button"
                          className="btn btn-secondary btn-sm"
                          disabled={Boolean(sampleBusy)}
                          onClick={handleEnhanceSample}
                        >
                          {sampleBusy === 'enhance' ? 'Enhancing...' : 'Enhance active'}
                        </button>
                      </div>
                    </div>
                  </div>
                  <div className="text-xs text-muted mt-1">
                    The active file is used for Voice Library generation. Switch files here when you want to test or use a different reference clip.
                  </div>
                </div>
              )}
              <div className="field">
                <label htmlFor="library-voice-notes">Notes</label>
                <textarea
                  id="library-voice-notes"
                  name="library-voice-notes"
                  rows={5}
                  value={draft.notes}
                  onChange={event => updateDraft({ notes: event.target.value })}
                  placeholder="Tone, source, or usage notes."
                />
              </div>
            </div>

            <div>
              <div className="field">
                <label htmlFor="library-voice-speed">Speed - {Number(draft.speed).toFixed(2)}x</label>
                <input
                  id="library-voice-speed"
                  name="library-voice-speed"
                  type="range"
                  min="0.5"
                  max="2.0"
                  step="0.05"
                  value={draft.speed}
                  onChange={event => updateDraft({ speed: parseFloat(event.target.value) })}
                />
                <div className="range-ticks text-xs text-muted">
                  <span className="range-tick range-tick-start">0.5x</span>
                  <span className="range-tick" style={{ left: '33.333%' }}>1.0x</span>
                  <span className="range-tick range-tick-end">2.0x</span>
                </div>
              </div>
              {draft.engine === 'f5-tts' ? (
                <div className="field">
                  <label htmlFor="library-voice-temperature">Temperature - {Number(draft.temperature).toFixed(2)}</label>
                  <input
                    id="library-voice-temperature"
                    name="library-voice-temperature"
                    type="range"
                    min="0"
                    max="1.5"
                    step="0.05"
                    value={draft.temperature}
                    onChange={event => updateDraft({ temperature: parseFloat(event.target.value) })}
                  />
                  <div className="range-ticks text-xs text-muted">
                    <span className="range-tick range-tick-start">steady</span>
                    <span className="range-tick" style={{ left: '46.667%' }}>balanced</span>
                    <span className="range-tick range-tick-end">varied</span>
                  </div>
                </div>
              ) : draft.engine === 'chatterbox' ? (
                <>
                  <div className="field">
                    <label htmlFor="library-voice-expression">Expression - {Number(draft.exaggeration).toFixed(2)}</label>
                    <input
                      id="library-voice-expression"
                      name="library-voice-expression"
                      type="range" min="0.25" max="1" step="0.05"
                      value={draft.exaggeration}
                      onChange={event => updateDraft({ exaggeration: parseFloat(event.target.value) })}
                    />
                  </div>
                  <div className="field">
                    <label htmlFor="library-voice-cfg">CFG Weight - {Number(draft.cfg_weight).toFixed(2)}</label>
                    <input
                      id="library-voice-cfg"
                      name="library-voice-cfg"
                      type="range" min="0" max="1" step="0.05"
                      value={draft.cfg_weight}
                      onChange={event => updateDraft({ cfg_weight: parseFloat(event.target.value) })}
                    />
                  </div>
                </>
              ) : null}
              <button className="btn btn-primary w-full" type="submit" disabled={saving}>
                {saving ? 'Saving...' : isNew ? '+ Save Voice' : 'Save Voice'}
              </button>
            </div>
          </div>

          <div className="glass p-4 mt-4" style={{ borderRadius: 'var(--radius-sm)' }} data-tip-anchor="voice-library-test">
            <div className="section-title">Test Voice</div>
            <div className="text-xs text-muted mb-3">
              Testing with {ENGINE_LABELS[draft.engine] || draft.engine} using the defaults above.
            </div>
            <textarea
              name="library-voice-test-text"
              aria-label="Voice test text"
              rows={3}
              value={testText}
              onChange={event => setTestText(event.target.value)}
            />
            <div className="flex gap-2 items-center mt-3">
              <button
                type="button"
                className="btn btn-secondary"
                onClick={handleTest}
                disabled={testing || (isNew && draftUsesCloneEngine && !draft.file) || (!draftUsesCloneEngine && !draft.provider_voice_id) || (!isNew && !selectedVoice?.engine_configured)}
              >
                {testing ? 'Testing...' : `Test with ${ENGINE_LABELS[draft.engine] || draft.engine}`}
              </button>
              <audio ref={audioRef} style={{ flex: 1 }} controls />
            </div>
          </div>
        </form>
      </div>
    </div>
  )
}
