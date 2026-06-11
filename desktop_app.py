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

from backend.app.main import app

def check_for_updates():
    """Check GitHub for newer releases and prompt the user."""
    try:
        # Only check when running natively as packaged app
        if not getattr(sys, 'frozen', False):
            return
            
        print("Checking for updates...")
        response = requests.get("https://api.github.com/repos/ckchessmaster/echo-scribe/releases/latest", timeout=3)
        if response.status_code == 200:
            latest_release = response.json()
            latest_version = latest_release.get("tag_name", "").lstrip("v")
            
            def parse_ver(v):
                return tuple(int(x) for x in v.split(".") if x.isdigit())
                
            if parse_ver(latest_version) > parse_ver(APP_VERSION):
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                msg = f"A new version of Echo-Scribe is available! (v{latest_version})\n\nYou are currently running v{APP_VERSION}.\n\nWould you like to open GitHub to download the update?"
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
                print("Echo-Scribe started! Opening browser...")
                webbrowser.open(url)
                return
        except Exception:
            pass
        time.sleep(0.5)
    print("Timeout waiting for internal server to start.")

if __name__ == "__main__":
    check_for_updates()
    
    port = 8000
    url = f"http://127.0.0.1:{port}"
    
    threading.Thread(target=open_browser, args=(url,), daemon=True).start()
    
    print(f"Starting Echo-Scribe on {url}...")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
