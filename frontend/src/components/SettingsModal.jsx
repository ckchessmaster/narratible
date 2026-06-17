import { useState, useEffect } from 'react'
import { getSettings, saveSettings, getSystemInfo,
         validateGeminiKey, validateOpenAIKey, validateHuggingFaceToken } from '../api'
import Coachmark from './Coachmark'
import useTips from '../useTips'

const PRESET_FAMILIES = [
  {
    name: "Gemma 4",
    recommended: true,
    description: "Google's reasoning and instruction-following models. (Gated)",
    variants: [
      { id: "google/gemma-4-E2B-it", name: "E2B" },
      { id: "google/gemma-4-E4B-it", name: "E4B" },
      { id: "google/gemma-4-12B-it", name: "12B" },
      { id: "google/gemma-4-31B-it", name: "31B" },
    ]
  },
  {
    name: "DeepSeek R1 (Thinking)",
    description: "Models that reason through OCR errors before outputting text.",
    variants: [
      { id: "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B", name: "1.5B" },
      { id: "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B", name: "7B" },
      { id: "deepseek-ai/DeepSeek-R1-Distill-Llama-8B", name: "8B" },
    ]
  },
  {
    name: "Qwen 2.5",
    description: "Fast, efficient workhorses. Great balance of speed and quality.",
    variants: [
      { id: "Qwen/Qwen2.5-0.5B-Instruct", name: "0.5B" },
      { id: "Qwen/Qwen2.5-1.5B-Instruct", name: "1.5B" },
      { id: "Qwen/Qwen2.5-3B-Instruct", name: "3B" },
      { id: "Qwen/Qwen2.5-7B-Instruct", name: "7B" },
    ]
  },
  {
    name: "Llama 3",
    description: "Meta's highly stable production models. (Gated)",
    variants: [
      { id: "meta-llama/Llama-3.2-1B-Instruct", name: "1B" },
      { id: "meta-llama/Llama-3.2-3B-Instruct", name: "3B" },
      { id: "meta-llama/Meta-Llama-3.1-8B-Instruct", name: "8B" },
    ]
  },
  {
    name: "Phi-3.5",
    description: "Microsoft's logic specialist. Good at formatting and document structure.",
    variants: [
      { id: "microsoft/Phi-3.5-mini-instruct", name: "3.8B" },
    ]
  }
]

const TABS = [
  ['ai', 'Cloud LLM Keys'],
  ['local', 'Local AI'],
  ['integrations', 'Integrations'],
  ['system', 'System'],
]

export default function SettingsModal({ onClose, toast }) {
  const [cfg, setCfg] = useState(null)
  const [saving, setSaving] = useState(false)
  const [systemInfo, setSystemInfo] = useState(null)
  const [geminiModels, setGeminiModels] = useState(null)
  const [fetchingGeminiModels, setFetchingGeminiModels] = useState(false)
  const [activeTab, setActiveTab] = useState('ai')
  // Which accordion sections are open (Set of provider ids)
  const [openSections, setOpenSections] = useState(new Set(['gemini']))
  // Key visibility toggles: { gemini: bool, openai: bool, hf: bool }
  const [showKey, setShowKey] = useState({ gemini: false, openai: false, hf: false })
  // Tracks which key fields the user has modified this session
  const [dirtyKeys, setDirtyKeys] = useState(new Set())
  // Validation state: { field: 'validating' | 'ok' | 'error', message: string }
  const [keyValidation, setKeyValidation] = useState({})
  // Tooltip hover state for 4-bit quantization info (retained for future use)
  const [showQuantTip, setShowQuantTip] = useState(false)
  // First-time-user coach-mark tips for the Settings modal
  const { getActiveTips, dismiss, disableAll, reset } = useTips()
  const settingsTips = getActiveTips(t => t.context === 'settings' && t.tab === activeTab)

  useEffect(() => {
    getSettings().then(cfg => {
      setCfg(cfg)
      // Open the currently active provider section by default
      if (cfg?.llm_provider) setOpenSections(new Set([cfg.llm_provider]))
    }).catch(e => {
      console.warn('Failed to load settings', e)
    })
    getSystemInfo().then(setSystemInfo).catch(e => console.warn('Failed to load system info', e))
  }, [])

  const set = (key, val) => setCfg(c => ({ ...c, [key]: val }))

  const setKey = (field, cfgKey, val) => {
    set(cfgKey, val)
    setDirtyKeys(prev => new Set(prev).add(field))
    // Clear validation status when user edits
    setKeyValidation(prev => ({ ...prev, [field]: null }))
  }

  const clearKey = (field, cfgKey) => {
    set(cfgKey, '')
    setDirtyKeys(prev => new Set(prev).add(field))
    setKeyValidation(prev => ({ ...prev, [field]: null }))
  }

  const toggleShowKey = (field) =>
    setShowKey(prev => ({ ...prev, [field]: !prev[field] }))

  const toggleSection = (id) =>
    setOpenSections(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })

  const fetchGeminiModels = async (apiKey) => {
    const key = apiKey ?? cfg?.gemini_api_key
    if (!key) return
    setFetchingGeminiModels(true)
    try {
      const res = await fetch(`/api/gemini/models?api_key=${encodeURIComponent(key)}`)
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Failed to fetch models')
      }
      const data = await res.json()
      setGeminiModels(data.models)
    } catch (e) {
      setGeminiModels(null)
      console.warn('Gemini model fetch failed:', e.message)
    } finally {
      setFetchingGeminiModels(false)
    }
  }

  const handleSave = async () => {
    setSaving(true)
    // Validate dirty non-empty keys before saving
    const validations = []
    if (dirtyKeys.has('gemini') && cfg?.gemini_api_key) {
      validations.push({ field: 'gemini', fn: () => validateGeminiKey(cfg.gemini_api_key), label: 'Gemini API key' })
    }
    if (dirtyKeys.has('openai') && cfg?.openai_api_key) {
      validations.push({ field: 'openai', fn: () => validateOpenAIKey(cfg.openai_api_key), label: 'OpenAI API key' })
    }
    if (dirtyKeys.has('hf') && cfg?.huggingface_token) {
      validations.push({ field: 'hf', fn: () => validateHuggingFaceToken(cfg.huggingface_token), label: 'HuggingFace token' })
    }
    for (const v of validations) {
      setKeyValidation(prev => ({ ...prev, [v.field]: 'validating' }))
      try {
        const result = await v.fn()
        if (!result.valid) {
          setKeyValidation(prev => ({ ...prev, [v.field]: 'error' }))
          toast(`Invalid ${v.label}: ${result.error || 'Validation failed'}`, 'error')
          setSaving(false)
          return
        }
        setKeyValidation(prev => ({ ...prev, [v.field]: 'ok' }))
      } catch (e) {
        setKeyValidation(prev => ({ ...prev, [v.field]: 'error' }))
        toast(`Failed to validate ${v.label}: ${e.message}`, 'error')
        setSaving(false)
        return
      }
    }
    try {
      await saveSettings(cfg)
      toast('Settings saved!', 'success')
      onClose()
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  const provider = cfg?.llm_provider ?? 'gemini'

  // Derive whether the selected GPU supports CUDA
  const selectedGpuIndex = cfg?.selected_gpu_index ?? 0
  const gpus = systemInfo?.gpus ?? []
  const selectedGpu = gpus.find(g => g.index === selectedGpuIndex) ?? gpus[0] ?? null
  const cudaEnabled = selectedGpu?.cuda ?? true // default true when systemInfo not yet loaded

  // Helper: renders a key field with show/hide + clear buttons
  const renderKeyField = (field, cfgKey, placeholder) => {
    const val = cfg?.[cfgKey] ?? ''
    const visible = showKey[field]
    const vState = keyValidation[field]
    return (
      <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
        <input
          type={visible ? 'text' : 'password'}
          placeholder={placeholder}
          value={val}
          onChange={e => setKey(field, cfgKey, e.target.value)}
          onBlur={() => {
            if (field === 'gemini' && val) fetchGeminiModels(val)
          }}
          autoComplete="off"
          style={{ flex: 1, ...(vState === 'error' ? { borderColor: 'var(--danger, #ef4444)' } : vState === 'ok' ? { borderColor: 'var(--success, #22c55e)' } : {}) }}
        />
        <button
          type="button"
          className="btn btn-ghost btn-icon"
          title={visible ? 'Hide' : 'Show'}
          onClick={() => toggleShowKey(field)}
          style={{ padding: '0 8px', fontSize: 14 }}
        >
          {visible ? '🙈' : '👁'}
        </button>
        {val && (
          <button
            type="button"
            className="btn btn-ghost btn-icon"
            title="Clear"
            onClick={() => clearKey(field, cfgKey)}
            style={{ padding: '0 8px', fontSize: 14, color: 'var(--text-muted)' }}
          >
            ✕
          </button>
        )}
        {vState === 'validating' && <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Checking…</span>}
        {vState === 'ok' && <span style={{ fontSize: 14 }}>✅</span>}
        {vState === 'error' && <span style={{ fontSize: 14 }}>❌</span>}
      </div>
    )
  }

  const temperatureField = cfg && (
    <div className="field" data-tip-anchor="settings-temperature">
      <div className="flex justify-between items-center mb-2">
        <label style={{ margin: 0 }}>LLM Temperature (0.0 – 1.0)</label>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <input
            type="range"
            min="0"
            max="1"
            step="0.1"
            value={cfg.llm_temperature ?? 0.1}
            onChange={e => set('llm_temperature', parseFloat(e.target.value))}
            style={{ width: '120px', margin: 0, accentColor: 'var(--accent-primary)' }}
          />
          <span style={{ fontSize: '13px', fontWeight: 600, width: '25px', textAlign: 'right' }}>
            {(cfg.llm_temperature ?? 0.1).toFixed(1)}
          </span>
        </div>
      </div>
      <div className="text-xs text-muted mb-4">
        Higher values = more variation/creativity. Lower values = stricter adherence to text bounds. If local LLMs hallucinate loops, increase to 0.1 or 0.2.
      </div>
    </div>
  )

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <div className="modal-title">⚙ Settings</div>
          <button className="btn btn-ghost btn-icon" onClick={onClose}>✕</button>
        </div>

        {!cfg ? (
          <div className="text-secondary">Loading…</div>
        ) : (
          <>
            {/* Tab bar */}
            <div className="settings-tabs">
              {TABS.map(([id, label]) => (
                <button
                  key={id}
                  className={`settings-tab${activeTab === id ? ' active' : ''}`}
                  onClick={() => setActiveTab(id)}
                >
                  {label}
                </button>
              ))}
            </div>

            {/* ── Cloud LLM Keys tab ─────────────────────────────────────────────── */}
            {activeTab === 'ai' && (() => {
              const accentBorder = '1px solid var(--glass-border)'
              const sectionStyle = (isActive) => ({
                borderRadius: 'var(--radius-sm)',
                border: isActive ? '1.5px solid var(--accent-primary)' : accentBorder,
                overflow: 'hidden',
                marginBottom: 8,
              })
              const headerStyle = (isActive) => ({
                display: 'flex', alignItems: 'center', gap: 10,
                padding: '12px 14px', cursor: 'pointer',
                background: isActive ? 'rgba(99,102,241,0.07)' : 'transparent',
              })
              const bodyStyle = {
                padding: '14px 16px 16px',
                borderTop: accentBorder,
                background: 'rgba(0,0,0,0.15)',
              }
              const badge = (text, color) => (
                <span style={{
                  fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 99,
                  background: color === 'green' ? 'rgba(34,197,94,0.12)' : 'rgba(255,255,255,0.06)',
                  color: color === 'green' ? 'var(--success, #22c55e)' : 'var(--text-muted)',
                  border: `1px solid ${color === 'green' ? 'rgba(34,197,94,0.25)' : 'var(--glass-border)'}`,
                  whiteSpace: 'nowrap',
                }}>
                  {text}
                </span>
              )
              const chevron = (open) => (
                <span style={{ fontSize: 12, color: 'var(--text-muted)', marginLeft: 4, transition: 'transform 0.15s', display: 'inline-block', transform: open ? 'rotate(90deg)' : 'none' }}>▶</span>
              )

              // ── Gemini ──────────────────────────────────────────
              const geminiOpen = openSections.has('gemini')
              const geminiActive = provider === 'gemini'
              const geminiConfigured = !!(cfg.gemini_api_key)

              // ── OpenAI ───────────────────────────────────────────
              const openaiOpen = openSections.has('openai')
              const openaiActive = provider === 'openai'
              const openaiConfigured = !!(cfg.openai_api_key)

              return (
                <div style={{ marginTop: 4 }}>

                  {/* Gemini */}
                  <div style={sectionStyle(geminiActive)} data-tip-anchor="settings-gemini">
                    <div style={headerStyle(geminiActive)}
                      onClick={() => toggleSection('gemini')}
                    >
                      <input type="radio" name="llm_provider" checked={geminiActive}
                        onChange={e => { e.stopPropagation(); set('llm_provider', 'gemini') }}
                        onClick={e => e.stopPropagation()}
                        style={{ width: 'auto', flexShrink: 0 }}
                      />
                      <div style={{ flex: 1 }}>
                        <div style={{ fontWeight: 600, fontSize: 14 }}>Gemini</div>
                        <div className="text-xs text-muted">Google AI · free tier available</div>
                      </div>
                      {geminiConfigured ? badge('✓ Key set', 'green') : badge('No key', null)}
                      {chevron(geminiOpen)}
                    </div>
                    {geminiOpen && (
                      <div style={bodyStyle}>
                        <div className="field">
                          <label>API Key</label>
                          {renderKeyField('gemini', 'gemini_api_key', 'AIza…')}
                          <div className="text-xs text-muted mt-1">
                            <a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noreferrer"
                              style={{ color: 'var(--accent-primary)' }}>Get a free key →</a>
                          </div>
                        </div>
                        {cfg.gemini_api_key && (
                          <>
                            <div className="field">
                              <label>Model {fetchingGeminiModels && <span className="text-muted">(loading…)</span>}</label>
                              {geminiModels ? (
                                <select value={cfg.gemini_model || 'gemma-4-31b-it'} onChange={e => set('gemini_model', e.target.value)}>
                                  {geminiModels.map(m => (
                                    <option key={m.id} value={m.id}>{m.display_name || m.id}</option>
                                  ))}
                                </select>
                              ) : (
                                <input type="text" placeholder="gemma-4-31b-it" value={cfg.gemini_model || ''} onChange={e => set('gemini_model', e.target.value)} autoComplete="off" />
                              )}
                              <div className="text-xs text-muted mt-1">Models auto-load when your key is saved.</div>
                            </div>
                            {temperatureField}
                          </>
                        )}
                      </div>
                    )}
                  </div>

                  {/* OpenAI */}
                  <div style={sectionStyle(openaiActive)}>
                    <div style={headerStyle(openaiActive)}
                      onClick={() => toggleSection('openai')}
                    >
                      <input type="radio" name="llm_provider" checked={openaiActive}
                        onChange={e => { e.stopPropagation(); set('llm_provider', 'openai') }}
                        onClick={e => e.stopPropagation()}
                        style={{ width: 'auto', flexShrink: 0 }}
                      />
                      <div style={{ flex: 1 }}>
                        <div style={{ fontWeight: 600, fontSize: 14 }}>OpenAI</div>
                        <div className="text-xs text-muted">Paid API · GPT-4o mini</div>
                      </div>
                      {openaiConfigured ? badge('✓ Key set', 'green') : badge('No key', null)}
                      {chevron(openaiOpen)}
                    </div>
                    {openaiOpen && (
                      <div style={bodyStyle}>
                        <div className="field">
                          <label>API Key</label>
                          {renderKeyField('openai', 'openai_api_key', 'sk-…')}
                        </div>
                        {cfg.openai_api_key && temperatureField}
                      </div>
                    )}
                  </div>

                </div>
              )
            })()}

            {/* ── Integrations tab ────────────────────────────────────── */}
            {activeTab === 'integrations' && (
              <>
                <div className="section-title">Audiobookshelf</div>

                <div className="field" data-tip-anchor="settings-abs">
                  <label>Server URL</label>
                  <input
                    type="url"
                    placeholder="http://192.168.1.x:13378"
                    value={cfg.audiobookshelf_url}
                    onChange={e => set('audiobookshelf_url', e.target.value)}
                    autoComplete="off"
                  />
                </div>

                <div className="field">
                  <label>API Token</label>
                  <input
                    type="password"
                    placeholder="Your Audiobookshelf API token"
                    value={cfg.audiobookshelf_token}
                    onChange={e => set('audiobookshelf_token', e.target.value)}
                    autoComplete="off"
                  />
                  <div className="text-xs text-muted mt-1">
                    Found in Audiobookshelf → Settings → Users → your user → API Token
                  </div>
                </div>
              </>
            )}

            {/* ── System tab ─────────────────────────────────────────────────────── */}
            {activeTab === 'system' && (
              <>
                <div className="section-title">GPU Selection</div>
                {!systemInfo ? (
                  <div className="text-muted text-sm">Loading hardware info…</div>
                ) : (
                  <div className="flex flex-col gap-2 mb-4" data-tip-anchor="settings-gpu">
                    {(systemInfo.gpus ?? []).map(gpu => (
                      <label
                        key={gpu.index}
                        className="glass flex items-center gap-3 p-3 glass-hover"
                        style={{ borderRadius: 'var(--radius-sm)', cursor: 'pointer',
                          border: (cfg.selected_gpu_index ?? 0) === gpu.index ? '2px solid var(--accent-primary)' : '' }}
                      >
                        <input
                          type="radio"
                          name="gpu"
                          checked={(cfg.selected_gpu_index ?? 0) === gpu.index}
                          onChange={() => set('selected_gpu_index', gpu.index)}
                          style={{ width: 'auto' }}
                        />
                        <div style={{ flex: 1 }}>
                          <div style={{ fontWeight: 600, fontSize: 14 }}>{gpu.name}</div>
                          {gpu.cuda && (
                            <div className="text-xs text-muted mt-0.5">
                              {(gpu.vram_mb / 1024).toFixed(1)} GB VRAM &middot; CUDA enabled
                            </div>
                          )}
                          {!gpu.cuda && gpu.index >= 0 && gpu.cuda_unavailable_reason && (
                            <div className="text-xs mt-0.5" style={{ color: 'rgb(245,158,11)' }}>
                              {gpu.vram_mb > 0 ? `${(gpu.vram_mb / 1024).toFixed(1)} GB VRAM · ` : ''}{gpu.cuda_unavailable_reason}
                            </div>
                          )}
                        </div>
                        {gpu.cuda && (
                          <span style={{ fontSize: 11, color: 'var(--success, #22c55e)', fontWeight: 600 }}>CUDA</span>
                        )}
                        {!gpu.cuda && gpu.index >= 0 && (
                          <span style={{ fontSize: 11, color: 'rgb(245,158,11)', fontWeight: 600 }}>No CUDA</span>
                        )}
                      </label>
                    ))}
                  </div>
                )}

                {/* Warning when non-CUDA is selected */}
                {!cudaEnabled && (
                  <div className="glass p-3" style={{
                    borderRadius: 'var(--radius-sm)',
                    background: 'rgba(245,158,11,0.08)',
                    border: '1px solid rgba(245,158,11,0.35)'
                  }}>
                    <div style={{ fontWeight: 600, fontSize: 13, color: 'rgb(245,158,11)', marginBottom: 4 }}>
                      ⚠️ No CUDA GPU selected
                    </div>
                    <div className="text-xs text-muted">
                      Local LLM cleanup, Kokoro TTS, and Voice Clone (F5-TTS) all require a CUDA-capable GPU.
                      Edge-TTS and cloud LLM providers (Gemini, OpenAI) will still work.
                    </div>
                  </div>
                )}

                <div className="section-title mt-4">Developer</div>
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div style={{ fontWeight: 500, fontSize: 14 }}>Debug Mode</div>
                    <div className="text-xs text-muted mt-0.5">Exposes extra testing options during PDF import.</div>
                  </div>
                  <label className="flex items-center gap-2 cursor-pointer">
                    <div className="toggle-switch">
                      <input type="checkbox" checked={cfg.debug_mode || false}
                        onChange={e => set('debug_mode', e.target.checked)} />
                      <span className="toggle-slider"></span>
                    </div>
                  </label>
                </div>

                <div className="section-title mt-4">Tooltips</div>
                <div className="flex items-center justify-between gap-3" data-tip-anchor="settings-reset">
                  <div className="text-xs text-muted" style={{ flex: 1 }}>
                    Replay the first-time onboarding tips throughout the app.
                  </div>
                  <button
                    className="btn btn-ghost btn-sm"
                    onClick={() => { reset(); toast('Tooltip progress reset.', 'success') }}
                  >
                    Reset tooltip progress
                  </button>
                </div>
              </>
            )}

            {/* ── Local AI tab ─────────────────────────────────────────────────── */}
            {activeTab === 'local' && (
              <>
                {!cudaEnabled && (
                  <div className="glass p-3 mb-4" style={{
                    borderRadius: 'var(--radius-sm)',
                    background: 'rgba(245,158,11,0.08)',
                    border: '1px solid rgba(245,158,11,0.35)'
                  }}>
                    <div style={{ fontWeight: 600, fontSize: 13, color: 'rgb(245,158,11)', marginBottom: 4 }}>
                      ⚠️ No CUDA GPU selected
                    </div>
                    <div className="text-xs text-muted">
                      All local features require a CUDA GPU. Select one in the <strong>System</strong> tab.
                    </div>
                  </div>
                )}

                <div className="section-title">HuggingFace Token</div>
                <div className="field" data-tip-anchor="settings-hf" style={{ opacity: cudaEnabled ? 1 : 0.5, pointerEvents: cudaEnabled ? 'auto' : 'none' }}>
                  {renderKeyField('hf', 'huggingface_token', 'hf_…')}
                  <div className="text-xs text-muted mt-1">
                    Required for gated models (Llama, Gemma). Free account at{' '}
                    <a href="https://huggingface.co" target="_blank" rel="noreferrer" style={{ color: 'var(--accent-primary)' }}>huggingface.co</a>.
                  </div>
                </div>

                <div style={{ opacity: cudaEnabled ? 1 : 0.5, pointerEvents: cudaEnabled ? 'auto' : 'none' }}>
                  <div className="field" data-tip-anchor="settings-chunk">
                    <label>Chunk Size: {(cfg.llm_chunk_size || 16000).toLocaleString()} characters</label>
                    <input type="range" min="1000" max="32000" step="1000"
                      value={cfg.llm_chunk_size || 16000}
                      onChange={e => set('llm_chunk_size', parseInt(e.target.value) || 16000)} />
                    <div className="flex justify-between text-xs text-muted mt-1">
                      <span>1k (fast)</span><span>16k (balanced)</span><span>32k (quality)</span>
                    </div>
                    <div className="text-xs text-muted mt-2">
                      Characters passed to the LLM per chunk. Larger = better context but more VRAM.
                    </div>
                  </div>

                  <div className="field" data-tip-anchor="settings-models">
                    <div className="flex justify-between items-start mb-2">
                      <div className="section-title" style={{ margin: 0 }}>Embedded LLM Model</div>
                      <label className="flex items-center gap-2 cursor-pointer">
                        <div className="toggle-switch">
                          <input type="checkbox" checked={cfg.use_4bit_quantization || false}
                            onChange={e => set('use_4bit_quantization', e.target.checked)} />
                          <span className="toggle-slider"></span>
                        </div>
                        <span style={{ fontWeight: 500, fontSize: 13, color: cfg.use_4bit_quantization ? 'var(--accent-primary)' : 'var(--text-secondary)' }}>
                          4-bit Quantization
                        </span>
                        <span
                          style={{ position: 'relative', display: 'inline-block', cursor: 'help', fontSize: 13, color: 'var(--text-muted)' }}
                          onMouseEnter={() => setShowQuantTip(true)}
                          onMouseLeave={() => setShowQuantTip(false)}
                        >
                          ⓘ
                          {showQuantTip && (
                            <div style={{
                              position: 'absolute', bottom: '130%', right: 0, width: 240,
                              background: 'var(--glass-bg, #1e1e2e)', border: '1px solid var(--glass-border)',
                              borderRadius: 8, padding: '10px 12px', fontSize: 12, lineHeight: 1.5,
                              color: 'var(--text-primary)', zIndex: 100, boxShadow: '0 4px 20px rgba(0,0,0,0.4)',
                              pointerEvents: 'none',
                            }}>
                              Loads model weights in 4-bit instead of 16-bit precision — roughly 4× less VRAM.
                              Slightly slower inference but lets you run much larger models on smaller GPUs.
                            </div>
                          )}
                        </span>
                      </label>
                    </div>
                    <div className="flex flex-col gap-3 mt-2 mb-2">
                      {PRESET_FAMILIES.map(family => {
                        const isFamilySelected = family.variants.some(v => v.id === cfg?.embedded_llm_model)
                        return (
                          <div key={family.name} className="glass p-4 flex flex-col gap-2 glass-hover"
                            style={{ borderRadius: 'var(--radius-sm)', border: isFamilySelected ? '2px solid var(--accent-primary)' : '' }}>
                            <div className="flex items-center gap-2 mb-1">
                              <div style={{ fontWeight: 600, fontSize: 14 }}>{family.name}</div>
                              {family.recommended && (
                                <span style={{
                                  fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px',
                                  padding: '2px 7px', borderRadius: 99, background: 'rgba(99,102,241,0.18)',
                                  color: 'var(--accent-primary)', border: '1px solid rgba(99,102,241,0.35)'
                                }}>★ Recommended</span>
                              )}
                            </div>
                            <div className="text-xs text-muted" style={{ marginBottom: 6 }}>{family.description}</div>
                            <div className="flex flex-wrap gap-2">
                              {family.variants.map(v => {
                                const sel = v.id === cfg?.embedded_llm_model
                                return (
                                  <button key={v.id} type="button" onClick={() => set('embedded_llm_model', v.id)}
                                    style={{
                                      fontSize: 12, padding: '4px 12px', borderRadius: 16,
                                      border: '1px solid var(--glass-border)', cursor: 'pointer', transition: 'all 0.2s',
                                      background: sel ? 'var(--accent-primary)' : 'rgba(255,255,255,0.05)',
                                      color: sel ? '#fff' : 'var(--text-secondary)',
                                    }}>
                                    {v.name}
                                  </button>
                                )
                              })}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                </div>
              </>
            )}

            {/* ── Footer ──────────────────────────────────────────────── */}
            <div className="flex justify-between mt-4">
              <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
              <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
                {saving ? 'Saving…' : 'Save Settings'}
              </button>
            </div>

            {/* First-time-user coach-mark tips for Settings (above the modal) */}
            <Coachmark tips={settingsTips} onDismiss={dismiss} onDisableAll={disableAll} zIndex={250} />
          </>
        )}
      </div>
    </div>
  )
}
