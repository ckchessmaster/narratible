import { useState, useEffect } from 'react'
import { getSettings, saveSettings, getLlmModels } from '../api'

export default function SettingsModal({ onClose, toast }) {
  const [cfg, setCfg] = useState(null)
  const [saving, setSaving] = useState(false)
  const [llmModelsData, setLlmModelsData] = useState({ system_vram_mb: 0, families: [] })
  const [familyVariants, setFamilyVariants] = useState({})

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

              {llmModelsData.families.length > 0 ? (
                <div className="flex flex-col gap-4 mt-2">
                  {llmModelsData.families.map(family => {
                    const activeVariantId = familyVariants[family.name] 
                      || family.variants.find(v => v.id === cfg?.embedded_llm_model)?.id 
                      || family.variants[0].id
                    
                    const activeVariant = family.variants.find(v => v.id === activeVariantId) || family.variants[0]
                    const isFamilySelected = family.variants.some(v => v.id === cfg?.embedded_llm_model)

                    // Dynamic VRAM calculations based on Quantization toggle
                    const isQuantized = cfg?.use_4bit_quantization || false
                    const activeAdjVram = isQuantized ? activeVariant.min_vram_mb / 2 : activeVariant.min_vram_mb
                    const isActiveRecommended = llmModelsData.system_vram_mb > 0 
                      ? llmModelsData.system_vram_mb >= activeAdjVram 
                      : true

                    const vramPercent = llmModelsData.system_vram_mb > 0 
                      ? Math.min(100, (activeAdjVram / llmModelsData.system_vram_mb) * 100) 
                      : 0

                    return (
                      <div
                        key={family.name}
                        className={`glass p-4 flex flex-col gap-3 ${isActiveRecommended ? 'glass-hover' : ''}`}
                        style={{
                          borderRadius: 'var(--radius-sm)',
                          opacity: isActiveRecommended ? 1 : 0.65,
                          border: isFamilySelected ? '2px solid var(--accent-primary)' : ''
                        }}
                      >
                        <div className="flex items-start gap-3">
                          <input
                            type="radio"
                            name="embedded_llm_model_family"
                            checked={isFamilySelected}
                            onChange={() => set('embedded_llm_model', activeVariantId)}
                            disabled={!isActiveRecommended}
                            style={{ marginTop: 4, cursor: isActiveRecommended ? 'pointer' : 'not-allowed' }}
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
                            
                            {llmModelsData.system_vram_mb > 0 && (
                              <div>
                                <div className="flex justify-between text-xs text-muted mb-1">
                                  <span>
                                    VRAM Usage: {(activeAdjVram / 1024).toFixed(1)}GB
                                    {isQuantized && <span style={{ color: 'var(--accent-primary)', marginLeft: 4 }}>(4-bit)</span>}
                                  </span>
                                  <span>Total: {(llmModelsData.system_vram_mb / 1024).toFixed(1)}GB</span>
                                </div>
                                <div className="progress-bar" style={{ height: 6 }}>
                                  <div 
                                    className="progress-bar-fill" 
                                    style={{ 
                                      width: `${vramPercent}%`,
                                      background: !isActiveRecommended ? 'var(--danger)' : (vramPercent > 80 ? 'orange' : 'var(--success)')
                                    }} 
                                  />
                                </div>
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
