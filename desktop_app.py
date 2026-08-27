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

from backend.app.hf_cache import configure_frozen_huggingface_cache
from backend.app.version import APP_VERSION

configure_frozen_huggingface_cache()


def _runtime_cli_option(name: str) -> str:
    if name not in sys.argv:
        return ""
    try:
        return sys.argv[sys.argv.index(name) + 1]
    except IndexError:
        return ""


def _write_runtime_ini(path_value: str, section: str, values: dict) -> None:
    if not path_value:
        return
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"[{section}]"]
    for key, value in values.items():
        clean_value = str(value).replace("\r", " ").replace("\n", " ")
        lines.append(f"{key}={clean_value}")
    temp_path = path.with_name(f"{path.name}.tmp")
    temp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(temp_path, path)


def _run_runtime_cli() -> int | None:
    """Handle installer/runtime commands before importing the FastAPI app."""
    runtime_flags = {
        "--runtime-preflight",
        "--runtime-status",
        "--runtime-bootstrap",
        "--runtime-update-installed",
        "--runtime-verify",
    }
    if not runtime_flags.intersection(sys.argv):
        return None

    progress_file = _runtime_cli_option("--runtime-progress-file")
    result_file = _runtime_cli_option("--runtime-result-file")

    def publish(message: str, progress: int, stage: str, profile: str = "") -> None:
        payload = {
            "status": "running",
            "stage": stage,
            "progress": progress,
            "message": message,
        }
        if profile:
            payload["profile"] = profile
        print_json(payload)
        _write_runtime_ini(progress_file, "progress", payload)

    def finish(exit_code: int, message: str = "") -> int:
        _write_runtime_ini(
            result_file,
            "result",
            {"exit_code": exit_code, "message": message},
        )
        return exit_code

    from backend.app.runtime_engines import (
        RUNTIME_EXIT_OK,
        RUNTIME_EXIT_SETUP_FAILED,
        RUNTIME_EXIT_UNSUPPORTED_HARDWARE,
        RUNTIME_EXIT_VERIFICATION_FAILED,
        RuntimeSetupError,
        install_profile,
        nvidia_preflight,
        print_json,
        runtime_status,
        update_installed_profiles,
        verify_profile_environment,
    )

    if "--runtime-preflight" in sys.argv:
        result = nvidia_preflight()
        print_json(result)
        return finish(
            RUNTIME_EXIT_OK if result["supported"] else RUNTIME_EXIT_UNSUPPORTED_HARDWARE,
            result.get("reason") or "NVIDIA hardware is supported.",
        )

    if "--runtime-update-installed" in sys.argv:
        try:
            result = update_installed_profiles(
                lambda message, progress, stage: publish(message, progress, stage)
            )
        except (RuntimeSetupError, ValueError) as exc:
            print_json({"status": "error", "message": str(exc)})
            return finish(RUNTIME_EXIT_SETUP_FAILED, str(exc))
        print_json({"status": "complete", "profiles": result})
        return finish(RUNTIME_EXIT_OK, "Installed local AI profiles are up to date.")

    for flag, operation, failure_code in (
        ("--runtime-bootstrap", install_profile, RUNTIME_EXIT_SETUP_FAILED),
        ("--runtime-verify", verify_profile_environment, RUNTIME_EXIT_VERIFICATION_FAILED),
    ):
        if flag not in sys.argv:
            continue
        try:
            profile_id = sys.argv[sys.argv.index(flag) + 1]
        except IndexError:
            print_json({"status": "error", "message": f"{flag} requires a profile ID."})
            return finish(failure_code, f"{flag} requires a profile ID.")
        if flag == "--runtime-bootstrap":
            preflight = nvidia_preflight()
            if not preflight["supported"]:
                print_json(preflight)
                return finish(RUNTIME_EXIT_UNSUPPORTED_HARDWARE, preflight.get("reason", "Unsupported hardware."))
        try:
            if flag == "--runtime-bootstrap":
                result = operation(
                    profile_id,
                    lambda message, progress, stage: publish(message, progress, stage, profile_id),
                )
            else:
                result = operation(profile_id)
        except (RuntimeSetupError, ValueError) as exc:
            print_json({"status": "error", "profile": profile_id, "message": str(exc)})
            return finish(failure_code, str(exc))
        print_json({"status": "verified", "profile": profile_id, "runtime": result})
        return finish(RUNTIME_EXIT_OK, f"{profile_id} is ready.")

    print_json(runtime_status())
    return finish(RUNTIME_EXIT_OK, "Runtime status loaded.")


if __name__ == "__main__":
    from backend.app.subprocess_utils import configure_child_process_job

    configure_child_process_job()
    runtime_exit_code = _run_runtime_cli()
    if runtime_exit_code is not None:
        raise SystemExit(runtime_exit_code)


def _verify_packaged_frontend():
    """Verify the app shell references a bundle with every TTS engine."""
    if not getattr(sys, "frozen", False):
        return

    from backend.app.package_verify import verify_packaged_frontend

    frontend_dir = Path(sys._MEIPASS) / "frontend_dist"
    bundle_name = verify_packaged_frontend(frontend_dir)
    print("Packaged frontend OK | bundle", bundle_name)


def _verify_packaged_tts_imports():
    """Verify the slim base runtime and managed-engine metadata."""
    _verify_packaged_frontend()
    import numpy
    import edge_tts

    from backend.app.runtime_engines import load_runtime_catalog, runtime_python, uv_executable

    catalog = load_runtime_catalog()
    if not any(profile["id"] == "kokoro" for profile in catalog["profiles"]):
        raise RuntimeError("Managed runtime catalog is missing Kokoro.")
    if getattr(sys, "frozen", False):
        if not runtime_python().is_file():
            raise RuntimeError("Private runtime Python is missing from the packaged app.")
        if not uv_executable().is_file():
            raise RuntimeError("uv is missing from the packaged app.")

    print(
        "Packaged base imports OK | numpy",
        numpy.__version__,
        "| edge-tts",
        edge_tts.__version__,
        "| managed profiles",
        len(catalog["profiles"]),
    )


if __name__ == "__main__" and "--verify-tts-imports" in sys.argv:
    _verify_packaged_tts_imports()
    raise SystemExit(0)


from backend.app.main import app


def _ask_to_open_update(latest_version: str) -> bool:
    """Show a native Windows prompt without loading Tcl/Tk."""
    if os.name != "nt":
        return False
    import ctypes

    message = (
        f"A new version of narratible is available! (v{latest_version})\n\n"
        f"You are currently running v{APP_VERSION}.\n\n"
        "Would you like to open GitHub to download the update?"
    )
    result = ctypes.windll.user32.MessageBoxW(
        None,
        message,
        "narratible Update Available",
        0x00000004 | 0x00000040,
    )
    return result == 6

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
                if _ask_to_open_update(latest_version):
                    webbrowser.open(latest_release.get("html_url"))
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


def _run_server(port: int) -> None:
    """Run Uvicorn through narratible's file-backed logging configuration."""
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=port,
        log_level="info",
        log_config=None,
    )


if __name__ == "__main__":
    check_for_updates()

    if getattr(sys, 'frozen', False):
        _augment_path_with_ffmpeg()

    port = 8000
    url = f"http://127.0.0.1:{port}"
    
    threading.Thread(target=open_browser, args=(url,), daemon=True).start()
    
    print(f"Starting narratible on {url}...")
    _run_server(port)
