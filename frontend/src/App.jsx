import { useState, useCallback } from 'react'
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
  const [projectId, setProjectId] = useState(null)
  const [showSettings, setShowSettings] = useState(false)
  const [toasts, setToasts] = useState([])

  const toast = useCallback((message, type = 'info') => {
    const id = Date.now()
    setToasts(t => [...t, { id, message, type }])
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 4000)
  }, [])

  const next = () => setStep(s => Math.min(s + 1, 4))
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
            return (
              <div key={n} className="step-item">
                {i > 0 && <div className="step-connector" />}
                <div className={`step-num ${isActive ? 'active' : isDone ? 'done' : ''}`}>
                  {isDone ? '✓' : n}
                </div>
                <span className={`step-label ${isActive ? 'active' : ''}`}>{s.label}</span>
              </div>
            )
          })}
        </nav>

        <button className="btn btn-ghost btn-sm" onClick={() => setShowSettings(true)}>
          ⚙ Settings
        </button>
      </header>

      {/* Main */}
      <main className="main">
        {step === 1 && (
          <Step1Upload
            projectId={projectId}
            setProjectId={setProjectId}
            onNext={next}
            toast={toast}
          />
        )}
        {step === 2 && (
          <Step2Editor
            projectId={projectId}
            onNext={next}
            onBack={back}
            toast={toast}
          />
        )}
        {step === 3 && (
          <Step3TTS
            projectId={projectId}
            onNext={next}
            onBack={back}
            toast={toast}
          />
        )}
        {step === 4 && (
          <Step4Export
            projectId={projectId}
            onBack={back}
            toast={toast}
          />
        )}
      </main>

      {/* Settings modal */}
      {showSettings && (
        <SettingsModal onClose={() => setShowSettings(false)} toast={toast} />
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

