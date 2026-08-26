# narratible

narritable is an end-to-end PDF-to-Ebook/Audiobook creation tool. It parses a PDF, cleans up the text (handling footnotes, margins, and parsing artifacts), organizes the text into chapters with an interactive editor, generates natural-sounding audiobook files (MP3) using local/cloud TTS engines, compiles the book into EPUB, and can optionally upload the results to Audiobookshelf.

## Architecture

The project consists of two main components:
- **Backend**: A Python FastAPI server that handles file processing, text extraction, LLM cleanup, TTS synthesis, and EPUB generation.
- **Frontend**: A React + Vite web application that provides a wizard-driven user interface for uploading, editing, and exporting projects.

---

## Windows Native App Installer (.exe)

For Windows users who want to run the app natively without Docker or starting separate server/frontend processes, narratible provides a seamless standalone installer.

1. Navigate to the **Releases** tab on GitHub.
2. Download the latest `narratible_Installer.exe`.
3. Run the installer and launch narratible from your Start Menu.
   - A background server will initialize quietly, and your default web browser will open to the app natively.
   - During the installation, FFmpeg is automatically downloaded via Windows Package Manager (`winget`) so that high-quality audio merging is fully enabled without triggering GPL distribution violations in the installer.
   - The installer bundles all other core dependencies (including the PyTorch CUDA extensions offline) so you can use high-quality local TTS engines like Kokoro and F5-TTS without any extra config.

*Note: Data and configuration for packaged apps are saved in your user profile at `%APPDATA%\narratible`.*

### Build the Windows executable locally

Local native builds require Windows, Python 3.12, and Node.js 20. The build
script creates a dedicated `.venv-build` environment and installs the locked
backend, GPU voice, Chatterbox, and PyInstaller dependencies automatically.
It does not modify or depend on the development environment in `backend\.venv`.

From the repository root:

```powershell
# Prepare frontend dependencies once.
cd frontend
npm install
cd ..

# Create/update .venv-build, then build the frontend and executable.
.\build_local.ps1
```

The first run downloads the CUDA-enabled PyTorch and local voice dependencies,
so it can take several minutes and requires substantial disk space. Later runs
reuse `.venv-build` and only synchronize it when a dependency file changes.

The executable and its bundled files are written to
`dist\narratible\narratible.exe`. Run it from that directory so its bundled
runtime files remain available.

Use `-SkipFrontend` to reuse an existing `frontend\dist` build:

```powershell
.\build_local.ps1 -SkipFrontend
```

Prepare or verify the build environment without compiling the application:

```powershell
.\build_local.ps1 -SetupOnly
```

If the environment becomes damaged or package installation was interrupted,
recreate it before building:

```powershell
.\build_local.ps1 -RecreateBuildEnv
```

To also create `packaging\Output\narratible_Installer.exe`, install
[Inno Setup 6](https://jrsoftware.org/isdl.php) at its default location and run:

```powershell
.\build_local.ps1 -Full
```

The environment validation checks that Chatterbox imports successfully and
that the PyTorch wheel includes CUDA support before PyInstaller starts.

---

## Quick Start (Local Dev)

You need two terminals — one for the backend, one for the frontend.

### 1. Backend

```powershell
cd backend
.venv\Scripts\Activate.ps1     # activate the virtual environment
python run.py                   # starts FastAPI on http://localhost:8000
```

> **First time only** — create the venv using the `narratible` conda env (Python 3.12):
> ```powershell
> conda run -n narratible python -m venv .venv
> .venv\Scripts\pip install "pip==26.2.1" "setuptools==70.2.0"
> .venv\Scripts\pip install -c constraints.txt "torch==2.11.0" "torchaudio==2.11.0" --index-url https://download.pytorch.org/whl/cu128
> .venv\Scripts\pip install -r requirements.txt
> .venv\Scripts\pip install -r requirements-gpu.txt
> .venv\Scripts\pip install -r requirements-chatterbox.txt  # optional
> .venv\Scripts\pip install --force-reinstall -c constraints.txt "torch==2.11.0" "torchaudio==2.11.0" --index-url https://download.pytorch.org/whl/cu128
> ```

Python dependencies are locked through `backend/constraints.txt`. Update the
constraints and the matching requirements files together when intentionally
upgrading packages.

### 2. Frontend

```powershell
cd frontend
npm install       # first time only
npm run dev       # starts Vite dev server on http://localhost:5173
```

Then open **http://localhost:5173** in your browser.

### MCP server for agents

The backend exposes an MCP server for local agents while it is running:

- Streamable HTTP endpoint: `http://localhost:8000/mcp`
- Stdio entry point: `cd backend && .venv\Scripts\python.exe -m app.mcp_server`

Current MCP tools include project/task inspection plus `tail_logs` and `watch_logs`
for reading live backend logs.

---

## Docker

Requires [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) and Docker Desktop with GPU enabled.

```powershell
docker compose up --build
```
Open **http://localhost**.

> First build is ~6 GB (PyTorch CUDA + kokoro + f5-tts). Subsequent builds use the cache.

### Docker log and polling controls

You can control request-log verbosity and task polling via environment variables in a root `.env` file.

1. Copy `.env.example` to `.env`.
2. Set values as needed:
   - `UVICORN_ACCESS_LOG=0` (backend request logs off, set to `1` to enable)
   - `NGINX_ACCESS_LOG=0` (frontend nginx access logs off, set to `1` to enable)
   - `VITE_TASK_POLL_INTERVAL_MS=2000` (frontend task polling interval in ms)

Apply notes:
- `UVICORN_ACCESS_LOG` and `NGINX_ACCESS_LOG` are runtime settings.
- `VITE_TASK_POLL_INTERVAL_MS` is a frontend build-time setting and requires rebuilding the frontend image.

Recommended after changing values:

```powershell
docker compose up --build -d
```

Project files, config, and the Voice Library persist in Docker named volumes (`projects_data`, `config_data`).  
The API is also available directly at **http://localhost:8000/docs** (Swagger UI).

---



| Engine | Quality | Speed | Requires |
|---|---|---|---|
| Edge-TTS | Good | Instant | Internet |
| Kokoro-82M | Great | Fast (GPU) | Local model (auto-downloaded) |
| F5-TTS Clone | Excellent | Moderate (GPU) | Your `.wav` voice sample |
| Chatterbox Clone | Excellent | Moderate | Your voice sample; CUDA, MPS, or CPU |

Local engines use narratible's audio-only text preparation layer before
synthesis. This expands high-confidence speech forms such as scripture ranges
(`Matthew 10:14-15` -> `Matthew 10, verses 14 through 15`), common
abbreviations (`etc.` -> `et cetera`), and units (`55 mph` -> `55 miles per
hour`) while preserving the original chapter text and EPUB output. Kokoro,
F5-TTS, and Chatterbox also receive shorter speech segments with explicit pauses between
sentences and paragraphs to improve long-form pacing.

Edge-TTS may still pronounce unusual domain text more naturally because the
hosted service has a larger proprietary text-normalization and prosody front
end. Kokoro has a lighter local pipeline, while F5-TTS and Chatterbox prioritize
voice cloning, so narratible adds these deterministic speech cues locally.

### Voice Library with F5-TTS or Chatterbox
1. Record a clean 10-15 second `.wav` clip of the voice you want to clone.
2. Open **Voice Library**, create a reusable voice, and test it before saving or using it.
3. In Step 3, select **F5-TTS Clone** or **Chatterbox Clone** and choose a saved voice.
4. Model weights download automatically on first use (~800 MB for F5-TTS or
   ~3 GB for Chatterbox).

Chatterbox uses narration-tuned defaults (`cfg_weight=0.3`,
`exaggeration=0.5`), removes generated dead air at segment boundaries, and
applies the existing speed control with pitch-preserving time stretching. A
speed around `0.90x` to `0.95x` is a useful starting point for a fast reference
speaker. Its model (~3 GB) downloads into the standard Hugging Face cache on
first use.

Chatterbox is optional because its pinned ML dependencies may not match every
PyTorch installation. Install it separately after the core requirements:

```bash
python -m pip install -r backend/requirements-chatterbox.txt
```

Then install the PyTorch build recommended by the
[official selector](https://pytorch.org/get-started/locally/) for the target
machine. This is especially important for newer NVIDIA GPU generations.
Narratible uses the selected CUDA device when available, Apple Metal on a Mac,
and otherwise CPU. Selecting CPU explicitly in Settings is also respected.
The official Windows installer already includes Chatterbox and a compatible
CUDA-enabled PyTorch build; these manual steps are only for source checkouts.

#### Optional AI reference cleanup

The Voice Library can create a denoised, bandwidth-restored copy of its active
reference clip with [Resemble Enhance](https://github.com/resemble-ai/resemble-enhance).
The source recording is always retained so you can compare the two or switch
back. This does not upload the recording to a service, but the model is
downloaded on first use and enhancement can take several minutes on CPU.

Resemble Enhance currently pins an older PyTorch release, which may conflict
with the PyTorch build used by F5-TTS. Install it in its own environment:

```bash
python3 -m venv .venv-voice-enhance
.venv-voice-enhance/bin/python -m pip install -r backend/requirements-voice-enhancement.txt
export NARRATIBLE_VOICE_ENHANCER_PYTHON="$PWD/.venv-voice-enhance/bin/python"
```

On Windows PowerShell, use `.venv-voice-enhance\Scripts\python.exe` for both
the install command and `NARRATIBLE_VOICE_ENHANCER_PYTHON`. Keep that variable
set in the environment that starts narratible. For a recent NVIDIA GPU, install
the compatible CUDA build of PyTorch in this enhancement environment using the
[official PyTorch selector](https://pytorch.org/get-started/locally/) after the
requirements step.

Resemble Enhance stays in this sidecar environment even in the packaged
Windows app because its pinned PyTorch version conflicts with the newer build
used by the bundled cloning engines. The installer includes the enhancement
worker and requirements file under
`%LOCALAPPDATA%\narratible\_internal\optional_runtime`; point the environment
variable at the sidecar environment's `python.exe`, never at
`narratible.exe`. Without that variable, the packaged app reports enhancement
as unavailable instead of accidentally relaunching itself.

The enhancement control supports **Auto**, **CUDA**, **Apple Metal (MPS)**, and
**CPU**. Auto tries narratible's selected CUDA device, then MPS, then CPU. If an
accelerator is detected but an operation is unsupported, Auto retries on CPU;
an explicitly selected device reports the error instead. CPU is the most
portable option. Resemble Enhance is optional: without this environment, all
existing Voice Library and cloning features continue to work unchanged.

Saved voices persist in the app data directory (`~/.narratible/voice_library` for local and Docker runs, `%APPDATA%\narratible\voice_library` for packaged Windows builds).

### Optional: LLM Text Cleanup
For better text extraction from complex PDFs, add an API key in **⚙ Settings**:
- [Gemini API key](https://aistudio.google.com/app/apikey) (free tier available)
- OpenAI API key (paid)

### Optional: Audiobookshelf Upload
Configure your server URL and API token in **⚙ Settings** to upload finished books directly.
