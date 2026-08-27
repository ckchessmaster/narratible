import { useDeferredValue, useEffect, useRef, useState } from 'react'
import {
  Copy,
  Download,
  FolderOpen,
  Pause,
  Play,
  Power,
  RefreshCw,
  X,
} from 'lucide-react'
import {
  getDesktopLogs,
  openDesktopLogFolder,
  quitDesktopApp,
  watchDesktopLogs,
} from '../api'

const MAX_BUFFERED_LINES = 1000

function logLevelClass(line) {
  const match = line.match(/\b(CRITICAL|ERROR|WARNING|INFO|DEBUG)\b/i)
  return match ? `diagnostics-line-${match[1].toLowerCase()}` : ''
}

export default function DiagnosticsModal({ onClose, toast }) {
  const [lines, setLines] = useState([])
  const [logFile, setLogFile] = useState('')
  const [level, setLevel] = useState('')
  const [search, setSearch] = useState('')
  const [live, setLive] = useState(true)
  const [loading, setLoading] = useState(true)
  const [disconnected, setDisconnected] = useState(false)
  const [error, setError] = useState('')
  const [refreshKey, setRefreshKey] = useState(0)
  const [watchGeneration, setWatchGeneration] = useState(0)
  const [quitting, setQuitting] = useState(false)
  const deferredSearch = useDeferredValue(search.trim())
  const cursorRef = useRef(0)
  const outputRef = useRef(null)

  useEffect(() => {
    const controller = new AbortController()

    getDesktopLogs({
      lines: 200,
      level: level || undefined,
      contains: deferredSearch || undefined,
      signal: controller.signal,
    }).then(result => {
      setLines(result.lines ?? [])
      setLogFile(result.log_file ?? '')
      cursorRef.current = result.next_offset ?? 0
      setError('')
      setDisconnected(false)
      setWatchGeneration(value => value + 1)
    }).catch(fetchError => {
      if (fetchError.name !== 'AbortError') setError(fetchError.message || 'Unable to load logs.')
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false)
    })

    return () => controller.abort()
  }, [level, deferredSearch, refreshKey])

  useEffect(() => {
    if (!live || loading) return undefined
    const controller = new AbortController()
    let cancelled = false

    async function followLogs() {
      while (!cancelled) {
        try {
          const result = await watchDesktopLogs({
            startOffset: cursorRef.current,
            seconds: 10,
            maxLines: 200,
            level: level || undefined,
            contains: deferredSearch || undefined,
            signal: controller.signal,
          })
          cursorRef.current = result.next_offset ?? cursorRef.current
          if (result.lines?.length) {
            setLines(current => [...current, ...result.lines].slice(-MAX_BUFFERED_LINES))
          }
          setDisconnected(false)
        } catch (watchError) {
          if (watchError.name !== 'AbortError') {
            setDisconnected(true)
            setError(watchError.message || 'Live log connection was interrupted.')
          }
          break
        }
      }
    }

    followLogs()
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [live, loading, watchGeneration, level, deferredSearch])

  useEffect(() => {
    if (live && outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight
    }
  }, [lines, live])

  const visibleText = lines.join('\n')

  const copyLogs = async () => {
    try {
      await navigator.clipboard.writeText(visibleText)
      toast('Visible logs copied.', 'success')
    } catch (copyError) {
      toast(copyError.message || 'Could not copy logs.', 'error')
    }
  }

  const downloadLogs = () => {
    const blob = new Blob([visibleText], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = 'narratible-logs.txt'
    link.click()
    URL.revokeObjectURL(url)
  }

  const quitApp = async () => {
    if (!window.confirm('Quit narratible? Any processing currently in progress will stop.')) return
    setQuitting(true)
    try {
      await quitDesktopApp()
    } catch (quitError) {
      setQuitting(false)
      toast(quitError.message || 'Could not quit narratible.', 'error')
    }
  }

  return (
    <div className="modal-overlay" onClick={event => event.target === event.currentTarget && onClose()}>
      <div className="modal diagnostics-modal" role="dialog" aria-modal="true" aria-labelledby="diagnostics-title">
        <div className="modal-header diagnostics-header">
          <div>
            <div className="modal-title" id="diagnostics-title">Diagnostics</div>
            <div className="diagnostics-path" title={logFile}>{logFile || 'narratible.log'}</div>
          </div>
          <button type="button" className="btn btn-ghost btn-icon" title="Close diagnostics" onClick={onClose}>
            <X size={18} aria-hidden="true" />
          </button>
        </div>

        <div className="diagnostics-toolbar">
          <select value={level} onChange={event => { setLoading(true); setLevel(event.target.value) }} aria-label="Filter logs by level">
            <option value="">All levels</option>
            <option value="info">Info</option>
            <option value="warning">Warning</option>
            <option value="error">Error</option>
            <option value="critical">Critical</option>
          </select>
          <input
            type="search"
            value={search}
            onChange={event => setSearch(event.target.value)}
            placeholder="Filter log text"
            aria-label="Filter log text"
          />
          <button type="button" className={`btn btn-sm ${live ? 'btn-primary' : 'btn-ghost'}`} onClick={() => setLive(value => !value)}>
            {live ? <Pause size={15} aria-hidden="true" /> : <Play size={15} aria-hidden="true" />}
            {live ? 'Pause' : 'Live'}
          </button>
          <button type="button" className="btn btn-ghost btn-icon" title="Refresh logs" onClick={() => { setLoading(true); setRefreshKey(value => value + 1) }}>
            <RefreshCw size={17} aria-hidden="true" />
          </button>
        </div>

        <div className="diagnostics-status">
          <span>{loading ? 'Loading logs...' : `${lines.length} visible line${lines.length === 1 ? '' : 's'}`}</span>
          <span className={disconnected ? 'diagnostics-disconnected' : 'diagnostics-connected'}>
            {live ? (disconnected ? 'Disconnected' : 'Live') : 'Paused'}
          </span>
        </div>

        <div className="diagnostics-output" ref={outputRef} aria-label="Application logs" tabIndex="0">
          {!loading && lines.length === 0 ? (
            <div className="diagnostics-empty">No log lines match the current filters.</div>
          ) : lines.map((line, index) => (
            <div className={`diagnostics-line ${logLevelClass(line)}`} key={`${index}-${line}`}>{line}</div>
          ))}
        </div>

        {error && <div className="diagnostics-error">{error}</div>}

        <div className="diagnostics-actions">
          <div className="diagnostics-actions-group">
            <button type="button" className="btn btn-ghost btn-sm" disabled={!lines.length} onClick={copyLogs}>
              <Copy size={15} aria-hidden="true" /> Copy
            </button>
            <button type="button" className="btn btn-ghost btn-sm" disabled={!lines.length} onClick={downloadLogs}>
              <Download size={15} aria-hidden="true" /> Download
            </button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => openDesktopLogFolder().catch(folderError => toast(folderError.message, 'error'))}>
              <FolderOpen size={15} aria-hidden="true" /> Open Folder
            </button>
          </div>
          <button type="button" className="btn btn-danger btn-sm" disabled={quitting} onClick={quitApp}>
            <Power size={15} aria-hidden="true" /> {quitting ? 'Quitting...' : 'Quit narratible'}
          </button>
        </div>
      </div>
    </div>
  )
}