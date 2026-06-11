import { useState, useEffect } from 'react'
import { getSettings, saveSettings } from '../api'

const PRESET_FAMILIES = [
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
    name: "Gemma 4",
    description: "Google's reasoning and instruction following models. (Gated)",
    variants: [
      { id: "google/gemma-4-E2B-it", name: "E2B" },
      { id: "google/gemma-4-E4B-it", name: "E4B" },
      { id: "google/gemma-4-12B-it", name: "12B" },
      { id: "google/gemma-4-31B-it", name: "31B" },
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

export default function SettingsModal({ onClose, toast }) {
  const [cfg, setCfg] = useState(null)
  const [saving, setSaving] = useState(false)
  const [modelInfo, setModelInfo] = useState(null)
  const [checkingModel, setCheckingModel] = useState(false)
  const [checkingModelError, setCheckingModelError] = useState(null) 
  const [systemInfo, setSystemInfo] = useState(null)
  const [geminiModels, setGeminiModels] = useState(null)
  const [fetchingGeminiModels, setFetchingGeminiModels] = useState(false)

  useEffect(() => {
    getSettings().then(setCfg).catch(e => {
      console.warn('Failed to load settings', e)
      if (!cfg) toast('Failed to load settings', 'error')
    })
    import('../api').then(({ getSystemInfo }) => {
      getSystemInfo().then(setSystemInfo).catch(e => console.warn('Failed to load system info', e))
    })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Auto-verify model when the selected model string changes (debounced slightly to avoid spamming if typing)
  useEffect(() => {
    if (!cfg?.embedded_llm_model) {
      setModelInfo(null);
      return;
    }
    const timer = setTimeout(() => {
      handleCheckModel();
    }, 500);
    return () => clearTimeout(timer);
  }, [cfg?.embedded_llm_model, cfg?.huggingface_token]);

  const handleCheckModel = async () => {
    if (!cfg?.embedded_llm_model) return;
    
    setCheckingModel(true);
    setCheckingModelError(null);
    setModelInfo(null);
    
    try {
      const res = await fetch(`/api/llm/model-info?model_id=${encodeURIComponent(cfg.embedded_llm_model)}&token=${encodeURIComponent(cfg.huggingface_token || '')}`);
      if (!res.ok) {
        const errorData = await res.json();
        throw new Error(errorData.detail || "Failed to fetch model info");
      }
      const data = await res.json();
      setModelInfo(data);
    } catch (e) {
      setCheckingModelError(e.message);
    } finally {
      setCheckingModel(false);
    }
  }

  const set = (key, val) => setCfg(c => ({ ...c, [key]: val }))

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
              <div style={{ display: 'flex', gap: '8px' }}>
                <input
                  type="password"
                  placeholder="AIza…"
                  value={cfg.gemini_api_key}
                  onChange={e => set('gemini_api_key', e.target.value)}
                  autoComplete="off"
                  style={{ flex: 1 }}
                />
                <button
                  className="btn btn-secondary"
                  style={{ whiteSpace: 'nowrap', fontSize: '12px', padding: '0 10px' }}
                  disabled={!cfg.gemini_api_key || fetchingGeminiModels}
                  onClick={() => fetchGeminiModels(cfg.gemini_api_key)}
                >
                  {fetchingGeminiModels ? '…' : 'Load Models'}
                </button>
              </div>
              <div className="text-xs text-muted mt-1">
                Used for LLM-based text cleanup.{' '}
                <a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noreferrer"
                  style={{ color: 'var(--accent-primary)' }}>Get key →</a>
              </div>
            </div>

            <div className="field">
              <label>Gemini Model</label>
              {geminiModels ? (
                <select
                  value={cfg.gemini_model || 'gemini-2.5-flash'}
                  onChange={e => set('gemini_model', e.target.value)}
                >
                  {geminiModels.map(m => (
                    <option key={m.id} value={m.id}>{m.display_name || m.id}</option>
                  ))}
                </select>
              ) : (
                <input
                  type="text"
                  placeholder="gemini-2.5-flash"
                  value={cfg.gemini_model || ''}
                  onChange={e => set('gemini_model', e.target.value)}
                />
              )}
              <div className="text-xs text-muted mt-1">
                Enter a model ID manually or click "Load Models" above to pick from available models.
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

              <div className="flex flex-col gap-4 mt-2 mb-4">
                {PRESET_FAMILIES.map(family => {
                  const isFamilySelected = family.variants.some(v => v.id === cfg?.embedded_llm_model)

                  return (
                    <div
                      key={family.name}
                      className="glass p-4 flex flex-col gap-3 glass-hover"
                      style={{
                        borderRadius: 'var(--radius-sm)',
                        border: isFamilySelected ? '2px solid var(--accent-primary)' : ''
                      }}
                    >
                      <div className="flex items-start gap-3">
                        <div style={{ flex: 1 }}>
                          <div className="flex justify-between items-center mb-1">
                            <div style={{ fontWeight: 600, fontSize: 15 }}>
                              {family.name}
                            </div>
                          </div>
                          <div className="text-xs text-muted mb-3">{family.description}</div>

                          <div className="flex flex-wrap gap-2 mb-1">
                            {family.variants.map(v => {
                              const isVariantSelected = v.id === cfg?.embedded_llm_model
                              const btnStyle = isVariantSelected 
                                ? { background: 'var(--accent-primary)', color: '#fff', borderColor: 'transparent' }
                                : { background: 'rgba(255,255,255,0.05)', color: 'var(--text-secondary)' }
                              return (
                                <button
                                  key={v.id}
                                  type="button"
                                  onClick={() => set('embedded_llm_model', v.id)}
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
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>

<div className="text-xs text-muted mt-3 mb-2" style={{ fontWeight: 600 }}>
                Currently Selected Model ID:
              </div>

              <div className="glass p-4" style={{ borderRadius: 'var(--radius-sm)', border: '1px solid var(--accent-primary)' }}>
                 <div className="flex gap-2 mb-3">
                   <input 
                     type="text" 
                     value={cfg?.embedded_llm_model || ''}
                     onChange={e => {
                       set('embedded_llm_model', e.target.value);
                       setModelInfo(null); // Clear previous check if typed manually
                     }}
                     placeholder="e.g. google/gemma-4-E4B-it"
                     style={{ flex: 1, fontWeight: 500, border: '1px solid var(--glass-border)' }}
                   />
                 </div>

                 {checkingModel && (
                   <div className="text-muted text-sm mb-3 italic">
                     Querying Hugging Face for model details...
                   </div>
                 )}

                 {checkingModelError && !checkingModel && (
                     <div className="text-danger text-sm mb-3">
                       {checkingModelError}
                     </div>
                   )}

                 {modelInfo && !checkingModelError && !checkingModel && (
                     <div className="text-sm p-3 bg-base" style={{ borderRadius: 'var(--radius-sm)', border: '1px solid var(--glass-border)' }}>
                       <div className="flex justify-between mb-1">
                         <strong>{modelInfo.id}</strong>
                         <span className="text-muted">{modelInfo.size_mb > 0 ? `${(modelInfo.size_mb / 1024).toFixed(1)} GB` : 'Unknown size'}</span>
                       </div>
                       
                       <div className="text-muted text-xs mb-2">
                         {modelInfo.author && <span className="mr-2">👤 {modelInfo.author}</span>}
                         Tags: {modelInfo.tags?.slice(0, 5).join(', ')}{modelInfo.tags?.length > 5 ? '...' : ''}
                       </div>
                       
                       {modelInfo.gated && (
                         <div className="mb-2 p-2 text-xs" style={{ background: 'rgba(245, 158, 11, 0.1)', border: '1px solid rgba(245, 158, 11, 0.3)', borderRadius: 6 }}>
                           <span className="text-warning" style={{ fontWeight: 600 }}>⚠ Gated Model: </span> 
                           Make sure you have <a href={`https://huggingface.co/${modelInfo.id}`} target="_blank" rel="noreferrer" style={{color: 'var(--accent-primary)', textDecoration: 'underline'}}>accepted the license agreement here ↗</a> with your HuggingFace account before use.
                         </div>
                       )}

                       {modelInfo.system_vram_mb > 0 && modelInfo.size_mb > 0 && (
                         <div className={`text-xs ${modelInfo.size_mb > modelInfo.system_vram_mb ? 'text-danger' : 'text-success'}`} style={{ marginTop: '8px' }}>
                           {modelInfo.size_mb > modelInfo.system_vram_mb 
                             ? `Warning: Model size (${(modelInfo.size_mb / 1024).toFixed(1)} GB) exceeds your system VRAM (${(modelInfo.system_vram_mb / 1024).toFixed(1)} GB). It will likely fall back to slow CPU RAM.`
                             : `Model size should fit within your ${ (modelInfo.system_vram_mb / 1024).toFixed(1) } GB of VRAM limit.`}
                         </div>
                       )}
                     </div>
                   )}
                </div>
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
