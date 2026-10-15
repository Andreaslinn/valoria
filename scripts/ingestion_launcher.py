"""Host-safe structured child diagnostics; no arbitrary stdout/stderr forwarding."""
import json
import re

COUNTERS = {"inserted", "updated", "known_unchanged", "skipped", "raw_cards", "unique_cards",
            "raw_cards_http", "valid_cards", "persisted_from_card", "persisted_from_detail",
            "pending_uf", "pending_uf_reprocessed", "validation_errors", "unexpected_errors",
            "blocked_or_captcha", "fetch_errors", "geo_stage_errors", "scraped", "raw_scraped", "discarded"}


def sanitize_error(value):
    if not isinstance(value, dict):
        return {"type": "UnknownChildError", "stage": "container"}
    result = {}
    for key in ("type", "stage"):
        text = str(value.get(key, "unknown"))
        result[key] = text if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", text) else "redacted"
    if value.get("reason") == "UF real no disponible":
        result["reason"] = value["reason"]
    frames = []
    for frame in value.get("frames", [])[-8:]:
        if not isinstance(frame, dict):
            continue
        if (re.fullmatch(r"[A-Za-z0-9_]+\.py", str(frame.get("file", "")))
            and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(frame.get("function", "")))
            and isinstance(frame.get("line"), int)):
            frames.append({k: frame[k] for k in ("file", "line", "function")})
    result["frames"] = frames
    return result


def summarize_process(result):
    counts, error = {}, None
    for line in result.stdout.splitlines()[-100:]:
        try:
            candidate = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(candidate, dict):
            continue
        if "error" in candidate:
            error = sanitize_error(candidate["error"])
        counts.update({k: int(v) for k, v in candidate.items() if k in COUNTERS
                       and isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v < 10**9})
    if result.returncode and error is None:
        # Legacy traceback: extract exception class and frame positions, never exception message/source lines.
        text = result.stderr[-16000:]
        names = re.findall(r"^([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception|Expired))(?::|$)", text, re.M)
        frames = [{"file": name, "line": int(line), "function": function}
                  for name, line, function in re.findall(r'File "[^"\n]*[/\\]([A-Za-z0-9_]+\.py)", line (\d+), in ([A-Za-z_][A-Za-z0-9_]*)', text)]
        error = {"type": names[-1] if names else "ChildProcessError", "stage": "container", "frames": frames[-8:]}
        if names and names[-1] == "UFServiceError":
            error["reason"] = "UF real no disponible"
    return {"exit_code": result.returncode, "counts": counts, "runtime_error": bool(result.returncode),
            "error": error}
