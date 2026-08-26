"""One-off type-annotation patcher for the server package (run once)."""

from pathlib import Path

NL = chr(10)

# --- store.py ---
p = Path("apiverity/server/store.py")
s = p.read_text(encoding="utf-8")
s = s.replace(
    "import sqlite3" + NL + "from datetime import datetime, timedelta, timezone",
    "import sqlite3" + NL + "from datetime import UTC, datetime, timedelta",
)
s = s.replace("datetime.now(timezone.utc)", "datetime.now(UTC)")
s = s.replace(
    "from pathlib import Path",
    "from pathlib import Path" + NL + "from typing import Any",
)
s = s.replace("-> dict:", "-> dict[str, Any]:")
s = s.replace("params: tuple = (org_id,)", "params: tuple[Any, ...] = (org_id,)")
s = s.replace("return int(cur.lastrowid)", "return int(cur.lastrowid or 0)")
s = s.replace(
    'f"DELETE FROM {table} WHERE created_at < ?", (cutoff,)  # noqa: S608',
    'f"DELETE FROM {table} WHERE created_at < ?", (cutoff,)',
)
p.write_text(s, encoding="utf-8")

# --- auth.py ---
p = Path("apiverity/server/auth.py")
s = p.read_text(encoding="utf-8")
s = s.replace(
    "from typing import Protocol",
    "from typing import Any, Protocol",
)
s = s.replace(
    "def verify(self, token: str) -> tuple[str, dict] | None:",
    "def verify(self, token: str) -> tuple[str, dict[str, Any]] | None:",
)
s = s.replace(
    "def __init__(self, store) -> None:",
    "def __init__(self, store: Any) -> None:",
)
p.write_text(s, encoding="utf-8")

# --- webhooks.py ---
p = Path("apiverity/server/webhooks.py")
s = p.read_text(encoding="utf-8")
s = s.replace(
    "from collections.abc import Callable",
    "from collections.abc import Callable" + NL + "from typing import Any",
)
s = s.replace("webhooks: list[dict],", "webhooks: list[dict[str, Any]],")
s = s.replace("payload: dict,", "payload: dict[str, Any],")
p.write_text(s, encoding="utf-8")

# --- api.py ---
p = Path("apiverity/server/api.py")
s = p.read_text(encoding="utf-8")
s = s.replace("webhook_transport=None,", "webhook_transport: Any = None,")
s = s.replace("secret_resolver=None,", "secret_resolver: Any = None,")
s = s.replace(
    "def current_identity(action: str) -> tuple[Identity | None, tuple | None]:",
    "def current_identity(action: str) -> tuple[Identity | None, tuple[Any, ...] | None]:",
)
s = s.replace(
    "def compute_can_i_deploy(store: Store, org_id: int, body: dict) -> dict:",
    "def compute_can_i_deploy(store: Store, org_id: int, body: dict[str, Any]) -> dict[str, Any]:",
)
s = s.replace("-> list[dict]:", "-> list[dict[str, Any]]:")
p.write_text(s, encoding="utf-8")

# --- api.py list[dict] ---
p = Path("apiverity/server/api.py")
s = p.read_text(encoding="utf-8")
s = s.replace("-> list[dict]:", "-> list[dict[str, Any]]:")
p.write_text(s, encoding="utf-8")

# --- store.py audit lastrowid + optional dicts ---
p = Path("apiverity/server/store.py")
s = p.read_text(encoding="utf-8")
s = s.replace('"id": int(cur.lastrowid),', '"id": int(cur.lastrowid or 0),')
s = s.replace("-> dict | None:", "-> dict[str, Any] | None:")
s = s.replace("-> list[dict]:", "-> list[dict[str, Any]]:")
s = s.replace("spec: dict,", "spec: dict[str, Any],")
s = s.replace("findings: list[dict]", "findings: list[dict[str, Any]]")
s = s.replace("payload: dict | None = None", "payload: dict[str, Any] | None = None")
p.write_text(s, encoding="utf-8")

print("patched all four files")
