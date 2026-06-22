const BASE = '/api'
const parsedPollIntervalMs = Number.parseInt(import.meta.env.VITE_TASK_POLL_INTERVAL_MS ?? '2000', 10)
const DEFAULT_TASK_POLL_INTERVAL_MS = Number.isFinite(parsedPollIntervalMs) && parsedPollIntervalMs > 0
  ? parsedPollIntervalMs
  : 2000

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
export const getCustomInstructionPrompts = () => request('GET', '/custom-instructions/prompts')

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

export const parsePdf = (projectId, cleaner = 'regex', modules = [], cleaningProfile = 'safe', modernizationProfile = 'standard_modern') => {
  const moduleParams = modules.map(m => `&modules=${encodeURIComponent(m)}`).join('')
  return request('POST', `/projects/${projectId}/parse?cleaner=${cleaner}&cleaning_profile=${encodeURIComponent(cleaningProfile)}&modernization_profile=${encodeURIComponent(modernizationProfile)}${moduleParams}`)
}

export const getParsingModules = () => request('GET', '/parsing-modules')
export const getCleaningProfiles = () => request('GET', '/cleaning-profiles')
export const getModernizationProfiles = () => request('GET', '/modernization-profiles')

export const cancelTask = (projectId) => request('POST', `/projects/${projectId}/cancel`)

// Chapters
export const getChapters = (id) => request('GET', `/projects/${id}/chapters`)
export const saveChapters = (id, chapters) => request('PUT', `/projects/${id}/chapters`, chapters)
export const updateChapter = (projectId, chapterId, updates) =>
  request('PATCH', `/projects/${projectId}/chapters/${encodeURIComponent(chapterId)}`, updates)
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
export const getModernizationEval = (id) => request('GET', `/projects/${id}/modernization-eval`)
export const saveModernizationEval = (id, evaluation) => request('PUT', `/projects/${id}/modernization-eval`, evaluation)
export const modernizeChapter = (id, chapterIndex, modernizationProfile = 'standard_modern', provider = null) =>
  request('POST', `/projects/${id}/chapters/${chapterIndex}/modernize`, { modernization_profile: modernizationProfile, provider })
export const modernizeProject = (id, modernizationProfile = 'standard_modern', provider = null) =>
  request('POST', `/projects/${id}/modernize`, { modernization_profile: modernizationProfile, provider })
export const redoModernizationChunk = (id, chapterIndex, chunkId, modernizationProfile = 'standard_modern', provider = null, redoMode = 'try_again', instruction = null) =>
  request('POST', `/projects/${id}/chapters/${chapterIndex}/modernization-chunks/${chunkId}/redo`, { modernization_profile: modernizationProfile, provider, redo_mode: redoMode, instruction })
export const applyModernizationVariant = (id, chapterIndex, chunkId, variantId, applyToChapterText = false) =>
  request('POST', `/projects/${id}/chapters/${chapterIndex}/modernization-chunks/${chunkId}/apply-variant`, { variant_id: variantId, apply_to_chapter_text: applyToChapterText })
export const selectModernizationVariant = (id, chapterIndex, chunkId, variantId) =>
  request('POST', `/projects/${id}/chapters/${chapterIndex}/modernization-chunks/${chunkId}/select-variant`, { variant_id: variantId })
export const skipModernizationChunk = (id, chapterIndex, chunkId) =>
  request('POST', `/projects/${id}/chapters/${chapterIndex}/modernization-chunks/${chunkId}/skip`)
export const clearModernizationSelection = (id, chapterIndex, chunkId) =>
  request('POST', `/projects/${id}/chapters/${chapterIndex}/modernization-chunks/${chunkId}/clear-selection`)
export const commitModernizationSession = (id, chapterIndex) =>
  request('POST', `/projects/${id}/chapters/${chapterIndex}/modernization/commit`)
export const undoLastModernizationCommit = (id, chapterIndex) =>
  request('POST', `/projects/${id}/chapters/${chapterIndex}/modernization/undo-last-commit`)
export const discardModernizationSession = (id, chapterIndex) =>
  request('POST', `/projects/${id}/chapters/${chapterIndex}/modernization/discard`)

// Cover
export const uploadCover = (projectId, file) => {
  const fd = new FormData()
  fd.append('file', file)
  return request('POST', `/projects/${projectId}/upload-cover`, fd, true)
}
export const coverImageUrl = (projectId, coverImage) =>
  `${BASE}/projects/${encodeURIComponent(projectId)}/cover?v=${encodeURIComponent(coverImage || '')}`

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
export const synthesizeBook = (projectId, engine, voice, speed, singleFile = false, audioFormat = 'm4b', readHeadings = true, force = false) =>
  request('POST', `/projects/${projectId}/tts/synthesize?engine=${encodeURIComponent(engine)}&voice=${encodeURIComponent(voice)}&speed=${speed}&single_file=${singleFile}&audio_format=${encodeURIComponent(audioFormat)}&read_headings=${readHeadings}&force=${force}`)
export const synthesizeChapter = (projectId, chapterId, force = false) =>
  request('POST', `/projects/${projectId}/chapters/${encodeURIComponent(chapterId)}/tts?force=${force}`)
export const chapterAudioUrl = (projectId, chapterId) =>
  `${BASE}/projects/${projectId}/chapters/${encodeURIComponent(chapterId)}/audio`

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
export const addLibraryVoiceSample = (id, file, activate = true) => {
  const fd = new FormData()
  fd.append('activate', activate)
  fd.append('file', file)
  return request('POST', `/voice-library/${encodeURIComponent(id)}/samples`, fd, true)
}
export const setLibraryVoiceSample = (id, sampleFilename) =>
  request('POST', `/voice-library/${encodeURIComponent(id)}/samples/active`, { sample_filename: sampleFilename })
export const deleteLibraryVoiceSample = (id, sampleFilename) =>
  request('DELETE', `/voice-library/${encodeURIComponent(id)}/samples/${encodeURIComponent(sampleFilename)}`)
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
export const testLibraryVoice = (id, text, options = {}) =>
  fetch(`${BASE}/voice-library/${encodeURIComponent(id)}/test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, ...options }),
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
export const exportEpub = (projectId, includeNotes = false) =>
  fetch(`${BASE}/projects/${projectId}/export/epub?include_notes=${includeNotes}`, { method: 'POST' })
export const listExports = (projectId) => request('GET', `/projects/${projectId}/exports`)
export const deleteExport = (projectId, filename) =>
  request('DELETE', `/projects/${projectId}/exports/${encodeURIComponent(filename)}`)
export const downloadExportUrl = (projectId, filename) =>
  `${BASE}/projects/${projectId}/exports/${encodeURIComponent(filename)}`

// Audiobookshelf
export const getAbsLibraries = () => request('GET', '/audiobookshelf/libraries')
export const uploadToAbs = (projectId, libraryId, files) =>
  request('POST', `/projects/${projectId}/upload-to-abs`, { library_id: libraryId, files })

// Task polling
export const getTask = (taskId) => request('GET', `/tasks/${taskId}`)
export const submitTaskDecision = (taskId, action) =>
  request('POST', `/tasks/${encodeURIComponent(taskId)}/decision`, { action })
export async function pollTask(taskId, onProgress, intervalMs = DEFAULT_TASK_POLL_INTERVAL_MS) {
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
