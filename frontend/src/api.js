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
        if (e instanceof SyntaxError) throw new Error(text || res.statusText, { cause: e })
        throw e
      }
    }
  if (res.status === 204) return null
  return res.json()
}

// API endpoints
// Settings
export const getSettings = () => request('GET', '/settings')
export const saveSettings = (cfg) => request('PUT', '/settings', cfg)
export const getSystemInfo = () => request('GET', '/system/info')

// Key validation
export const validateGeminiKey = (api_key) => request('POST', '/validate/gemini-key', { api_key })
export const validateOpenAIKey = (api_key) => request('POST', '/validate/openai-key', { api_key })
export const validateHuggingFaceToken = (api_key) => request('POST', '/validate/huggingface-token', { api_key })

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

export const parsePdf = (projectId, cleaner = 'regex', modules = [], cleaningProfile = 'safe') => {
  const moduleParams = modules.map(m => `&modules=${encodeURIComponent(m)}`).join('')
  return request('POST', `/projects/${projectId}/parse?cleaner=${cleaner}&cleaning_profile=${encodeURIComponent(cleaningProfile)}${moduleParams}`)
}

export const getParsingModules = () => request('GET', '/parsing-modules')
export const getCleaningProfiles = () => request('GET', '/cleaning-profiles')

export const cancelTask = (projectId) => request('POST', `/projects/${projectId}/cancel`)

// Chapters
export const getChapters = (id) => request('GET', `/projects/${id}/chapters`)
export const saveChapters = (id, chapters) => request('PUT', `/projects/${id}/chapters`, chapters)
export const getDebugChapters = (id) => request('GET', `/projects/${id}/debug-chapters`)
export const getDebugPrompt = (id) => request('GET', `/projects/${id}/debug-prompt`)
export const getCleaningEval = (id) => request('GET', `/projects/${id}/cleaning-eval`)
export const saveCleaningEval = (id, evaluation) => request('PUT', `/projects/${id}/cleaning-eval`, evaluation)
export const redoCleaningChunk = (id, chapterIndex, chunkId, cleaningProfile = 'balanced', provider = null) =>
  request('POST', `/projects/${id}/chapters/${chapterIndex}/chunks/${chunkId}/redo-cleaning`, { cleaning_profile: cleaningProfile, provider })
export const applyCleaningVariant = (id, chapterIndex, chunkId, variantId, applyToChapterText = false) =>
  request('POST', `/projects/${id}/chapters/${chapterIndex}/chunks/${chunkId}/apply-variant`, { variant_id: variantId, apply_to_chapter_text: applyToChapterText })
export const batchRedoCleaning = (id, chunks, cleaningProfile = 'balanced', provider = null) =>
  request('POST', `/projects/${id}/batch-redo-cleaning`, { chunks, cleaning_profile: cleaningProfile, provider })
export const getCleaningReport = (id) => request('GET', `/projects/${id}/cleaning-report`)

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
export const ttsDebugText = (projectId, text, engine, voice, speed) =>
  request('POST', `/projects/${projectId}/tts/debug-text`, { text, engine, voice, speed })
export const synthesizeBook = (projectId, engine, voice, speed, singleFile = false, audioFormat = 'm4b', readHeadings = true) =>
  request('POST', `/projects/${projectId}/tts/synthesize?engine=${encodeURIComponent(engine)}&voice=${encodeURIComponent(voice)}&speed=${speed}&single_file=${singleFile}&audio_format=${encodeURIComponent(audioFormat)}&read_headings=${readHeadings}`)

// Voice library
export const listLibraryVoices = () => request('GET', '/voice-library')
export const createLibraryVoice = ({ name, notes, speed, temperature, file }) => {
  const fd = new FormData()
  fd.append('name', name)
  fd.append('notes', notes || '')
  fd.append('speed', speed ?? 1.0)
  fd.append('temperature', temperature ?? 0.7)
  fd.append('file', file)
  return request('POST', '/voice-library', fd, true)
}
export const updateLibraryVoice = (id, updates) => request('PATCH', `/voice-library/${encodeURIComponent(id)}`, updates)
export const deleteLibraryVoice = (id) => request('DELETE', `/voice-library/${encodeURIComponent(id)}`)
export const testDraftLibraryVoice = ({ text, speed, temperature, file }) => {
  const fd = new FormData()
  fd.append('text', text)
  fd.append('speed', speed ?? 1.0)
  fd.append('temperature', temperature ?? 0.7)
  fd.append('file', file)
  return fetch(`${BASE}/voice-library/test-draft`, {
    method: 'POST',
    body: fd,
  })
}
export const testLibraryVoice = (id, text) =>
  fetch(`${BASE}/voice-library/${encodeURIComponent(id)}/test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })

// Voice samples
export const uploadVoiceSample = (projectId, file) => {
  const fd = new FormData()
  fd.append('file', file)
  return request('POST', `/projects/${projectId}/voices/upload`, fd, true)
}
export const listVoiceSamples = (projectId) => request('GET', `/projects/${projectId}/voices`)
export const deleteVoiceSample = (projectId, filename) =>
  request('DELETE', `/projects/${projectId}/voices/${encodeURIComponent(filename)}`)

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
        if (t.status === 'cancelled') {
          clearInterval(iv)
          const err = new Error(t.message || 'Processing cancelled.')
          err.cancelled = true
          reject(err)
        }
        if (t.status === 'error') { clearInterval(iv); reject(new Error(t.message)) }
      } catch (e) { clearInterval(iv); reject(e) }
    }, intervalMs)
  })
}
