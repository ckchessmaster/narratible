const BASE = '/api'

async function request(method, path, body, isFormData = false) {
  const opts = { method, headers: {} }
  if (body) {
    if (isFormData) {
      opts.body = body
    } else {
      opts.headers['Content-Type'] = 'application/json'
      opts.body = JSON.stringify(body)
    }
  }
  const res = await fetch(`${BASE}${path}`, opts)
  if (!res.ok) {
      const text = await res.text()
      try {
        const j = JSON.parse(text)
        throw new Error(j.detail || j.message || res.statusText)
      } catch (e) {
        if (e instanceof SyntaxError) throw new Error(text || res.statusText)
        throw e
      }
    }
  if (res.status === 204) return null
  return res.json()
}

// API endpoints
export const getSystemDiagnostics = () => request('GET', '/system/diagnostics')

// Settings
export const getSettings = () => request('GET', '/settings')
export const saveSettings = (cfg) => request('PUT', '/settings', cfg)
export const getLlmModels = () => request('GET', '/llm/models')

// Projects
export const listProjects = () => request('GET', '/projects')
export const createProject = (title, author) => request('POST', '/projects', { title, author })
export const getProject = (id) => request('GET', `/projects/${id}`)
export const updateProject = (id, updates) => request('PATCH', `/projects/${id}`, updates)
export const deleteProject = (id) => request('DELETE', `/projects/${id}`)

// PDF
export const uploadPdf = (projectId, file) => {
  const fd = new FormData()
  fd.append('file', file)
  return request('POST', `/projects/${projectId}/upload-pdf`, fd, true)
}

export const parsePdf = (projectId, cleaner = 'regex') =>
  request('POST', `/projects/${projectId}/parse?cleaner=${cleaner}`)

export const cancelTask = (projectId) => request('POST', `/projects/${projectId}/cancel`)

// Chapters
export const getChapters = (id) => request('GET', `/projects/${id}/chapters`)
export const saveChapters = (id, chapters) => request('PUT', `/projects/${id}/chapters`, chapters)

// Cover
export const uploadCover = (projectId, file) => {
  const fd = new FormData()
  fd.append('file', file)
  return request('POST', `/projects/${projectId}/upload-cover`, fd, true)
}

// TTS
export const getVoices = (engine = 'edge-tts') => request('GET', `/tts/voices?engine=${engine}`)
export const ttsPreview = (projectId, text, engine, voice, speed) =>
  fetch(`${BASE}/projects/${projectId}/tts/preview`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, engine, voice, speed }),
  })
export const synthesizeBook = (projectId, engine, voice, speed, singleFile = false) =>
  request('POST', `/projects/${projectId}/tts/synthesize?engine=${engine}&voice=${voice}&speed=${speed}&single_file=${singleFile}`)

// Voice samples
export const uploadVoiceSample = (projectId, file) => {
  const fd = new FormData()
  fd.append('file', file)
  return request('POST', `/projects/${projectId}/voices/upload`, fd, true)
}
export const listVoiceSamples = (projectId) => request('GET', `/projects/${projectId}/voices`)

// Exports
export const exportEpub = (projectId) =>
  fetch(`${BASE}/projects/${projectId}/export/epub`, { method: 'POST' })
export const listExports = (projectId) => request('GET', `/projects/${projectId}/exports`)
export const downloadExportUrl = (projectId, filename) =>
  `${BASE}/projects/${projectId}/exports/${encodeURIComponent(filename)}`

// Audiobookshelf
export const getAbsLibraries = () => request('GET', '/audiobookshelf/libraries')
export const uploadToAbs = (projectId, libraryId, files) =>
  request('POST', `/projects/${projectId}/upload-to-abs`, { library_id: libraryId, files })

// Task polling
export const getTask = (taskId) => request('GET', `/tasks/${taskId}`)
export async function pollTask(taskId, onProgress, intervalMs = 1000) {
  return new Promise((resolve, reject) => {
    const iv = setInterval(async () => {
      try {
        const t = await getTask(taskId)
        onProgress(t)
        if (t.status === 'done') { clearInterval(iv); resolve(t) }
        if (t.status === 'error') { clearInterval(iv); reject(new Error(t.message)) }
      } catch (e) { clearInterval(iv); reject(e) }
    }, intervalMs)
  })
}
