import multiprocessing
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path
import uvicorn
import requests

# Set python path to backend to avoid structural import issues
sys.path.insert(0, str(Path(__file__).parent / "backend"))

# Important for PyInstaller multiprocess spawn
if __name__ == '__main__':
    multiprocessing.freeze_support()

from backend.app.main import app

def open_browser(url):
    start = time.time()
    while time.time() - start < 15:
        try:
            r = requests.get(f"{url}/api/health", timeout=1)
            if r.status_code == 200:
                print("Echo-Scribe started! Opening browser...")
                webbrowser.open(url)
                return
        except Exception:
            pass
        time.sleep(0.5)
    print("Timeout waiting for internal server to start.")

if __name__ == "__main__":
    port = 8000
    url = f"http://127.0.0.1:{port}"
    
    threading.Thread(target=open_browser, args=(url,), daemon=True).start()
    
    print(f"Starting Echo-Scribe on {url}...")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
