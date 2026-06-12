# Echo-Scribe

Echo-Scribe is an end-to-end PDF-to-Ebook/Audiobook creation tool. It parses a PDF, cleans up the text (handling footnotes, margins, and parsing artifacts), organizes the text into chapters with an interactive editor, generates natural-sounding audiobook files (MP3) using local/cloud TTS engines, compiles the book into EPUB, and can optionally upload the results to Audiobookshelf.

## Architecture

The project consists of two main components:
- **Backend**: A Python FastAPI server that handles file processing, text extraction, LLM cleanup, TTS synthesis, and EPUB generation.
- **Frontend**: A React + Vite web application that provides a wizard-driven user interface for uploading, editing, and exporting projects.

---

## Windows Native App Installer (.exe)

For Windows users who want to run the app natively without Docker or starting separate server/frontend processes, Echo-Scribe provides a seamless standalone installer.

1. Navigate to the **Releases** tab on GitHub.
2. Download the latest `EchoScribe_Installer.exe`.
3. Run the installer and launch Echo-Scribe from your Start Menu.
   - A background server will initialize quietly, and your default web browser will open to the app natively.
   - During the installation, FFmpeg is automatically downloaded via Windows Package Manager (`winget`) so that high-quality audio merging is fully enabled without triggering GPL distribution violations in the installer.
   - The installer bundles all other core dependencies (including the PyTorch CUDA extensions offline) so you can use high-quality local TTS engines like Kokoro and F5-TTS without any extra config.

*Note: Data and configuration for packaged apps are saved in your user profile at `%APPDATA%\EchoScribe`.*

---

## Quick Start (Local Dev)

You need two terminals — one for the backend, one for the frontend.

### 1. Backend

```powershell
cd backend
.venv\Scripts\Activate.ps1     # activate the virtual environment
python run.py                   # starts FastAPI on http://localhost:8000
```

> **First time only** — create the venv using the `echoscribe` conda env (Python 3.12):
> ```powershell
> conda run -n echoscribe python -m venv .venv
> .venv\Scripts\pip install -r requirements.txt
> .venv\Scripts\pip install kokoro f5-tts
> .venv\Scripts\pip install torch --force-reinstall --index-url https://download.pytorch.org/whl/cu128
> ```

### 2. Frontend

```powershell
cd frontend
npm install       # first time only
npm run dev       # starts Vite dev server on http://localhost:5173
```

Then open **http://localhost:5173** in your browser.

---

## Docker

Requires [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) and Docker Desktop with GPU enabled.

```powershell
docker compose up --build
```
Open **http://localhost**.

> First build is ~6 GB (PyTorch CUDA + kokoro + f5-tts). Subsequent builds use the cache.

Project files persist in Docker named volumes (`projects_data`, `config_data`).  
The API is also available directly at **http://localhost:8000/docs** (Swagger UI).

---



| Engine | Quality | Speed | Requires |
|---|---|---|---|
| Edge-TTS | Good | Instant | Internet |
| Kokoro-82M | Great | Fast (GPU) | Local model (auto-downloaded) |
| F5-TTS Clone | Excellent | Moderate (GPU) | Your `.wav` voice sample |

### Voice Cloning with F5-TTS
1. Record a clean 10–15 second `.wav` clip of the voice you want to clone
2. In Step 3, upload it via **Voice Samples → Upload Sample**
3. Select **F5-TTS Clone** as the engine
4. The model weights (~800 MB) download automatically on first use

### Optional: LLM Text Cleanup
For better text extraction from complex PDFs, add an API key in **⚙ Settings**:
- [Gemini API key](https://aistudio.google.com/app/apikey) (free tier available)
- OpenAI API key (paid)

### Optional: Audiobookshelf Upload
Configure your server URL and API token in **⚙ Settings** to upload finished books directly.

