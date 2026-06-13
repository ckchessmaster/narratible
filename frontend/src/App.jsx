import { useState, useCallback, useEffect } from 'react'
import { cancelTask, getSystemInfo, getSettings } from './api'
import './App.css'
import './index.css'
import Step1Upload from './components/Step1Upload'
import Step2Editor from './components/Step2Editor'
import Step3TTS from './components/Step3TTS'
import Step4Export from './components/Step4Export'
import SettingsModal from './components/SettingsModal'

const STEPS = [
  { label: 'Upload' },
  { label: 'Edit' },
  { label: 'Voice' },
  { label: 'Export' },
]

export default function App() {
  const [step, setStep] = useState(1)
  const [maxStep, setMaxStep] = useState(1)
  const [projectId, setProjectId] = useState(null)
  const [showSettings, setShowSettings] = useState(false)
  const [toasts, setToasts] = useState([])
  const [cudaEnabled, setCudaEnabled] = useState(true)
  const [hasCloudKey, setHasCloudKey] = useState(false)

  const refreshHardwareState = useCallback(() => {
    Promise.all([getSystemInfo(), getSettings()]).then(([info, cfg]) => {
      const gpus = info?.gpus ?? []
      const selectedIdx = cfg?.selected_gpu_index ?? 0
      const selectedGpu = gpus.find(g => g.index === selectedIdx) ?? gpus[0]
      setCudaEnabled(selectedGpu?.cuda ?? true)
      setHasCloudKey(!!(cfg?.gemini_api_key || cfg?.openai_api_key))
    }).catch(() => {})
  }, [])

  // Fetch on mount
  useEffect(() => { refreshHardwareState() }, [refreshHardwareState])

  const toast = useCallback((message, type = 'info') => {
    const id = Date.now()
    setToasts(t => [...t, { id, message, type }])
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 4000)
  }, [])

  const next = () => setStep(s => { const n = Math.min(s + 1, 4); setMaxStep(m => Math.max(m, n)); return n })
  const back = () => setStep(s => Math.max(s - 1, 1))

  return (
    <div className="app">
      {/* Header */}
      <header className="header">
        <div className="header-brand">
          <span className="header-logo">Echo-Scribe</span>
          <span className="header-subtitle">PDF → Audiobook</span>
        </div>

        <nav className="stepper">
          {STEPS.map((s, i) => {
            const n = i + 1
            const isActive = step === n
            const isDone = step > n
            const isReachable = n <= maxStep && n !== step
            return (
              <div
                key={n}
                className="step-item"
                style={{ cursor: isReachable ? 'pointer' : 'default' }}
                onClick={() => isReachable && setStep(n)}
              >
                {i > 0 && <div className="step-connector" />}
                <div className={`step-num ${isActive ? 'active' : isDone ? 'done' : ''}`}>
                  {isDone ? '✓' : n}
                </div>
                <span className={`step-label ${isActive ? 'active' : ''}`}>{s.label}</span>
              </div>
            )
          })}
        </nav>

        <div style={{ display: "flex", gap: "0.5rem" }}>
          {(step > 1 || projectId) && (
            <button className="btn btn-ghost btn-sm" onClick={() => { if (projectId) cancelTask(projectId).catch(() => {}); setProjectId(null); setStep(1); setMaxStep(1); }}>
              ↺ Clear Project
            </button>
          )}
          <button className="btn btn-ghost btn-sm" onClick={() => setShowSettings(true)}>
            ⚙ Settings
          </button>
        </div>
      </header>

      {/* Main */}
      <main className="main">
        <div style={{ display: step === 1 ? 'block' : 'none' }}>
          <Step1Upload
            projectId={projectId}
            setProjectId={setProjectId}
            isActive={step === 1}
            onNext={next}
            toast={toast}
            cudaEnabled={cudaEnabled}
            hasCloudKey={hasCloudKey}
          />
        </div>
        <div style={{ display: step === 2 ? 'block' : 'none' }}>
          <Step2Editor
            projectId={projectId}
            isActive={step === 2}
            onNext={next}
            onBack={back}
            toast={toast}
          />
        </div>
        <div style={{ display: step === 3 ? 'block' : 'none' }}>
          <Step3TTS
            projectId={projectId}
            isActive={step === 3}
            onNext={next}
            onBack={back}
            toast={toast}
            cudaEnabled={cudaEnabled}
          />
        </div>
        <div style={{ display: step === 4 ? 'block' : 'none' }}>
          <Step4Export
            projectId={projectId}
            isActive={step === 4}
            onBack={back}
            toast={toast}
          />
        </div>
      </main>

      {/* Settings modal */}
      {showSettings && (
        <SettingsModal onClose={() => { setShowSettings(false); refreshHardwareState() }} toast={toast} />
      )}

      {/* Toasts */}
      <div className="toast-container">
        {toasts.map(t => (
          <div key={t.id} className={`toast toast-${t.type}`}>{t.message}</div>
        ))}
      </div>
    </div>
  )
}

