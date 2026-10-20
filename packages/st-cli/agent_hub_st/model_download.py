"""Private child entry point; the public command admits work before launching it."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from urllib.parse import urlsplit

import httpx

from .model_download_registry import Registry, model_name

DEFAULT_REGISTRY = "https://registry.ollama.ai"
DEFAULT_OLLAMA = "http://127.0.0.1:11434"


def local_ollama() -> str:
    endpoint = os.environ.get("ST_MODELS_OLLAMA_HOST", DEFAULT_OLLAMA)
    parsed = urlsplit(endpoint)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("ST_MODELS_OLLAMA_HOST must be an HTTP 127.0.0.1 origin.")
    return endpoint.rstrip("/")


def installed_models(endpoint: str) -> dict[str, str]:
    with httpx.Client(trust_env=False, timeout=10) as client:
        response = client.get(f"{endpoint}/api/tags")
        response.raise_for_status()
        return {item["name"]: item["digest"] for item in response.json()["models"]}


def installed_digest(endpoint: str, model: str) -> str | None:
    for name, digest in installed_models(endpoint).items():
        try:
            candidate = model_name(name)
        except ValueError:
            continue  # Temporary loopback names are not public destination names.
        if candidate == model_name(model):
            return digest
    return None


def native(endpoint: str, *args: str, quiet: bool = False) -> None:
    subprocess.run(
        ["ollama", *args], check=True,
        env={**os.environ, "OLLAMA_HOST": endpoint},
        stdout=subprocess.DEVNULL if quiet else None,
        stderr=subprocess.DEVNULL if quiet else None,
        timeout=15 if quiet else None,
    )


def pull(model: str) -> None:
    model_name(model)
    endpoint = local_ollama()
    registry = Registry(model, os.environ.get("ST_MODELS_REGISTRY", DEFAULT_REGISTRY))
    try:
        before = installed_digest(endpoint, model)
        if before == registry.digest:
            print(f"Already installed {model} ({registry.digest}).", flush=True)
            return
        if before is not None:
            raise ValueError("Destination already contains a different manifest; choose a different model tag.")
        with registry.serve() as temporary:
            if temporary in installed_models(endpoint):
                raise ValueError("Temporary registry name already exists; leaving it unchanged.")
            try:
                native(endpoint, "pull", "--insecure", temporary)
                if installed_digest(endpoint, model) is not None:
                    raise ValueError("Destination appeared during download; leaving it unchanged.")
                native(endpoint, "cp", temporary, model)
                if installed_digest(endpoint, model) != registry.digest:
                    raise ValueError("Installed model manifest did not match the frozen public manifest.")
            finally:
                try:
                    native(endpoint, "rm", temporary, quiet=True)
                except (subprocess.SubprocessError, OSError) as exc:
                    raise ValueError(f"Could not remove temporary model {temporary}; remove that exact alias with ollama rm.") from exc
        print(f"Installed {model} ({registry.digest}).", flush=True)
    finally:
        registry.close()


def main() -> int:
    def cancel(_signum: int, _frame: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, cancel)
    try:
        pull(sys.argv[1])
        return 0
    except KeyboardInterrupt:
        print("Model download cancelled.", file=sys.stderr)
        return 130
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (httpx.HTTPError, httpx.InvalidURL, KeyError, TypeError, OSError, subprocess.SubprocessError):
        # Network exception strings may contain signed redirect URLs.
        print("Model download failed; check the public model name and local Ollama service.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
