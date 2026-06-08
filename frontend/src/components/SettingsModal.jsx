import { useState, useEffect } from 'react'
import { getSettings, saveSettings } from '../api'

export default function SettingsModal({ onClose, toast }) {
  const [cfg, setCfg] = useState(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    getSettings().then(setCfg).catch(e => toast(e.message, 'error'))
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
