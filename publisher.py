"""Publish text or image posts through the installed Binance Square skill."""
from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Iterable, List, Optional, Union

from runtime import PROJECT_DIR
import publication_intent as intents
from text_integrity import sanitize_safe_markup
from production_guard import final_text_reasons

logger = logging.getLogger(__name__)

ImageInput = Optional[Union[str, Iterable[str]]]


@dataclass(frozen=True)
class PublishResult:
    success: bool
    post_id: str = ""
    stdout: str = ""
    stderr: str = ""
    returncode: int = -1

    def __bool__(self) -> bool:
        return self.success


def _existing_images(image_path: ImageInput) -> List[str]:
    if image_path is None:
        return []
    candidates = [image_path] if isinstance(image_path, str) else list(image_path)
    result = []
    for candidate in candidates:
        path = Path(str(candidate)).expanduser().resolve()
        if path.is_file():
            result.append(str(path))
        else:
            logger.warning("Skipping missing image: %s", candidate)
    return result


def _extract_post_id(stdout: str) -> str:
    text = str(stdout or "").strip()
    if not text:
        return ""
    try:
        payload = json.loads(text)
        stack = [payload]
        while stack:
            current = stack.pop()
            if isinstance(current, dict):
                for key, value in current.items():
                    if str(key).lower() in {"contentid", "postid"} and value not in (None, ""):
                        return str(value)
                    stack.append(value)
            elif isinstance(current, list):
                stack.extend(current)
    except (ValueError, TypeError):
        pass
    patterns = (
        r'"(?:contentId|postId)"\s*:\s*"?([A-Za-z0-9_-]+)',
        r"(?:Content ID|Post ID)\s*[:=]\s*([A-Za-z0-9_-]+)",
        r"Success!\s*ID\s*[:=]\s*([A-Za-z0-9_-]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return ""


def normalize_square_cashtags(text: str) -> str:
    """Keep Binance Square cashtags isolated from colon punctuation."""
    value = str(text or "")
    return re.sub(r"(\$[A-Za-z][A-Za-z0-9]{0,19})\s*[:：]", r"\1 —", value)


def _prepare_text_for_square(text: str) -> tuple[str, tuple[str, ...]]:
    """Safe final-boundary cleanup plus a hard artifact gate."""
    original = str(text or "")
    text = sanitize_safe_markup(original)
    normalized = normalize_square_cashtags(text)
    reasons = final_text_reasons(normalized)
    return normalized, reasons


def publish(text: str, image_path: ImageInput = None) -> PublishResult:
    if not text or not text.strip():
        logger.error("Refusing to publish an empty post")
        return PublishResult(False, stderr="empty post")

    prepared, reasons = _prepare_text_for_square(text)
    if reasons:
        diagnostic = ", ".join(reasons)
        logger.error("Refusing to publish text with integrity artifacts: %s", diagnostic)
        return PublishResult(False, stderr=f"text integrity: {diagnostic}")
    if prepared != text:
        logger.info("Normalized Square text/cashtag formatting before publish")
    text = prepared

    if not text.strip():
        logger.error("Refusing to publish a post emptied by text cleanup")
        return PublishResult(False, stderr="empty post after cleanup")

    skill_dir = find_skill_dir()
    if not skill_dir:
        logger.error("Binance Square skill directory not found")
        return PublishResult(False, stderr="skill not found")

    api_key = (os.getenv("SQUARE_API") or os.getenv("BINANCE_SQUARE_OPENAPI_KEY") or "").strip()
    if not api_key:
        logger.error("No Binance Square API key configured")
        return PublishResult(False, stderr="API key missing")

    environment = os.environ.copy()
    environment["BINANCE_SQUARE_OPENAPI_KEY"] = api_key
    images = _existing_images(image_path)

    if images:
        script = Path(skill_dir) / "scripts" / "post-image.mjs"
        command = ["node", str(script), "--text", text, "--images", ",".join(images)]
        logger.info("Publishing image post (%s chars, %s image(s))", len(text), len(images))
    else:
        script = Path(skill_dir) / "scripts" / "post-text.mjs"
        command = ["node", str(script), "--text", text]
        logger.info("Publishing text post (%s chars)", len(text))

    if not script.is_file():
        logger.error("Publish script does not exist: %s", script)
        return PublishResult(False, stderr=f"script missing: {script}")

    try:
        rows = intents.load_intents()
        previous = rows.get(intents.fingerprint(text))
        if previous:
            # A prior confirmed receipt is not a new publication success: do not
            # duplicate cooldowns, analytics or outcome metadata in the caller.
            post_id = previous.get("post_id") or intents.reconcile(text, previous)
            return PublishResult(False, post_id=post_id, stderr="prior send already exists; resend blocked")
        symbols = set(re.findall(r"\$([A-Za-z][A-Za-z0-9]{0,19})", text.upper()))
        if any(row.get("status") == "pending" and symbols.intersection(row.get("symbols", [])) for row in rows.values()):
            return PublishResult(False, stderr="unresolved send for this symbol; publication blocked")
        intent = intents.begin(text)
    except (OSError, ValueError, TypeError) as exc:
        return PublishResult(False, stderr=f"send journal unavailable: {exc}")

    try:
        result = subprocess.run(
            command,
            cwd=skill_dir,
            env=environment,
            capture_output=True,
            text=True,
            timeout=int(os.getenv("PUBLISH_TIMEOUT", "90")),
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.error("Binance Square publication timed out")
        post_id = intents.reconcile(text, intent)
        if post_id:
            return PublishResult(True, post_id=post_id, stderr="timeout reconciled from public profile")
        return PublishResult(False, stderr="timeout; unresolved send saved, resend blocked")
    except (OSError, ValueError) as exc:
        logger.error("Publication process failed: %s", exc)
        return PublishResult(False, stderr=str(exc))

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if stdout:
        logger.info("Publisher output: %s", stdout[:1200])
    if stderr:
        logger.warning("Publisher stderr: %s", stderr[:1200])

    post_id = _extract_post_id(stdout)
    if post_id.lower() in {"unavailable", "undefined", "null", "none", "false", "n/a", "0"}:
        post_id = ""
    # Exit 0 (including empty stdout or a help message) is not confirmation.
    # Never add a fictitious success to cooldown/history/outcome tracking.
    explicit_failure = bool(re.search(r'"success"\s*:\s*false|"error"\s*:\s*[{"\[]', stdout, re.I))
    success = result.returncode == 0 and bool(post_id) and not explicit_failure
    if success:
        intents.confirm(text, post_id)
        return PublishResult(True, post_id=post_id, stdout=stdout, stderr=stderr, returncode=result.returncode)

    post_id = intents.reconcile(text, intent)
    if post_id:
        return PublishResult(True, post_id=post_id, stdout=stdout, stderr=stderr, returncode=result.returncode)
    logger.error("Publication unconfirmed (exit code %s); intent retained", result.returncode)
    return PublishResult(False, post_id=post_id, stdout=stdout, stderr=stderr, returncode=result.returncode)


def find_skill_dir() -> Optional[str]:
    roots = [
        PROJECT_DIR,
        Path(os.getenv("GITHUB_WORKSPACE", PROJECT_DIR)),
        Path.cwd(),
        Path.home(),
    ]
    explicit = (os.getenv("SQUARE_SKILL_DIR") or "").strip()
    candidates = [Path(explicit)] if explicit else []
    for root in roots:
        candidates.extend(
            [
                root / ".agents" / "skills" / "square-post",
                root / "node_modules" / "@binance" / "square-post",
                root / "skills" / "binance" / "square-post",
            ]
        )

    seen = set()
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        scripts = resolved / "scripts"
        if (scripts / "post-text.mjs").is_file() or (scripts / "post-image.mjs").is_file():
            return str(resolved)
    return None
