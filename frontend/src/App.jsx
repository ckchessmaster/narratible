import { useState, useCallback, useEffect } from 'react'
import { cancelTask, deleteProject, getSystemInfo, getSettings, listProjects } from './api'
import './App.css'
import './index.css'
import Step1Upload from './components/Step1Upload'
import Step2Editor from './components/Step2Editor'
import Step3TTS from './components/Step3TTS'
import Step4Export from './components/Step4Export'
import SettingsModal from './components/SettingsModal'
import VoiceLibraryPage from './components/VoiceLibraryPage'
import Coachmark from './components/Coachmark'
import useTips from './useTips'

const STEPS = [
  { label: 'Upload' },
  { label: 'Edit' },
  { label: 'Voice' },
  { label: 'Export' },
]

const STEP_BY_STATUS = {
  upload: 1,
  edit: 2,
  voice: 3,
  export: 4,
}

export default function App() {
  const [step, setStep] = useState(1)
  const [maxStep, setMaxStep] = useState(1)
  const [projectId, setProjectId] = useState(null)
  const [showSettings, setShowSettings] = useState(false)
  const [view, setView] = useState('wizard')
  const [voiceLibraryRevision, setVoiceLibraryRevision] = useState(0)
  const [toasts, setToasts] = useState([])
  const [cudaEnabled, setCudaEnabled] = useState(true)
  const [hasCloudKey, setHasCloudKey] = useState(false)
  const [debugMode, setDebugMode] = useState(false)
  const [projects, setProjects] = useState([])
  const [projectsLoading, setProjectsLoading] = useState(false)
  const [deletingProjectId, setDeletingProjectId] = useState(null)
  const [projectSearch, setProjectSearch] = useState('')
  const { getActiveTips, dismiss, disableAll } = useTips()
  const wizardTips = getActiveTips(t => t.context === 'wizard' && t.step === step)
  const voiceLibraryTips = getActiveTips(t => t.context === 'voice-library')
  const activeTips = view === 'voice-library' ? voiceLibraryTips : wizardTips

  const refreshHardwareState = useCallback(() => {
    Promise.all([getSystemInfo(), getSettings()]).then(([info, cfg]) => {
      const gpus = info?.gpus ?? []
      const selectedIdx = cfg?.selected_gpu_index ?? 0
      const selectedGpu = gpus.find(g => g.index === selectedIdx) ?? gpus[0]
      setCudaEnabled(selectedGpu?.cuda ?? true)
      setHasCloudKey(!!(cfg?.gemini_api_key || cfg?.openai_api_key))
      setDebugMode(!!(cfg?.debug_mode))
    }).catch(() => {})
  }, [])

  // Fetch on mount
  useEffect(() => { refreshHardwareState() }, [refreshHardwareState])

  const refreshProjects = useCallback(() => {
    setProjectsLoading(true)
    listProjects()
      .then(items => setProjects((items ?? []).slice().sort((a, b) => (b.updated_at || '').localeCompare(a.updated_at || ''))))
      .catch(() => {})
      .finally(() => setProjectsLoading(false))
  }, [])

  useEffect(() => {
    const timer = setTimeout(refreshProjects, 0)
    return () => clearTimeout(timer)
  }, [refreshProjects])

  const toast = useCallback((message, type = 'info') => {
    const id = Date.now()
    setToasts(t => [...t, { id, message, type }])
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 4000)
  }, [])

  const next = () => setStep(s => { const n = Math.min(s + 1, 4); setMaxStep(m => Math.max(m, n)); return n })
  const back = () => setStep(s => Math.max(s - 1, 1))
  const resumeProject = (project) => {
    const resumeStep = STEP_BY_STATUS[project.current_step] || (project.chapter_count ? 2 : 1)
    setProjectId(project.id)
    setStep(resumeStep)
    setMaxStep(Math.max(resumeStep, project.chapter_count ? 2 : 1))
    setView('wizard')
  }

  const handleDeleteProject = async (project) => {
    if (!window.confirm(`Delete project "${project.title}"? This cannot be undone.`)) return
    setDeletingProjectId(project.id)
    try {
      await deleteProject(project.id)
      toast(`Deleted project: ${project.title}`, 'success')
      refreshProjects()
    } catch (e) {
      toast(e.message || 'Failed to delete project.', 'error')
    } finally {
      setDeletingProjectId(null)
    }
  }

  const normalizedProjectSearch = projectSearch.trim().toLowerCase()
  const filteredProjects = normalizedProjectSearch
    ? projects.filter(project => {
        const title = (project.title || '').toLowerCase()
        const author = (project.author || '').toLowerCase()
        return title.includes(normalizedProjectSearch) || author.includes(normalizedProjectSearch)
      })
    : projects

  return (
    <div className="app">
      {/* Header */}
      <header className="header">
        <div className="header-brand">
          <img src="/logo.png" alt="narratible" style={{ height: 36, width: 'auto' }} />
          <span className="header-subtitle">PDF → Audiobook</span>
        </div>

        <nav className="stepper">
          {STEPS.map((s, i) => {
            const n = i + 1
            const isActive = view === 'wizard' && step === n
            const isDone = view === 'wizard' && step > n
            const isReachable = n <= maxStep && (view !== 'wizard' || n !== step)
            return (
              <div
                key={n}
                className="step-item"
                style={{ cursor: isReachable ? 'pointer' : 'default' }}
                onClick={() => { if (isReachable) { setView('wizard'); setStep(n) } }}
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
          <button
            className={`btn btn-ghost btn-sm${view === 'voice-library' ? ' is-active' : ''}`}
            data-tip-anchor="voice-library-button"
            onClick={() => setView('voice-library')}
          >
            Voice Library
          </button>
          {(step > 1 || projectId) && (
            <button className="btn btn-ghost btn-sm" onClick={() => { if (projectId) cancelTask(projectId).catch(() => {}); setProjectId(null); setStep(1); setMaxStep(1); setView('wizard') }}>
              ↺ Clear Project
            </button>
          )}
          <button className="btn btn-ghost btn-sm" data-tip-anchor="settings-button" onClick={() => setShowSettings(true)}>
            ⚙ Settings
          </button>
        </div>
      </header>

      {/* Main */}
      <main className="main">
        {view === 'voice-library' ? (
          <VoiceLibraryPage
            onBack={() => setView('wizard')}
            toast={toast}
            onChanged={() => setVoiceLibraryRevision(value => value + 1)}
          />
        ) : (
          <>
            {!projectId && step === 1 && (
              <section className="resume-panel" data-tip-anchor="resume-projects">
                <div>
                  <div className="step-title">Start or resume</div>
                  <div className="step-desc">Pick up an existing project without re-running completed parsing, cleanup, or TTS work.</div>
                </div>
                {projects.length > 0 && (
                  <div className="resume-search-row" data-tip-anchor="resume-search">
                    <input
                      type="text"
                      className="resume-search-input"
                      value={projectSearch}
                      onChange={e => setProjectSearch(e.target.value)}
                      placeholder="Search projects by title or author"
                      aria-label="Search projects"
                    />
                    {projectSearch && (
                      <button type="button" className="btn btn-ghost btn-sm" onClick={() => setProjectSearch('')}>
                        Clear
                      </button>
                    )}
                    <span className="resume-search-count">
                      {filteredProjects.length} of {projects.length}
                    </span>
                  </div>
                )}
                {projectsLoading ? (
                  <div className="text-sm text-muted">Loading projects…</div>
                ) : filteredProjects.length ? (
                  <div className="resume-list-scroll">
                    <div className="resume-grid">
                      {filteredProjects.map(project => (
                        <article key={project.id} className="resume-card glass-hover">
                          <button type="button" className="resume-open" onClick={() => resumeProject(project)}>
                            <span className="resume-title">{project.title}</span>
                            <span className="resume-meta">
                              {project.author || 'Unknown author'} · {project.chapter_count || 0} chapter{project.chapter_count === 1 ? '' : 's'} · {project.current_step || 'upload'}
                            </span>
                          </button>
                          <button
                            type="button"
                            className="btn btn-danger btn-sm resume-delete"
                            data-tip-anchor="resume-delete"
                            disabled={deletingProjectId === project.id}
                            onClick={() => handleDeleteProject(project)}
                          >
                            {deletingProjectId === project.id ? 'Deleting…' : 'Delete'}
                          </button>
                        </article>
                      ))}
                    </div>
                  </div>
                ) : projects.length ? (
                  <div className="text-sm text-muted">No projects match that search.</div>
                ) : (
                  <div className="text-sm text-muted">No saved projects yet. Create one below.</div>
                )}
              </section>
            )}
            <div style={{ display: step === 1 ? 'block' : 'none' }}>
              <Step1Upload
                projectId={projectId}
                setProjectId={setProjectId}
                isActive={step === 1}
                onNext={next}
                toast={toast}
                cudaEnabled={cudaEnabled}
                hasCloudKey={hasCloudKey}
                debugMode={debugMode}
                onProjectChanged={refreshProjects}
              />
            </div>
            <div style={{ display: step === 2 ? 'block' : 'none' }}>
              <Step2Editor
                projectId={projectId}
                isActive={step === 2}
                onNext={next}
                onBack={back}
                toast={toast}
                debugMode={debugMode}
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
                onOpenVoiceLibrary={() => setView('voice-library')}
                voiceLibraryRevision={voiceLibraryRevision}
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
          </>
        )}
      </main>

      {/* First-time-user coach-mark tips (hidden while Settings modal is open) */}
      {!showSettings && (
        <Coachmark tips={activeTips} onDismiss={dismiss} onDisableAll={disableAll} zIndex={150} />
      )}

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
