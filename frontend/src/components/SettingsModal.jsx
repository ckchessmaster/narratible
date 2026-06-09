import { useState, useEffect, useMemo } from 'react'
import { getSettings, saveSettings, getLlmModels } from '../api'

export default function SettingsModal({ onClose, toast }) {
  const [cfg, setCfg] = useState(null)
  const [saving, setSaving] = useState(false)
  const [llmModelsData, setLlmModelsData] = useState({ system_vram_mb: 0, families: [] })
  const [familyVariants, setFamilyVariants] = useState({})

  // Global sticky VRAM calculations
  const isQuantized = cfg?.use_4bit_quantization || false
  const chunkSize = cfg?.llm_chunk_size || 5000
  // Note: Tokens map roughly to 4 chars. A 24K char chunk is roughly ~6K tokens.
  // 6K context in a typical transformer demands closer to ~1.2GB padding 
  const contextVramCost = (chunkSize / 1000) * 50 // Assume ~50MB per 1k chars of context
  
  const selectedModelInfo = useMemo(() => {
    if (!llmModelsData || !llmModelsData.families) return null;
    for (const family of llmModelsData.families) {
      const variant = family.variants.find(v => v.id === cfg?.embedded_llm_model);
      if (variant) return variant;
    }
    return null;
  }, [llmModelsData, cfg?.embedded_llm_model]);

  const activeBaseVram = selectedModelInfo ? (selectedModelInfo.base_vram_mb || selectedModelInfo.min_vram_mb) : 0
  const activeAdjVram = activeBaseVram ? (isQuantized ? activeBaseVram / 2 : activeBaseVram) + contextVramCost : 0
  
  const vramPercent = llmModelsData.system_vram_mb > 0 
    ? Math.min(100, (activeAdjVram / llmModelsData.system_vram_mb) * 100) 
    : 0

  useEffect(() => {
    Promise.all([getSettings(), getLlmModels()])
      .then(([settingsData, modelsData]) => {
        setCfg(settingsData)
        setLlmModelsData(modelsData)
        if (modelsData && modelsData.families) {
          const initial = {}
          modelsData.families.forEach(f => {
            const found = f.variants.find(v => v.id === settingsData?.embedded_llm_model)
            initial[f.name] = found ? found.id : f.variants[0].id
          })
          setFamilyVariants(initial)
        }
      })
      .catch(e => {
        console.warn('Failed to load modal data', e)
        if (!cfg) toast('Failed to load settings', 'error')
      })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const set = (key, val) => setCfg(c => ({ ...c, [key]: val }))

  const handleSave = async () => {
    setSaving(true)
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
            <div className="section-title">AI Text Cleanup</div>

            <div className="field">
              <label>Gemini API Key</label>
              <input
                type="password"
                placeholder="AIza…"
                value={cfg.gemini_api_key}
                onChange={e => set('gemini_api_key', e.target.value)}
                autoComplete="off"
              />
              <div className="text-xs text-muted mt-1">
                Used for LLM-based text cleanup.{' '}
                <a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noreferrer"
                  style={{ color: 'var(--accent-primary)' }}>Get key →</a>
              </div>
            </div>

            <div className="field">
              <label>OpenAI API Key</label>
              <input
                type="password"
                placeholder="sk-…"
                value={cfg.openai_api_key}
                onChange={e => set('openai_api_key', e.target.value)}
                autoComplete="off"
              />
              <div className="text-xs text-muted mt-1">Fallback LLM cleanup provider.</div>
            </div>

            <div className="field">
              <label>HuggingFace Token</label>
              <input
                type="password"
                placeholder="hf_..."
                value={cfg.huggingface_token}
                onChange={e => set('huggingface_token', e.target.value)}
                autoComplete="off"
              />
              <div className="text-xs text-muted mt-1">
                Required for gated/restricted models (like Llama / Gemma).
              </div>
            </div>

            <div className="field">
              <div className="flex justify-between items-center mb-2">
                <label style={{ margin: 0 }}>LLM Temperature (0.0 - 1.0)</label>
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

            <div className="field">
              <div className="flex justify-between items-start mb-2">
                <label style={{ margin: 0 }}>Embedded Local LLM Model</label>
                <label className="flex items-center gap-2 cursor-pointer" title="Drastically reduces the VRAM required to load larger LLM models, at the cost of slower generation speed. Enables larger models to run on smaller GPUs!">
                  <div className="toggle-switch">
                    <input
                      type="checkbox"
                      checked={cfg.use_4bit_quantization || false}
                      onChange={e => set('use_4bit_quantization', e.target.checked)}
                    />
                    <span className="toggle-slider"></span>
                  </div>
                  <span style={{ fontWeight: 500, fontSize: 13, color: cfg.use_4bit_quantization ? 'var(--accent-primary)' : 'var(--text-secondary)' }}>
                    4-bit Quantization
                  </span>
                </label>
              </div>

              {llmModelsData.system_vram_mb > 0 && activeBaseVram > 0 && (
                <div className="glass p-3 mb-4" style={{ position: 'sticky', top: 0, zIndex: 10, background: 'var(--bg-primary)', borderBottom: '1px solid var(--glass-border)' }}>
                  <div className="flex justify-between text-xs mb-1">
                    <span style={{ fontWeight: 600 }}>Active VRAM Usage ({selectedModelInfo?.name})</span>
                    <span>
                      {(activeAdjVram / 1024).toFixed(1)}GB / {(llmModelsData.system_vram_mb / 1024).toFixed(1)}GB
                      {isQuantized && <span style={{ color: 'var(--accent-primary)', marginLeft: 4 }}>(4-bit)</span>}
                    </span>
                  </div>
                  <div className="progress-bar" style={{ height: 8 }}>
                    <div 
                      className="progress-bar-fill" 
                      style={{ 
                        width: `${vramPercent}%`,
                        background: vramPercent > 100 ? 'var(--danger)' : (vramPercent > 80 ? 'orange' : 'var(--success)')
                      }} 
                    />
                  </div>
                </div>
              )}

              {llmModelsData.families.length > 0 ? (
                <div className="flex flex-col gap-4 mt-2">
                  {llmModelsData.families.map(family => {
                    const activeVariantId = familyVariants[family.name] 
                      || family.variants.find(v => v.id === cfg?.embedded_llm_model)?.id 
                      || family.variants[0].id
                    
                    const activeVariant = family.variants.find(v => v.id === activeVariantId) || family.variants[0]
                    const isFamilySelected = family.variants.some(v => v.id === cfg?.embedded_llm_model)

                    // Dynamic VRAM calculations based on Quantization & Chunk toggle
                    const isQuantized = cfg?.use_4bit_quantization || false
                    const chunkSize = cfg?.llm_chunk_size || 5000
                    const contextVramCost = (chunkSize / 1000) * 50 // Assume ~50MB per 1k chars of context
                    
                    const activeBaseVram = activeVariant.base_vram_mb || activeVariant.min_vram_mb
                    const activeAdjVram = (isQuantized ? activeBaseVram / 2 : activeBaseVram) + contextVramCost
                    
                    const isActiveRecommended = llmModelsData.system_vram_mb > 0 
                      ? llmModelsData.system_vram_mb >= activeAdjVram 
                      : true
                    
                    const isGated = activeVariant.gated
                    const hasToken = !!cfg?.huggingface_token
                    const needsToken = isGated && !hasToken
                    // Gated models require EULA agreement regardless of token presence.
                    // We only "disable" selection if the token is completely missing.
                    const isDisabled = !isActiveRecommended || needsToken

                    return (
                      <div
                        key={family.name}
                        className={`glass p-4 flex flex-col gap-3 ${!isDisabled ? 'glass-hover' : ''}`}
                        style={{
                          borderRadius: 'var(--radius-sm)',
                          opacity: !isDisabled ? 1 : 0.65,
                          border: isFamilySelected ? '2px solid var(--accent-primary)' : ''
                        }}
                      >
                        <div className="flex items-start gap-3">
                          <input
                            type="radio"
                            name="embedded_llm_model_family"
                            checked={isFamilySelected}
                            onChange={() => set('embedded_llm_model', activeVariantId)}
                            disabled={isDisabled}
                            style={{ marginTop: 4, cursor: !isDisabled ? 'pointer' : 'not-allowed' }}
                          />
                          <div style={{ flex: 1 }}>
                            <div className="flex justify-between items-center mb-1">
                              <div style={{ fontWeight: 600, fontSize: 15 }}>
                                {family.name}
                                {!isActiveRecommended && (
                                  <span className="text-danger text-xs ml-2">(Insufficient VRAM)</span>
                                )}
                              </div>
                            </div>
                            <div className="text-xs text-muted mb-3">{family.description}</div>

                            <div className="flex flex-wrap gap-2 mb-3">
                              {family.variants.map(v => {
                                const isVariantSelected = v.id === activeVariantId
                                const btnStyle = isVariantSelected 
                                  ? { background: 'var(--accent-primary)', color: '#fff', borderColor: 'transparent' }
                                  : { background: 'rgba(255,255,255,0.05)', color: 'var(--text-secondary)' }
                                return (
                                  <button
                                    key={v.id}
                                    type="button"
                                    onClick={() => {
                                      setFamilyVariants(prev => ({...prev, [family.name]: v.id}))
                                      if (isFamilySelected) set('embedded_llm_model', v.id)
                                    }}
                                    style={{
                                      fontSize: 12, padding: '4px 12px', borderRadius: 16, 
                                      border: '1px solid var(--glass-border)', cursor: 'pointer',
                                      transition: 'all 0.2s', ...btnStyle
                                    }}
                                  >
                                    {v.name}
                                  </button>
                                )
                              })}
                            </div>

                            {isGated && (
                              <div className="mb-3 p-2 text-xs" style={{ background: 'rgba(245, 158, 11, 0.1)', border: '1px solid rgba(245, 158, 11, 0.3)', borderRadius: 6 }}>
                                <span className="text-warning" style={{ fontWeight: 600 }}>⚠ Gated Model: </span> 
                                {needsToken ? "Requires a HuggingFace Token above. " : ""}
                                Make sure you have <a href={`https://huggingface.co/${activeVariant.id}`} target="_blank" rel="noreferrer" style={{color: 'var(--accent-primary)', textDecoration: 'underline'}}>accepted the license agreement here ↗</a> with your HuggingFace account before use.
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    )
                  })}
                  <div className="text-xs text-muted mt-3">
                    Alternatively, specify a custom HuggingFace model ID below:
                  </div>
                  <input
                    type="text"
                    placeholder="Custom model ID..."
                    value={cfg.embedded_llm_model}
                    onChange={e => set('embedded_llm_model', e.target.value)}
                  />
                </div>
              ) : (
                <>
                  <input
                    type="text"
                    placeholder="HuggingFaceTB/SmolLM2-1.7B-Instruct"
                    value={cfg.embedded_llm_model}
                    onChange={e => set('embedded_llm_model', e.target.value)}
                  />
                  <div className="text-xs text-muted mt-1">
                    Local model loaded via Transformers. Make sure you have enough VRAM.
                  </div>
                </>
              )}
            </div>

            <div className="field mt-3">
              <label>LLM Content Chunk Size: {(cfg.llm_chunk_size || 5000).toLocaleString()} characters</label>
              <input
                type="range"
                min="1000"
                max="32000"
                step="1000"
                value={cfg.llm_chunk_size || 5000}
                onChange={e => set('llm_chunk_size', parseInt(e.target.value) || 5000)}
              />
              <div className="flex justify-between text-xs text-muted mt-1">
                <span>1k (Fast, Tiny VRAM)</span>
                <span>16k (Balanced)</span>
                <span>32k (Slow, Heavy VRAM)</span>
              </div>
              <div className="text-xs text-muted mt-2">
                How many characters of the book to pass to the LLM at a time. Larger contexts give the AI better understanding of sentence flows and margin layouts, but consume significantly more memory.
              </div>
            </div>

            <div className="divider" />
            <div className="section-title">Audiobookshelf</div>

            <div className="field">
              <label>Server URL</label>
              <input
                type="url"
                placeholder="http://192.168.1.x:13378"
                value={cfg.audiobookshelf_url}
                onChange={e => set('audiobookshelf_url', e.target.value)}
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

            <div className="divider" />
            <div className="section-title">Default TTS Engine</div>

            <div className="field">
              <select
                value={cfg.default_tts_engine}
                onChange={e => set('default_tts_engine', e.target.value)}
              >
                <option value="edge-tts">Edge-TTS (online, free)</option>
                <option value="kokoro">Kokoro-82M (local, GPU)</option>
              </select>
            </div>

            <div className="flex justify-between mt-4">
              <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
              <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
                {saving ? 'Saving…' : 'Save Settings'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
