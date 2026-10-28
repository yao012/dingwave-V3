import os
import sys
import logging

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

logger = logging.getLogger(__name__)


def _detect_dingtalk_version(data_dir):
    """Detect DingTalk version (v2 or v3) from the data directory path."""
    if data_dir and "_v3" in os.path.basename(data_dir):
        return 3
    return 2


def _read_v3_salt(data_dir):
    """Read the salt from V3's user_config file.

    V3 stores a base64-encoded JSON in {data_dir}/user_config containing
    a 'salt' field needed for key derivation.
    Returns the salt hex string, or None if not found.
    """
    import base64
    import json

    user_config_path = os.path.join(data_dir, "user_config")
    if not os.path.isfile(user_config_path):
        logger.warning(f"V3 user_config not found: {user_config_path}")
        return None

    try:
        with open(user_config_path, "r") as f:
            raw = f.read().strip()
        decoded = base64.b64decode(raw).decode("utf-8")
        config_data = json.loads(decoded)
        salt = config_data.get("salt")
        if salt:
            logger.info(f"V3 salt loaded from user_config ({len(salt)} chars)")
            return salt
        logger.warning("V3 user_config has no 'salt' field")
        return None
    except Exception as e:
        logger.error(f"Failed to read V3 user_config: {e}")
        return None


def _read_redirected_appdata():
    """Read DingTalk's redirectAppData.dat and return the custom data roots.

    DingTalk lets users (or the installer) move its data directory elsewhere.
    The chosen root is stored in {APPDATA}/DingTalk/redirectAppData.dat and
    contains the *_v2 / *_v3 user folders directly (not a DingTalk subfolder).
    """
    roots = []
    for base in (os.environ.get("APPDATA"), os.environ.get("LOCALAPPDATA")):
        if not base:
            continue
        redirect_file = os.path.join(base, "DingTalk", "redirectAppData.dat")
        if not os.path.isfile(redirect_file):
            continue
        try:
            with open(redirect_file, "r", encoding="utf-8", errors="ignore") as f:
                root = f.readline().strip().strip('"').strip()
        except OSError as e:
            logger.debug(f"Failed to read {redirect_file}: {e}")
            continue
        if not root or not os.path.isdir(root):
            logger.debug(f"Ignoring redirected data root (not found): {root}")
            continue
        logger.info(f"Detected redirected DingTalk data root: {root}")
        roots.append(root)
        roots.append(os.path.join(root, "DingTalk"))
    return roots


def _detect_v3_uid_from_logs(data_dir):
    """Detect the numeric V3 UID on Windows from DingTalk's gaea log.

    V3 logs lines like `uid=35984434@dingding` / `real_uid=35984434@dingding`.
    The logs live in {parent_of_data_dir}/log, so the newest ones are scanned
    from the tail (they can be tens of MB).
    """
    if sys.platform != "win32":
        return None

    import glob
    import re

    log_dir = os.path.join(os.path.dirname(os.path.normpath(data_dir)), "log")
    log_files = sorted(
        glob.glob(os.path.join(log_dir, "gaea.log*")),
        key=os.path.getmtime,
        reverse=True,
    )
    pattern = re.compile(rb"(?:real_)?uid=(\d+)@dingding")
    for path in log_files[:3]:
        try:
            size = os.path.getsize(path)
            with open(path, "rb") as f:
                f.seek(max(0, size - 2 * 1024 * 1024))
                chunk = f.read()
            matches = pattern.findall(chunk)
            if matches:
                uid = matches[-1].decode()
                logger.info(f"Auto-detected V3 UID from DingTalk logs: {uid}")
                return uid
        except OSError as e:
            logger.debug(f"Failed to scan {path} for UID: {e}")
    return None


def _detect_v3_uid_from_plist():
    """Try to detect the real numeric UID from DingTalk's plist on macOS.

    V3 uses a short numeric UID (9-10 digits) for key derivation, which is
    different from the folder name. On macOS, it can be found in the
    SafeModeKey.safemode_last_crash_uid field of the DingTalk plist.
    """
    if sys.platform != "darwin":
        return None

    import plistlib

    plist_path = os.path.expanduser(
        "~/Library/Containers/5ZSL2CJU2T.com.dingtalk.mac/"
        "Data/Library/Preferences/5ZSL2CJU2T.com.dingtalk.mac.plist"
    )
    if not os.path.isfile(plist_path):
        return None

    try:
        with open(plist_path, "rb") as f:
            plist = plistlib.load(f)
        safe_mode = plist.get("SafeModeKey", {})
        if isinstance(safe_mode, dict):
            uid_val = safe_mode.get("safemode_last_crash_uid")
            if uid_val:
                return str(uid_val)
    except Exception as e:
        logger.debug(f"Failed to read plist for UID: {e}")
    return None


def _detect_dingtalk_user():
    """Auto-detect DingTalk user data directory, UID, version, and V3 salt.

    Scans multiple possible DingTalk data directories for *_v2 / *_v3 folders.
    Returns (data_dir, uid, version, salt) or (None, None, 2, None) if not found.

    For V3, the UID used for key derivation is a short numeric ID (9-10 digits),
    NOT the folder name. It is read from the macOS plist, from DingTalk's Windows
    logs, or can be set via DINGTALK_UID environment variable.

    Override with environment variables:
      DINGTALK_UID       — your DingTalk user UID (numeric, for key derivation)
      DINGTALK_DATA_DIR  — full path to the *_v2 or *_v3 directory
    """
    # Environment variables take highest priority
    env_uid = os.environ.get("DINGTALK_UID", "").strip()
    env_dir = os.environ.get("DINGTALK_DATA_DIR", "").strip()

    if env_uid and env_dir:
        version = _detect_dingtalk_version(env_dir)
        salt = _read_v3_salt(env_dir) if version == 3 else None
        logger.info(f"Using config from environment: UID={env_uid}, version=v{version}")
        return env_dir, env_uid, version, salt

    # Multiple possible DingTalk base directories (ordered by likelihood)
    search_bases = []
    # A redirected data root supersedes the default locations.
    search_bases.extend(_read_redirected_appdata())
    appdata = os.environ.get("APPDATA", "")
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    userprofile = os.environ.get("USERPROFILE", "")

    if appdata:
        search_bases.append(os.path.join(appdata, "DingTalk"))
    if local_appdata and local_appdata != appdata:
        search_bases.append(os.path.join(local_appdata, "DingTalk"))
    if userprofile:
        search_bases.append(os.path.join(userprofile, "AppData", "Roaming", "DingTalk"))
        search_bases.append(os.path.join(userprofile, "AppData", "Local", "DingTalk"))
        search_bases.append(os.path.join(userprofile, "DingTalk"))

    # macOS and Linux paths
    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        container_base = os.path.join(home, "Library", "Containers", "5ZSL2CJU2T.com.dingtalk.mac", "Data", "Library", "Application Support", "DingTalkMac")
        search_bases.append(container_base)
        search_bases.append(os.path.join(home, "Library", "Application Support", "DingTalk"))
    elif sys.platform.startswith("linux"):
        search_bases.append(os.path.join(home, ".config", "DingTalk"))
        search_bases.append(os.path.join(home, ".local", "share", "DingTalk"))

    # Deduplicate while preserving order
    seen = set()
    unique_bases = []
    for b in search_bases:
        b_norm = os.path.normcase(os.path.normpath(b))
        if b_norm not in seen:
            seen.add(b_norm)
            unique_bases.append(b)
    search_bases = unique_bases

    # Find all *_v2 / *_v3 user directories that have a database file
    found_dirs = []
    for dingtalk_base in search_bases:
        if not os.path.isdir(dingtalk_base):
            continue
        for entry in os.listdir(dingtalk_base):
            if entry.endswith(("_v2", "_v3")):
                full_path = os.path.join(dingtalk_base, entry)
                if os.path.isdir(full_path):
                    db_file = os.path.join(full_path, "DBFiles", "dingtalk.db")
                    if os.path.exists(db_file):
                        folder_id = entry.rsplit("_v", 1)[0]
                        version = _detect_dingtalk_version(full_path)
                        mtime = os.path.getmtime(db_file)
                        found_dirs.append((folder_id, full_path, mtime, version))

    if not found_dirs:
        return None, None, 2, None

    # Prefer V3 over V2, then most recently modified
    found_dirs.sort(key=lambda x: (x[3], x[2]), reverse=True)
    folder_id, path, _, version = found_dirs[0]

    # For V3, the real UID is NOT the folder name — it's a short numeric ID
    if version == 3:
        uid = _detect_v3_uid_from_plist() or _detect_v3_uid_from_logs(path)
        if uid:
            logger.info(f"Auto-detected V3 UID from plist: {uid}")
        else:
            uid = folder_id
            logger.warning(
                f"Could not detect V3 numeric UID from plist, using folder name: {uid}\n"
                f"Set DINGTALK_UID environment variable to the correct numeric UID."
            )
        salt = _read_v3_salt(path)
    else:
        uid = folder_id
        salt = None

    if len(found_dirs) == 1:
        logger.info(f"Auto-detected DingTalk user: UID={uid}, version=v{version}")
    else:
        all_info = [f"  {fid} (v{v}, path={p})" for fid, p, _, v in found_dirs]
        logger.warning(
            f"Multiple DingTalk users found, using v{version} (UID={uid}):\n"
            + "\n".join(all_info)
            + "\nTo use a different user, set DINGTALK_UID and DINGTALK_DATA_DIR."
        )

    return path, uid, version, salt


def _detect_dingwave():
    """Auto-detect the dingwave binary in the tools/ directory.

    Checks multiple possible filenames to handle:
    - Platform differences (dingwave.exe vs dingwave)
    - Users who rename or download with different names
    """
    tools_dir = os.path.join(PROJECT_DIR, "tools")
    candidates = []

    if sys.platform == "win32":
        candidates = ["dingwave.exe", "dingwave"]
    else:
        candidates = ["dingwave", "dingwave.exe"]

    # Check exact names first
    for name in candidates:
        full = os.path.join(tools_dir, name)
        if os.path.isfile(full):
            return full

    # Fallback: find any executable-like file in tools/ with 'dingwave' in name
    if os.path.isdir(tools_dir):
        for f in os.listdir(tools_dir):
            lower = f.lower()
            if "dingwave" in lower and not lower.endswith((".md", ".txt", ".zip", ".tar", ".gz")):
                full = os.path.join(tools_dir, f)
                if os.path.isfile(full):
                    logger.info(f"Found dingwave binary: {f}")
                    return full

    # Return default (will fail later with clear message)
    return os.path.join(tools_dir, candidates[0])


# --- DingTalk data paths ---
# Auto-detection is tried first. If it fails (e.g. DingTalk not installed),
# set environment variables or edit the defaults below.
#
# Environment variables (recommended for override):
#   DINGTALK_UID       = your user UID (the number in the _v2 folder name)
#   DINGTALK_DATA_DIR  = full path to your DingTalk data directory
#
# Manual defaults (fallback when auto-detection and env vars both fail):
_detected_dir, _detected_uid, _detected_version, _detected_salt = _detect_dingtalk_user()

DINGTALK_DATA_DIR = _detected_dir or r"C:\Users\<YOUR_USERNAME>\AppData\Roaming\DingTalk\<YOUR_UID>_v2"
USER_UID = _detected_uid or "<YOUR_UID>"
DINGTALK_VERSION = _detected_version  # 2 or 3
V3_SALT = _detected_salt  # hex string, only for V3

ENCRYPTED_DB_DIR = os.path.join(DINGTALK_DATA_DIR, "DBFiles")
ENCRYPTED_DB = os.path.join(ENCRYPTED_DB_DIR, "dingtalk.db")

# dingwave tool — auto-detected
DINGWAVE_PATH = _detect_dingwave()

# Sync settings
SYNC_INTERVAL_HOURS = 4
COPY_RETRY_COUNT = 3
COPY_RETRY_DELAY = 30  # seconds

# Data directories
DATA_DIR = os.path.join(PROJECT_DIR, "data")
DECRYPTED_DIR = os.path.join(DATA_DIR, "decrypted")
EXPORT_DIR = os.path.join(DATA_DIR, "exports")
LOGS_DIR = os.path.join(PROJECT_DIR, "logs")

# File paths
DECRYPTED_DB_PATH = os.path.join(DECRYPTED_DIR, "dingtalk.db")
SYNC_STATE_FILE = os.path.join(DATA_DIR, "sync_state.json")

# Attachment directories (relative to DINGTALK_DATA_DIR)
ATTACHMENT_DIRS = {
    "image": "ImageFiles",
    "audio": "AudioFiles",
    "video": "VideoFiles",
    "resource_cache": "resource_cache",
}

# Message content types
CONTENT_TYPE_TEXT = 1
CONTENT_TYPE_IMAGE = 2
CONTENT_TYPE_VOICE = 300
CONTENT_TYPE_FILE = 501
CONTENT_TYPE_RICH_TEXT = 1200
CONTENT_TYPE_INTERACTIVE_CARD = 2900
CONTENT_TYPE_MINI_APP_CARD = 2950
CONTENT_TYPE_QUOTE = 3100
CONTENT_TYPE_VIDEO_CALL = 1101
CONTENT_TYPE_APPROVAL = 1400

# Content type names for display
CONTENT_TYPE_NAMES = {
    1: "文本",
    2: "图片",
    4: "文件",
    102: "系统消息",
    104: "系统通知",
    202: "链接",
    300: "语音",
    400: "视频",
    500: "位置",
    501: "文件",
    503: "文件",
    1101: "通话",
    1200: "富文本",
    1201: "交互卡片",
    1202: "系统提示",
    1400: "审批",
    1500: "任务",
    1600: "日程",
    2900: "互动卡片",
    2950: "小程序卡片",
    3100: "引用消息",
}

# Web server settings
WEB_HOST = "0.0.0.0"
WEB_PORT = 8090

# Ensure directories exist
for d in [DATA_DIR, DECRYPTED_DIR, EXPORT_DIR, LOGS_DIR]:
    os.makedirs(d, exist_ok=True)
