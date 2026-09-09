"""Render schemas/config-v1.schema.json from apiverity/core/config.py.

The config's validation rules and its published schema have to agree, and the
only reliable way to make two things agree is to have one of them produce the
other. Editors read the schema; `apiverity config validate` reads the module.
If they diverged, an editor would autocomplete a key the tool rejects.

    python scripts/generate_config_schema.py            # write
    python scripts/generate_config_schema.py --check    # verify (CI)
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from apiverity.core.config import json_schema

TARGET = pathlib.Path(__file__).resolve().parents[1] / "schemas" / "config-v1.schema.json"


def render() -> str:
    return json.dumps(json_schema(), indent=2) + "\n"


def main() -> int:
    rendered = render()
    previous = TARGET.read_text(encoding="utf-8") if TARGET.is_file() else None
    if previous == rendered:
        print(f"ok     {TARGET.name}")
        return 0
    if "--check" in sys.argv:
        print(
            "error: schemas/config-v1.schema.json is stale; run scripts/generate_config_schema.py",
            file=sys.stderr,
        )
        return 1
    TARGET.write_text(rendered, encoding="utf-8")
    print(f"wrote  {TARGET.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
