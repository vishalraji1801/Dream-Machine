"""
Config editor — read current values for the editable schema, validate proposed
changes against the schema bounds, and write them back to config.yaml while
preserving comments and formatting (ruamel round-trip).

The bot loads config once at startup, so edits take effect on the next bot start
(the UI says as much). Nothing here can change a value outside the schema.
"""
import os
import re
from typing import Any

from ruamel.yaml import YAML

from webapp.config_schema import SCHEMA, field_index

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096  # don't wrap long lines
    return y


def _dig(node: Any, path: str) -> Any:
    cur = node
    for part in path.split("."):
        if cur is None or part not in cur:
            return None
        cur = cur[part]
    return cur


def _is_int_field(f) -> bool:
    vals = [v for v in (f.min, f.max, f.step) if v is not None]
    return bool(vals) and all(float(v).is_integer() for v in vals) and f.unit != "%"


def _plain(v: Any) -> Any:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float, str)):
        return v
    return str(v)


# ── read ──────────────────────────────────────────────────────────────────────

def read_config(config_path: str) -> dict:
    """Return groups + current values for the editor UI."""
    with open(config_path, encoding="utf-8") as f:
        doc = _yaml().load(f)

    groups = []
    for g in SCHEMA:
        section = doc.get(g.section, {}) or {}
        fields = []
        for fld in g.fields:
            fields.append({
                "key": fld.key, "label": fld.label, "type": fld.type,
                "min": fld.min, "max": fld.max, "step": fld.step, "unit": fld.unit,
                "options": list(fld.options), "help": fld.help,
                "value": _plain(_dig(section, fld.key)),
            })
        groups.append({"section": g.section, "label": g.label, "fields": fields})
    return {"groups": groups}


# ── validate ──────────────────────────────────────────────────────────────────

def _coerce_and_validate(fld, section: str, raw: Any) -> Any:
    """Return the coerced value or raise ValueError with a UI-friendly message."""
    where = f"{section}.{fld.key}"
    if fld.type == "bool":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            return raw.strip().lower() in ("true", "1", "yes", "on")
        raise ValueError(f"{where}: expected a boolean")
    if fld.type == "select":
        if raw not in fld.options:
            raise ValueError(f"{where}: must be one of {list(fld.options)}")
        return raw
    if fld.type == "time":
        if not (isinstance(raw, str) and _TIME_RE.match(raw)):
            raise ValueError(f"{where}: must be HH:MM (24h)")
        return raw
    if fld.type == "text":
        return "" if raw is None else str(raw)
    if fld.type == "number":
        try:
            num = float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{where}: must be a number")
        if fld.min is not None and num < fld.min:
            raise ValueError(f"{where}: min is {fld.min}")
        if fld.max is not None and num > fld.max:
            raise ValueError(f"{where}: max is {fld.max}")
        return int(round(num)) if _is_int_field(fld) else round(num, 6)
    raise ValueError(f"{where}: unknown field type {fld.type}")


def validate_updates(updates: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """
    updates: {section: {key: value}}. Returns the same shape with coerced values.
    Raises ValueError on the first unknown field or out-of-bounds value.
    """
    index = field_index()
    clean: dict[str, dict[str, Any]] = {}
    for section, kv in updates.items():
        for key, value in kv.items():
            hit = index.get(f"{section}.{key}")
            if hit is None:
                raise ValueError(f"{section}.{key} is not an editable field")
            _, fld = hit
            clean.setdefault(section, {})[key] = _coerce_and_validate(fld, section, value)
    return clean


# ── write ─────────────────────────────────────────────────────────────────────

def apply_updates(config_path: str, updates: dict[str, dict[str, Any]]) -> dict:
    """Validate then write. Atomic replace; comments preserved."""
    clean = validate_updates(updates)
    yaml = _yaml()
    with open(config_path, encoding="utf-8") as f:
        doc = yaml.load(f)

    for section, kv in clean.items():
        node = doc.setdefault(section, {})
        for key, value in kv.items():
            parts = key.split(".")
            target = node
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            target[parts[-1]] = value

    tmp = config_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        yaml.dump(doc, f)
    os.replace(tmp, config_path)
    return read_config(config_path)
