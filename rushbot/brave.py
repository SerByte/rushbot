"""Extract and decrypt Chromium cookies for one host from a Chrome/Brave profile.

Chromium encrypts cookie values with AES-256-GCM; the key lives in
`Local State` (os_crypt.encrypted_key), itself protected by DPAPI for the
current Windows user. Locked live databases are read through a volume shadow
copy, which needs administrator rights.
"""
from __future__ import annotations

import base64
import ctypes
import hashlib
import ctypes.wintypes as wt
import json
import os
import shutil
import sqlite3
import sys
import tempfile

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def dpapi_unprotect(blob: bytes) -> bytes:
    buf_in = DATA_BLOB(len(blob), ctypes.cast(ctypes.create_string_buffer(blob), ctypes.POINTER(ctypes.c_char)))
    buf_out = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(buf_in), None, None, None, None, 0x1, ctypes.byref(buf_out)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(buf_out.pbData, buf_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(buf_out.pbData)


def master_key(local_state_path: str) -> bytes:
    with open(local_state_path, encoding="utf8") as f:
        state = json.load(f)
    enc = base64.b64decode(state["os_crypt"]["encrypted_key"])
    if enc[:5] != b"DPAPI":
        raise ValueError("unexpected key header")
    return dpapi_unprotect(enc[5:])


def decrypt_value(key: bytes, blob: bytes, host_key: str = "") -> str:
    if blob[:3] in (b"v10", b"v11", b"v20"):
        nonce, payload = blob[3:15], blob[15:]
        plain = AESGCM(key).decrypt(nonce, payload, None)
        # schema >= 24 prefixes the value with SHA256(host_key)
        digest = hashlib.sha256(host_key.encode()).digest()
        if len(plain) > 32 and plain[:32] == digest:
            plain = plain[32:]
        return plain.decode("utf8", "replace")
    return blob.decode("utf8", "replace")


def shadow_cookies_db(profile_dir: str) -> str:
    """Copy the profile's cookie DB out of the newest readable shadow copy."""
    live = os.path.join(profile_dir, "Network", "Cookies")
    tmp = tempfile.mkdtemp()
    dst = os.path.join(tmp, "Cookies")
    try:
        shutil.copy2(live, dst)
        return dst
    except OSError:
        pass
    rel = live[3:] if live[1:3] == ":\\" else live
    for n in range(20, 0, -1):
        src = rf"\\?\GLOBALROOT\Device\HarddiskVolumeShadowCopy{n}\{rel}"
        try:
            shutil.copy2(src, dst)
            return dst
        except OSError:
            continue
    raise FileNotFoundError("cookie database unreadable (no usable shadow copy)")


def host_cookies(profile_dir: str, host: str) -> dict:
    db = shadow_cookies_db(profile_dir)
    key = master_key(os.path.join(os.path.dirname(profile_dir.rstrip("\\")), "Local State"))
    con = sqlite3.connect(db)
    rows = con.execute(
        "select host_key,name,encrypted_value,value from cookies "
        "where host_key = ? or host_key = ?", (host, "." + host)).fetchall()
    con.close()
    out = {}
    for host_key, name, enc, plain in rows:
        try:
            out[name] = decrypt_value(key, enc, host_key) if enc else plain
        except Exception:
            continue
    return out


BROWSERS = {
    "brave": ("BraveSoftware", "Brave-Browser"),
    "chrome": ("Google", "Chrome"),
    "edge": ("Microsoft", "Edge"),
}


def profile_dir(browser: str = "brave", profile: str = "Default") -> str:
    vendor, product = BROWSERS[browser]
    root = os.path.join(os.environ["LOCALAPPDATA"], vendor, product, "User Data")
    return os.path.join(root, profile)


def cookie_file(browser: str = "brave", profile: str = "Default",
                host: str = "statlocker.gg", out: str | None = None) -> str:
    """Write the Cookie header for `host` to `out` and return the path."""
    cookies = host_cookies(profile_dir(browser, profile), host)
    if not cookies:
        raise SystemExit(f"no {host} cookies in {browser}/{profile} (not logged in?)")
    header = "; ".join(f"{k}={v}" for k, v in cookies.items())
    out = out or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "cookie.txt")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf8") as f:
        f.write(header)
    return out
