import os
import shutil
import subprocess
import logging
import time
import tempfile
import hashlib

import config

logger = logging.getLogger(__name__)

# V3 PBKDF2 constants (from reverse engineering: kanxue thread-287455)
_V3_PBKDF2_SALT = b"666DingTalk888"[:8]  # saltlen=8 -> "666DingT"
_V3_PBKDF2_ITERATIONS = 1000
_V3_PBKDF2_DKLEN = 32
_AES_PAGE_SIZE = 4096


def generate_key_v2(uid):
    """Generate AES key for V2: MD5(uid) hex[:16]."""
    md5_hex = hashlib.md5(uid.encode("utf-8")).hexdigest()
    return md5_hex[:16].encode("ascii")


def generate_key_v3(uid, salt_hex):
    """Generate AES key for V3: PBKDF2(uid+salt, "666DingT", 1000, 32) -> MD5 hex[:16].

    Key derivation (from reverse engineering):
      1. password = uid + salt  (uid is numeric string, salt is 32-char hex)
      2. PKCS5_PBKDF2_HMAC_SHA1(password, "666DingT", 1000, 32) -> 32 bytes
      3. MD5(32 bytes) -> hex string, take first 16 chars as AES-128 key
    """
    if not salt_hex:
        raise ValueError(
            "V3 salt is required but not found.\n"
            "Make sure the user_config file exists in the DingTalk data directory."
        )
    password = (uid + salt_hex).encode("utf-8")
    dk = hashlib.pbkdf2_hmac(
        "sha1", password, _V3_PBKDF2_SALT, _V3_PBKDF2_ITERATIONS, dklen=_V3_PBKDF2_DKLEN
    )
    md5_hex = hashlib.md5(dk).hexdigest()
    return md5_hex[:16].encode("ascii")


def generate_key(uid=None, version=None, salt_hex=None):
    """Generate the AES decryption key based on DingTalk version."""
    uid = uid or config.USER_UID
    version = version or config.DINGTALK_VERSION
    salt_hex = salt_hex or config.V3_SALT

    if version == 3:
        return generate_key_v3(uid, salt_hex)
    return generate_key_v2(uid)


def _decrypt_aes_ecb(data, key):
    """Decrypt data using AES-128-ECB, page by page (4096 bytes)."""
    from Crypto.Cipher import AES

    cipher = AES.new(key, AES.MODE_ECB)
    result = bytearray()

    for offset in range(0, len(data), _AES_PAGE_SIZE):
        page = data[offset : offset + _AES_PAGE_SIZE]
        if len(page) == _AES_PAGE_SIZE:
            for i in range(0, _AES_PAGE_SIZE, 16):
                result.extend(cipher.decrypt(page[i : i + 16]))
        else:
            # Partial last page — keep as-is
            result.extend(page)

    return bytes(result)


def copy_encrypted_db(retry_count=None, retry_delay=None):
    """Copy encrypted database files to a temp directory to avoid lock conflicts."""
    if retry_count is None:
        retry_count = config.COPY_RETRY_COUNT
    if retry_delay is None:
        retry_delay = config.COPY_RETRY_DELAY

    if not os.path.isfile(config.ENCRYPTED_DB):
        raise FileNotFoundError(
            f"DingTalk database not found at: {config.ENCRYPTED_DB}\n"
            "Make sure the DingTalk desktop client is installed and logged in, "
            "or set DINGTALK_DATA_DIR / DINGTALK_UID."
        )

    temp_dir = tempfile.mkdtemp(prefix="dingtalk_encrypt_", dir=config.DECRYPTED_DIR)
    dest_db = os.path.join(temp_dir, "dingtalk_encrypted.db")

    files_to_copy = [
        (config.ENCRYPTED_DB, dest_db),
        (config.ENCRYPTED_DB + "-wal", dest_db + "-wal"),
        (config.ENCRYPTED_DB + "-shm", dest_db + "-shm"),
    ]

    for attempt in range(retry_count):
        try:
            for src, dst in files_to_copy:
                if os.path.exists(src):
                    shutil.copy2(src, dst)
            logger.info(f"Successfully copied encrypted database to {temp_dir}")
            return dest_db
        except (PermissionError, OSError) as e:
            logger.warning(f"Copy attempt {attempt + 1}/{retry_count} failed: {e}")
            if attempt < retry_count - 1:
                time.sleep(retry_delay)
            else:
                shutil.rmtree(temp_dir, ignore_errors=True)
                raise RuntimeError(
                    f"Failed to copy encrypted database after {retry_count} attempts: {e}"
                )

    shutil.rmtree(temp_dir, ignore_errors=True)
    raise RuntimeError("Failed to copy encrypted database")


def decrypt_database_native(encrypted_db_path, output_path, key):
    """Decrypt database using pure Python AES-ECB (works for both V2 and V3)."""
    logger.info(f"Decrypting (native): {encrypted_db_path} -> {output_path}")

    with open(encrypted_db_path, "rb") as f:
        encrypted_data = f.read()

    decrypted = _decrypt_aes_ecb(encrypted_data, key)

    # Verify SQLite header
    if decrypted[:16] != b"SQLite format 3\x00":
        raise RuntimeError(
            "Decryption failed: output does not have valid SQLite header.\n"
            "Check that DINGTALK_UID and salt are correct."
        )

    with open(output_path, "wb") as f:
        f.write(decrypted)

    size_mb = os.path.getsize(output_path) / 1024 / 1024
    logger.info(f"Decryption complete. Output size: {size_mb:.1f} MB")
    return output_path


def decrypt_database_dingwave(encrypted_db_path, output_path):
    """Decrypt database using dingwave CLI tool (V2 only)."""
    if not os.path.isfile(config.DINGWAVE_PATH):
        raise FileNotFoundError(
            f"dingwave binary not found at: {config.DINGWAVE_PATH}\n"
            f"Please download it from https://github.com/p1g3/dingwave/releases\n"
            f"and place it in the tools/ directory."
        )

    logger.info(f"Decrypting (dingwave): {encrypted_db_path} -> {output_path}")

    cmd = [
        config.DINGWAVE_PATH,
        "-d", encrypted_db_path,
        "-k", config.USER_UID,
        "-o", output_path,
    ]

    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )

        max_wait = 300
        check_interval = 1
        waited = 0
        while waited < max_wait:
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                time.sleep(2)
                if os.path.exists(output_path):
                    break
            time.sleep(check_interval)
            waited += check_interval

        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            logger.info("dingwave process terminated after decryption")

        if proc.stdout:
            output = proc.stdout.read()
            for line in output.strip().split("\n"):
                if line.strip():
                    logger.info(f"dingwave: {line.strip()}")

        if not os.path.exists(output_path):
            raise RuntimeError(f"Decryption failed: output file not created at {output_path}")

        size_mb = os.path.getsize(output_path) / 1024 / 1024
        logger.info(f"Decryption complete. Output size: {size_mb:.1f} MB")
        return output_path

    except Exception:
        if "proc" in locals() and proc.poll() is None:
            proc.kill()
            proc.wait()
        raise


def decrypt_database(encrypted_db_path=None, output_path=None):
    """Decrypt the database. Uses native Python for V3, dingwave or native for V2."""
    if encrypted_db_path is None:
        encrypted_db_path = copy_encrypted_db()
    if output_path is None:
        output_path = config.DECRYPTED_DB_PATH

    try:
        # Always use native decryption (works for both V2 and V3)
        key = generate_key()
        logger.info(
            f"Using v{config.DINGTALK_VERSION} decryption "
            f"(UID={config.USER_UID}, key={key.decode('ascii')})"
        )
        return decrypt_database_native(encrypted_db_path, output_path, key)
    finally:
        # Clean up the encrypted copy
        if encrypted_db_path and os.path.dirname(encrypted_db_path) != config.ENCRYPTED_DB_DIR:
            temp_dir = os.path.dirname(encrypted_db_path)
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.info(f"Cleaned up temp directory: {temp_dir}")


def sync_decrypt():
    """Full sync: copy encrypted DB, decrypt, return path to decrypted DB."""
    logger.info("=== Starting sync decrypt ===")
    encrypted_copy = copy_encrypted_db()
    decrypted_path = decrypt_database(encrypted_copy)
    logger.info("=== Sync decrypt complete ===")
    return decrypted_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(f"DingTalk version: v{config.DINGTALK_VERSION}")
    print(f"UID: {config.USER_UID}")
    print(f"Data dir: {config.DINGTALK_DATA_DIR}")
    if config.DINGTALK_VERSION == 3:
        print(f"V3 salt: {config.V3_SALT}")
    path = sync_decrypt()
    print(f"Decrypted database: {path}")
