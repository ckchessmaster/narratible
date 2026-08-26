import multiprocessing
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path
import uvicorn
import requests
import tkinter as tk
from tkinter import messagebox

# Current App Version
APP_VERSION = "0.1.0"

# Set python path to backend to avoid structural import issues
sys.path.insert(0, str(Path(__file__).parent / "backend"))

# Important for PyInstaller multiprocess spawn
if __name__ == '__main__':
    multiprocessing.freeze_support()

from backend.app.hf_cache import configure_frozen_huggingface_cache

configure_frozen_huggingface_cache()


def _verify_packaged_frontend():
    """Verify the app shell references a bundle with every TTS engine."""
    if not getattr(sys, "frozen", False):
        return

    from backend.app.package_verify import verify_packaged_frontend

    frontend_dir = Path(sys._MEIPASS) / "frontend_dist"
    bundle_name = verify_packaged_frontend(frontend_dir)
    print("Packaged frontend OK | bundle", bundle_name)


def _verify_packaged_tts_imports():
    """Import every bundled TTS runtime and its packaged support assets."""
    _verify_packaged_frontend()
    import numpy
    import scipy.linalg
    import scipy.sparse
    import torch
    import torchaudio

    from backend.app.tts import _prepare_frozen_torch

    _prepare_frozen_torch(torch)
    import en_core_web_sm
    from kokoro import KPipeline  # noqa: F401
    from f5_tts.api import F5TTS  # noqa: F401
    from chatterbox.tts import ChatterboxTTS  # noqa: F401
    from perth.perth_net import PerthImplicitWatermarker

    en_core_web_sm.load(
        disable=["tok2vec", "tagger", "parser", "attribute_ruler", "lemmatizer", "ner"]
    )
    PerthImplicitWatermarker()

    print(
        "Packaged TTS imports OK | numpy",
        numpy.__version__,
        "| torch",
        torch.__version__,
        "| torchaudio",
        torchaudio.__version__,
        "| cuda",
        torch.version.cuda,
    )


if __name__ == "__main__" and "--verify-tts-imports" in sys.argv:
    _verify_packaged_tts_imports()
    raise SystemExit(0)


from backend.app.main import app

def check_for_updates():
    """Check GitHub for newer releases and prompt the user."""
    try:
        # Only check when running natively as packaged app
        if not getattr(sys, 'frozen', False):
            return
            
        print("Checking for updates...")
        response = requests.get("https://api.github.com/repos/ckchessmaster/narratible/releases/latest", timeout=3)
        if response.status_code == 200:
            latest_release = response.json()
            latest_version = latest_release.get("tag_name", "").lstrip("v")
            
            def parse_ver(v):
                return tuple(int(x) for x in v.split(".") if x.isdigit())
                
            if parse_ver(latest_version) > parse_ver(APP_VERSION):
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                msg = f"A new version of narratible is available! (v{latest_version})\n\nYou are currently running v{APP_VERSION}.\n\nWould you like to open GitHub to download the update?"
                if messagebox.askyesno("Update Available", msg):
                    webbrowser.open(latest_release.get("html_url"))
                root.destroy()
    except Exception as e:
        print(f"Update check failed: {e}")

def open_browser(url):
    start = time.time()
    while time.time() - start < 15:
        try:
            r = requests.get(f"{url}/api/health", timeout=1)
            if r.status_code == 200:
                print("narratible started! Opening browser...")
                webbrowser.open(url)
                return
        except Exception:
            pass
        time.sleep(0.5)
    print("Timeout waiting for internal server to start.")


def _augment_path_with_ffmpeg():
    """Prepend the winget FFmpeg bin directory to PATH if found.

    The Inno Setup installer installs FFmpeg via winget at install time, but
    the newly added PATH entry is not visible to the current process.  This
    function locates the winget-managed FFmpeg package directory and injects
    its bin/ folder so that subprocess calls can find ffmpeg.exe.
    """
    local_app_data = os.environ.get('LOCALAPPDATA', '')
    if not local_app_data:
        return
    winget_pkgs = Path(local_app_data) / 'Microsoft' / 'WinGet' / 'Packages'
    if not winget_pkgs.exists():
        return
    for candidate in sorted(winget_pkgs.glob('Gyan.FFmpeg*')):
        for bin_dir in candidate.glob('*/bin'):
            if bin_dir.is_dir():
                current_path = os.environ.get('PATH', '')
                os.environ['PATH'] = str(bin_dir) + os.pathsep + current_path
                print(f"FFmpeg located at: {bin_dir}")
                return


if __name__ == "__main__":
    check_for_updates()

    if getattr(sys, 'frozen', False):
        _augment_path_with_ffmpeg()

    port = 8000
    url = f"http://127.0.0.1:{port}"
    
    threading.Thread(target=open_browser, args=(url,), daemon=True).start()
    
    print(f"Starting narratible on {url}...")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
