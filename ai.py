"""AI integration: user-configurable OpenAI-compatible chat completions.

The provider, key and model are configured from the web UI and stored locally
in data/ai_config.json (gitignored). The API key never leaves the backend.
"""

import copy
import json
import logging
import os
import shutil
import sys
import urllib.error
import urllib.request

import config
from parser import get_connection, get_messages

logger = logging.getLogger(__name__)


def _user_config_dir():
    """Return the per-user config directory, outside the service code tree."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "dingwave-V3")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/dingwave-V3")
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "dingwave-V3")


# Secrets live outside the repo. Override the location with DINGTALK_AI_CONFIG
# if needed; either way the file is only ever read into memory here.
AI_CONFIG_PATH = os.environ.get("DINGTALK_AI_CONFIG") or os.path.join(
    _user_config_dir(), "ai_config.json"
)
_LEGACY_CONFIG_PATH = os.path.join(config.DATA_DIR, "ai_config.json")

# In-memory cache; invalidated when the file's mtime changes or after writes.
_store_cache = None
_store_mtime = None

# Any OpenAI-compatible endpoint works (DeepSeek, Qwen/DashScope, Kimi, GLM,
# Ollama, one-api, ...). Anthropic's native protocol is not supported; put a
# gateway exposing it as OpenAI-compatible in front if needed.
DEFAULT_TEMPERATURE = 0.7
DEFAULT_MAX_TOKENS = 2000

# Roughly 30k tokens; keeps requests inside typical context windows.
MAX_CONTEXT_CHARS = 120_000
REQUEST_TIMEOUT = 180

SYSTEM_PROMPT = (
    "You are an assistant that analyzes DingTalk chat transcripts. "
    "Answer in the same language as the user's request. "
    "Base your answer only on the provided transcript, and say so when "
    "the information needed is missing. Be concise and use Markdown."
)


def _model_id(base_url, model):
    """Build the stable id used to deduplicate saved models."""
    return f"{(base_url or '').rstrip('/')}|{model or ''}"


def _normalize_entry(item):
    """Return a model entry with defaults filled in."""
    return {
        "base_url": (item.get("base_url") or "").strip(),
        "model": (item.get("model") or "").strip(),
        "api_key": item.get("api_key") or "",
        "temperature": float(item.get("temperature", DEFAULT_TEMPERATURE)),
        "max_tokens": int(item.get("max_tokens", DEFAULT_MAX_TOKENS)),
    }


def _migrate_legacy_config():
    """Move a config left in the old in-repo data/ path to the user config dir."""
    if os.path.isfile(AI_CONFIG_PATH) or not os.path.isfile(_LEGACY_CONFIG_PATH):
        return
    try:
        os.makedirs(os.path.dirname(AI_CONFIG_PATH), exist_ok=True)
        shutil.move(_LEGACY_CONFIG_PATH, AI_CONFIG_PATH)
        os.chmod(AI_CONFIG_PATH, 0o600)
        logger.info(f"Moved AI config out of the service directory: {AI_CONFIG_PATH}")
    except OSError as e:
        logger.warning(f"Failed to migrate legacy AI config: {e}")


def _load_store():
    """Read the local model store: {"active": id, "models": [...]}.

    The local file is authoritative and is cached in memory (reloaded when
    its mtime changes). A legacy single-config file is migrated to the list
    format in memory.
    """
    global _store_cache, _store_mtime

    _migrate_legacy_config()
    if not os.path.isfile(AI_CONFIG_PATH):
        return {"active": "", "models": []}

    try:
        mtime = os.path.getmtime(AI_CONFIG_PATH)
    except OSError:
        mtime = None

    if _store_cache is not None and mtime == _store_mtime:
        return copy.deepcopy(_store_cache)

    store = {"active": "", "models": []}
    try:
        with open(AI_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"Failed to load AI config: {e}")
        return store

    if isinstance(data.get("models"), list):
        entries = data["models"]
    elif data.get("base_url") and data.get("model"):
        entries = [data]  # legacy single-model file
    else:
        entries = []

    seen = set()
    for item in entries:
        if not isinstance(item, dict):
            continue
        entry = _normalize_entry(item)
        if not entry["base_url"] or not entry["model"]:
            continue
        mid = _model_id(entry["base_url"], entry["model"])
        if mid in seen:
            continue
        seen.add(mid)
        store["models"].append(entry)

    active = data.get("active") or ""
    if active not in seen:
        active = next(
            (_model_id(m["base_url"], m["model"]) for m in store["models"]), ""
        )
    store["active"] = active
    _store_cache = store
    _store_mtime = mtime
    return copy.deepcopy(store)


def _write_store(store):
    """Persist the model store atomically with owner-only permissions."""
    global _store_cache, _store_mtime

    os.makedirs(os.path.dirname(AI_CONFIG_PATH), exist_ok=True)
    tmp_path = AI_CONFIG_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(tmp_path, 0o600)
    except OSError:
        # Windows ACLs are not managed by chmod; the file stays user-scoped
        # under %APPDATA% either way.
        pass
    os.replace(tmp_path, AI_CONFIG_PATH)

    _store_cache = copy.deepcopy(store)
    try:
        _store_mtime = os.path.getmtime(AI_CONFIG_PATH)
    except OSError:
        _store_mtime = None


def get_active_config():
    """Return the currently selected model entry, or None if unconfigured."""
    store = _load_store()
    for entry in store["models"]:
        if _model_id(entry["base_url"], entry["model"]) == store["active"]:
            return entry
    return None


def save_config(data):
    """Add or update a model in the local store and make it active.

    Models are deduplicated by (base_url, model): saving an existing pair
    updates it in place instead of appending a duplicate. An empty api_key
    keeps the previously saved key for that entry.
    """
    base_url = (data.get("base_url") or "").strip()
    model = (data.get("model") or "").strip()
    if not base_url or not model:
        raise ValueError("base_url and model are required")

    store = _load_store()
    mid = _model_id(base_url, model)
    entry = next(
        (m for m in store["models"] if _model_id(m["base_url"], m["model"]) == mid),
        None,
    )
    if entry is None:
        entry = _normalize_entry({"base_url": base_url, "model": model})
        store["models"].append(entry)

    entry["base_url"] = base_url
    entry["model"] = model
    if (data.get("api_key") or "").strip():
        entry["api_key"] = data["api_key"].strip()
    if data.get("temperature") is not None:
        entry["temperature"] = float(data["temperature"])
    if data.get("max_tokens") is not None:
        entry["max_tokens"] = int(data["max_tokens"])

    store["active"] = mid
    _write_store(store)
    return store


def set_active(model_id):
    """Select one of the locally saved models as the active one."""
    store = _load_store()
    if not any(_model_id(m["base_url"], m["model"]) == model_id for m in store["models"]):
        raise ValueError("Model not found in local config")
    store["active"] = model_id
    _write_store(store)


def _public_entry(entry):
    """Return a model entry safe to expose to the frontend (key never included)."""
    return {
        "id": _model_id(entry["base_url"], entry["model"]),
        "base_url": entry["base_url"],
        "model": entry["model"],
        "temperature": entry["temperature"],
        "max_tokens": entry["max_tokens"],
        "has_key": bool(entry.get("api_key")),
    }


def public_config():
    """Return saved models and the active one, with API keys masked."""
    store = _load_store()
    models = [_public_entry(m) for m in store["models"]]
    active = next((m for m in models if m["id"] == store["active"]), None)
    return {
        "configured": active is not None,
        "active": active,
        "models": models,
    }


def _completions_url(base_url):
    """Build the chat completions URL from a base URL."""
    url = base_url.rstrip("/")
    if url.endswith("/chat/completions"):
        return url
    return url + "/chat/completions"


def _build_request(cfg, messages, stream=False, temperature=None, max_tokens=None):
    """Build the chat-completions request for the active model."""
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": cfg["temperature"] if temperature is None else temperature,
        "max_tokens": cfg["max_tokens"] if max_tokens is None else max_tokens,
    }
    if stream:
        payload["stream"] = True

    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        headers["Authorization"] = "Bearer " + cfg["api_key"]

    return urllib.request.Request(
        _completions_url(cfg["base_url"]),
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )


def _open(req):
    """Open a request, converting transport errors into RuntimeError."""
    try:
        return urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"AI API returned HTTP {e.code}: {detail}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Cannot reach AI API: {e.reason}")
    except OSError as e:
        # Covers timeouts and dropped connections (http.client errors are OSError)
        raise RuntimeError(f"AI API request failed: {e}")


def chat(messages, temperature=None, max_tokens=None):
    """Send messages to the configured model and return the reply text."""
    cfg = get_active_config()
    if not cfg:
        raise ValueError("AI is not configured yet")

    req = _build_request(cfg, messages, temperature=temperature, max_tokens=max_tokens)
    with _open(req) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return _extract_answer(body)


def stream_chat(messages):
    """Stream a completion, yielding ("reasoning"|"content", text) deltas.

    Providers that ignore stream=true and return one JSON body are handled by
    a fallback that emits the whole answer as a single content delta.
    """
    cfg = get_active_config()
    if not cfg:
        raise ValueError("AI is not configured yet")

    req = _build_request(cfg, messages, stream=True)
    with _open(req) as resp:
        if resp.headers.get_content_type() != "text/event-stream":
            body = json.loads(resp.read().decode("utf-8"))
            answer = _extract_answer(body)
            if answer:
                yield ("content", answer)
            return

        for raw_line in resp:
            line = raw_line.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data:
                continue
            if data == "[DONE]":
                return
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue

            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            reasoning = delta.get("reasoning_content") or delta.get("reasoning") or ""
            content = delta.get("content") or ""
            if reasoning:
                yield ("reasoning", reasoning)
            if content:
                yield ("content", content)


def _extract_answer(body):
    """Extract the assistant text from an OpenAI-compatible response."""
    choices = body.get("choices") or []
    if not choices:
        raise RuntimeError(f"AI response has no choices: {str(body)[:300]}")
    content = (choices[0].get("message") or {}).get("content") or ""
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    return content.strip()


def test_connection():
    """Send a tiny prompt to verify the configured endpoint works."""
    return chat([{"role": "user", "content": "Reply with OK."}], max_tokens=16)


def _conversation_title(conn, cid):
    """Look up a conversation title by cid."""
    row = conn.execute(
        "SELECT title FROM tbconversation WHERE cid = ?", (cid,)
    ).fetchone()
    return (row["title"] if row and row["title"] else cid)


def build_transcript(conn, cid, limit):
    """Build a plain-text transcript of the newest `limit` messages.

    The oldest lines are dropped when the transcript exceeds MAX_CONTEXT_CHARS,
    so the most recent context always survives the truncation.
    """
    data = get_messages(conn, cid, limit=limit)
    messages = data.get("messages", [])

    lines = []
    for msg in messages:
        text = (msg.get("text") or "").strip()
        if not text:
            continue
        sender = msg.get("sender_name") or str(msg.get("sender_id") or "")
        lines.append(f"[{msg.get('created_at_str', '')}] {sender}: {text}")

    kept = []
    budget = MAX_CONTEXT_CHARS
    for line in reversed(lines):
        if len(line) + 1 > budget:
            break
        kept.append(line)
        budget -= len(line) + 1

    kept.reverse()
    return "\n".join(kept), len(kept), data.get("total", 0)


def analyze_stream(cid, prompt, limit=200):
    """Stream an analysis as event dicts: meta / reasoning / content / done.

    Raises ValueError/RuntimeError on configuration or provider problems;
    the caller is expected to catch them while consuming the generator.
    """
    conn = get_connection()
    try:
        title = _conversation_title(conn, cid)
        transcript, used, total = build_transcript(conn, cid, limit)
    finally:
        conn.close()

    if not transcript:
        raise ValueError("No text messages to analyze in this conversation")

    cfg = get_active_config()
    if not cfg:
        raise ValueError("AI is not configured yet")

    yield {
        "type": "meta",
        "model": cfg["model"],
        "messages_used": used,
        "messages_total": total,
    }

    user_content = (
        f"Conversation: {title}\n\n"
        f"--- Chat transcript (oldest first) ---\n{transcript}\n--- End ---\n\n"
        f"User request:\n{prompt}"
    )
    for kind, text in stream_chat(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
    ):
        yield {"type": kind, "text": text}

    yield {"type": "done"}
