import { useState, useEffect, useRef } from 'react'
import { getProject, exportEpub, listExports, downloadExportUrl,
         getAbsLibraries, uploadToAbs, synthesizeBook, pollTask } from '../api'

export default function Step4Export({ projectId, isActive, onBack, toast }) {
  const [meta, setMeta] = useState(null)
  const [exports, setExports] = useState([])
  const [exporting, setExporting] = useState(false)
  const [synthesizing, setSynthesizing] = useState(false)
  const [taskProgress, setTaskProgress] = useState(null)
  const [singleAudio, setSingleAudio] = useState(false)
  const [audioFormat, setAudioFormat] = useState('m4b')
  const [libraries, setLibraries] = useState([])
  const [selectedLib, setSelectedLib] = useState('')
  const [selectedFiles, setSelectedFiles] = useState([])
  const [uploading, setUploading] = useState(false)
  const [uploadLog, setUploadLog] = useState([])
  const [loadingLibs, setLoadingLibs] = useState(false)

  // Incremented every time a new synthesis starts or the project is cleared.
  // The pollTask callback checks this to discard results from a stale session.
  const synthesizeSessionRef = useRef(0)

  useEffect(() => {
    if (!projectId || !isActive) return
    getProject(projectId).then(setMeta).catch(() => {})
    refreshExports()
  // eslint-disable-next-line react-hooks/exhaustive-deps -- refreshExports closes over projectId which is already in deps
  }, [projectId, isActive])

  useEffect(() => {
    if (!projectId) {
      synthesizeSessionRef.current += 1  // invalidate any in-progress poll
      setSynthesizing(false)
      setTaskProgress(null)
    }
  }, [projectId])

  const refreshExports = () => {
    listExports(projectId)
      .then(res => setExports(res.files))
      .catch(() => {})
  }

  const handleExportEpub = async () => {
    setExporting(true)
    try {
      const res = await exportEpub(projectId)
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail) }
      const blob = await res.blob()
      const cd = res.headers.get('content-disposition') || ''
      const match = cd.match(/filename="?([^"]+)"?/)
      const filename = match ? match[1] : 'book.epub'
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = filename; a.click()
      URL.revokeObjectURL(url)
      toast('EPUB downloaded!', 'success')
      refreshExports()
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setExporting(false)
    }
  }

  const handleSynthesize = async () => {
    if (!meta || !meta.tts_engine) {
      toast('Please go back and configure a voice first.', 'error')
      return
    }
    const session = ++synthesizeSessionRef.current
    setSynthesizing(true)
    setTaskProgress({ status: 'running', message: 'Queued…', progress: 0 })
    try {
      const { task_id } = await synthesizeBook(projectId, meta.tts_engine, meta.tts_voice, meta.tts_speed, singleAudio, audioFormat, meta.tts_read_headings ?? true)
      await pollTask(task_id, t => {
        if (synthesizeSessionRef.current !== session) return
        setTaskProgress(t)
      })
      if (synthesizeSessionRef.current === session) {
        if (taskProgress?.status !== 'error') toast('Synthesis complete!', 'success')
        refreshExports()
      }
    } catch (e) {
      if (synthesizeSessionRef.current === session) toast(e.message, 'error')
    } finally {
      if (synthesizeSessionRef.current === session) setSynthesizing(false)
    }
  }

  const handleLoadLibraries = async () => {
    setLoadingLibs(true)
    try {
      const res = await getAbsLibraries()
      setLibraries(res.libraries)
      if (res.libraries.length > 0) setSelectedLib(res.libraries[0].id)
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setLoadingLibs(false)
    }
  }

  const toggleFile = (f) => {
    setSelectedFiles(prev =>
      prev.includes(f) ? prev.filter(x => x !== f) : [...prev, f]
    )
  }

  const handleUploadToAbs = async () => {
    if (!selectedLib) { toast('Select a library first.', 'error'); return }
    if (selectedFiles.length === 0) { toast('Select at least one file to upload.', 'error'); return }
    setUploading(true)
    setUploadLog(['Starting upload…'])
    try {
      const res = await uploadToAbs(projectId, selectedLib, selectedFiles)
      setUploadLog(prev => [...prev, res.message || 'Upload successful.'])
      toast('Uploaded to Audiobookshelf!', 'success')
    } catch (e) {
      setUploadLog(prev => [...prev, `Error: ${e.message}`])
      toast(e.message, 'error')
    } finally {
      setUploading(false)
    }
  }

  const iconFor = (filename) => {
    if (filename.endsWith('.epub')) return '📖'
    if (filename.endsWith('.mp3') || filename.endsWith('.m4b')) return '🎧'
    return '📄'
  }

  return (
    <div className="step-card">
      <div className="step-header">
        <div>
          <div className="step-title">Export & Upload</div>
          <div className="step-desc">
            Download your EPUB or audio files, or upload directly to Audiobookshelf.
          </div>
        </div>
      </div>

      <div className="flex gap-6">
        {/* Left: Export actions */}
        <div style={{ flex: 1 }}>
          <div className="section-title">Generate Files</div>
          <div className="flex gap-3 mb-6">
            <div className="glass p-4" style={{ flex: 1, borderRadius: 'var(--radius-sm)' }} data-tip-anchor="export-epub">
              <div style={{ fontSize: 28, marginBottom: 8 }}>📖</div>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>EPUB Ebook</div>
              <div className="text-sm text-muted mb-4">
                Generates a valid EPUB 3 file with all chapters, metadata, and cover.
              </div>
              <button className="btn btn-primary w-full" onClick={handleExportEpub} disabled={exporting}>
                {exporting ? '⏳ Building…' : '↓ Export EPUB'}
              </button>
            </div>

            <div className="glass p-4" style={{ flex: 1, borderRadius: 'var(--radius-sm)' }} data-tip-anchor="generate-audio">
              <div style={{ fontSize: 28, marginBottom: 8 }}>🎧</div>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>Audiobook MP3</div>
              <div className="text-sm text-muted mb-4">
                Generate audio based on the voice configured in Step 3.
              </div>
              <label className="flex items-center gap-2 mb-3 text-sm cursor-pointer">
                <input type="checkbox" checked={singleAudio} onChange={e => setSingleAudio(e.target.checked)} disabled={synthesizing} />
                Merge into single audio file (requires FFmpeg)
              </label>
              {singleAudio && (
                <div className="flex items-center gap-2 mb-3 text-sm" data-tip-anchor="audio-format-toggle">
                  <span className="text-muted">Format:</span>
                  <div className="segmented" role="group" aria-label="Merged audio format">
                    <button
                      type="button"
                      className={`segmented-btn${audioFormat === 'm4b' ? ' is-active' : ''}`}
                      onClick={() => setAudioFormat('m4b')}
                      disabled={synthesizing}
                      aria-pressed={audioFormat === 'm4b'}
                    >
                      M4B
                    </button>
                    <button
                      type="button"
                      className={`segmented-btn${audioFormat === 'mp3' ? ' is-active' : ''}`}
                      onClick={() => setAudioFormat('mp3')}
                      disabled={synthesizing}
                      aria-pressed={audioFormat === 'mp3'}
                    >
                      MP3
                    </button>
                  </div>
                </div>
              )}
              <button className="btn btn-primary w-full" onClick={handleSynthesize} disabled={synthesizing}>
                {synthesizing ? '⏳ Synthesizing…' : '🎙 Generate Audio'}
              </button>
              {taskProgress && taskProgress.status !== 'done' && (
                <div className="mt-3">
                  <div className="flex justify-between text-xs text-secondary mb-1">
                    <span>{taskProgress.message}</span>
                    <span>{taskProgress.progress}%</span>
                  </div>
                  <div className="progress-bar">
                    <div className="progress-bar-fill" style={{ width: `${taskProgress.progress}%` }} />
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* File list */}
          <div className="section-title">Generated Files</div>
          {exports.length === 0 ? (
            <div className="text-sm text-muted">No files yet. Export an EPUB or synthesize audio first.</div>
          ) : (
            <div className="flex flex-col gap-2">
              {exports.map(f => (
                <div
                  key={f}
                  className="glass flex items-center gap-3 p-3 glass-hover"
                  style={{ borderRadius: 'var(--radius-sm)', cursor: 'pointer' }}
                  onClick={() => toggleFile(f)}
                >
                  <input
                    type="checkbox"
                    checked={selectedFiles.includes(f)}
                    onChange={() => toggleFile(f)}
                    style={{ width: 'auto', cursor: 'pointer' }}
                    onClick={e => e.stopPropagation()}
                  />
                  <span style={{ fontSize: 20 }}>{iconFor(f)}</span>
                  <span className="truncate text-sm" style={{ flex: 1 }}>{f}</span>
                  <a
                    href={downloadExportUrl(projectId, f)}
                    download={f}
                    className="btn btn-ghost btn-sm"
                    onClick={e => e.stopPropagation()}
                  >
                    ↓
                  </a>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Right: Audiobookshelf */}
        <div style={{ width: 280, flexShrink: 0 }} data-tip-anchor="abs-panel">
          <div className="section-title">Audiobookshelf Upload</div>
          <div className="glass p-4" style={{ borderRadius: 'var(--radius-sm)' }}>
            <div className="text-xs text-muted mb-3">
              Configure your server URL and token in Settings, then select files and upload.
            </div>

            <button
              className="btn btn-ghost btn-sm w-full mb-3"
              onClick={handleLoadLibraries}
              disabled={loadingLibs}
            >
              {loadingLibs ? 'Loading…' : '🔄 Load Libraries'}
            </button>

            {libraries.length > 0 && (
              <div className="field">
                <label>Target Library</label>
                <select value={selectedLib} onChange={e => setSelectedLib(e.target.value)}>
                  {libraries.map(lib => (
                    <option key={lib.id} value={lib.id}>{lib.name}</option>
                  ))}
                </select>
              </div>
            )}

            {selectedFiles.length > 0 && (
              <div className="text-xs text-secondary mb-3">
                {selectedFiles.length} file{selectedFiles.length !== 1 ? 's' : ''} selected
              </div>
            )}

            <button
              className="btn btn-primary w-full"
              onClick={handleUploadToAbs}
              disabled={uploading || selectedFiles.length === 0}
            >
              {uploading ? '⏳ Uploading…' : '☁ Upload to Audiobookshelf'}
            </button>

            {uploadLog.length > 0 && (
              <div className="mt-3 glass p-3" style={{
                borderRadius: 'var(--radius-sm)',
                fontFamily: 'var(--font-mono)', fontSize: 12,
                background: 'rgba(0,0,0,0.3)',
              }}>
                {uploadLog.map((line, i) => (
                  <div key={i} className={line.startsWith('Error') ? 'text-danger' : 'text-success'}>
                    {line}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="step-nav">
        <button className="btn btn-ghost" onClick={onBack}>← Back</button>
        <div className="badge badge-success">🎉 Project Complete</div>
      </div>
    </div>
  )
}
