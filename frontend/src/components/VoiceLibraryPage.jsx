import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  createLibraryVoice,
  deleteLibraryVoice,
  listLibraryVoices,
  testDraftLibraryVoice,
  testLibraryVoice,
  updateLibraryVoice,
} from '../api'

const DEFAULT_TEST_TEXT = 'Welcome to narratible. This is a quick test of the saved library voice.'
const NEW_DRAFT = { name: '', notes: '', speed: 1.0, temperature: 0.7, file: null }

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
    notes: voice?.notes || '',
    speed: voice?.speed ?? 1.0,
    temperature: voice?.temperature ?? 0.7,
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
  const [testText, setTestText] = useState(DEFAULT_TEST_TEXT)
  const [previewUrl, setPreviewUrl] = useState('')
  const audioRef = useRef(null)
  const formRef = useRef(null)

  const selectedVoice = useMemo(
    () => voices.find(voice => voice.id === selectedId) || null,
    [voices, selectedId]
  )
  const isNew = !selectedVoice

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
    if (isNew && !draft.file) {
      toast('Add a reference audio file first.', 'error')
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
          notes: draft.notes,
          speed: draft.speed,
          temperature: draft.temperature,
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

  const handleTest = async () => {
    if (isNew && !draft.file) {
      toast('Add a reference audio file first.', 'error')
      return
    }
    if (!testText.trim()) {
      toast('Add some test text first.', 'error')
      return
    }
    setTesting(true)
    try {
      const response = isNew
        ? await testDraftLibraryVoice({ text: testText, speed: draft.speed, temperature: draft.temperature, file: draft.file })
        : await testLibraryVoice(selectedVoice.id, testText)
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
          <div className="step-desc">Create reusable cloned voices, tune their defaults, then pick them in the TTS step.</div>
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
                  <span className="text-xs text-muted truncate" title={voice.sample_filename}>{voice.sample_filename}</span>
                  <span className="text-xs text-secondary">{(voice.speed ?? 1).toFixed(2)}x speed</span>
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
                {isNew ? 'Add a reference clip and save it before testing.' : selectedVoice?.sample_filename}
              </div>
            </div>
            {!isNew && (
              <button type="button" className="btn btn-danger btn-sm" onClick={handleDelete}>Delete</button>
            )}
          </div>

          <div className="voice-editor-grid">
            <div>
              <div className="field">
                <label>Name</label>
                <input
                  type="text"
                  value={draft.name}
                  onChange={event => updateDraft({ name: event.target.value })}
                  placeholder="Warm narrator"
                />
              </div>
              {isNew && (
                <div className="field">
                  <label>Reference audio</label>
                  <input
                    type="file"
                    accept=".wav,.mp3,.flac"
                    onChange={event => updateDraft({ file: event.target.files?.[0] || null })}
                  />
                  <div className="text-xs text-muted mt-1">Use a clean 5-15 second clip with one speaker and no music.</div>
                </div>
              )}
              <div className="field">
                <label>Notes</label>
                <textarea
                  rows={5}
                  value={draft.notes}
                  onChange={event => updateDraft({ notes: event.target.value })}
                  placeholder="Tone, source, or usage notes."
                />
              </div>
            </div>

            <div>
              <div className="field">
                <label>Speed - {Number(draft.speed).toFixed(2)}x</label>
                <input
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
              <div className="field">
                <label>Temperature - {Number(draft.temperature).toFixed(2)}</label>
                <input
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
              <button className="btn btn-primary w-full" type="submit" disabled={saving}>
                {saving ? 'Saving...' : isNew ? '+ Save Voice' : 'Save Voice'}
              </button>
            </div>
          </div>

          <div className="glass p-4 mt-4" style={{ borderRadius: 'var(--radius-sm)' }} data-tip-anchor="voice-library-test">
            <div className="section-title">Test Voice</div>
            <textarea
              rows={3}
              value={testText}
              onChange={event => setTestText(event.target.value)}
            />
            <div className="flex gap-2 items-center mt-3">
              <button type="button" className="btn btn-secondary" onClick={handleTest} disabled={testing || (isNew && !draft.file)}>
                {testing ? 'Testing...' : isNew ? 'Test Draft' : 'Test Voice'}
              </button>
              <audio ref={audioRef} style={{ flex: 1 }} controls />
            </div>
          </div>
        </form>
      </div>
    </div>
  )
}