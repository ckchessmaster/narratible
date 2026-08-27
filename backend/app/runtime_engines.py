"""Managed local-AI runtime catalog, hardware preflight, and status."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any, Callable
import uuid

from .runtime_state import load_engine_manifest
from .runtime_state import save_engine_manifest
from .subprocess_utils import hidden_process_kwargs
from .version import APP_VERSION

RUNTIME_EXIT_OK = 0
RUNTIME_EXIT_UNSUPPORTED_HARDWARE = 10
RUNTIME_EXIT_SETUP_FAILED = 20
RUNTIME_EXIT_VERIFICATION_FAILED = 30


class RuntimeSetupError(RuntimeError):
    """Raised when a managed runtime operation cannot complete safely."""


_NVIDIA_PREFLIGHT_TTL_SECONDS = 30.0
_nvidia_preflight_cached_at = 0.0
_nvidia_preflight_cached_result: dict[str, Any] | None = None


def runtime_root() -> Path:
    configured = os.environ.get("NARRATIBLE_ENGINE_RUNTIME_DIR", "").strip()
    if configured:
        return Path(configured)
    local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    return local_app_data / "narratible-engine-runtime"


def runtime_tools_root() -> Path:
    configured = os.environ.get("NARRATIBLE_RUNTIME_TOOLS_DIR", "").strip()
    if configured:
        return Path(configured)
    if getattr(sys, "frozen", False):
        bundle_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return bundle_root / "runtime-tools"
    return Path(sys.executable).parent


def runtime_python() -> Path:
    configured = os.environ.get("NARRATIBLE_RUNTIME_PYTHON", "").strip()
    if configured:
        return Path(configured)
    if getattr(sys, "frozen", False):
        tools_root = runtime_tools_root()
        marker_path = tools_root / "python-path.txt"
        if marker_path.is_file():
            relative_path = marker_path.read_text(encoding="ascii").strip()
            candidate = (tools_root / relative_path).resolve()
            resolved_root = tools_root.resolve()
            if candidate != resolved_root and resolved_root not in candidate.parents:
                raise RuntimeSetupError("Private Python marker points outside the runtime tools directory.")
            return candidate
        return tools_root / "python-managed" / "python.exe"
    return Path(sys.executable)


def uv_executable() -> Path:
    configured = os.environ.get("NARRATIBLE_UV_EXECUTABLE", "").strip()
    if configured:
        return Path(configured)
    return runtime_tools_root() / "uv.exe"


def catalog_path() -> Path:
    configured = os.environ.get("NARRATIBLE_RUNTIME_CATALOG", "").strip()
    if configured:
        return Path(configured)
    if getattr(sys, "frozen", False):
        bundle_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return bundle_root / "runtime_profiles" / "catalog.json"
    return Path(__file__).resolve().parents[1] / "runtime_profiles" / "catalog.json"


def load_runtime_catalog() -> dict[str, Any]:
    source_path = catalog_path()
    with open(source_path, "r", encoding="utf-8") as f:
        catalog = json.load(f)
    if catalog.get("pytorch", {}).get("allow_cpu_fallback") is not False:
        raise ValueError("Runtime catalog must explicitly disable CPU PyTorch fallback.")
    profile_ids = [profile.get("id") for profile in catalog.get("profiles", [])]
    if len(profile_ids) != len(set(profile_ids)) or any(not value for value in profile_ids):
        raise ValueError("Runtime catalog profile IDs must be unique and non-empty.")
    for profile in catalog.get("profiles", []):
        lock_name = profile.get("lock_file")
        if not lock_name:
            continue
        lock_path = source_path.parent / lock_name
        if not lock_path.is_file():
            raise ValueError(f"Runtime profile {profile['id']} lock file is missing.")
        lock_bytes = lock_path.read_bytes()
        actual_hash = hashlib.sha256(lock_bytes).hexdigest()
        if actual_hash != profile.get("lock_sha256"):
            raise ValueError(f"Runtime profile {profile['id']} lock hash does not match the catalog.")
        lock_text = lock_bytes.decode("utf-8")
        if "/whl/cpu" in lock_text or "+cpu" in lock_text:
            raise ValueError(f"Runtime profile {profile['id']} contains a forbidden CPU PyTorch source.")
        expected_suffix = "+" + catalog["pytorch"]["backend"]
        if profile.get("requires_cuda") and expected_suffix not in lock_text:
            raise ValueError(f"Runtime profile {profile['id']} does not lock CUDA PyTorch.")
    return catalog


def nvidia_preflight(*, force: bool = False) -> dict[str, Any]:
    """Probe NVIDIA hardware and drivers without importing PyTorch."""
    global _nvidia_preflight_cached_at, _nvidia_preflight_cached_result
    now = time.monotonic()
    if (
        not force
        and _nvidia_preflight_cached_result is not None
        and now - _nvidia_preflight_cached_at < _NVIDIA_PREFLIGHT_TTL_SECONDS
    ):
        return _nvidia_preflight_cached_result

    def finish(result: dict[str, Any]) -> dict[str, Any]:
        global _nvidia_preflight_cached_at, _nvidia_preflight_cached_result
        _nvidia_preflight_cached_at = time.monotonic()
        _nvidia_preflight_cached_result = result
        return result

    command = [
        "nvidia-smi",
        "--query-gpu=index,name,driver_version,memory.total",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            **hidden_process_kwargs(),
        )
    except FileNotFoundError:
        return finish({
            "supported": False,
            "reason": "nvidia-smi was not found. A supported NVIDIA GPU and driver are required for local AI.",
            "gpus": [],
        })
    except subprocess.TimeoutExpired:
        return finish({
            "supported": False,
            "reason": "NVIDIA driver detection timed out.",
            "gpus": [],
        })
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        return finish({
            "supported": False,
            "reason": detail or "NVIDIA driver detection failed.",
            "gpus": [],
        })

    gpus = []
    for line in result.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 4:
            continue
        try:
            gpus.append(
                {
                    "index": int(parts[0]),
                    "name": parts[1],
                    "driver_version": parts[2],
                    "vram_mb": int(parts[3]),
                }
            )
        except ValueError:
            continue
    return finish({
        "supported": bool(gpus),
        "reason": None if gpus else "No NVIDIA GPUs were reported by nvidia-smi.",
        "gpus": gpus,
    })


def runtime_status() -> dict[str, Any]:
    catalog = load_runtime_catalog()
    manifest = load_engine_manifest()
    installed = manifest.get("profiles", {})
    profiles = []
    for profile in catalog["profiles"]:
        state = installed.get(profile["id"], {})
        installable = bool(profile.get("lock_file"))
        unavailable_status = profile.get("availability", "not_available")
        status = state.get("status", "not_installed" if installable else unavailable_status)
        if (
            status == "verified"
            and profile.get("lock_sha256")
            and state.get("lock_sha256") != profile["lock_sha256"]
        ):
            status = "needs_update"
        profiles.append(
            {
                **profile,
                "installable": installable,
                "status": status,
                "installed_version": state.get("version"),
                "last_error": state.get("last_error"),
            }
        )
    return {
        "app_version": APP_VERSION,
        "runtime_root": str(runtime_root()),
        "catalog_schema_version": catalog["schema_version"],
        "worker_protocol_version": catalog["worker_protocol_version"],
        "python_version": catalog["python_version"],
        "pytorch": catalog["pytorch"],
        "manifest_app_version": manifest.get("active_app_version"),
        "profiles": profiles,
    }


def installed_profile_state(profile_id: str) -> dict[str, Any] | None:
    state = load_engine_manifest().get("profiles", {}).get(profile_id)
    if state is None or state.get("status") != "verified":
        return None
    profile, _project_dir = _profile_definition(profile_id)
    if state.get("lock_sha256") != profile.get("lock_sha256"):
        return None
    active_env = state.get("active_env")
    if not active_env:
        return None
    state = state.copy()
    state["python_executable"] = str(_profile_env_python(_managed_environment_path(active_env)))
    return state


def _profile_definition(profile_id: str) -> tuple[dict[str, Any], Path]:
    catalog = load_runtime_catalog()
    profile = next(
        (item for item in catalog["profiles"] if item["id"] == profile_id),
        None,
    )
    if profile is None:
        raise ValueError(f"Unknown runtime profile: {profile_id}")
    project_name = profile.get("project_file")
    lock_name = profile.get("lock_file")
    if not project_name or not lock_name:
        raise RuntimeSetupError(f"Runtime profile {profile_id} is not installable yet.")
    project_path = catalog_path().parent / project_name
    return profile, project_path.parent


def _profile_env_python(env_path: Path) -> Path:
    return env_path / "Scripts" / "python.exe"


def _run_command(command: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            env=env,
            **hidden_process_kwargs(),
        )
    except OSError as exc:
        raise RuntimeSetupError(f"Could not start runtime tool: {command[0]}") from exc


def verify_profile_environment(
    profile_id: str,
    env_path: Path | None = None,
    *,
    require_device: bool = False,
    prefetch_model: bool = False,
    cuda_index: int = 0,
) -> dict[str, Any]:
    profile, _project_dir = _profile_definition(profile_id)
    if env_path is None:
        state = load_engine_manifest().get("profiles", {}).get(profile_id, {})
        active_env = state.get("active_env")
        if not active_env:
            raise RuntimeSetupError(f"Runtime profile {profile_id} is not installed.")
        env_path = Path(active_env)
    python_path = _profile_env_python(env_path)
    if not python_path.is_file():
        raise RuntimeSetupError(f"Runtime profile {profile_id} Python is missing.")
    verification_parts = [
        "import importlib,json,torch",
        f"importlib.import_module({profile['verify_module']!r})",
        "cuda=torch.version.cuda",
    ]
    if require_device:
        verification_parts.append("assert torch.cuda.is_available(), 'CUDA build installed but the NVIDIA driver is unavailable' ")
        verification_parts.append(f"assert {cuda_index} < torch.cuda.device_count(), 'Configured CUDA device is unavailable'")
    if prefetch_model and profile_id == "kokoro":
        verification_parts.extend(
            [
                "from kokoro import KPipeline",
                f"KPipeline(lang_code='a',device='cuda:{cuda_index}',trf=False)",
            ]
        )
    elif prefetch_model and profile_id == "f5-tts":
        verification_parts.extend(
            [
                "from f5_tts.api import F5TTS",
                f"F5TTS(device='cuda:{cuda_index}')",
            ]
        )
    elif prefetch_model and profile_id == "chatterbox":
        verification_parts.extend(
            [
                "from chatterbox.tts import ChatterboxTTS",
                f"ChatterboxTTS.from_pretrained(device='cuda:{cuda_index}')",
            ]
        )
    verification_parts.extend(
        [
            "print(json.dumps({'torch':torch.__version__,'cuda':cuda}))",
            "raise SystemExit(0 if cuda else 3)",
        ]
    )
    verification = ";".join(verification_parts)
    result = _run_command([str(python_path), "-c", verification])
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        if result.returncode == 3:
            detail = "The profile resolved CPU-only PyTorch, which narratible forbids."
        raise RuntimeSetupError(detail or f"Runtime profile {profile_id} verification failed.")
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise RuntimeSetupError(f"Runtime profile {profile_id} returned invalid verification output.") from exc


def _report_progress(
    callback: Callable[[str, int, str], None] | None,
    message: str,
    progress: int,
    stage: str,
) -> None:
    if callback is not None:
        callback(message, progress, stage)


def install_profile(
    profile_id: str,
    progress_cb: Callable[[str, int, str], None] | None = None,
) -> dict[str, Any]:
    """Sync, verify, and atomically activate one locked runtime profile."""
    profile, project_dir = _profile_definition(profile_id)
    manifest = load_engine_manifest()
    previous = manifest.get("profiles", {}).get(profile_id, {}).copy()
    if (
        previous.get("status") == "verified"
        and previous.get("lock_sha256") == profile["lock_sha256"]
        and previous.get("active_env")
    ):
        _report_progress(progress_cb, f"Verifying existing {profile['label']} runtime...", 80, "verifying")
        verification = verify_profile_environment(
            profile_id,
            require_device=True,
            prefetch_model=profile.get("model_download") in {"installer", "install"},
        )
        previous.update(
            operation_status="idle",
            torch_version=verification["torch"],
            cuda_version=verification["cuda"],
            last_error=None,
        )
        manifest["active_app_version"] = APP_VERSION
        manifest["profiles"][profile_id] = previous
        save_engine_manifest(manifest)
        _report_progress(progress_cb, f"{profile['label']} is ready.", 100, "complete")
        return previous

    uv_path = uv_executable()
    python_path = runtime_python()
    if not uv_path.is_file():
        raise RuntimeSetupError(f"uv is missing from the runtime tools directory: {uv_path}")
    if not python_path.is_file():
        raise RuntimeSetupError(f"Private Python is missing from the runtime tools directory: {python_path}")

    root = runtime_root()
    pending = {
        **previous,
        "status": previous.get("status", "installing"),
        "operation_status": "installing",
        "last_error": None,
    }
    manifest.setdefault("profiles", {})[profile_id] = pending
    save_engine_manifest(manifest)

    lock_key = profile["lock_sha256"][:16]
    operation_id = uuid.uuid4().hex[:8]
    environment_name = f"{lock_key}-{operation_id}"
    staging_path = root / "staging" / f"{profile_id}-{environment_name}"
    active_path = root / "envs" / profile_id / environment_name
    cache_path = root / "cache" / "uv"
    shutil.rmtree(staging_path, ignore_errors=True)
    staging_path.parent.mkdir(parents=True, exist_ok=True)
    active_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.mkdir(parents=True, exist_ok=True)
    _report_progress(progress_cb, f"Preparing {profile['label']} runtime...", 5, "preparing")

    command_env = os.environ.copy()
    command_env.update(
        {
            "UV_CACHE_DIR": str(cache_path),
            "UV_PROJECT_ENVIRONMENT": str(staging_path),
            "UV_PYTHON_DOWNLOADS": "never",
        }
    )
    try:
        _report_progress(progress_cb, f"Downloading and syncing {profile['label']}...", 15, "syncing")
        result = _run_command(
            [
                str(uv_path),
                "sync",
                "--frozen",
                "--no-managed-python",
                "--python",
                str(python_path),
                "--project",
                str(project_dir),
            ],
            env=command_env,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeSetupError(detail or f"Failed to sync runtime profile {profile_id}.")

        _report_progress(progress_cb, f"Verifying {profile['label']} CUDA runtime...", 85, "verifying")
        verification = verify_profile_environment(
            profile_id,
            staging_path,
            require_device=True,
            prefetch_model=profile.get("model_download") in {"installer", "install"},
        )
        _report_progress(progress_cb, f"Activating {profile['label']}...", 95, "activating")
        os.replace(staging_path, active_path)

        manifest = load_engine_manifest()
        manifest["active_app_version"] = APP_VERSION
        manifest.setdefault("profiles", {})[profile_id] = {
            "status": "verified",
            "operation_status": "idle",
            "version": profile["version"],
            "lock_sha256": profile["lock_sha256"],
            "active_env": str(active_path),
            "rollback_env": previous.get("active_env"),
            "torch_version": verification["torch"],
            "cuda_version": verification["cuda"],
            "last_error": None,
        }
        save_engine_manifest(manifest)
        _report_progress(progress_cb, f"{profile['label']} is ready.", 100, "complete")
        return manifest["profiles"][profile_id]
    except Exception as exc:
        shutil.rmtree(staging_path, ignore_errors=True)
        manifest = load_engine_manifest()
        manifest.setdefault("profiles", {})[profile_id] = {
            **previous,
            "status": previous.get("status", "failed"),
            "operation_status": "failed",
            "last_error": str(exc),
        }
        save_engine_manifest(manifest)
        raise


def verify_installed_profile(profile_id: str) -> dict[str, Any]:
    profile, _project_dir = _profile_definition(profile_id)
    verification = verify_profile_environment(
        profile_id,
        require_device=True,
        prefetch_model=profile.get("model_download") in {"installer", "install"},
    )
    manifest = load_engine_manifest()
    state = manifest.get("profiles", {}).get(profile_id)
    if state is None:
        raise RuntimeSetupError(f"Runtime profile {profile_id} is not installed.")
    state.update(
        status="verified",
        operation_status="idle",
        torch_version=verification["torch"],
        cuda_version=verification["cuda"],
        last_error=None,
    )
    save_engine_manifest(manifest)
    return state


def _managed_environment_path(path_value: str) -> Path:
    root = (runtime_root() / "envs").resolve()
    candidate = Path(path_value).resolve()
    if candidate != root and root not in candidate.parents:
        raise RuntimeSetupError("Refusing to remove a runtime environment outside the managed root.")
    return candidate


def remove_profile(profile_id: str) -> None:
    _profile_definition(profile_id)
    manifest = load_engine_manifest()
    state = manifest.get("profiles", {}).get(profile_id)
    if state is None:
        return
    for key in ("active_env", "rollback_env"):
        path_value = state.get(key)
        if path_value:
            shutil.rmtree(_managed_environment_path(path_value), ignore_errors=True)
    manifest["profiles"].pop(profile_id, None)
    save_engine_manifest(manifest)


def update_installed_profiles(
    progress_cb: Callable[[str, int, str], None] | None = None,
) -> dict[str, Any]:
    manifest = load_engine_manifest()
    installed_ids = list(manifest.get("profiles", {}))
    results: dict[str, Any] = {}
    if not installed_ids:
        _report_progress(progress_cb, "No managed local AI profiles need updating.", 100, "complete")
        return results
    for index, profile_id in enumerate(installed_ids, start=1):
        profile, _project_dir = _profile_definition(profile_id)
        if not profile.get("lock_file"):
            continue
        base_progress = int(100 * (index - 1) / len(installed_ids))
        span = max(1, int(100 / len(installed_ids)))

        def report(message: str, progress: int, stage: str) -> None:
            overall = min(99, base_progress + int(span * progress / 100))
            _report_progress(progress_cb, message, overall, stage)

        results[profile_id] = install_profile(profile_id, report)
    _report_progress(progress_cb, "Installed local AI profiles are up to date.", 100, "complete")
    return results


def print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))