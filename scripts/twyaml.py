from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


class YamlLiteError(Exception):
    pass


_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
_INT_RE = re.compile(r"^-?[0-9]+$")
# Match simple decimals like 1.0, -0.25.
_FLOAT_RE = re.compile(r"^-?[0-9]+[.][0-9]+$")


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _next_nonblank(lines: list[str], idx: int) -> int:
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    return idx


def _parse_scalar(text: str) -> Any:
    t = text.strip()
    if t == "":
        return ""
    if t == "[]":
        return []
    if t == "{}":
        return {}
    if t in {"null", "~"}:
        return None
    if t in {"true", "True"}:
        return True
    if t in {"false", "False"}:
        return False
    if _INT_RE.match(t):
        try:
            return int(t)
        except Exception:
            return t
    if _FLOAT_RE.match(t):
        try:
            return float(t)
        except Exception:
            return t
    if (t.startswith('"') and t.endswith('"')) or (t.startswith("'") and t.endswith("'")):
        quote = t[0]
        inner = t[1:-1]
        if quote == '"':
            inner = inner.replace('\\"', '"').replace("\\\\", "\\")
        if quote == "'":
            inner = inner.replace("\\'", "'").replace("\\\\", "\\")
        return inner
    return t


def _parse_block(lines: list[str], idx: int, indent: int) -> tuple[Any, int]:
    idx = _next_nonblank(lines, idx)
    if idx >= len(lines):
        return {}, idx
    line = lines[idx]
    if _indent_of(line) < indent:
        return {}, idx
    stripped = line[indent:]
    if stripped.startswith("- "):
        return _parse_list(lines, idx, indent)
    return _parse_dict(lines, idx, indent)


def _parse_dict(lines: list[str], idx: int, indent: int) -> tuple[dict[str, Any], int]:
    out: dict[str, Any] = {}
    while True:
        idx = _next_nonblank(lines, idx)
        if idx >= len(lines):
            break
        line = lines[idx]
        ind = _indent_of(line)
        if ind < indent:
            break
        if ind != indent:
            raise YamlLiteError(f"Unexpected indentation at line {idx+1}: {line!r}")
        stripped = line[ind:]
        if stripped.startswith("- "):
            raise YamlLiteError(f"Unexpected list item at line {idx+1}: {line!r}")
        if ":" not in stripped:
            raise YamlLiteError(f"Expected key:value at line {idx+1}: {line!r}")
        key, rest = stripped.split(":", 1)
        key = key.strip()
        if not _KEY_RE.match(key):
            raise YamlLiteError(f"Invalid key {key!r} at line {idx+1}")
        rest = rest.strip()
        idx += 1
        if rest == "":
            idx2 = _next_nonblank(lines, idx)
            if idx2 >= len(lines):
                out[key] = {}
                idx = idx2
                continue
            next_line = lines[idx2]
            next_ind = _indent_of(next_line)
            if next_ind <= indent:
                out[key] = {}
                idx = idx2
                continue
            val, idx = _parse_block(lines, idx2, next_ind)
            out[key] = val
        else:
            out[key] = _parse_scalar(rest)
    return out, idx


def _parse_list(lines: list[str], idx: int, indent: int) -> tuple[list[Any], int]:
    out: list[Any] = []
    while True:
        idx = _next_nonblank(lines, idx)
        if idx >= len(lines):
            break
        line = lines[idx]
        ind = _indent_of(line)
        if ind < indent:
            break
        if ind != indent:
            raise YamlLiteError(f"Unexpected indentation at line {idx+1}: {line!r}")
        stripped = line[ind:].strip()
        if not stripped.startswith("- "):
            break
        item_text = stripped[2:].strip()
        idx += 1

        if item_text == "":
            idx2 = _next_nonblank(lines, idx)
            if idx2 >= len(lines):
                out.append(None)
                idx = idx2
                continue
            next_ind = _indent_of(lines[idx2])
            if next_ind <= indent:
                out.append(None)
                idx = idx2
                continue
            val, idx = _parse_block(lines, idx2, next_ind)
            out.append(val)
            continue

        # Inline dict item: "- key: value" plus optional additional fields on following indented lines.
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*)[ ]*:[ ]*(.*)$", item_text)
        if m:
            k = m.group(1)
            rest = m.group(2)
            item: dict[str, Any] = {k: _parse_scalar(rest) if rest != "" else None}
            idx2 = _next_nonblank(lines, idx)
            if idx2 < len(lines):
                next_ind = _indent_of(lines[idx2])
                if next_ind > indent:
                    extra, idx = _parse_dict(lines, idx2, next_ind)
                    item.update(extra)
                else:
                    idx = idx2
            out.append(item)
            continue

        out.append(_parse_scalar(item_text))
    return out, idx


def parse_yaml_lite(text: str) -> dict[str, Any]:
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    idx = _next_nonblank(lines, 0)
    if idx >= len(lines):
        return {}
    obj, idx2 = _parse_block(lines, idx, 0)
    if not isinstance(obj, dict):
        raise YamlLiteError("Top-level frontmatter must be a dict")
    return obj


def _needs_quotes(s: str) -> bool:
    if s == "":
        return True
    if s.strip() != s:
        return True
    if s.startswith(("-", "?", ":", "#", "[", "]", "{", "}", "&", "*", "!", "|", ">", "@", "`")):
        return True
    if ":" in s:
        return True
    if "#" in s:
        return True
    return False


def _dump_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value)
    if _needs_quotes(s):
        esc = s.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{esc}"'
    return s


def dump_yaml_lite(obj: dict[str, Any], indent: int = 0) -> str:
    def dump_any(value: Any, ind: int) -> list[str]:
        pad = " " * ind
        if isinstance(value, dict):
            if not value:
                return [pad + "{}"]
            lines: list[str] = []
            for k, v in value.items():
                if isinstance(v, (dict, list)):
                    if isinstance(v, dict) and not v:
                        lines.append(f"{pad}{k}: {{}}")
                    elif isinstance(v, list) and not v:
                        lines.append(f"{pad}{k}: []")
                    else:
                        lines.append(f"{pad}{k}:")
                        lines.extend(dump_any(v, ind + 2))
                else:
                    lines.append(f"{pad}{k}: {_dump_scalar(v)}")
            return lines
        if isinstance(value, list):
            if not value:
                return [pad + "[]"]
            lines = []
            for item in value:
                if isinstance(item, dict):
                    if not item:
                        lines.append(pad + "- {}")
                        continue
                    # Put the first key on the same line for readability.
                    first_key = next(iter(item.keys()))
                    first_val = item[first_key]
                    if isinstance(first_val, (dict, list)):
                        lines.append(pad + "-")
                        lines.extend(dump_any(item, ind + 2))
                        continue
                    lines.append(pad + f"- {first_key}: {_dump_scalar(first_val)}")
                    rest = {k: v for k, v in item.items() if k != first_key}
                    if rest:
                        lines.extend(dump_any(rest, ind + 2))
                    continue
                if isinstance(item, list):
                    lines.append(pad + "-")
                    lines.extend(dump_any(item, ind + 2))
                    continue
                lines.append(pad + f"- {_dump_scalar(item)}")
            return lines
        return [pad + _dump_scalar(value)]

    lines = dump_any(obj, indent)
    return "\n".join(lines).rstrip() + "\n"


@dataclass
class MarkdownDoc:
    frontmatter: dict[str, Any]
    body: str


def split_frontmatter(text: str) -> MarkdownDoc:
    if not text.startswith("---\n") and text.strip() != "---":
        return MarkdownDoc(frontmatter={}, body=text)
    lines = text.splitlines(keepends=True)
    if not lines or not lines[0].startswith("---"):
        return MarkdownDoc(frontmatter={}, body=text)
    # Find closing delimiter
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        raise YamlLiteError("Frontmatter started with --- but no closing --- found")
    fm_text = "".join(lines[1:end])
    body = "".join(lines[end + 1 :])
    fm = parse_yaml_lite(fm_text)
    return MarkdownDoc(frontmatter=fm, body=body.lstrip("\n"))


def join_frontmatter(doc: MarkdownDoc) -> str:
    fm = dump_yaml_lite(doc.frontmatter).rstrip("\n")
    body = doc.body or ""
    if not body.endswith("\n"):
        body += "\n"
    return f"---\n{fm}\n---\n\n{body}"
