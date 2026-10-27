"""Paths and environment settings, read once per call so tests can override them."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = SERVER_DIR.parent


def load_dotenv(path: Path = SERVER_DIR / ".env") -> None:
    """KEY=value lines from server/.env (gitignored) into the environment. Variables already
    set in the shell win, so a deploy's real environment is never overridden."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        os.environ.setdefault(name.strip(), value.strip().strip("\"'"))


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    spec_dir: Path
    data_dir: Path
    host: str
    port: int
    speed: float
    event_log_keep: int
    msg_id_ttl_s: int
    clarify_timeout_ms: int | None
    llm_timeout_s: float
    cerebras_model: str
    anthropic_model: str
    mock: bool
    # When set, every request except /v1/health must carry it (X-Bara-Token header or ?token=).
    access_token: str | None = None
    # Where the build library lives; tests and side engines point it away from the real one.
    library_override: Path | None = None

    @property
    def schemas_dir(self) -> Path:
        return self.spec_dir / "schemas"

    @property
    def fixtures_dir(self) -> Path:
        return self.spec_dir / "fixtures"

    @property
    def assets_dir(self) -> Path:
        return self.data_dir / "assets"

    @property
    def catalog_dir(self) -> Path:
        return self.data_dir / "catalog"

    @property
    def library_dir(self) -> Path:
        return self.library_override or self.data_dir / "library"


def load_settings() -> Settings:
    clarify_raw = os.environ.get("BARA_CLARIFY_TIMEOUT_MS")
    clarify_timeout = None
    if clarify_raw:
        try:
            clarify_timeout = max(0, int(clarify_raw))
        except ValueError:
            clarify_timeout = None
    return Settings(
        spec_dir=Path(os.environ.get("BARA_SPEC_DIR", REPO_DIR / "spec")),
        data_dir=Path(os.environ.get("BARA_DATA_DIR", SERVER_DIR / "data")),
        host=os.environ.get("BARA_HOST", "127.0.0.1"),
        port=_int_env("BARA_PORT", 8790),
        speed=max(0.0, _float_env("BARA_SPEED", 1.0)),
        event_log_keep=max(1, _int_env("BARA_EVENT_LOG_KEEP", 5000)),
        msg_id_ttl_s=max(1, _int_env("BARA_MSG_ID_TTL_S", 600)),
        clarify_timeout_ms=clarify_timeout,
        llm_timeout_s=max(0.1, _float_env("BARA_LLM_TIMEOUT_S", 60.0)),
        cerebras_model=os.environ.get("BARA_CEREBRAS_MODEL", "llama-3.3-70b"),
        anthropic_model=os.environ.get("BARA_ANTHROPIC_MODEL", "claude-sonnet-5-5"),
        mock=os.environ.get("BARA_MOCK", "1") not in ("0", "false", "no"),
        access_token=os.environ.get("BARA_ACCESS_TOKEN") or None,
        library_override=Path(lib) if (lib := os.environ.get("BARA_LIBRARY_DIR")) else None,
    )
