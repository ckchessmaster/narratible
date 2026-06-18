// First-time-user coach-mark tips: definitions + localStorage persistence.
//
// Each tip is anchored to a DOM element carrying a matching
// `data-tip-anchor="<anchor>"` attribute. Tips are shown one at a time
// (chained) per context, can be dismissed individually, or globally
// disabled via the "Don't show tips" checkbox. State persists in
// localStorage so dismissed tips never reappear until progress is reset.
//
// NOTE FOR FUTURE FRONTEND WORK: when you add or change a user-facing
// control or wizard step, evaluate whether it needs a tip here and add a
// matching `data-tip-anchor` to the element. See the "First-Time Tips"
// section in .github/instructions/frontend.instructions.md.

const DISMISSED_KEY = 'narratible.tips.dismissed'
const DISABLED_KEY = 'narratible.tips.disabled'

export const TIPS = [
  // ── Wizard · Step 1 (Upload) ──────────────────────────────────────────
  {
    id: 'w1-settings', context: 'wizard', step: 1, anchor: 'settings-button', placement: 'bottom',
    title: 'Start in Settings',
    body: 'First time here? Open Settings to add a Gemini or OpenAI key (or set up Local AI) before you begin.',
  },
  {
    id: 'w1-resume-projects', context: 'wizard', step: 1, anchor: 'resume-projects', placement: 'bottom',
    title: 'Resume saved work',
    body: 'Saved projects appear here so you can continue without re-running completed parsing, cleanup, or audio steps.',
  },
  {
    id: 'w1-resume-search', context: 'wizard', step: 1, anchor: 'resume-search', placement: 'bottom',
    title: 'Find a project quickly',
    body: 'Search by title or author to filter the list when you have many saved projects.',
  },
  {
    id: 'w1-resume-delete', context: 'wizard', step: 1, anchor: 'resume-delete', placement: 'bottom',
    title: 'Remove old projects',
    body: 'Use Delete on a project card to permanently remove it and all generated files for that project.',
  },
  {
    id: 'w1-meta', context: 'wizard', step: 1, anchor: 'upload-meta', placement: 'bottom',
    title: 'Book details',
    body: 'Enter your book’s title (required) and author — these are written into the EPUB metadata.',
  },
  {
    id: 'w1-cleanup', context: 'wizard', step: 1, anchor: 'cleanup-method', placement: 'top',
    title: 'Text cleanup method',
    body: 'Heuristic is fast and offline. LLM gives the best quality (needs a key). Embedded runs locally on your GPU.',
  },
  {
    id: 'w1-cleanup-profile', context: 'wizard', step: 1, anchor: 'cleanup-profile', placement: 'top',
    title: 'Choose cleanup strictness',
    body: 'Conservative preserves text most strictly. Balanced repairs more OCR damage. Restorative is best for chunks you plan to review.',
  },
  {
    id: 'w1-parsing-modules', context: 'wizard', step: 1, anchor: 'parsing-modules', placement: 'top',
    title: 'Reading enhancements',
    body: 'Optional add-ons that rewrite text so it reads correctly. The Bible expander turns references like “Ps 1:4” into “Psalms 1:4”.',
  },
  {
    id: 'w1-parse', context: 'wizard', step: 1, anchor: 'parse-button', placement: 'top',
    title: 'Parse your PDF',
    body: 'Drop a PDF above, then click Parse to extract and clean the text.',
  },

  // ── Wizard · Step 2 (Edit) ────────────────────────────────────────────
  {
    id: 'w2-chapters', context: 'wizard', step: 2, anchor: 'chapter-list', placement: 'right',
    title: 'Review chapters',
    body: 'Select, reorder (▲▼), or delete (✕) chapters here. ⚠️ flags possible boundary issues to double-check.',
  },
  {
    id: 'w2-split', context: 'wizard', step: 2, anchor: 'split-button', placement: 'bottom',
    title: 'Split a chapter',
    body: 'Place your cursor in the text where a new chapter should start, then click Split Here.',
  },
  {
    id: 'w2-meta', context: 'wizard', step: 2, anchor: 'metadata-sidebar', placement: 'left',
    title: 'Metadata & cover',
    body: 'Set the title/author and upload a cover image. Your edits auto-save when you click Continue.',
  },
  {
    id: 'w2-cleaning-review', context: 'wizard', step: 2, anchor: 'cleaning-review', placement: 'left',
    title: 'Review cleanup warnings',
    body: 'Warnings show the chapter and nearby text to check. Advanced cleanup tools keep retry and comparison details nearby.',
  },

  // ── Wizard · Step 3 (Voice) ───────────────────────────────────────────
  {
    id: 'w3-engine', context: 'wizard', step: 3, anchor: 'engine-select', placement: 'bottom',
    title: 'Pick an engine',
    body: 'Edge-TTS is free and online. Kokoro and Voice Library generation run locally on a GPU.',
  },
  {
    id: 'w3-voice', context: 'wizard', step: 3, anchor: 'voice-speed', placement: 'top',
    title: 'Voice & speed',
    body: 'Choose a voice and adjust the narration speed to taste. Voice Library selections come from saved reusable voices.',
  },
  {
    id: 'w3-library-select', context: 'wizard', step: 3, anchor: 'voice-library-select', placement: 'top',
    title: 'Saved voices',
    body: 'Pick a saved library voice here. Create and test new voices from the Manage button or the header.',
  },
  {
    id: 'w3-read-headings', context: 'wizard', step: 3, anchor: 'read-headings', placement: 'top',
    title: 'Read chapter headings',
    body: 'When on, each chapter’s title is spoken before its content. Turn it off if your text already includes the headings.',
  },
  {
    id: 'w3-preview', context: 'wizard', step: 3, anchor: 'preview-section', placement: 'top',
    title: 'Preview before you commit',
    body: 'Generate a quick sample to hear the selected voice before using it for every chapter.',
  },

  // ── Voice Library ─────────────────────────────────────────────────────
  {
    id: 'vl-create', context: 'voice-library', anchor: 'voice-library-create', placement: 'right',
    title: 'Create once',
    body: 'Save a clean reference clip here so the voice can be reused across future projects. Speed and temperature are saved with the voice.',
  },
  {
    id: 'vl-test', context: 'voice-library', anchor: 'voice-library-test', placement: 'left',
    title: 'Test in isolation',
    body: 'Use short sample text to tune and compare voices before selecting one in the TTS step.',
  },
  {
    id: 'vl-list', context: 'voice-library', anchor: 'voice-library-list', placement: 'top',
    title: 'Manage saved voices',
    body: 'Pick a saved voice from this list, or start a new one. The main panel always edits the current voice.',
  },

  // ── Wizard · Step 4 (Export) ──────────────────────────────────────────
  {
    id: 'w4-epub', context: 'wizard', step: 4, anchor: 'export-epub', placement: 'bottom',
    title: 'Export an EPUB',
    body: 'Generate a complete EPUB 3 with all chapters, metadata, and cover.',
  },
  {
    id: 'w4-audio', context: 'wizard', step: 4, anchor: 'generate-audio', placement: 'bottom',
    title: 'Generate the audiobook',
    body: 'Synthesize audio using the voice from Step 3. Optionally merge everything into one file (needs FFmpeg).',
  },
  {
    id: 'w4-audio-format', context: 'wizard', step: 4, anchor: 'audio-format-toggle', placement: 'top',
    title: 'M4B vs MP3',
    body: 'M4B is the audiobook standard — re-encoded to AAC, with the best player support (chapters, bookmarks, resume). MP3 is a universally compatible single track, stream-copied so it merges faster. Pick MP3 for maximum compatibility, M4B for a proper audiobook.',
  },
  {
    id: 'w4-chapter-audio', context: 'wizard', step: 4, anchor: 'chapter-audio-status', placement: 'top',
    title: 'Regenerate only changed chapters',
    body: 'Each chapter tracks whether its audio is ready, missing, failed, or stale after text or voice settings change.',
  },
  {
    id: 'w4-abs', context: 'wizard', step: 4, anchor: 'abs-panel', placement: 'left',
    title: 'Download or upload',
    body: 'Download files from the list, or upload them straight to your Audiobookshelf server (configure it in Settings → Integrations).',
  },

  // ── Settings · Cloud LLM Keys ─────────────────────────────────────────
  {
    id: 's-cloud-key', context: 'settings', tab: 'ai', anchor: 'settings-gemini', placement: 'bottom',
    title: 'Add a cloud key',
    body: 'Add a Gemini key (free tier) or OpenAI key to unlock high-quality LLM text cleanup. Keys are validated when you save.',
  },
  {
    id: 's-temperature', context: 'settings', tab: 'ai', anchor: 'settings-temperature', placement: 'top',
    title: 'Temperature',
    body: 'Lower = stricter adherence to the text; higher = more variation. Bump to 0.1–0.2 if a local model gets stuck looping.',
  },

  // ── Settings · Local AI ───────────────────────────────────────────────
  {
    id: 's-hf', context: 'settings', tab: 'local', anchor: 'settings-hf', placement: 'bottom',
    title: 'HuggingFace token',
    body: 'Add a HuggingFace token to download gated local models like Llama and Gemma. A free account is all you need.',
  },
  {
    id: 's-models', context: 'settings', tab: 'local', anchor: 'settings-models', placement: 'top',
    title: 'Pick a local model',
    body: 'Choose an embedded LLM — Gemma 4 is recommended. Enable 4-bit quantization to fit larger models on smaller GPUs.',
  },
  {
    id: 's-chunk', context: 'settings', tab: 'local', anchor: 'settings-chunk', placement: 'top',
    title: 'Chunk size',
    body: 'Larger chunks give the model more context but use more VRAM.',
  },

  // ── Settings · Integrations ───────────────────────────────────────────
  {
    id: 's-abs', context: 'settings', tab: 'integrations', anchor: 'settings-abs', placement: 'bottom',
    title: 'Audiobookshelf',
    body: 'Add your Audiobookshelf server URL and API token here to upload finished audiobooks from the Export step.',
  },

  // ── Settings · System ─────────────────────────────────────────────────
  {
    id: 's-gpu', context: 'settings', tab: 'system', anchor: 'settings-gpu', placement: 'bottom',
    title: 'Select a GPU',
    body: 'Pick a CUDA GPU to unlock local LLM cleanup, Kokoro, and F5-TTS. Without one, you can still use Edge-TTS and cloud LLMs.',
  },
  {
    id: 's-reset', context: 'settings', tab: 'system', anchor: 'settings-reset', placement: 'top',
    title: 'Replay the tips',
    body: 'Want to see this onboarding guidance again? Reset tooltip progress here any time.',
  },
]

function readDismissed() {
  try {
    const raw = localStorage.getItem(DISMISSED_KEY)
    const arr = raw ? JSON.parse(raw) : []
    return Array.isArray(arr) ? arr : []
  } catch {
    return []
  }
}

function writeDismissed(ids) {
  try {
    localStorage.setItem(DISMISSED_KEY, JSON.stringify(ids))
  } catch {
    /* localStorage unavailable — tips simply won't persist */
  }
}

export function getDismissedTips() {
  return new Set(readDismissed())
}

export function isTipsDisabled() {
  try {
    return localStorage.getItem(DISABLED_KEY) === 'true'
  } catch {
    return false
  }
}

export function dismissTip(id) {
  const ids = readDismissed()
  if (!ids.includes(id)) {
    ids.push(id)
    writeDismissed(ids)
  }
}

export function disableAllTips() {
  try {
    localStorage.setItem(DISABLED_KEY, 'true')
  } catch {
    /* ignore */
  }
}

export function resetTips() {
  try {
    localStorage.removeItem(DISMISSED_KEY)
    localStorage.removeItem(DISABLED_KEY)
  } catch {
    /* ignore */
  }
  window.dispatchEvent(new Event('tips:reset'))
}
