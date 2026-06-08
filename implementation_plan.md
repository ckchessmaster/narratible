# Echo-Scribe Implementation Plan

Echo-Scribe is an end-to-end PDF-to-Ebook/Audiobook creation tool. It parses a PDF, cleans up the text (handling footnotes, margins, and parsing artifacts), organizes the text into chapters with an interactive editor, generates natural-sounding audiobook files (MP3) using local/cloud TTS engines (with a focus on Kokoro and Edge-TTS). Finally, it compiles the book into EPUB, and uploads the results to Audiobookshelf.

## User Review Required

> [!IMPORTANT]
> **Dependencies & Heavy Libraries**
> - **Kokoro-82M / PyTorch / CUDA**: Since you have an RTX 3060ti / RTX 4060 GPU, we will design the TTS module to run Kokoro locally with PyTorch CUDA acceleration. This requires installing PyTorch with CUDA support. We will provide a script/instructions for installing these dependencies in your environment.
> - **Voice Cloning (XTTS-v2)**: Local voice cloning requires the `TTS` package (XTTS-v2) which leverages PyTorch and CUDA. It will be an optional module that you can enable to avoid slow CPU inference.
> - **LLM-based Cleanup**: To clean up complex PDFs (e.g., margins, footer notes), we will support the Gemini API and OpenAI API. You will need to provide your API key in the app settings, but we will also provide a free, local regex-based fallback.

> [!NOTE]
> **Audiobookshelf Upload**
> - The application will require an Audiobookshelf API token and server URL to execute uploads. These settings will be persisted locally in `config.json` inside the project.

---

## Proposed Changes

We will organize the project into two main directories: `backend` (FastAPI) and `frontend` (React + Vite).

```
echo-scribe/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py            # FastAPI entry point
│   │   ├── config.py          # App settings (JSON based)
│   │   ├── projects.py        # Project CRUD and file structure management
│   │   ├── parser.py          # PDF text and image extractor (PyMuPDF)
│   │   ├── cleaner.py         # Text cleanup engine (LLM / Regex)
│   │   ├── tts.py             # TTS manager (Kokoro, Edge-TTS, Piper)
│   │   ├── epub.py            # EPUB ebook generator
│   │   └── uploader.py        # Audiobookshelf uploader
│   ├── requirements.txt       # Python backend dependencies
│   └── run.py                 # Backend launch helper
└── frontend/
    # React + Vite application (Vanilla CSS styling)
```

### Backend (Python FastAPI)

The backend manages project storage, handles long-running parsing and speech synthesis tasks, and serves as an API for the React frontend.

#### [NEW] [requirements.txt](file:///c:/projects/echo-scribe/backend/requirements.txt)
Define dependencies:
- FastAPI, Uvicorn (web framework & server)
- PyMuPDF (fitz), pdfplumber (PDF parsing)
- edge-tts (free natural TTS)
- kokoro (local fast TTS), soundfile, numpy (audio processing)
- TTS (optional local voice cloning library, i.e., XTTS-v2)
- requests (for API communication with Audiobookshelf)
- google-generativeai, openai (for optional LLM cleaning/ElevenLabs voice cloning API)
- pydantic (data validation)

#### [NEW] [main.py](file:///c:/projects/echo-scribe/backend/app/main.py)
- Establish FastAPI endpoints for:
  - Settings: Get and update global configuration.
  - Projects: Create, list, retrieve, and delete projects.
  - Parsing: Trigger PDF extraction (asynchronous task).
  - Cleaning: Trigger text cleanup (asynchronous task).
  - TTS: Generate voice previews and synthesize the entire book/chapters (asynchronous tasks).
  - Export: Compile EPUB and MP3 files.
  - Upload: Send generated book to Audiobookshelf.

#### [NEW] [config.py](file:///c:/projects/echo-scribe/backend/app/config.py)
- Global settings manager. Saves configuration to a central `config.json` file in the user's home or project root directory.
- Configurable settings: Gemini API key, OpenAI API key, Audiobookshelf URL/Token, default TTS engine, and Kokoro parameters.

#### [NEW] [projects.py](file:///c:/projects/echo-scribe/backend/app/projects.py)
- Manage local project directories under a local `projects/` directory.
- Folder structure per project:
  ```
  projects/<project_id>/
  ├── metadata.json           # Title, Author, Cover image path, TTS settings
  ├── book.pdf                # Original uploaded PDF
  ├── raw_text.txt            # Raw text extracted from PDF
  ├── cleaned_text.txt        # Cleaned text
  ├── chapters.json           # Array of chapter objects: [{title, text, audio_path}]
  ├── voices/                 # Uploaded voice samples (.wav) for local cloning
  └── exports/                # Generated output EPUB and MP3 files
  ```

#### [NEW] [parser.py](file:///c:/projects/echo-scribe/backend/app/parser.py)
- Extracts text and images from PDF using PyMuPDF (fitz) or pdfplumber.
- Emits progress events for the client.

#### [NEW] [cleaner.py](file:///c:/projects/echo-scribe/backend/app/cleaner.py)
- Regex Cleaner: Removes standard PDF header/footer page numbers, merges hyphenated line-endings.
- LLM Cleaner: Sends text chunks to Gemini/OpenAI to rebuild structure, merge paragraphs, move footnotes to end of chapters, and correct OCR errors.

#### [NEW] [tts.py](file:///c:/projects/echo-scribe/backend/app/tts.py)
- Edge-TTS: Runs asynchronous downloads of Microsoft's read-aloud voices.
- Kokoro-82M: Checks if model weights are present locally, downloads them if missing, and runs inference. Integrates PyTorch and CUDA.
- XTTS-v2: Runs local voice cloning with reference `.wav` files uploaded to the project. Utilizes GPU execution.
- ElevenLabs: Connects to ElevenLabs Instant/Professional voice cloning using your API Key and voice IDs.
- Integrates audio stitching to merge chapter sections into single MP3 audio files.

#### [NEW] [epub.py](file:///c:/projects/echo-scribe/backend/app/epub.py)
- Creates valid EPUB files including NCX, OPF, HTML documents, and cover images from the chapter text and metadata JSON.

#### [NEW] [uploader.py](file:///c:/projects/echo-scribe/backend/app/uploader.py)
- Uploads the generated EPUB and MP3 files to Audiobookshelf using API endpoints.

---

### Frontend (React + Vite + Vanilla CSS)

A wizard-driven user interface styled with a modern, glassmorphic dark theme (indigo/violet accents).

#### [NEW] [index.css](file:///c:/projects/echo-scribe/frontend/src/index.css)
- CSS custom properties (variables) for dark mode colors, fonts, spacing, glassmorphic borders, and animations.
- Scrollbar, buttons, input fields, and layout utilities.

#### [NEW] [App.jsx](file:///c:/projects/echo-scribe/frontend/src/App.jsx)
- Top navigation and Wizard container.
- Manages state for:
  - Current active step (1 to 4)
  - Current active project ID
  - Settings drawer/modal status

#### [NEW] [Step1Upload.jsx](file:///c:/projects/echo-scribe/frontend/src/components/Step1Upload.jsx)
- File drop zone for PDFs.
- Selectable parsing and cleaning options (Heuristic/Regex vs. LLM API).
- Dynamic progress bar showing text extraction status.

#### [NEW] [Step2Editor.jsx](file:///c:/projects/echo-scribe/frontend/src/components/Step2Editor.jsx)
- Side-by-side layout:
  - **Left**: Chapter List (drag-and-drop ordering, rename, add, delete, split/merge tools).
  - **Right**: Markdown or rich text editor for editing chapter contents.
  - **Toolbar**: "Split here" button to divide a chapter at the cursor position.
- Book Metadata inputs: Title, Author, Cover Image picker.

#### [NEW] [Step3TTS.jsx](file:///c:/projects/echo-scribe/frontend/src/components/Step3TTS.jsx)
- Voice configuration panel: engine selection (Kokoro, Edge-TTS, XTTS-v2, ElevenLabs), voice list, speed slider.
- Custom Voice Upload widget: Dropzone to upload `.wav` voice samples for XTTS cloning, and interface to manage cloned voices.
- Audio Preview widget: click to hear a quick 1-sentence synthesis.
- Synthesis queue: displays progress bars for each chapter as they are generated.

#### [NEW] [Step4Export.jsx](file:///c:/projects/echo-scribe/frontend/src/components/Step4Export.jsx)
- Output cards for downloading:
  - EPUB File
  - Audiobook MP3
- Audiobookshelf Upload panel: Trigger upload to server with visual confirmation and status logs.

---

## Verification Plan

### Automated Tests
- We will write Python unit tests in `backend/tests/` to verify:
  - PDF parser text extraction correctness.
  - Regex cleanup rules.
  - EPUB packaging validity.
  - API endpoints using FastAPI's `TestClient`.

### Manual Verification
1. Run backend server (`python backend/run.py`).
2. Run Vite client (`npm run dev`).
3. Upload a sample multi-chapter PDF, verify parse and LLM cleanup.
4. Modify chapter splits in Step 2, ensuring split chapter text is correct.
5. Generate a short audio snippet using Kokoro/Edge-TTS.
6. Export EPUB and MP3, inspect EPUB using an e-reader, and listen to the MP3.
7. Attempt an upload to a local Audiobookshelf instance.
