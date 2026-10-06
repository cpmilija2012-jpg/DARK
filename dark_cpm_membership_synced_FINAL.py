#!/usr/bin/env python3
"""DARK CPM - Mini App (ALL-IN-ONE: bot + cpm1_core + cpm1_clone + siren + plates)."""
from __future__ import annotations


import os, time, json, hashlib, zlib, sqlite3, secrets, html, threading, struct, base64, struct, base64
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import requests, urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
try:
    import brotli
    HAS_BROTLI = True
except ImportError:
    brotli = None
    HAS_BROTLI = False
try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad, unpad
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

FK = "AIzaSyBW1ZbMiUeDZHYUO2bY8Bfnf5rRgrQGPTM"
LOAD_URL = "https://europe-west1-cp-multiplayer.cloudfunctions.net/GetPlayerRecords3"
SAVE_URL = "https://europe-west1-cp-multiplayer.cloudfunctions.net/SavePlayerRecordsPartially8"
RANK_URL = "https://us-central1-cp-multiplayer.cloudfunctions.net/SetUserRating5"
MAX_MONEY = 50_000_000
MAX_COIN = 500_000
GAME_HEADERS = {
    "Accept": "*/*",
    "Accept-Encoding": "gzip",
    "Content-Type": "application/json",
    "User-Agent": "UnityPlayer/2022.3.62f2 (UnityWebRequest/1.0, libcurl/8.10.1-DEV)",
    "X-Unity-Version": "2022.3.62f2",
}
http_session = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=50, pool_maxsize=50, max_retries=3)
http_session.mount("https://", adapter)

USE_MONGO = False
db_path = "cpm_web.db"
tokens_col = users_col = premium_col = admins_col = user_data_col = None

with sqlite3.connect(db_path) as c:
    c.execute("CREATE TABLE IF NOT EXISTS tokens (user_id INTEGER PRIMARY KEY, auth_token TEXT, email TEXT, password TEXT, refresh_token TEXT, firebase_uid TEXT, token_expires_at REAL)")
    c.execute("CREATE TABLE IF NOT EXISTS user_data (cache_key TEXT PRIMARY KEY, email TEXT, data_json TEXT, saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    c.execute("""CREATE TABLE IF NOT EXISTS license_keys (
        key_code TEXT PRIMARY KEY, max_devices INTEGER DEFAULT 1, devices TEXT DEFAULT '[]',
        expires_at REAL DEFAULT 0, created_at REAL, created_by TEXT, active INTEGER DEFAULT 1)""")
    c.execute("CREATE TABLE IF NOT EXISTS user_keys (session_id TEXT PRIMARY KEY, key_code TEXT, activated_at REAL)")
    c.execute("CREATE TABLE IF NOT EXISTS admins (username TEXT PRIMARY KEY, password TEXT)")
    c.commit()

def make_xor_key(uid: str) -> bytes:
    chars = list(str(uid or ""))
    if len(chars) >= 9: chars[1], chars[8] = chars[8], chars[1]
    if len(chars) >= 3: chars.pop(2)
    if len(chars) >= 5: chars.append(chars[4])
    return "".join(chars).encode("utf-8") or b"0"

def xor_bytes(data: bytes, key: bytes) -> bytes: return bytes(data[i] ^ key[i % len(key)] for i in range(len(data)))

def decompress(data: bytes):
    if HAS_BROTLI:
        try: return brotli.decompress(data)
        except: pass
    for args in ((zlib.MAX_WBITS | 16,), tuple()):
        try: return zlib.decompress(data, *args)
        except: pass
    return None

def decrypt_aes(data: bytes, key: bytes):
    if not HAS_CRYPTO: return None
    try: return unpad(AES.new(key[:16], AES.MODE_CBC, b"\x00" * 16).decrypt(data), 16)
    except: return None

def _md5(text: str) -> bytes: return hashlib.md5(str(text).encode()).digest()
def _sha1(text: str) -> bytes: return hashlib.sha1(str(text).encode()).digest()[:16]
def build_aes_keys(uid: str, password: str = None, email: str = None) -> list:
    keys = [_md5("olzhas_carparking")]
    if password: keys.extend([_md5(password), _sha1(password)])
    if uid: keys.extend([_md5(uid), _sha1(uid)])
    if email: keys.append(_md5(email))
    return keys

class Reader:
    def __init__(self, data: bytes): self.buf, self.pos = data, 0
    def has_bytes(self, n: int) -> bool: return self.pos + n <= len(self.buf)
    def read_byte(self) -> int:
        if not self.has_bytes(1): return 0
        v = self.buf[self.pos]; self.pos += 1; return v
    def read_int(self) -> int:
        if not self.has_bytes(4): self.pos = len(self.buf); return 0
        v = struct.unpack_from("<i", self.buf, self.pos)[0]; self.pos += 4; return v
    def read_float(self) -> float:
        if not self.has_bytes(4): self.pos = len(self.buf); return 0.0
        v = struct.unpack_from("<f", self.buf, self.pos)[0]; self.pos += 4; return v
    def read_string(self) -> str:
        marker = self.read_int()
        if marker in (0, -1): return ""
        length = (-marker) - 1 if marker < -1 else marker
        if marker < -1: self.read_int()
        length = max(0, min(length, 1000000))
        if not self.has_bytes(length): return ""
        text = self.buf[self.pos:self.pos + length].decode("utf-8", errors="replace")
        self.pos += length
        return text.replace("\x00", "").strip()
    def read_list(self, item_fn):
        count = self.read_int()
        if count <= 0 or count > 1000000: return []
        res = []
        for _ in range(count):
            if self.pos >= len(self.buf): break
            val = item_fn()
            if val is not None: res.append(val)
        return res
    def read_dict(self) -> dict:
        count = self.read_int()
        if count <= 0 or count > 1000000: return {}
        return {self.read_int(): self.read_int() for _ in range(count) if self.pos < len(self.buf)}
    def read_equipment(self):
        if self.read_byte() == 0: return None
        return {k: self.read_list(self.read_int) for k in ["hair", "face", "beard", "cap", "mask", "top", "gloves", "bag", "pants", "shoes", "glasses", "SelectedEquipments"]} | {"Gender": self.read_int()}

def parse_player(buf: bytes) -> dict:
    r = Reader(buf)
    if r.read_byte() == 0: return None
    player = {"Name": r.read_string(), "money": r.read_int(), "coin": r.read_int(), "localID": r.read_string(), "boughtFsos": r.read_list(r.read_int)}
    player["FriendsID"] = r.read_list(lambda: (r.read_byte(), {"id": r.read_string(), "Name": r.read_string(), "accountID": r.read_string()})[1])
    player.update({"LevelsDoneTime": r.read_list(r.read_float), "floats": r.read_list(r.read_float), "integers": r.read_list(r.read_int), "fcar": r.read_list(r.read_int), "favouriteWheels": r.read_list(r.read_int), "favouriteVinyls": r.read_list(r.read_int), "favouriteEmojis": r.read_list(r.read_int), "personEquipmentsMale": r.read_equipment(), "personEquipmentsFemale": r.read_equipment()})
    if r.read_byte() == 0: player["platesData"] = None
    else:
        def read_vinyl(): r.read_byte(); return {"vectors": r.read_list(lambda: {"x": r.read_float(), "y": r.read_float(), "z": r.read_float()}), "v": r.read_list(r.read_string), "floats": r.read_list(r.read_float), "text": r.read_string()}
        def read_plate(): r.read_byte(); return {"plateId": r.read_int(), "frontCarId": r.read_int(), "rearCarId": r.read_int(), "vinyls": r.read_list(read_vinyl)}
        player["platesData"] = {"allPlates": r.read_list(read_plate)}

    if r.read_byte() == 0: player["carIDnStatus"] = None
    else: player["carIDnStatus"] = {"carGeneratedIDs": r.read_list(r.read_string), "carStatus": r.read_list(r.read_int)}
    
    player["allData"] = r.read_string()
    player["flags"] = r.read_dict()
    player["animations"] = r.read_list(r.read_int)
    player["emojiPacks"] = r.read_list(r.read_int)
    player["wheels"] = r.read_list(r.read_int)
    player["boughtPoliceLights"] = r.read_list(r.read_int)
    player["boughtPoliceSirens"] = r.read_list(r.read_int)
    return player

def try_parse(buf: bytes) -> dict:
    candidates = [buf, decompress(buf)]
    if candidates[1]: candidates.append(decompress(candidates[1]))
    for candidate in filter(None, candidates):
        if candidate[0] in (17, 23, 24):
            try:
                p = parse_player(candidate)
                if p and p.get("Name") is not None: return p
            except: pass
        try:
            clean = candidate[3:] if len(candidate) >= 3 and candidate[:2] == b"\xef\xbb" else candidate
            if clean and clean[0] == 123: return json.loads(clean.decode("utf-8"))
        except: pass
    return None

def decrypt_player_record(base64_text: str, uid: str, password: str = None, email: str = None) -> dict:
    try: buf = base64.b64decode(base64_text)
    except: return {"success": False, "message": "Bad base64"}
    if len(buf) < 10: return {"success": False, "message": "Too small"}
    direct = try_parse(buf)
    if direct: return {"success": True, "record": direct}
    if uid:
        try:
            decoded = decompress(xor_bytes(buf, make_xor_key(uid)))
            if decoded:
                parsed = try_parse(decoded)
                if parsed: return {"success": True, "record": parsed}
        except: pass
    for key in build_aes_keys(uid or "", password, email):
        plain = decrypt_aes(buf, key)
        if not plain: continue
        parsed = try_parse(plain)
        if parsed: return {"success": True, "record": parsed}
    return {"success": False, "message": "Could not decrypt"}

class Writer:
    def __init__(self): self._p: List[bytes] = []
    def write_byte(self, v): self._p.append(bytes([int(v or 0) & 0xFF]))
    def write_int(self, v): self._p.append(struct.pack("<i", int(v or 0)))
    def write_float(self, v): self._p.append(struct.pack("<f", float(v or 0.0)))
    def write_string(self, s):
        if s is None: self._p.append(struct.pack("<i", -1)); return
        s = str(s)
        if s == "": self._p.append(struct.pack("<i", 0)); return
        enc = s.encode("utf-8")
        self._p.append(struct.pack("<ii", -(len(enc)) - 1, len(s)) + enc)
    def write_list(self, lst, fn):
        if lst is None: self._p.append(struct.pack("<i", -1)); return
        self._p.append(struct.pack("<i", len(lst)))
        for item in lst: fn(item)
    def write_equipment(self, data):
        if not data: self.write_byte(0); return
        self.write_byte(13)
        for key in ["hair", "face", "beard", "cap", "mask", "top", "gloves", "bag", "pants", "shoes", "glasses", "SelectedEquipments"]:
            self.write_list(data.get(key, []), self.write_int)
        self.write_int(data.get("Gender", 0))
    def write_plates(self, data):
        if not data: self.write_byte(0); return
        self.write_byte(1)
        plates = data.get("allPlates", [])
        self._p.append(struct.pack("<i", len(plates)))
        for plate in plates:
            self.write_byte(4); self.write_int(plate.get("plateId", 0)); self.write_int(plate.get("frontCarId", 0)); self.write_int(plate.get("rearCarId", 0))
            vinyls = plate.get("vinyls", [])
            self._p.append(struct.pack("<i", len(vinyls)))
            for vinyl in vinyls:
                self.write_byte(4)
                vecs = vinyl.get("vectors", [])
                self._p.append(struct.pack("<i", len(vecs)))
                for vec in vecs: self._p.append(struct.pack("<fff", vec.get("x", 0), vec.get("y", 0), vec.get("z", 0)))
                self.write_list(vinyl.get("v", []), self.write_string)
                self.write_list(vinyl.get("floats", []), self.write_float)
                self.write_string(vinyl.get("text", ""))
    def write_car_id_status(self, data):
        if not data: self.write_byte(0); return
        self.write_byte(2)
        self.write_list(data.get("carGeneratedIDs", []), self.write_string)
        self.write_list(data.get("carStatus", []), self.write_int)
    def to_bytes(self): return b"".join(self._p)

FIELD_MAPPING = [(1, "localID"), (2, "money"), (3, "Name"), (4, "coin"), (5, "allData"), (6, "boughtFsos"), (7, "boughtPoliceLights"), (8, "boughtPoliceSirens"), (9, "FriendsID"), (10, "LevelsDoneTime"), (11, "floats"), (12, "integers"), (13, "fcar"), (14, "favouriteWheels"), (15, "favouriteVinyls"), (16, "favouriteEmojis"), (18, "emojiPacks"), (41, "personEquipmentsMale"), (42, "personEquipmentsFemale"), (43, "platesData"), (44, "carIDnStatus"), (45, "flags"), (46, "animations"), (48, "wheels")]
INT_LIST_FIELDS = {6, 7, 8, 12, 13, 14, 15, 16, 18, 46, 48}
FLOAT_LIST_FIELDS = {10, 11}

def _field_modified(new_value, old_value) -> bool:
    if new_value is None and old_value is None: return False
    if new_value is None or old_value is None: return True
    if type(new_value) != type(old_value): return True
    if isinstance(new_value, (dict, list)): return json.dumps(new_value, sort_keys=True) != json.dumps(old_value, sort_keys=True)
    return new_value != old_value

def serialize_field(fid: int, value: Any) -> Optional[bytes]:
    w = Writer()
    if fid in (1, 3, 5): w.write_string(value); return w.to_bytes()
    if fid in (2, 4): w.write_int(value or 0); return w.to_bytes()
    if fid == 9:
        friends = value or []
        w._p.append(struct.pack("<i", len(friends)))
        for friend in friends: w.write_byte(3); w.write_string(friend.get("id", "")); w.write_string(friend.get("Name", "")); w.write_string(friend.get("accountID", ""))
        return w.to_bytes()
    if fid in INT_LIST_FIELDS: w.write_list(value or [], w.write_int); return w.to_bytes()
    if fid in FLOAT_LIST_FIELDS: w.write_list(value or [], w.write_float); return w.to_bytes()
    if fid in (41, 42): w.write_equipment(value); return w.to_bytes()
    if fid == 43: w.write_plates(value); return w.to_bytes()
    if fid == 44: w.write_car_id_status(value); return w.to_bytes()
    if fid == 45:
        w._p.append(struct.pack("<i", len(value or {})))
        for key, val in (value or {}).items(): w.write_int(int(key)); w.write_int(int(val))
        return w.to_bytes()
    return None

def build_payload(record: Dict[str, Any], uid: str, original: Optional[Dict[str, Any]] = None, force_fields: Optional[set] = None) -> str:
    force_fields = set(force_fields or [])
    fields = []
    for fid, key in FIELD_MAPPING:
        value = record.get(key)
        if value is None: continue
        if key == "allData": should_send = isinstance(value, str) and len(value) > 0
        elif key in force_fields: should_send = True
        elif original is not None: should_send = _field_modified(value, original.get(key))
        else: should_send = True
        if not should_send: continue
        raw = serialize_field(fid, value)
        if raw is not None: fields.append((fid, raw))
    parts = [struct.pack("<i", len(fields))]
    for fid, raw in fields: parts.extend([struct.pack("<hi", fid, len(raw)), raw])
    combined = b"".join(parts)
    compressed = brotli.compress(combined) if HAS_BROTLI else zlib.compress(combined)
    encrypted = xor_bytes(compressed, make_xor_key(uid))
    return base64.b64encode(encrypted).decode("ascii")

class SyncCPMNuker:
    def __init__(self):
        self.cache = {}

    def _ck(self, uid: int, email: Optional[str] = None) -> str:
        td = self.get_token_data(uid)
        return f"{uid}_{email or (td.get('email') if td else '')}"

    def save_token(self, uid: int, auth: str, email: str, pw: Optional[str] = None, rt: Optional[str] = None, fuid: Optional[str] = None):
        if USE_MONGO:
            try:
                tokens_col.update_one({"user_id": uid}, {"$set": {"auth_token": auth, "email": email, "password": pw, "refresh_token": rt, "firebase_uid": fuid, "token_expires_at": time.time() + 3600}}, upsert=True)
            except: pass
        else:
            with sqlite3.connect(db_path) as c:
                c.execute("INSERT OR REPLACE INTO tokens (user_id, auth_token, email, password, refresh_token, firebase_uid, token_expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (uid, auth, email, pw, rt, fuid, time.time() + 3600))
                c.commit()

    def get_token_data(self, uid: int) -> Optional[Dict[str, Any]]:
        if USE_MONGO:
            try:
                row = tokens_col.find_one({"user_id": uid})
                if not row: return None
                return row
            except: return None
        else:
            with sqlite3.connect(db_path) as c:
                row = c.execute("SELECT auth_token, email, password, refresh_token, firebase_uid, token_expires_at FROM tokens WHERE user_id=?", (uid,)).fetchone()
            if not row: return None
            return {"auth_token": row[0], "email": row[1], "password": row[2], "refresh_token": row[3], "firebase_uid": row[4], "token_expires_at": row[5]}

    def update_token(self, uid: int, auth: str, rt: Optional[str] = None):
        if USE_MONGO:
            try:
                update_data = {"auth_token": auth, "token_expires_at": time.time() + 3600}
                if rt: update_data["refresh_token"] = rt
                tokens_col.update_one({"user_id": uid}, {"$set": update_data})
            except: pass
        else:
            with sqlite3.connect(db_path) as c:
                if rt: c.execute("UPDATE tokens SET auth_token=?, refresh_token=?, token_expires_at=? WHERE user_id=?", (auth, rt, time.time() + 3600, uid))
                else: c.execute("UPDATE tokens SET auth_token=?, token_expires_at=? WHERE user_id=?", (auth, time.time() + 3600, uid))
                c.commit()

    def delete_token(self, uid: int):
        if USE_MONGO:
            try: tokens_col.delete_one({"user_id": uid})
            except: pass
        else:
            with sqlite3.connect(db_path) as c:
                c.execute("DELETE FROM tokens WHERE user_id=?", (uid,))
                c.commit()
        for key in list(self.cache.keys()):
            if key.startswith(str(uid)): del self.cache[key]

    def is_expired(self, uid: int) -> bool:
        td = self.get_token_data(uid)
        return not td or not td.get("token_expires_at") or td.get("token_expires_at") < time.time()

    def get_record(self, uid: int, email: Optional[str] = None) -> Dict[str, Any]:
        ck = self._ck(uid, email)
        if ck not in self.cache:
            if USE_MONGO:
                try:
                    doc = user_data_col.find_one({"cache_key": ck})
                    if doc and "data_json" in doc: self.cache[ck] = json.loads(doc["data_json"])
                except: pass
            else:
                with sqlite3.connect(db_path) as c:
                    row = c.execute("SELECT data_json FROM user_data WHERE cache_key=?", (ck,)).fetchone()
                if row:
                    try: self.cache[ck] = json.loads(row[0])
                    except: pass
        return self.cache.get(ck, {})

    def set_record(self, uid: int, data: Dict[str, Any], email: Optional[str] = None):
        ck = self._ck(uid, email)
        self.cache[ck] = data
        if USE_MONGO:
            try:
                user_data_col.update_one({"cache_key": ck}, {"$set": {"email": email, "data_json": json.dumps(data), "saved_at": datetime.now()}}, upsert=True)
            except: pass
        else:
            with sqlite3.connect(db_path) as c:
                c.execute("INSERT OR REPLACE INTO user_data (cache_key, email, data_json) VALUES (?, ?, ?)", (ck, email, json.dumps(data)))
                c.commit()

    def _post(self, url: str, payload: Dict[str, Any], headers: Dict[str, str]) -> Dict[str, Any]:
        try:
            clean_headers = {k: v for k, v in headers.items() if k.lower() != "host"}
            resp = http_session.post(url, json=payload, headers=clean_headers, timeout=15)
            try: return resp.json()
            except: return {"raw": resp.text, "status": resp.status_code, "ok": False}
        except Exception as e:
            return {"ok": False, "message": f"CONNECTION FAILED."}

    def login(self, email: str, password: str) -> Dict[str, Any]:
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FK}"
        payload = {"email": email, "password": password, "returnSecureToken": True, "clientType": "CLIENT_TYPE_ANDROID"}
        result = self._post(url, payload, GAME_HEADERS)
        if result.get("ok") is False: return result
        if "idToken" in result: return {"ok": True, "message": "OK", "auth": result["idToken"], "refresh_token": result.get("refreshToken", ""), "firebase_uid": result.get("localId", "")}
        err = "INVALID_CREDENTIALS"
        try:
            if isinstance(result.get("error"), dict): err = str(result["error"].get("message", "INVALID_CREDENTIALS"))
            elif isinstance(result.get("error"), str): err = result["error"]
        except: pass
        return {"ok": False, "message": err.upper()[:80]}

    def register(self, email: str, password: str) -> Dict[str, Any]:
        email = (email or "").strip()
        password = password or ""
        if not email or "@" not in email or "." not in email.split("@")[-1]:
            return {"ok": False, "message": "INVALID_EMAIL"}
        if len(password) < 6:
            return {"ok": False, "message": "WEAK_PASSWORD (min 6 chars)"}
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={FK}"
        payload = {
            "email": email,
            "password": password,
            "returnSecureToken": True,
            "clientType": "CLIENT_TYPE_ANDROID",
        }
        result = self._post(url, payload, GAME_HEADERS)
        if result.get("ok") is False:
            return {"ok": False, "message": result.get("message", "CONNECTION FAILED")}
        if "idToken" in result:
            return {
                "ok": True,
                "message": "OK",
                "auth": result["idToken"],
                "refresh_token": result.get("refreshToken", ""),
                "firebase_uid": result.get("localId", ""),
            }
        err = "REGISTRATION_FAILED"
        try:
            if isinstance(result.get("error"), dict):
                err = str(result["error"].get("message", "FAILED"))
            elif isinstance(result.get("error"), str):
                err = result["error"]
        except Exception:
            pass
        el = err.upper()
        if "EMAIL_EXISTS" in el:
            err = "EMAIL_EXISTS — use Login"
        elif "INVALID_EMAIL" in el:
            err = "INVALID_EMAIL"
        elif "WEAK_PASSWORD" in el:
            err = "WEAK_PASSWORD — min 6 characters"
        elif "OPERATION_NOT_ALLOWED" in el:
            err = "SIGNUP_DISABLED on Firebase"
        elif "TOO_MANY_ATTEMPTS" in el:
            err = "TOO_MANY_ATTEMPTS — try later"
        return {"ok": False, "message": err[:100]}


    def _refresh(self, uid: int) -> Tuple[bool, str]:
        td = self.get_token_data(uid)
        if not td: return False, "NO_TOKEN"
        rt, em, pw = td.get("refresh_token"), td.get("email"), td.get("password")
        if rt:
            res = self._post(f"https://securetoken.googleapis.com/v1/token?key={FK}", {"grant_type": "refresh_token", "refresh_token": rt}, {"Content-Type": "application/json"})
            if res.get("id_token"):
                self.update_token(uid, res["id_token"], res.get("refresh_token", rt))
                return True, "OK"
        if em and pw:
            res = self.login(em, pw)
            if res.get("ok"):
                self.save_token(uid, res["auth"], em, pw, res.get("refresh_token", ""), res.get("firebase_uid", ""))
                return True, "OK"
        return False, "REFRESH_FAILED"

    def get_auth(self, uid: int) -> Tuple[bool, str, str]:
        if self.is_expired(uid):
            ok, msg = self._refresh(uid)
            if not ok: return False, msg, ""
        td = self.get_token_data(uid)
        if td and td.get("auth_token"): return True, "OK", td.get("auth_token")
        return False, "NO_TOKEN", ""

    def load(self, uid: int, force: bool = False) -> bool:
        td = self.get_token_data(uid)
        if not td: return False
        if not force and self._ck(uid) in self.cache: return True
        ok, msg, auth = self.get_auth(uid)
        if not ok: return False
        res = self._post(LOAD_URL, {"data": None}, {**GAME_HEADERS, "Authorization": f"Bearer {auth}"})
        if res.get("ok") is False or not res.get("result"): return False
        dec = decrypt_player_record(res["result"], td.get("firebase_uid", ""), td.get("password", ""), td.get("email", ""))
        if dec.get("success") and dec.get("record"):
            self.set_record(uid, dec["record"], td.get("email", ""))
            return True
        return False

    def _ok(self, value: Any) -> bool:
        if value in (1, True, "1"): return True
        if value in (0, False, None, "0"): return False
        if isinstance(value, str):
            try: return self._ok(json.loads(value.strip()))
            except: return False
        if isinstance(value, dict):
            for k in ("result", "ok", "success"):
                if k in value: return self._ok(value[k])
        return False

    def _send(self, auth: str, record: Dict[str, Any], fuid: str, original: Optional[Dict[str, Any]] = None, force_fields: Optional[set] = None) -> Tuple[bool, str]:
        if not fuid: return False, "NO_FIREBASE_UID"
        try:
            payload = build_payload(record, fuid, original, force_fields=force_fields)
            res = self._post(SAVE_URL, {"data": {"data": payload, "deviceId": fuid[:8]}}, {**GAME_HEADERS, "Authorization": f"Bearer {auth}", "Connection": "Keep-Alive", "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 12; Pixel 6 Build/SD1A.210817.036)"})
            if res.get("ok") is False: return False, res.get("message", "API TIMEOUT")
            if res and self._ok(res): return True, "OK"
            return False, f"SAVE-FAILED"
        except Exception as e: return False, str(e)

    def _save(self, uid: int, data: Dict[str, Any], force_fields: Optional[set] = None) -> Dict[str, Any]:
        ok, msg, auth = self.get_auth(uid)
        if not ok: return {"ok": False, "message": msg}
        td = self.get_token_data(uid)
        fuid = td.get("firebase_uid", "") if td else ""
        email = td.get("email", "") if td else ""
        original = self.get_record(uid, email) or None
        ok2, msg2 = self._send(auth, data, fuid, original, force_fields=force_fields)
        if ok2:
            self.set_record(uid, data, email)
            return {"ok": True, "message": "OK"}
        return {"ok": False, "message": msg2}

    def _modify(self, uid: int, mods: Dict[str, Any], force_fields: Optional[set] = None) -> Dict[str, Any]:
        if not self.load(uid): return {"ok": False, "message": "ACCOUNT LOAD FAILED. CHECK CREDENTIALS."}
        td = self.get_token_data(uid)
        data = deepcopy(self.get_record(uid, td.get("email") if td else None))
        if not data or data.get("Name") is None: return {"ok": False, "message": "PROFILE DATA CORRUPTED."}
        for k, v in mods.items():
            if k == "money": v = min(int(v), MAX_MONEY)
            if k == "coin": v = min(int(v), MAX_COIN)
            data[k] = v
        return self._save(uid, data, force_fields=set(force_fields or mods.keys()))

    def _set_floats(self, uid: int, indices_values: List[Tuple[int, float]]) -> Dict[str, Any]:
        if not self.load(uid): return {"ok": False, "message": "ACCOUNT LOAD FAILED."}
        td = self.get_token_data(uid)
        data = deepcopy(self.get_record(uid, td.get("email") if td else None))
        if not data or data.get("Name") is None: return {"ok": False, "message": "PROFILE DATA CORRUPTED."}
        floats = data.get("floats", [])
        max_idx = max(idx for idx, _ in indices_values)
        while len(floats) <= max_idx: floats.append(0.0)
        for idx, val in indices_values: floats[idx] = float(val)
        data["floats"] = floats
        return self._save(uid, data, force_fields={"floats"})

    def _set_integers(self, uid: int, indices_values: List[Tuple[int, int]]) -> Dict[str, Any]:
        if not self.load(uid): return {"ok": False, "message": "ACCOUNT LOAD FAILED."}
        td = self.get_token_data(uid)
        data = deepcopy(self.get_record(uid, td.get("email") if td else None))
        if not data or data.get("Name") is None: return {"ok": False, "message": "PROFILE DATA CORRUPTED."}
        integers = data.get("integers", [])
        max_idx = max(idx for idx, _ in indices_values)
        while len(integers) <= max_idx: integers.append(0)
        for idx, val in indices_values: integers[idx] = int(val)
        data["integers"] = integers
        return self._save(uid, data, force_fields={"integers"})

    def set_money(self, uid: int, amount: int) -> Dict[str, Any]: return self._modify(uid, {"money": min(int(amount), MAX_MONEY)}, force_fields={"money"})
    def set_coin(self, uid: int, amount: int) -> Dict[str, Any]: return self._modify(uid, {"coin": min(int(amount), MAX_COIN)}, force_fields={"coin"})
    
    def change_player_id(self, uid: int, new_id: str) -> Dict[str, Any]:
        if not self.load(uid, force=True): return {"ok": False, "message": "ACCOUNT LOAD FAILED."}
        td = self.get_token_data(uid)
        data = deepcopy(self.get_record(uid, td.get("email") if td else None))
        if not data or data.get("Name") is None: return {"ok": False, "message": "PROFILE DATA CORRUPTED."}
        new_id_upper = str(new_id).strip().upper()
        data["localID"] = new_id_upper
        result = self._save(uid, data, force_fields={"localID"})
        if result.get("ok"): return {"ok": True, "message": f"TAG MASKED TO {new_id_upper}", "new_id": new_id_upper}
        return {"ok": False, "message": result.get("message", "SAVE FAILED")}
        
    def change_player_name(self, uid: int, new_name: str) -> Dict[str, Any]:
        if not self.load(uid, force=True): return {"ok": False, "message": "ACCOUNT LOAD FAILED."}
        td = self.get_token_data(uid)
        data = deepcopy(self.get_record(uid, td.get("email") if td else None))
        data["Name"] = new_name
        return self._save(uid, data, force_fields={"Name"})

    def change_email(self, uid: int, new_email: str) -> Dict[str, Any]:
        td = self.get_token_data(uid)
        if not td: return {"ok": False, "message": "Not logged in"}
        return {"ok": True, "message": "OK"}

    def unlock_w16(self, uid: int) -> Dict[str, Any]: return self._set_floats(uid, [(32, 1.0)])
    def unlock_horns(self, uid: int) -> Dict[str, Any]: return self._set_floats(uid, [(27, 1.0), (28, 1.0), (29, 1.0), (30, 1.0), (31, 1.0)])
    def disable_damage(self, uid: int) -> Dict[str, Any]: return self._set_floats(uid, [(34, 1.0)])
    def unlimited_fuel(self, uid: int) -> Dict[str, Any]: return self._set_floats(uid, [(3, 1.0)])
    def unlock_smoke(self, uid: int) -> Dict[str, Any]: return self._set_floats(uid, [(33, 1.0)])
    
    def unlock_animations(self, uid: int) -> Dict[str, Any]:
        if not self.load(uid): return {"ok": False, "message": "ACCOUNT LOAD FAILED."}
        td = self.get_token_data(uid)
        data = deepcopy(self.get_record(uid, td.get("email") if td else None))
        data["animations"] = sorted(set(data.get("animations", []) + list(range(301))))
        return self._save(uid, data, force_fields={"animations"})

    def unlock_wheels(self, uid: int) -> Dict[str, Any]:
        if not self.load(uid): return {"ok": False, "message": "ACCOUNT LOAD FAILED."}
        td = self.get_token_data(uid)
        data = deepcopy(self.get_record(uid, td.get("email") if td else None))
        data["wheels"] = sorted(set(data.get("wheels", []) + list(range(73, 221))))
        integers = data.get("integers", [])
        while len(integers) < 113: integers.append(0)
        for idx in [0, 1, 2, 3, 4, 5, 110, 111, 112]: integers[idx] = 1
        data["integers"] = integers
        return self._save(uid, data, force_fields={"wheels", "integers"})

    def unlock_houses(self, uid: int) -> Dict[str, Any]: return self._set_integers(uid, [(8, 1), (110, 1), (111, 1), (112, 1)])
    def complete_all_levels(self, uid: int) -> Dict[str, Any]: return self._modify(uid, {"LevelsDoneTime": [0] + [120 if i == 43 else 1 for i in range(1, 110)]}, force_fields={"LevelsDoneTime"})

    def set_rank(self, uid: int) -> Dict[str, Any]:
        self.load(uid)
        ok, msg, auth = self.get_auth(uid)
        if not ok: return {"ok": True, "message": "OK"}
        rating_data = {"RatingData": {"time": 1e22, "cars": 1e16, "car_fix": 1e13, "car_collided": 1e12, "car_exchange": 1e13, "car_trade": 1e13, "car_wash": 1e13, "slicer_cut": 1e13, "drift_max": 1e14, "drift": 1e14, "cargo": 1e5, "delivery": 1e5, "race_win": 3e20, "taxi": 1e10, "levels": 10000990000, "gifts": 1e9, "fuel": 1e10, "offroad": 1e10, "speed_banner": 1e9, "reactions": 1e17, "run": 1e9, "real_estate": 1e9, "t_distance": 1e10, "treasure": 1e10, "block_post": 1e10, "push_ups": 1e12, "burnt_tire": 1e10, "passanger_distance": 1e8}}
        try: self._post(RANK_URL, {"data": json.dumps(rating_data)}, {**GAME_HEADERS, "Authorization": f"Bearer {auth}"})
        except: pass
        return {"ok": True, "message": "OK"}

    def _normalize_equipment(self, equipment: Dict[str, Any], gender: int) -> Dict[str, Any]:
        list_fields = ["hair", "face", "beard", "cap", "mask", "top", "gloves", "bag", "pants", "shoes", "glasses", "SelectedEquipments"]
        normalized = {key: [int(v) for v in (equipment.get(key, []) if isinstance(equipment, dict) else [])] for key in list_fields}
        normalized["Gender"] = int(gender)
        return normalized

    def unlock_all_clothes(self, uid: int) -> Dict[str, Any]:
        if not self.load(uid, force=True): return {"ok": False, "message": "ACCOUNT LOAD FAILED."}
        td = self.get_token_data(uid)
        data = deepcopy(self.get_record(uid, td.get("email") if td else None))
        
        eq_male = {"Gender": 0, "bag": list(range(101)), "beard": list(range(6, 21)) + [100], "cap": list(range(3, 64)), "face": [0, 1, 2, 100], "glasses": list(range(10)) + [100], "gloves": list(range(6)) + [100], "hair": list(range(3, 20)) + [100], "mask": list(range(3, 9)) + [100], "pants": list(range(26)), "shoes": list(range(31)), "top": list(range(2, 109)), "SelectedEquipments": [-1, 10, 19, 41, 100, 4, 20, 9, 22, 21, 74]}
        eq_female = {"Gender": 1, "bag": list(range(6)), "beard": [], "cap": list(range(3, 41)), "face": [0], "glasses": list(range(10)), "gloves": [1], "hair": [0, 7, 8, 9, 10], "mask": list(range(3, 8)), "pants": list(range(12)), "shoes": list(range(3, 15)), "top": list(range(5, 80)), "SelectedEquipments": [0, 0, -1, -1, -1, -1, -1, -1, 0, -1, -1]}
        
        data["personEquipmentsMale"] = self._normalize_equipment(eq_male, 0)
        data["personEquipmentsFemale"] = self._normalize_equipment(eq_female, 1)
        
        return self._save(uid, data, force_fields={"personEquipmentsMale", "personEquipmentsFemale"})

    def unlock_all_features(self, uid: int) -> Dict[str, Any]:
        feature_calls = [("W16 Engine", self.unlock_w16), ("Horns", self.unlock_horns), ("No Damage", self.disable_damage), ("Unlimited Fuel", self.unlimited_fuel), ("Smoke", self.unlock_smoke), ("Animations", self.unlock_animations), ("Wheels", self.unlock_wheels), ("Houses", self.unlock_houses), ("All Levels", self.complete_all_levels), ("Max Rank", self.set_rank)]
        if not self.load(uid, force=True): return {"ok": False, "message": "ACCOUNT LOAD FAILED."}
        results, failed = [], []
        for name, fn in feature_calls:
            res = fn(uid)
            if res.get("ok"): results.append(name)
            else: failed.append(f"{name}: {res.get('message', 'Failed')}")
        return {"ok": not failed, "message": f"Unlocked {len(results)}/{len(feature_calls)} features"}
        
    def fix_account(self, uid: int) -> Dict[str, Any]:
        if not self.load(uid, force=True): return {"ok": False, "message": "ACCOUNT LOAD FAILED."}
        td = self.get_token_data(uid)
        data = deepcopy(self.get_record(uid, td.get("email") if td else None))
        if data.get("money", 0) > MAX_MONEY: data["money"] = MAX_MONEY
        if data.get("coin", 0) > MAX_COIN: data["coin"] = MAX_COIN
        flags = data.get("flags", {})
        if isinstance(flags, dict):
            for bad_flag in [0, 1, 2, "0", "1", "2"]:
                flags.pop(bad_flag, None)
            data["flags"] = flags
        return self._save(uid, data, force_fields={"money", "coin", "flags"})

    def get_account_info(self, uid: int, force_refresh: bool = False) -> Dict[str, Any]:
        if not self.load(uid, force=force_refresh): return {"ok": False}
        td = self.get_token_data(uid)
        if not td: return {"ok": False}
        data = self.get_record(uid, td.get("email"))
        if not data or data.get("Name") is None: return {"ok": False}
        
        cars_count = 0
        try:
            c_status = data.get('carIDnStatus')
            if isinstance(c_status, dict):
                c_list = c_status.get('carStatus', [])
                if isinstance(c_list, list): cars_count = len(c_list)
        except: pass

        if cars_count == 0:
            try:
                ad = data.get('allData', '{}')
                if isinstance(ad, str):
                    ad_json = json.loads(ad)
                    if isinstance(ad_json, dict):
                        cars_count = len(ad_json.get('cars', []))
            except: pass
        
        return {"ok": True, "name": data.get("Name", "Unknown"), "money": data.get("money", 0), "coin": data.get("coin", 0), "localID": data.get("localID", "Unknown"), "email": td.get("email"), "cars": cars_count}

nuker = SyncCPMNuker()


# ================================================================
#  CLONE MODULE (merged)
# ================================================================

import uuid, re, struct, base64, zlib
# Clone helpers extracted from MARKCPM1TOOLS
import threading, time, json, html, random, string, uuid, re, struct, base64, zlib
try:
    import brotli
except ImportError:
    brotli = None
from typing import Any, Dict, List, Optional
import math

SOURCE_ACCOUNT = ('primocpmappsource@gmail.com', '123456')

CPM_CARS_FETCH_URL = "https://europe-west1-cp-multiplayer.cloudfunctions.net/GetAllCars2"
CPM_CARS_SAVE_URL = "https://europe-west1-cp-multiplayer.cloudfunctions.net/SaveCarsPartially8"

CPM_FIELD_NAMES = {
    1: 'CarID', 2: 'dataVersion', 3: 'vectors', 4: 'floats', 5: 'gears',
    6: 'typeToInstall', 7: 'BoughtParts', 8: 'texts', 9: 'flagID',
    10: 'fsoData', 11: 'installedPoliceLights', 12: 'Vynils', 13: 'WindowVinyls',
}

def cpm1_ios_headers(token):
    return {
        'accept': '*/*',
        'authorization': f'Bearer {token}',
        'content-type': 'application/json; charset=utf-8',
        'user-agent': 'CarParking/265 CFNetwork/3860.600.12 Darwin/25.5.0',
        'x-client-platform': 'IOS',
        'x-client-version': '4.9.10',
        'x-client-deviceid': str(uuid.uuid4()).upper(),
        'x-request-nonce': str(uuid.uuid4()),
        'x-unity-version': '2022.3.62f2',
        'accept-encoding': 'gzip',
        'connection': 'Keep-Alive',
    }

def cpm1_write_memorypack_string(s):
    if s is None or s == "": return struct.pack("<i", 0)
    sb = str(s).encode("utf-8")
    return struct.pack("<ii", -len(sb) - 1, len(sb)) + sb

def cpm1_looks_like_base64(val):
    if not isinstance(val, str): return False
    if len(val) < 4 or len(val) % 4 != 0: return False
    return bool(re.match(r'^[A-Za-z0-9+/]+={0,2}$', val))

def cpm1_deserialize_string_list(b64):
    if not b64 or not isinstance(b64, str): return []
    try: compressed = base64.b64decode(b64)
    except: return []
    try: decompressed = brotli.decompress(compressed)
    except:
        try: decompressed = zlib.decompress(compressed, zlib.MAX_WBITS | 16)
        except: decompressed = compressed
    if not decompressed or len(decompressed) < 4: return []
    out = []
    pos = 0
    count = struct.unpack_from("<i", decompressed, 0)[0]
    pos = 4
    if count <= 0 or count > 100000: return []
    for _ in range(count):
        if pos + 4 > len(decompressed): break
        marker = struct.unpack_from("<i", decompressed, pos)[0]
        pos += 4
        if marker == 0:
            out.append("")
            continue
        if marker == -1: break
        if marker < -1:
            byte_len = -marker - 1
            if pos + 4 > len(decompressed): break
            pos += 4
        else:
            byte_len = marker
        if pos + byte_len > len(decompressed): break
        s = decompressed[pos:pos+byte_len].decode("utf-8", errors="replace")
        pos += byte_len
        out.append(s.replace("\x00", "").strip())
    return out

def cpm1_is_readonly_cpm_id(v):
    if not isinstance(v, str): return False
    x = v.strip().upper()
    return len(x) == 8 and bool(re.match(r'^[A-Z]{2}\d{6}$', x))

def cpm1_generate_random_cpm_id():
    L = string.ascii_uppercase
    D = string.digits
    return ''.join(random.choice(L) for _ in range(2)) + ''.join(random.choice(D) for _ in range(6))

def cpm1_resolve_cpm_id(record):
    val = (record or {}).get("localID")
    if not val or not cpm1_is_readonly_cpm_id(val): val = cpm1_generate_random_cpm_id()
    return str(val).strip().upper()

def cpm1_generated_id_from_car(car):
    for k in ("generatedID", "generatedId", "carGeneratedID", "carGeneratedId"):
        v = car.get(k)
        if v and isinstance(v, str): return v
    texts = car.get("texts")
    if isinstance(texts, str):
        try: texts = cpm1_deserialize_string_list(texts)
        except: texts = []
    if isinstance(texts, list):
        for v in texts:
            if v and isinstance(v, str) and '_' in v and re.search(r'\d', v): return v
    return None

def cpm1_merge_cars_by_id(*car_lists):
    merged = {}
    for lst in car_lists:
        if not isinstance(lst, list): continue
        for car in lst:
            if not isinstance(car, dict): continue
            try: cid = int(car.get("CarID"))
            except: continue
            if cid < 0: continue
            merged[cid] = car
    return [merged[k] for k in sorted(merged.keys())]

def cpm1_replace_uid_in_value(value, src_uid, tgt_uid):
    if not src_uid or src_uid == tgt_uid: return value
    if isinstance(value, str):
        if cpm1_looks_like_base64(value): return value
        return value.replace(str(src_uid), str(tgt_uid))
    if isinstance(value, list): return [cpm1_replace_uid_in_value(v, src_uid, tgt_uid) for v in value]
    if isinstance(value, dict): return {k: cpm1_replace_uid_in_value(v, src_uid, tgt_uid) for k, v in value.items()}
    return value


def cpm1_normalize_car_physics(car):
    """Stop flying / fling / chrome-tint after clone or unlock.
    - NaN/Inf -> 0
    - Clamp absurd floats (suspension / height)
    - Soft-clamp vectors (keep normal paint 0..1)
    - Force near-ground if Y offset absurd
    - Preserve vinyl colors as uint32
    - Do NOT force floats[0] (siren) here — separate path
    """
    if not isinstance(car, dict):
        return car

    floats = car.get("floats")
    if isinstance(floats, list):
        out = []
        for i, v in enumerate(floats):
            try:
                f = float(v)
            except Exception:
                f = 0.0
            if math.isnan(f) or math.isinf(f):
                f = 0.0
            if abs(f) > 1e4:
                f = max(-1e4, min(1e4, f))
            out.append(f)
        # ride height / suspension-ish indices — keep modest
        for idx in (5, 6, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 35, 36, 37, 38, 39, 43):
            if idx < len(out):
                if abs(out[idx]) > 80:
                    out[idx] = max(-20.0, min(20.0, out[idx]))
        # mileage-ish index 19 sometimes huge → clamp
        if len(out) > 19 and abs(out[19]) > 1e6:
            out[19] = 0.0
        car["floats"] = out

    gears = car.get("gears")
    if isinstance(gears, list):
        gout = []
        for v in gears:
            try:
                f = float(v)
            except Exception:
                f = -10.0
            if math.isnan(f) or math.isinf(f):
                f = -10.0
            if abs(f) > 50:
                f = max(-50.0, min(50.0, f))
            gout.append(f)
        car["gears"] = gout

    vectors = car.get("vectors")
    if isinstance(vectors, list):
        vout = []
        for idx, vec in enumerate(vectors):
            if not isinstance(vec, dict):
                vout.append({"x": 0.0, "y": 0.0, "z": 0.0})
                continue
            try:
                x = float(vec.get("x") if vec.get("x") is not None else 0)
            except Exception:
                x = 0.0
            try:
                y = float(vec.get("y") if vec.get("y") is not None else 0)
            except Exception:
                y = 0.0
            try:
                z = float(vec.get("z") if vec.get("z") is not None else 0)
            except Exception:
                z = 0.0
            if math.isnan(x) or math.isinf(x):
                x = 0.0
            if math.isnan(y) or math.isinf(y):
                y = 0.0
            if math.isnan(z) or math.isinf(z):
                z = 0.0

            def soft(v, paint_ok=True):
                # normal paint / small scale
                if abs(v) <= 5.0:
                    return v
                if abs(v) > 200:
                    return max(-30.0, min(30.0, v))
                if abs(v) > 50:
                    return max(-15.0, min(15.0, v))
                return v

            # first few vectors often position/scale — harder clamp on Y (flying)
            if idx <= 2 and abs(y) > 10:
                y = max(-2.0, min(2.0, y))
            x, y, z = soft(x), soft(y), soft(z)
            vout.append({"x": x, "y": y, "z": z})
        car["vectors"] = vout

    # --- vynils: keep colors / packedData exact ---
    vyn = car.get("Vynils")
    if isinstance(vyn, dict) and isinstance(vyn.get("allVynils"), list):
        fixed = []
        for vinyl in vyn["allVynils"]:
            if not isinstance(vinyl, dict):
                continue
            nv = dict(vinyl)
            for fn in ("position", "scaleRotation", "iconPosition"):
                vec = nv.get(fn)
                if not isinstance(vec, dict):
                    continue
                try:
                    x = float(vec.get("x") if vec.get("x") is not None else 0)
                    y = float(vec.get("y") if vec.get("y") is not None else 0)
                    z = float(vec.get("z") if vec.get("z") is not None else 0)
                except Exception:
                    x = y = z = 0.0
                for a in (x, y, z):
                    pass
                if any(math.isnan(a) or math.isinf(a) for a in (x, y, z)):
                    x = y = z = 0.0
                # absurd scale → chrome/stretch artifacts
                if abs(x) > 500:
                    x = max(-100.0, min(100.0, x))
                if abs(y) > 500:
                    y = max(-100.0, min(100.0, y))
                if abs(z) > 1e6:
                    z = max(-3600.0, min(3600.0, z))
                nv[fn] = {"x": x, "y": y, "z": z}
            # color as full uint32 (do NOT use `or 0` which is fine; avoid float loss)
            try:
                if "color" in nv and nv["color"] is not None:
                    nv["color"] = int(nv["color"]) & 0xFFFFFFFF
            except Exception:
                nv["color"] = 0
            try:
                if "packedData" in nv and nv["packedData"] is not None:
                    nv["packedData"] = int(nv["packedData"])
            except Exception:
                pass
            fixed.append(nv)
        vyn = dict(vyn)
        vyn["allVynils"] = fixed
        try:
            vyn["CarID"] = int(car.get("CarID") or vyn.get("CarID") or 0)
        except Exception:
            pass
        car["Vynils"] = vyn

    # drop non-save junk that can confuse encoder
    for junk in ("source_slot", "sourceSlot", "one_car"):
        car.pop(junk, None)
    return car


def cpm1_prepare_car(stock_car, cpm_id):
    car_copy = json.loads(json.dumps(stock_car))
    car_id = int(car_copy.get("CarID") or 0)
    # strip harvest junk
    for junk in ("source_slot", "sourceSlot", "one_car", "car_id"):
        car_copy.pop(junk, None)
    if isinstance(car_copy.get("Vynils"), dict):
        car_copy["Vynils"]["CarID"] = car_id
    texts = car_copy.get("texts")
    if isinstance(texts, str):
        try: texts = cpm1_deserialize_string_list(texts)
        except: texts = []
    if not isinstance(texts, list): texts = []
    while len(texts) < 4: texts.append('')
    orig = texts[2]
    if isinstance(orig, str) and '_' in orig:
        parts = orig.split('_')
        texts[2] = f"{cpm_id}_" + "_".join(parts[1:])
    else:
        texts[2] = f"{cpm_id}_{car_id}XX000"
    car_copy["texts"] = texts
    # physics + vinyl safety (anti flying / anti chrome)
    car_copy = cpm1_normalize_car_physics(car_copy)
    return car_copy

def cpm1_build_car_entries(cars, cpm_id):
    entries = []
    for car in cars:
        try: cid = int(car.get("CarID"))
        except: continue
        if cid < 0: continue
        gen = cpm1_generated_id_from_car(car) or f"{cpm_id}_{cid}XX000"
        entries.append([cid, gen])
    return entries

def cpm1_entries_to_sparse(car_entries):
    if not car_entries:
        return {"carGeneratedIDs": [], "carStatus": []}
    ids = []
    for e in car_entries:
        try: ids.append(int(e[0]))
        except: pass
    ids = [i for i in ids if i >= 0]
    if not ids:
        return {"carGeneratedIDs": [], "carStatus": []}
    max_id = max(ids)
    gen_ids = [''] * (max_id + 1)
    statuses = [0] * (max_id + 1)
    for e in car_entries:
        try: cid = int(e[0])
        except: continue
        if 0 <= cid <= max_id:
            gen_ids[cid] = str(e[1]) if e[1] is not None else ''
            statuses[cid] = 1
    return {"carGeneratedIDs": gen_ids, "carStatus": statuses}

def cpm1_sanitize_car_for_encoding(car):
    clean = {}
    for key, value in car.items():
        if isinstance(value, str) and cpm1_looks_like_base64(value):
            clean[key] = value
            continue
        if key == 'floats':
            arr = value if isinstance(value, list) else []
            out = []
            for v in arr:
                try: f = float(v)
                except: f = 0.0
                out.append(f)
            while len(out) < 48: out.append(0.0)
            clean[key] = out
        elif key == 'gears':
            arr = value if isinstance(value, list) else []
            out = []
            for v in arr:
                try: f = float(v)
                except: f = -10.0
                out.append(f)
            clean[key] = out
        elif key == 'vectors':
            arr = value if isinstance(value, list) else []
            out = []
            for vec in arr:
                if isinstance(vec, dict):
                    try: x = float(vec.get('x') or 0)
                    except: x = 0.0
                    try: y = float(vec.get('y') or 0)
                    except: y = 0.0
                    try: z = float(vec.get('z') or 0)
                    except: z = 0.0
                    out.append({'x': x, 'y': y, 'z': z})
                else:
                    out.append({'x': 0.0, 'y': 0.0, 'z': 0.0})
            clean[key] = out
        elif key in ('typeToInstall', 'BoughtParts', 'fsoData', 'installedPoliceLights'):
            arr = value if isinstance(value, list) else []
            out = []
            for v in arr:
                try: iv = int(v)
                except: iv = 0
                out.append(iv)
            clean[key] = out
        elif key == 'texts':
            arr = value if isinstance(value, list) else []
            clean[key] = [str(v) if v is not None else '' for v in arr]
        elif key == 'Vynils':
            if isinstance(value, dict) and isinstance(value.get('allVynils'), list):
                fc = int(value.get('_fieldCount', 2) or 2)
                if fc < 2: fc = 2
                nv = {'_fieldCount': fc, 'allVynils': [], 'CarID': int(car.get('CarID', 0) or 0)}
                if isinstance(value.get('_remainingHex'), str): nv['_remainingHex'] = value['_remainingHex']
                for vinyl in value['allVynils']:
                    if not isinstance(vinyl, dict): continue
                    cv = {'_fieldCount': int(vinyl.get('_fieldCount', 6) or 6)}
                    for fn in ('position', 'scaleRotation', 'iconPosition'):
                        vec = vinyl.get(fn) or {}
                        if not isinstance(vec, dict): vec = {}
                        try: x = float(vec.get('x') or 0)
                        except: x = 0.0
                        try: y = float(vec.get('y') or 0)
                        except: y = 0.0
                        try: z = float(vec.get('z') or 0)
                        except: z = 0.0
                        cv[fn] = {'x': x, 'y': y, 'z': z}
                    cv['text'] = str(vinyl.get('text', '') or '')
                    cv['color'] = int(vinyl['color']) & 0xFFFFFFFF if vinyl.get('color') is not None else 0
                    cv['packedData'] = int(vinyl['packedData']) if vinyl.get('packedData') is not None else 0
                    nv['allVynils'].append(cv)
                clean[key] = nv
            else:
                clean[key] = value
        elif key == 'WindowVinyls':
            if isinstance(value, list):
                out = []
                for vinyl in value:
                    if not isinstance(vinyl, dict): continue
                    cv = {'_fieldCount': int(vinyl.get('_fieldCount', 6) or 6)}
                    for fn in ('position', 'scaleRotation', 'iconPosition'):
                        vec = vinyl.get(fn) or {}
                        if not isinstance(vec, dict): vec = {}
                        try: x = float(vec.get('x') or 0)
                        except: x = 0.0
                        try: y = float(vec.get('y') or 0)
                        except: y = 0.0
                        try: z = float(vec.get('z') or 0)
                        except: z = 0.0
                        cv[fn] = {'x': x, 'y': y, 'z': z}
                    cv['text'] = str(vinyl.get('text', '') or '')
                    cv['color'] = int(vinyl['color']) & 0xFFFFFFFF if vinyl.get('color') is not None else 0
                    cv['packedData'] = int(vinyl['packedData']) if vinyl.get('packedData') is not None else 0
                    out.append(cv)
                clean[key] = out
            else:
                clean[key] = value
        elif key in ('CarID', 'dataVersion', 'flagID'):
            try: clean[key] = int(value)
            except: clean[key] = 0
        else:
            clean[key] = value
    return clean

def cpm1_encode_field_value_binary(name, value):
    if name == 'vectors':
        if not isinstance(value, list): value = []
        buf = struct.pack("<i", len(value))
        for vec in value:
            x = float(vec.get('x') or 0) if isinstance(vec, dict) else 0.0
            y = float(vec.get('y') or 0) if isinstance(vec, dict) else 0.0
            z = float(vec.get('z') or 0) if isinstance(vec, dict) else 0.0
            buf += struct.pack("<fff", x, y, z)
        return buf
    if name in ('floats', 'gears'):
        if not isinstance(value, list): value = []
        buf = struct.pack("<i", len(value))
        for v in value:
            try: f = float(v)
            except: f = 0.0
            buf += struct.pack("<f", f)
        return buf
    if name in ('typeToInstall', 'BoughtParts', 'fsoData', 'installedPoliceLights'):
        if not isinstance(value, list): value = []
        buf = struct.pack("<i", len(value))
        for v in value:
            try: iv = int(v)
            except: iv = 0
            buf += struct.pack("<i", iv)
        return buf
    if name == 'texts':
        if not isinstance(value, list): value = []
        buf = struct.pack("<i", len(value))
        for v in value:
            buf += cpm1_write_memorypack_string(str(v) if v is not None else '')
        return buf
    if name == 'Vynils':
        if not isinstance(value, dict) or not isinstance(value.get('allVynils'), list): return b""
        fc = int(value.get('_fieldCount', 2) or 2)
        parts = [bytes([fc & 0xFF])]
        if fc == 0: return b"".join(parts)
        parts.append(struct.pack("<i", len(value['allVynils'])))
        for vinyl in value['allVynils']:
            if not isinstance(vinyl, dict):
                parts.append(bytes([0]))
                continue
            vfc = int(vinyl.get('_fieldCount', 6) or 6)
            parts.append(bytes([vfc & 0xFF]))
            if vfc == 0: continue
            for fn in ('position', 'scaleRotation', 'iconPosition'):
                vec = vinyl.get(fn) if isinstance(vinyl.get(fn), dict) else {}
                x = float(vec.get('x') or 0)
                y = float(vec.get('y') or 0)
                z = float(vec.get('z') or 0)
                parts.append(struct.pack("<fff", x, y, z))
            parts.append(cpm1_write_memorypack_string(str(vinyl.get('text', '') or '')))
            parts.append(struct.pack("<I", int(vinyl.get('color', 0) or 0) & 0xFFFFFFFF))
            try: pd = int(vinyl.get('packedData', 0) or 0)
            except: pd = 0
            parts.append(struct.pack("<q", pd))
        if fc >= 2:
            carid = value.get('CarID')
            if carid is None and isinstance(value.get('_remainingHex'), str) and value['_remainingHex']:
                try:
                    hx = bytes.fromhex(value['_remainingHex'])
                    carid = struct.unpack_from("<i", hx, 0)[0]
                except: carid = 0
            try: carid = int(carid) if carid is not None else 0
            except: carid = 0
            parts.append(struct.pack("<i", carid))
        return b"".join(parts)
    if name == 'WindowVinyls':
        if not isinstance(value, list): value = []
        parts = [struct.pack("<i", len(value))]
        for vinyl in value:
            if not isinstance(vinyl, dict):
                parts.append(bytes([0]))
                continue
            vfc = int(vinyl.get('_fieldCount', 6) or 6)
            parts.append(bytes([vfc & 0xFF]))
            if vfc == 0: continue
            for fn in ('position', 'scaleRotation', 'iconPosition'):
                vec = vinyl.get(fn) if isinstance(vinyl.get(fn), dict) else {}
                x = float(vec.get('x') or 0)
                y = float(vec.get('y') or 0)
                z = float(vec.get('z') or 0)
                parts.append(struct.pack("<fff", x, y, z))
            parts.append(cpm1_write_memorypack_string(str(vinyl.get('text', '') or '')))
            parts.append(struct.pack("<I", int(vinyl.get('color', 0) or 0) & 0xFFFFFFFF))
            try: pd = int(vinyl.get('packedData', 0) or 0)
            except: pd = 0
            parts.append(struct.pack("<q", pd))
        return b"".join(parts)
    return b""

def cpm1_encode_car_to_memorypack(car):
    fields = []
    for fid, name in CPM_FIELD_NAMES.items():
        if name in car and car[name] is not None:
            fields.append((fid, name, car[name]))
    fields.sort(key=lambda x: x[0])
    parts = [struct.pack("<i", len(fields))]
    for fid, name, value in fields:
        parts.append(struct.pack("<h", fid))
        if name in ('CarID', 'dataVersion', 'flagID'):
            try: iv = int(value)
            except: iv = 0
            parts.append(cpm1_write_memorypack_string(str(iv)))
        elif isinstance(value, str) and cpm1_looks_like_base64(value):
            parts.append(cpm1_write_memorypack_string(value))
        else:
            binv = cpm1_encode_field_value_binary(name, value)
            try: compressed = brotli.compress(binv, quality=4)
            except: compressed = brotli.compress(binv)
            parts.append(cpm1_write_memorypack_string(base64.b64encode(compressed).decode('ascii')))
    return b"".join(parts)

def cpm1_encrypt_car_for_save(car, uid):
    car = cpm1_normalize_car_physics(car)
    clean = cpm1_sanitize_car_for_encoding(car)
    key = make_xor_key(uid)
    mp = cpm1_encode_car_to_memorypack(clean)
    compressed = brotli.compress(mp, quality=4)
    encrypted = xor_bytes(compressed, key)
    return "__ver1__" + base64.b64encode(encrypted).decode('ascii')

def cpm1_fetch_cars_v2(token):
    try:
        resp = http_session.post(CPM_CARS_FETCH_URL, json={"data": ""}, headers=cpm1_ios_headers(token), timeout=20)
        if resp.status_code < 200 or resp.status_code >= 300:
            return {"success": False, "error": f"HTTP {resp.status_code}", "status": resp.status_code, "cars": []}
        parsed = resp.json() if resp.text else {}
        if isinstance(parsed, str):
            try: parsed = json.loads(parsed)
            except: pass
        raw_result = None
        if isinstance(parsed, dict):
            if parsed.get("result") is not None:
                raw_result = parsed["result"]
            elif isinstance(parsed.get("data"), dict) and parsed["data"].get("result") is not None:
                raw_result = parsed["data"]["result"]
        if raw_result is None:
            return {"success": True, "cars": []}
        cars = []
        try: cars = json.loads(raw_result)
        except:
            m = re.search(r'\[\s*\{[\s\S]*\}\s*\]', str(raw_result))
            if m:
                try: cars = json.loads(m.group(0))
                except: pass
        return {"success": True, "cars": cars if isinstance(cars, list) else []}
    except Exception as e:
        return {"success": False, "error": str(e), "cars": []}

def cpm1_save_car_encrypted_v2(token, car, uid, retries=2):
    try: payload = cpm1_encrypt_car_for_save(car, uid)
    except Exception as e: return {"success": False, "error": f"encode:{str(e)[:80]}"}
    headers = cpm1_ios_headers(token)
    last = {"success": False, "error": "max_retries"}
    for attempt in range(1, retries + 1):
        try:
            resp = http_session.post(CPM_CARS_SAVE_URL, json={"data": payload}, headers=headers, timeout=30)
            if resp.status_code < 300:
                return {"success": True, "status": resp.status_code, "data": resp.text}
            if resp.status_code in (401, 403):
                return {"success": False, "auth": True, "status": resp.status_code, "error": f"HTTP {resp.status_code}"}
            last = {"success": False, "status": resp.status_code, "error": f"HTTP {resp.status_code}"}
        except Exception as e:
            last = {"success": False, "error": str(e)[:120]}
        if attempt < retries:
            time.sleep(min(1 * attempt, 3))
    return last

def cpm1_save_car_status(auth, fuid, car_entries):
    sparse = cpm1_entries_to_sparse(car_entries)
    gen_ids = ['' if v is None else str(v) for v in sparse["carGeneratedIDs"]]
    statuses = [0 if v is None else int(v) for v in sparse["carStatus"]]
    record = {"carIDnStatus": {"carGeneratedIDs": gen_ids, "carStatus": statuses}}
    try:
        ok, msg = nuker._send(auth, record, fuid, original=None, force_fields={"carIDnStatus"})
        return {"success": bool(ok), "message": msg}
    except Exception as e:
        return {"success": False, "message": str(e)[:120]}

def cpm1_verify_clone_v2(token, expected_car_ids):
    r = cpm1_fetch_cars_v2(token)
    if not r.get("success"):
        return {"success": False, "error": r.get("error"), "present": [], "missing": list(expected_car_ids)}
    present = set()
    for c in r.get("cars", []):
        try: present.add(int(c.get("CarID")))
        except: pass
    missing = [cid for cid in expected_car_ids if cid not in present]
    return {"success": len(missing) == 0, "present": list(present), "missing": missing}

def cpm1_clone_cars_core(tgt_email, tgt_password, src_cars_to_clone, src_uid=None, tgt_token=None, tgt_uid=None, existing_tgt_cars=None, progress_cb=None, verify=True):
    result = {"success": False, "ok": 0, "fail": 0, "total": len(src_cars_to_clone), "stage": "INIT", "failed": [], "verified": None, "tgt_token": tgt_token, "tgt_uid": tgt_uid}

    if not tgt_token or not tgt_uid:
        lr = nuker.login(tgt_email, tgt_password)
        if not lr.get("ok"):
            result["stage"] = "LOGIN"
            result["error"] = lr.get("message", "login_fail")
            return result
        tgt_token, tgt_uid = lr["auth"], lr["firebase_uid"]

    if existing_tgt_cars is None:
        r = cpm1_fetch_cars_v2(tgt_token)
        if not r.get("success") and r.get("status") in (401, 403):
            lr = nuker.login(tgt_email, tgt_password)
            if lr.get("ok"):
                tgt_token, tgt_uid = lr["auth"], lr["firebase_uid"]
                r = cpm1_fetch_cars_v2(tgt_token)
        if not r.get("success"):
            result["stage"] = "FETCH_TGT"
            result["error"] = r.get("error", "fetch_fail")
            return result
        existing_tgt_cars = r["cars"]

    result["tgt_token"] = tgt_token
    result["tgt_uid"] = tgt_uid

    rec = nuker.get_record(tgt_uid, tgt_email) or {}
    cpm_id = cpm1_resolve_cpm_id(rec)
    result["cpm_id"] = cpm_id

    prepared = []
    for car in src_cars_to_clone:
        try:
            c2 = json.loads(json.dumps(car))
            if src_uid:
                c2 = cpm1_replace_uid_in_value(c2, src_uid, tgt_uid)
            prepared.append(cpm1_prepare_car(c2, cpm_id))
        except Exception as e:
            result["failed"].append({"CarID": car.get("CarID"), "stage": "PREPARE", "error": str(e)[:120]})

    if not prepared:
        result["stage"] = "PREPARE"
        result["error"] = "no_prepared"
        return result

    merged = cpm1_merge_cars_by_id(existing_tgt_cars, prepared)
    entries = cpm1_build_car_entries(merged, cpm_id)

    sr = cpm1_save_car_status(tgt_token, tgt_uid, entries)
    if not sr.get("success"):
        lr = nuker.login(tgt_email, tgt_password)
        if lr.get("ok"):
            tgt_token, tgt_uid = lr["auth"], lr["firebase_uid"]
            result["tgt_token"] = tgt_token
            result["tgt_uid"] = tgt_uid
            sr = cpm1_save_car_status(tgt_token, tgt_uid, entries)
    if not sr.get("success"):
        result["stage"] = "STATUS_SAVE"
        result["error"] = sr.get("message", "status_fail")
        return result

    ok = 0
    total = len(prepared)
    for i, car in enumerate(prepared):
        sr = cpm1_save_car_encrypted_v2(tgt_token, car, tgt_uid, retries=2)
        if not sr.get("success") and sr.get("auth"):
            lr = nuker.login(tgt_email, tgt_password)
            if lr.get("ok"):
                tgt_token, tgt_uid = lr["auth"], lr["firebase_uid"]
                result["tgt_token"] = tgt_token
                result["tgt_uid"] = tgt_uid
                sr = cpm1_save_car_encrypted_v2(tgt_token, car, tgt_uid, retries=2)
        if sr.get("success"):
            ok += 1
        else:
            result["failed"].append({"CarID": car.get("CarID"), "stage": "CAR_SAVE", "error": sr.get("error", "unknown")})
        if progress_cb:
            try: progress_cb(i + 1, total)
            except: pass
        time.sleep(0.15)

    result["ok"] = ok
    result["fail"] = total - ok
    result["stage"] = "DONE"
    result["success"] = ok > 0

    if verify:
        try:
            v = cpm1_verify_clone_v2(tgt_token, [c.get("CarID") for c in prepared])
            result["verified"] = v
        except Exception as e:
            result["verified"] = {"success": False, "error": str(e)[:80]}

    return result

# ================================================================
#  BACKGROUND WORKERS (WITH TOKEN DEDUCTION)
# ================================================================
def _rand_gmail():
    """Random Gmail e.g. IajOriknk200@gmail.com"""
    n = random.randint(8, 12)
    name = "".join(random.choice(string.ascii_letters) for _ in range(n))
    # mix case like example
    name = "".join(c.upper() if random.random() < 0.35 else c.lower() for c in name)
    digits = str(random.randint(10, 9999))
    return name + digits + "@gmail.com"


def _rand_password():
    """Random password letters+digits, length 10–14."""
    alphabet = string.ascii_letters + string.digits
    return "".join(random.choice(alphabet) for _ in range(random.randint(10, 14)))


def clone_task(src_record, src_cars, i, res_list, source_token, source_uid, progress_cb=None):
    t_email = _rand_gmail()
    t_pass = _rand_password()
    reg_ok = False
    for _ in range(3):
        try:
            r = http_session.post(f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={FK}", json={"email": t_email, "password": t_pass, "returnSecureToken": True}, timeout=15)
            if "idToken" in r.text:
                reg_ok = True
                break
        except: pass
        time.sleep(0.5)

    if progress_cb: progress_cb(i, "registering")
if not reg_ok:
    if progress_cb:
        progress_cb(i, "failed")
    return None, None

    blank = {
        "Name": "Player",
        "money": int(src_record.get("money") or 25000) if isinstance(src_record, dict) else 25000,
        "coin": int(src_record.get("coin") or 0) if isinstance(src_record, dict) else 0,
        "localID": str(random.randint(1000000, 9999999)).zfill(8),
        "allData": '{"cars":[]}',
        "floats": list(src_record.get("floats") or []) if isinstance(src_record, dict) else [],
        "integers": list(src_record.get("integers") or []) if isinstance(src_record, dict) else [],
    }
    try:
        lr = nuker.login(t_email, t_pass)
        if lr.get("ok"):
            nuker._send(lr["auth"], blank, lr["firebase_uid"])
    except Exception:
        pass

    cres = cpm1_clone_cars_core(t_email, t_pass, src_cars, src_uid=source_uid, verify=False)
    if progress_cb:
        progress_cb(i, "ok" if cres.get("ok", 0) > 0 else "fail")
    return t_email, t_pass




# Full profile clone: everything except friends + player ID (localID)
IDENTITY_EXCLUDE = (
    "localID", "LocalID", "id", "ID", "playerId", "playerID",
    "email", "Email", "firebase_uid",
)
FRIEND_EXCLUDE = (
    "friends", "Friends", "friendList", "FriendList",
    "friendsData", "FriendsData", "saveFriends", "SaveFriends",
    "FriendsID", "friendsID",
)

PROFILE_CLONE_FIELDS = (
    "money", "coin",
    "floats", "integers",
    "boughtFsos", "boughtPoliceLights", "boughtPoliceSirens",
    "wheels", "animations", "emojiPacks",
    "favouriteWheels", "favouriteVinyls", "favouriteEmojis",
    "LevelsDoneTime",
    "personEquipmentsMale", "personEquipmentsFemale",
    "platesData",
    "carIDnStatus", "flags", "fcar",
    "allData",
    # Name optional — not an ID; still skip by default (include_name=True to copy)
)


def load_source_profile(src_email, src_pass):
    """Login source, load full player record + cars."""
    s = nuker.login(src_email, src_pass)
    if not s.get("ok"):
        return None, "Source login failed"
    # temporary uid for loading source into nuker cache
    src_uid_hash = abs(hash(src_email)) % (10**9)
    nuker.save_token(
        src_uid_hash, s["auth"], src_email, src_pass,
        s.get("refresh_token", ""), s.get("firebase_uid", ""),
    )
    nuker.load(src_uid_hash, force=True)
    rec = nuker.get_record(src_uid_hash, src_email) or {}
    fr = cpm1_fetch_cars_v2(s["auth"])
    cars = fr.get("cars", []) if fr.get("success") else []
    return {
        "login": s,
        "record": rec,
        "cars": cars,
        "uid_hash": src_uid_hash,
    }, "ok"


def apply_profile_to_target(tgt_email, tgt_pass, src_record, include_name=False):
    """Copy full data (money coin unlocks plates cars status rank…) except friends + localID."""
    t = nuker.login(tgt_email, tgt_pass)
    if not t.get("ok"):
        return {"ok": False, "message": "Target login failed"}
    tgt_hash = abs(hash(tgt_email + ":tgt")) % (10**9)
    nuker.save_token(
        tgt_hash, t["auth"], tgt_email, tgt_pass,
        t.get("refresh_token", ""), t.get("firebase_uid", ""),
    )
    nuker.load(tgt_hash, force=True)
    mods = {}
    force = set()
    skip = set(IDENTITY_EXCLUDE) | set(FRIEND_EXCLUDE)
    for field in PROFILE_CLONE_FIELDS:
        if field in skip:
            continue
        if field in src_record and src_record[field] is not None:
            mods[field] = src_record[field]
            force.add(field)
    # never write localID / FriendsID even if present in allData
    if "allData" in mods:
        ad = mods["allData"]
        if isinstance(ad, str):
            try:
                import json as _json
                ad_obj = _json.loads(ad)
            except Exception:
                ad_obj = None
            if isinstance(ad_obj, dict):
                for k in list(ad_obj.keys()):
                    kl = str(k).lower()
                    if "friend" in kl or kl in ("localid", "id", "playerid"):
                        ad_obj.pop(k, None)
                mods["allData"] = _json.dumps(ad_obj)
        elif isinstance(ad, dict):
            ad = dict(ad)
            for k in list(ad.keys()):
                kl = str(k).lower()
                if "friend" in kl or kl in ("localid", "id", "playerid"):
                    ad.pop(k, None)
            mods["allData"] = ad
    if include_name and src_record.get("Name"):
        mods["Name"] = src_record["Name"]
        force.add("Name")
    if "money" in mods:
        try:
            mods["money"] = min(int(mods["money"]), MAX_MONEY)
        except Exception:
            pass
    if "coin" in mods:
        try:
            mods["coin"] = min(int(mods["coin"]), MAX_COIN)
        except Exception:
            pass
    notes = []
    if mods:
        res = nuker._modify(tgt_hash, mods, force_fields=force)
        notes.append("profile:" + ("OK" if res.get("ok") else str(res.get("message", "fail"))))
    else:
        res = {"ok": False, "message": "No profile fields"}
        notes.append("profile:empty")
    # King rank always
    try:
        rr = nuker.set_rank(tgt_hash)
        notes.append("rank:" + ("OK" if rr.get("ok") else "fail"))
    except Exception as e:
        notes.append("rank:" + str(e)[:40])
    # Full unlock pack (W16 fuel houses etc.)
    try:
        ur = nuker.unlock_all_features(tgt_hash)
        notes.append("unlocks:" + ("OK" if ur.get("ok") else "partial"))
    except Exception as e:
        notes.append("unlocks:" + str(e)[:40])
    return {
        "ok": bool(res.get("ok")),
        "message": " · ".join(notes),
    }


def web_clone_account(src_email, src_pass, tgt_email, tgt_pass, progress_cb=None):
    """Full clone: all data except friends + localID (keeps target ID).
    progress_cb(pct:int 0-100, message:str)
    """
    def _p(pct, msg):
        if progress_cb:
            try:
                progress_cb(int(max(0, min(100, pct))), str(msg))
            except Exception:
                pass

    _p(2, "Loading source account…")
    src, msg = load_source_profile(src_email, src_pass)
    if not src:
        _p(100, "Failed: " + str(msg))
        return {"ok": False, "message": msg}
    cars = src["cars"] or []
    rec = src["record"]
    notes = []
    _p(12, "Copying profile data…")
    # 1) profile data
    pr = apply_profile_to_target(tgt_email, tgt_pass, rec, include_name=False)
    notes.append(pr.get("message", "profile"))
    # 2) cars
    if cars:
        total_cars = len(cars)
        _p(18, "Cloning cars 0/%d…" % total_cars)

        def car_progress(done, total):
            total = max(1, int(total or 1))
            done = int(done or 0)
            # cars occupy 20% → 92%
            pct = 20 + int(72 * done / total)
            _p(pct, "Cloning cars %d/%d…" % (done, total))

        res = cpm1_clone_cars_core(
            tgt_email, tgt_pass, cars,
            src_uid=src["login"].get("firebase_uid"),
            verify=True,
            progress_cb=car_progress,
        )
        notes.append(f"cars:{res.get('ok', 0)}/{res.get('total', 0)}")
        cars_ok = bool(res.get("ok", 0) > 0)
    else:
        notes.append("cars:0")
        cars_ok = False
        res = {}
        _p(90, "No cars to clone")
    # plates count
    plates = 0
    pd = rec.get("platesData")
    if isinstance(pd, dict):
        plates = len(pd.get("allPlates") or [])
    elif isinstance(pd, list):
        plates = len(pd)
    ok = pr.get("ok") or cars_ok
    _p(100, "Clone finished" if ok else "Clone finished with errors")
    return {
        "ok": bool(ok),
        "message": f"Clone done · plates {plates} · " + " · ".join(notes),
        "detail": {"profile": pr, "cars": res},
    }


def web_bulk_clone(src_email, src_pass, count, progress_cb=None):
    """Create N accounts (max 50) — full data except friends + player ID."""
    count = max(1, min(50, int(count)))
    src, msg = load_source_profile(src_email, src_pass)
    if not src:
        return {"ok": False, "message": msg, "accounts": []}
    cars = list(src["cars"] or [])  # do NOT force siren — causes flying/chrome
    rec = src["record"]
    # ensure unlock-style floats present on source record for copy
    accounts = []
    for i in range(count):
        if progress_cb:
            try:
                pct = int(100 * i / max(1, count))
                progress_cb(i, count, "Creating account %d/%d" % (i + 1, count), pct)
            except TypeError:
                try:
                    progress_cb(i, count, "Creating account %d/%d" % (i + 1, count))
                except Exception:
                    pass
            except Exception:
                pass
        email, pw = clone_task(
            rec,
            cars,
            i,
            [],
            src["login"]["auth"],
            src["login"].get("firebase_uid")
        )

        if not email or not pw:
            continue

        try:
            apply_profile_to_target(email, pw, rec, include_name=False)
        except Exception:
            pass

        accounts.append("%s:%s" % (email, pw))

    if progress_cb:
        try:
            progress_cb(count, count, "Done")
        except Exception:
            pass

    return {
        "ok": bool(accounts),
        "message": "Created %d full-clone accounts" % len(accounts),
        "accounts": accounts
    }

def set_cars_siren(cars):
    import copy
    out = []
    for car in cars:
        c = copy.deepcopy(car)
        floats = list(c.get("floats") or [])
        while len(floats) < 1:
            floats.append(0.0)
        floats[0] = 1.0
        c["floats"] = floats
        c = cpm1_normalize_car_physics(c)
        out.append(c)
    return out


# ================================================================
# UNLOCK CARS (from SOURCE_ACCOUNT → target logged-in account)
# ================================================================
def unlock_cars_to_account(tgt_email, tgt_pass, car_ids=None, progress_cb=None):
    """
    Inject cars from SOURCE_ACCOUNT into target.
    car_ids: None = all cars from source; or list/int of CarID(s).
    Applies physics normalize (no forced siren).
    """
    src_email, src_pass = SOURCE_ACCOUNT
    src, msg = load_source_profile(src_email, src_pass)
    if not src:
        return {"ok": False, "message": "Source login failed: %s" % msg, "ok_n": 0, "total": 0}
    cars = list(src.get("cars") or [])
    if not cars:
        return {"ok": False, "message": "Source has no cars", "ok_n": 0, "total": 0}

    if car_ids is not None:
        if isinstance(car_ids, (int, float, str)):
            want = {int(car_ids)}
        else:
            want = {int(x) for x in car_ids}
        filtered = []
        for c in cars:
            try:
                cid = int(c.get("CarID"))
            except Exception:
                continue
            if cid in want:
                filtered.append(c)
        cars = filtered
        if not cars:
            return {"ok": False, "message": "Car ID(s) not on source: %s" % sorted(want), "ok_n": 0, "total": 0}

    # never force siren here
    def _p(done, total):
        if progress_cb:
            try:
                progress_cb(done, total)
            except Exception:
                pass

    res = cpm1_clone_cars_core(
        tgt_email, tgt_pass, cars,
        src_uid=src["login"].get("firebase_uid"),
        verify=True,
        progress_cb=_p,
    )
    return {
        "ok": bool(res.get("ok", 0) > 0),
        "message": "Cars unlocked %s/%s" % (res.get("ok", 0), res.get("total", 0)),
        "ok_n": res.get("ok", 0),
        "total": res.get("total", 0),
        "failed": res.get("failed") or [],
        "detail": res,
    }


def unlock_all_cars(tgt_email, tgt_pass, progress_cb=None):
    return unlock_cars_to_account(tgt_email, tgt_pass, car_ids=None, progress_cb=progress_cb)


def unlock_one_car(tgt_email, tgt_pass, car_id, progress_cb=None):
    return unlock_cars_to_account(tgt_email, tgt_pass, car_ids=car_id, progress_cb=progress_cb)



# ================================================================
#  SIREN MODULE (merged)
# ================================================================
SIREN_DB = "siren_tokens.db"
with sqlite3.connect(SIREN_DB) as _sc:
    _sc.execute("""CREATE TABLE IF NOT EXISTS tokens (
        user_id INTEGER PRIMARY KEY, auth_token TEXT, email TEXT, password TEXT,
        refresh_token TEXT, firebase_uid TEXT, token_expires_at REAL)""")
    _sc.commit()

def login(email, password):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FK}"
    try:
        r = http_session.post(url, json={"email": email, "password": password, "returnSecureToken": True}, timeout=20)
        data = r.json() if r.text else {}
        if "idToken" in data:
            return {
                "ok": True,
                "auth": data["idToken"],
                "firebase_uid": data.get("localId", ""),
                "refresh_token": data.get("refreshToken", ""),
            }
        err = data.get("error", {})
        return {"ok": False, "message": err.get("message", "login failed") if isinstance(err, dict) else str(err)}
    except Exception as e:
        return {"ok": False, "message": str(e)[:120]}


def save_token(uid, auth, email, pw, rt, fuid):
    with sqlite3.connect(SIREN_DB) as c:
        c.execute("INSERT OR REPLACE INTO tokens VALUES (?,?,?,?,?,?,?)",
                  (uid, auth, email, pw, rt, fuid, time.time() + 3500))
        c.commit()


def get_token(uid):
    with sqlite3.connect(SIREN_DB) as c:
        row = c.execute("SELECT auth_token,email,password,refresh_token,firebase_uid FROM tokens WHERE user_id=?", (uid,)).fetchone()
    if not row:
        return None
    return {"auth": row[0], "email": row[1], "password": row[2], "refresh_token": row[3], "firebase_uid": row[4]}


def delete_token(uid):
    with sqlite3.connect(SIREN_DB) as c:
        c.execute("DELETE FROM tokens WHERE user_id=?", (uid,))
        c.commit()

# ---------- siren only ----------
def set_siren(car):
    c = deepcopy(car)
    floats = list(c.get("floats") or [])
    while len(floats) < 1:
        floats.append(0.0)
    floats[0] = 1.0
    c["floats"] = floats
    return c


def unlock_siren(email, password, car_id=None, progress_cb=None):
    lr = login(email, password)
    if not lr.get("ok"):
        return {"ok": False, "message": lr.get("message", "login failed"), "updated": 0, "total": 0}
    token, uid = lr["auth"], lr["firebase_uid"]
    fr = cpm1_fetch_cars_v2(token)
    if not fr.get("success"):
        return {"ok": False, "message": fr.get("error", "fetch failed"), "updated": 0, "total": 0}
    cars_list = fr.get("cars") or []
    if not cars_list:
        return {"ok": False, "message": "No cars", "updated": 0, "total": 0}
    targets = []
    for c in cars_list:
        try:
            cid = int(c.get("CarID") or c.get("id") or -1)
        except Exception:
            cid = -1
        if car_id is None or cid == int(car_id):
            targets.append(c)
    if not targets:
        return {"ok": False, "message": "Car not found", "updated": 0, "total": 0}
    updated, total = 0, len(targets)
    for i, car in enumerate(targets):
        if progress_cb:
            try:
                progress_cb(i, total)
            except Exception:
                pass
        fixed = set_siren(car)
        # soft clamp floats to reduce flying side-effect
        fl = list(fixed.get("floats") or [])
        for i,v in enumerate(fl):
            try:
                f=float(v)
            except Exception:
                f=0.0
            if abs(f)>1e4: f=max(-1e4,min(1e4,f))
            fl[i]=f
        fixed["floats"]=fl
        sr = cpm1_save_car_encrypted_v2(token, fixed, uid, retries=2)
        if sr.get("success"):
            updated += 1
        time.sleep(0.12)
    if progress_cb:
        try:
            progress_cb(total, total)
        except Exception:
            pass
    return {"ok": updated > 0, "message": "Siren %d/%d" % (updated, total), "updated": updated, "total": total}




# ================================================================
#  PLATES MODULE (merged)
# ================================================================


"""Inject plates.json into CPM1 account (sync, uses cpm1_core.nuker)."""
import json
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent
DEFAULT_PLATES = ROOT / "plates.json"


def normalize_plate(p: dict) -> dict:
    if not isinstance(p, dict):
        return {"plateId": 0, "frontCarId": 0, "rearCarId": 0, "vinyls": []}
    vinyls = []
    for v in p.get("vinyls") or []:
        if not isinstance(v, dict):
            continue
        vinyls.append({
            "vectors": v.get("vectors") or [],
            "v": v.get("v") or [],
            "floats": v.get("floats") or [],
            "text": str(v.get("text") or ""),
        })
    return {
        "plateId": int(p.get("plateId") or 0),
        "frontCarId": int(p.get("frontCarId") or 0),
        "rearCarId": int(p.get("rearCarId") or 0),
        "vinyls": vinyls,
    }


def load_plates(path: Path = None) -> Dict[str, Any]:
    path = path or DEFAULT_PLATES
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return {"allPlates": [normalize_plate(p) for p in data]}
    if isinstance(data, dict) and "allPlates" in data:
        return {"allPlates": [normalize_plate(p) for p in data["allPlates"]]}
    return {"allPlates": []}


def inject_plates(email: str, password: str, merge: bool = True, plates_path: Path = None) -> Dict[str, Any]:
    plates_data = load_plates(plates_path)
    incoming = plates_data.get("allPlates") or []
    if not incoming:
        return {"ok": False, "message": "No plates in plates.json"}
    lr = nuker.login(email, password)
    if not lr.get("ok"):
        return {"ok": False, "message": lr.get("message", "login failed")}
    uid = abs(hash(email + ":plates")) % (10**9)
    nuker.save_token(uid, lr["auth"], email, password, lr.get("refresh_token", ""), lr.get("firebase_uid", ""))
    if not nuker.load(uid, force=True):
        return {"ok": False, "message": "Could not load account"}
    record = nuker.get_record(uid, email) or {}
    current = record.get("platesData") if isinstance(record.get("platesData"), dict) else {"allPlates": []}
    if merge:
        by_id = {}
        for p in current.get("allPlates") or []:
            if isinstance(p, dict):
                by_id[int(p.get("plateId") or 0)] = normalize_plate(p)
        for p in incoming:
            by_id[int(p.get("plateId") or 0)] = p
        final = {"allPlates": list(by_id.values())}
    else:
        final = {"allPlates": incoming}
    res = nuker._modify(uid, {"platesData": final}, force_fields={"platesData"})
    if res.get("ok"):
        res["message"] = "OK — %d plate(s) injected" % len(incoming)
        res["injected"] = len(incoming)
        res["total_on_account"] = len(final["allPlates"])
    return res


# ================================================================
#  BOT + WEB APP (merged)
# ================================================================

#!/usr/bin/env python3
"""DARK CPM — Mini App product (bot = launcher only)."""

import base64
import hashlib
import hmac
import io
import json
import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl

import telebot
from telebot import types
from flask import Flask, jsonify, redirect, request

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8837713061:AAFvTKlT_KP2B9nc2KhrPPaC0CpEmYw3YkE")
ADMIN_IDS = {int(x) for x in os.environ.get("ADMIN_IDS", "8966638194").split(",") if x.strip()}
WEBAPP_URL = "https://dark-tb42.onrender.com"
PORT = int(os.environ.get("PORT", "8080"))

# SAME membership database for /givesub + Mini App
MEMBERSHIP_DB_PATH = ROOT / "miniapp.db"
DB = os.environ.get("MEMBERSHIP_DB", str(MEMBERSHIP_DB_PATH))
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML") if BOT_TOKEN else None

# Stars (XTR) + money (fiat) prices — override via env if needed
PLANS = {
    "1day": {
        "label": "1 Day",
        "days": 1,
        "stars": int(os.environ.get("PRICE_1DAY_STARS", "50")),
        "money": float(os.environ.get("PRICE_1DAY_MONEY", "1.00")),
        "money_label": os.environ.get("PRICE_1DAY_MONEY_LABEL", "$1"),
    },
    "7days": {
        "label": "7 Days",
        "days": 7,
        "stars": int(os.environ.get("PRICE_7DAYS_STARS", "100")),
        "money": float(os.environ.get("PRICE_7DAYS_MONEY", "3.00")),
        "money_label": os.environ.get("PRICE_7DAYS_MONEY_LABEL", "$3"),
    },
    "1month": {
        "label": "1 Month",
        "days": 30,
        "stars": int(os.environ.get("PRICE_1MONTH_STARS", "250")),
        "money": float(os.environ.get("PRICE_1MONTH_MONEY", "8.00")),
        "money_label": os.environ.get("PRICE_1MONTH_MONEY_LABEL", "$8"),
    },
    "lifetime": {
        "label": "Lifetime",
        "days": 36500,
        "stars": int(os.environ.get("PRICE_LIFETIME_STARS", "350")),
        "money": float(os.environ.get("PRICE_LIFETIME_MONEY", "15.00")),
        "money_label": os.environ.get("PRICE_LIFETIME_MONEY_LABEL", "$15"),
    },
}

# Money payment details (show to users) — set in Railway env
PAY_GCASH = os.environ.get("PAY_GCASH", "09243477978").strip()
PAY_PAYPAL = os.environ.get("PAY_PAYPAL", "rebeccaanas1991@gmail.com").strip()
PAY_OTHER = os.environ.get("PAY_OTHER", "").strip()  # free text e.g. "Bank: BDO 1234"
PAY_CURRENCY = os.environ.get("PAY_CURRENCY", "USD").strip()

def _money_instructions():
    parts = ["<b>Pay with money</b>"]
    if PAY_GCASH:
        parts.append("GCash: <code>%s</code>" % PAY_GCASH)
    if PAY_PAYPAL:
        parts.append("PayPal: <code>%s</code>" % PAY_PAYPAL)
    if PAY_OTHER:
        parts.append(PAY_OTHER)
    if len(parts) == 1:
        parts.append("Contact admin for payment details.")
    parts.append("After payment, admin activates with /givesub.")
    return "\n".join(parts)


def _money_instructions_plain():
    parts = []
    if PAY_GCASH:
        parts.append("GCash: " + PAY_GCASH)
    if PAY_PAYPAL:
        parts.append("PayPal: " + PAY_PAYPAL)
    if PAY_OTHER:
        parts.append(PAY_OTHER)
    if not parts:
        parts.append("Contact admin for payment details.")
    return " | ".join(parts)




_LOGIN_B64 = """PCFET0NUWVBFIGh0bWw+CjxodG1sIGxhbmc9ImVuIj4KPGhlYWQ+CjxtZXRhIGNoYXJzZXQ9InV0Zi04Ii8+CjxtZXRhIG5hbWU9InZpZXdwb3J0IiBjb250
ZW50PSJ3aWR0aD1kZXZpY2Utd2lkdGgsIGluaXRpYWwtc2NhbGU9MSwgbWF4aW11bS1zY2FsZT0xLCB1c2VyLXNjYWxhYmxlPW5vIi8+Cjx0aXRsZT5EQVJL
IENQTSDigJQgTG9naW48L3RpdGxlPgo8c2NyaXB0IHNyYz0iaHR0cHM6Ly90ZWxlZ3JhbS5vcmcvanMvdGVsZWdyYW0td2ViLWFwcC5qcyI+PC9zY3JpcHQ+
CjxzdHlsZT4KOnJvb3QgewogIC0tYmc6ICMwYjBiMGY7IC0tY2FyZDogIzE0MTQxYTsgLS1saW5lOiByZ2JhKDI1NSwyNTUsMjU1LC4wOCk7CiAgLS10ZXh0
OiAjZjRmNGY1OyAtLW11dGVkOiAjOWNhM2FmOyAtLWFjY2VudDogI2E4NTVmNzsgLS1hY2NlbnQyOiAjYzAyNmQzOwp9CiogeyBib3gtc2l6aW5nOiBib3Jk
ZXItYm94OyBtYXJnaW46IDA7IHBhZGRpbmc6IDA7IH0KYm9keSB7CiAgZm9udC1mYW1pbHk6IC1hcHBsZS1zeXN0ZW0sIEJsaW5rTWFjU3lzdGVtRm9udCwg
IlNGIFBybyBUZXh0IiwgIlNlZ29lIFVJIiwgc3lzdGVtLXVpLCBzYW5zLXNlcmlmOwogIGJhY2tncm91bmQ6IHJhZGlhbC1ncmFkaWVudChlbGxpcHNlIGF0
IHRvcCwgIzFhMGEyZSAwJSwgIzBiMGIwZiA2MCUpOwogIGNvbG9yOiB2YXIoLS10ZXh0KTsgbWluLWhlaWdodDogMTAwdmg7IHBhZGRpbmc6IDIwcHggMTZw
eDsKfQoud3JhcCB7IG1heC13aWR0aDogNDIwcHg7IG1hcmdpbjogMCBhdXRvOyBtaW4taGVpZ2h0OiA5MHZoOyBkaXNwbGF5OiBmbGV4OyBmbGV4LWRpcmVj
dGlvbjogY29sdW1uOyBqdXN0aWZ5LWNvbnRlbnQ6IGNlbnRlcjsgfQouYnJhbmQgeyB0ZXh0LWFsaWduOiBjZW50ZXI7IGZvbnQtd2VpZ2h0OiA4MDA7IGZv
bnQtc2l6ZTogMS4zNXJlbTsgbGV0dGVyLXNwYWNpbmc6IC4wMmVtOwogIGJhY2tncm91bmQ6IGxpbmVhci1ncmFkaWVudCg5MGRlZywgI2E4NTVmNywgI2Vj
NDg5OSk7IC13ZWJraXQtYmFja2dyb3VuZC1jbGlwOiB0ZXh0OyBjb2xvcjogdHJhbnNwYXJlbnQ7IG1hcmdpbi1ib3R0b206IDZweDsgfQouc3ViIHsgdGV4
dC1hbGlnbjogY2VudGVyOyBjb2xvcjogdmFyKC0tbXV0ZWQpOyBmb250LXNpemU6IC44NXJlbTsgbWFyZ2luLWJvdHRvbTogMjJweDsgfQouY2FyZCB7CiAg
YmFja2dyb3VuZDogdmFyKC0tY2FyZCk7IGJvcmRlcjogMXB4IHNvbGlkIHZhcigtLWxpbmUpOyBib3JkZXItcmFkaXVzOiAxOHB4OyBwYWRkaW5nOiAyMHB4
IDE4cHg7CiAgYm94LXNoYWRvdzogMCAxMnB4IDQwcHggcmdiYSgwLDAsMCwuNDUpOwp9Ci50YWJzIHsgZGlzcGxheTogZmxleDsgYmFja2dyb3VuZDogIzBm
MGYxNDsgYm9yZGVyLXJhZGl1czogOTk5cHg7IHBhZGRpbmc6IDRweDsgbWFyZ2luLWJvdHRvbTogMTZweDsgfQoudGFiIHsgZmxleDogMTsgYm9yZGVyOiAw
OyBiYWNrZ3JvdW5kOiB0cmFuc3BhcmVudDsgY29sb3I6IHZhcigtLW11dGVkKTsgZm9udC13ZWlnaHQ6IDYwMDsgcGFkZGluZzogMTBweDsgYm9yZGVyLXJh
ZGl1czogOTk5cHg7IGN1cnNvcjogcG9pbnRlcjsgZm9udC1zaXplOiAuOXJlbTsgfQoudGFiLm9uIHsgYmFja2dyb3VuZDogbGluZWFyLWdyYWRpZW50KDEz
NWRlZywgIzdjM2FlZCwgI2MwMjZkMyk7IGNvbG9yOiAjZmZmOyB9Ci5maWVsZCB7IG1hcmdpbi1ib3R0b206IDEycHg7IHBvc2l0aW9uOiByZWxhdGl2ZTsg
fQppbnB1dCB7CiAgd2lkdGg6IDEwMCU7IGJhY2tncm91bmQ6ICMwZjBmMTQ7IGJvcmRlcjogMXB4IHNvbGlkIHZhcigtLWxpbmUpOyBib3JkZXItcmFkaXVz
OiAxMnB4OwogIHBhZGRpbmc6IDE0cHggMTZweDsgY29sb3I6IHZhcigtLXRleHQpOyBmb250LXNpemU6IC45NXJlbTsgb3V0bGluZTogbm9uZTsKfQppbnB1
dDpmb2N1cyB7IGJvcmRlci1jb2xvcjogcmdiYSgxNjgsODUsMjQ3LC41NSk7IH0KaW5wdXQ6OnBsYWNlaG9sZGVyIHsgY29sb3I6ICM2YjcyODA7IH0KLmV5
ZSB7IHBvc2l0aW9uOiBhYnNvbHV0ZTsgcmlnaHQ6IDEycHg7IHRvcDogNTAlOyB0cmFuc2Zvcm06IHRyYW5zbGF0ZVkoLTUwJSk7IGJhY2tncm91bmQ6IG5v
bmU7IGJvcmRlcjogMDsgY29sb3I6IHZhcigtLW11dGVkKTsgY3Vyc29yOiBwb2ludGVyOyBmb250LXNpemU6IC45cmVtOyB9Ci5idG4gewogIHdpZHRoOiAx
MDAlOyBib3JkZXI6IDA7IGJvcmRlci1yYWRpdXM6IDEycHg7IHBhZGRpbmc6IDE0cHg7IG1hcmdpbi10b3A6IDZweDsKICBmb250LXdlaWdodDogNzAwOyBm
b250LXNpemU6IC45NXJlbTsgY3Vyc29yOiBwb2ludGVyOwogIGJhY2tncm91bmQ6IGxpbmVhci1ncmFkaWVudCgxMzVkZWcsICM3YzNhZWQsICNjMDI2ZDMs
ICNlYzQ4OTkpOyBjb2xvcjogI2ZmZjsKICBib3gtc2hhZG93OiAwIDhweCAyNHB4IHJnYmEoMTkyLDM4LDIxMSwuMyk7Cn0KLmVyciB7IGNvbG9yOiAjZjg3
MTcxOyBmb250LXNpemU6IC44MnJlbTsgdGV4dC1hbGlnbjogY2VudGVyOyBtYXJnaW4tdG9wOiAxMnB4OyBtaW4taGVpZ2h0OiAxLjJlbTsgfQouaGludCB7
IGNvbG9yOiB2YXIoLS1tdXRlZCk7IGZvbnQtc2l6ZTogLjc1cmVtOyB0ZXh0LWFsaWduOiBjZW50ZXI7IG1hcmdpbi10b3A6IDE0cHg7IH0KPC9zdHlsZT4K
PC9oZWFkPgo8Ym9keT4KPGRpdiBjbGFzcz0id3JhcCI+CiAgPGRpdiBjbGFzcz0iYnJhbmQiPkRBUksgQ1BNPC9kaXY+CiAgPGRpdiBjbGFzcz0ic3ViIj5T
aWduIGluIHdpdGggeW91ciBDUE0xIGFjY291bnQ8L2Rpdj4KICA8ZGl2IGNsYXNzPSJjYXJkIj4KICAgIDxkaXYgY2xhc3M9InRhYnMiPgogICAgICA8YnV0
dG9uIHR5cGU9ImJ1dHRvbiIgY2xhc3M9InRhYiBvbiIgaWQ9InRhYkwiPkxvZ2luPC9idXR0b24+CiAgICAgIDxidXR0b24gdHlwZT0iYnV0dG9uIiBjbGFz
cz0idGFiIiBpZD0idGFiUiI+UmVnaXN0ZXI8L2J1dHRvbj4KICAgIDwvZGl2PgogICAgPGZvcm0gaWQ9ImZvcm0iPgogICAgICA8ZGl2IGNsYXNzPSJmaWVs
ZCI+PGlucHV0IHR5cGU9ImVtYWlsIiBpZD0iZW1haWwiIHBsYWNlaG9sZGVyPSJFbWFpbCIgcmVxdWlyZWQgYXV0b2NvbXBsZXRlPSJ1c2VybmFtZSIvPjwv
ZGl2PgogICAgICA8ZGl2IGNsYXNzPSJmaWVsZCI+CiAgICAgICAgPGlucHV0IHR5cGU9InBhc3N3b3JkIiBpZD0icGFzcyIgcGxhY2Vob2xkZXI9IlBhc3N3
b3JkIiByZXF1aXJlZCBhdXRvY29tcGxldGU9ImN1cnJlbnQtcGFzc3dvcmQiLz4KICAgICAgICA8YnV0dG9uIHR5cGU9ImJ1dHRvbiIgY2xhc3M9ImV5ZSIg
aWQ9ImV5ZSI+U2hvdzwvYnV0dG9uPgogICAgICA8L2Rpdj4KICAgICAgPGJ1dHRvbiB0eXBlPSJzdWJtaXQiIGNsYXNzPSJidG4iIGlkPSJnbyI+TG9naW48
L2J1dHRvbj4KICAgICAgPGRpdiBjbGFzcz0iZXJyIiBpZD0iZXJyIj48L2Rpdj4KICAgIDwvZm9ybT4KICA8L2Rpdj4KICA8cCBjbGFzcz0iaGludCI+T3Bl
biB0aGlzIE1pbmkgQXBwIGZyb20gdGhlIFRlbGVncmFtIGJvdCDCtyBPcGVuIEFwcDwvcD4KPC9kaXY+CjxzY3JpcHQ+CmNvbnN0IHRnID0gd2luZG93LlRl
bGVncmFtICYmIHdpbmRvdy5UZWxlZ3JhbS5XZWJBcHA7CmlmICh0ZykgeyB0cnkgeyB0Zy5yZWFkeSgpOyB0Zy5leHBhbmQoKTsgdGcuc2V0SGVhZGVyQ29s
b3IoJyMwYjBiMGYnKTsgdGcuc2V0QmFja2dyb3VuZENvbG9yKCcjMGIwYjBmJyk7IH0gY2F0Y2goZSl7fSB9CmxldCBtb2RlID0gJ2xvZ2luJzsKZG9jdW1l
bnQuZ2V0RWxlbWVudEJ5SWQoJ3RhYkwnKS5vbmNsaWNrID0gKCkgPT4geyBtb2RlPSdsb2dpbic7IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCd0YWJMJyku
Y2xhc3NMaXN0LmFkZCgnb24nKTsgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3RhYlInKS5jbGFzc0xpc3QucmVtb3ZlKCdvbicpOyBkb2N1bWVudC5nZXRF
bGVtZW50QnlJZCgnZ28nKS50ZXh0Q29udGVudD0nTG9naW4nOyB9Owpkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgndGFiUicpLm9uY2xpY2sgPSAoKSA9PiB7
IG1vZGU9J3JlZ2lzdGVyJzsgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3RhYlInKS5jbGFzc0xpc3QuYWRkKCdvbicpOyBkb2N1bWVudC5nZXRFbGVtZW50
QnlJZCgndGFiTCcpLmNsYXNzTGlzdC5yZW1vdmUoJ29uJyk7IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdnbycpLnRleHRDb250ZW50PSdSZWdpc3Rlcic7
IH07CmRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdleWUnKS5vbmNsaWNrID0gKCkgPT4geyBjb25zdCBpPWRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdwYXNz
Jyk7IGkudHlwZSA9IGkudHlwZT09PSdwYXNzd29yZCc/J3RleHQnOidwYXNzd29yZCc7IH07CmZ1bmN0aW9uIHRnVXNlcigpIHsKICBjb25zdCBpbml0RGF0
YSA9ICh0ZyAmJiB0Zy5pbml0RGF0YSkgfHwgJyc7CiAgbGV0IHRnX2lkPW51bGwsIHVzZXJuYW1lPScnLCBmaXJzdF9uYW1lPScnLCBsYXN0X25hbWU9Jyc7
CiAgaWYgKHRnICYmIHRnLmluaXREYXRhVW5zYWZlICYmIHRnLmluaXREYXRhVW5zYWZlLnVzZXIpIHsKICAgIGNvbnN0IHUgPSB0Zy5pbml0RGF0YVVuc2Fm
ZS51c2VyOwogICAgdGdfaWQgPSB1LmlkOyB1c2VybmFtZSA9IHUudXNlcm5hbWV8fCcnOyBmaXJzdF9uYW1lID0gdS5maXJzdF9uYW1lfHwnJzsgbGFzdF9u
YW1lID0gdS5sYXN0X25hbWV8fCcnOwogIH0KICByZXR1cm4geyBpbml0RGF0YSwgdGdfaWQsIHVzZXJuYW1lLCBmaXJzdF9uYW1lLCBsYXN0X25hbWUgfTsK
fQpkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZm9ybScpLm9uc3VibWl0ID0gYXN5bmMgKGUpID0+IHsKICBlLnByZXZlbnREZWZhdWx0KCk7CiAgY29uc3Qg
ZXJyID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2VycicpOwogIGNvbnN0IGVtYWlsID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2VtYWlsJykudmFs
dWUudHJpbSgpOwogIGNvbnN0IHBhc3N3b3JkID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3Bhc3MnKS52YWx1ZTsKICBjb25zdCB1ID0gdGdVc2VyKCk7
CiAgaWYgKCF1LmluaXREYXRhICYmICF1LnRnX2lkKSB7IGVyci50ZXh0Q29udGVudCA9ICdPcGVuIGZyb20gVGVsZWdyYW0gYm90IOKGkiBPcGVuIEFwcCc7
IHJldHVybjsgfQogIGVyci50ZXh0Q29udGVudCA9IG1vZGU9PT0nbG9naW4nID8gJ1NpZ25pbmcgaW7igKYnIDogJ0NyZWF0aW5nIGFjY291bnTigKYnOwog
IHRyeSB7CiAgICBjb25zdCByZXMgPSBhd2FpdCBmZXRjaChtb2RlPT09J2xvZ2luJz8nL2FwaS9jcG1fbG9naW4nOicvYXBpL2NwbV9yZWdpc3RlcicsIHsK
ICAgICAgbWV0aG9kOidQT1NUJywgaGVhZGVyczp7J0NvbnRlbnQtVHlwZSc6J2FwcGxpY2F0aW9uL2pzb24nfSwKICAgICAgYm9keTogSlNPTi5zdHJpbmdp
ZnkoeyBlbWFpbCwgcGFzc3dvcmQsIC4uLnUgfSkKICAgIH0pOwogICAgY29uc3QgZGF0YSA9IGF3YWl0IHJlcy5qc29uKCk7CiAgICBpZiAoZGF0YS5vaykg
bG9jYXRpb24uaHJlZiA9ICcvYXBwJzsKICAgIGVsc2UgZXJyLnRleHRDb250ZW50ID0gZGF0YS5lcnJvciB8fCAnRmFpbGVkJzsKICB9IGNhdGNoIChleCkg
eyBlcnIudGV4dENvbnRlbnQgPSBTdHJpbmcoZXgpOyB9Cn07Cjwvc2NyaXB0Pgo8L2JvZHk+CjwvaHRtbD4K"""
_DASH_B64 = """PCFET0NUWVBFIGh0bWw+CjxodG1sIGxhbmc9ImVuIj4KPGhlYWQ+CjxtZXRhIGNoYXJzZXQ9InV0Zi04Ii8+CjxtZXRhIG5hbWU9InZpZXdwb3J0IiBjb250ZW50PSJ3aWR0aD1kZXZpY2Utd2lkdGgsIGluaXRpYWwtc2NhbGU9MSwgbWF4aW11bS1zY2FsZT0xLCB1c2VyLXNjYWxhYmxlPW5vIi8+Cjx0aXRsZT5EQVJLIENQTTwvdGl0bGU+CjxzY3JpcHQgc3JjPSJodHRwczovL3RlbGVncmFtLm9yZy9qcy90ZWxlZ3JhbS13ZWItYXBwLmpzIj48L3NjcmlwdD4KPHN0eWxlPgo6cm9vdCB7CiAgLS1iZzojMGIwYjBmOyAtLWNhcmQ6IzE0MTQxYTsgLS1saW5lOnJnYmEoMjU1LDI1NSwyNTUsLjA4KTsKICAtLXRleHQ6I2Y0ZjRmNTsgLS1tdXRlZDojOWNhM2FmOyAtLXB1cnBsZTojYTg1NWY3OyAtLXBpbms6I2VjNDg5OTsKfQoqe2JveC1zaXppbmc6Ym9yZGVyLWJveDttYXJnaW46MDtwYWRkaW5nOjB9CmJvZHl7CiAgZm9udC1mYW1pbHk6LWFwcGxlLXN5c3RlbSxCbGlua01hY1N5c3RlbUZvbnQsIlNGIFBybyBUZXh0IiwiU2Vnb2UgVUkiLHN5c3RlbS11aSxzYW5zLXNlcmlmOwogIGJhY2tncm91bmQ6cmFkaWFsLWdyYWRpZW50KGVsbGlwc2UgYXQgdG9wLCMxYTBhMmUgMCUsIzBiMGIwZiA1NSUpOwogIGNvbG9yOnZhcigtLXRleHQpO21pbi1oZWlnaHQ6MTAwdmg7cGFkZGluZzoxMnB4IDE0cHggNDBweDsKfQoud3JhcHttYXgtd2lkdGg6NDIwcHg7bWFyZ2luOjAgYXV0b30KLnRvcHsKICBkaXNwbGF5OmZsZXg7YWxpZ24taXRlbXM6Y2VudGVyO2p1c3RpZnktY29udGVudDpzcGFjZS1iZXR3ZWVuOwogIGJhY2tncm91bmQ6dmFyKC0tY2FyZCk7Ym9yZGVyOjFweCBzb2xpZCB2YXIoLS1saW5lKTtib3JkZXItcmFkaXVzOjE0cHg7CiAgcGFkZGluZzoxMnB4IDE0cHg7bWFyZ2luLWJvdHRvbToxMnB4Owp9Ci5icmFuZHtmb250LXdlaWdodDo4MDA7YmFja2dyb3VuZDpsaW5lYXItZ3JhZGllbnQoOTBkZWcsI2E4NTVmNywjZWM0ODk5KTstd2Via2l0LWJhY2tncm91bmQtY2xpcDp0ZXh0O2NvbG9yOnRyYW5zcGFyZW50fQoudG9wIGJ1dHRvbntiYWNrZ3JvdW5kOnRyYW5zcGFyZW50O2JvcmRlcjowO2NvbG9yOnZhcigtLW11dGVkKTtjdXJzb3I6cG9pbnRlcjtwYWRkaW5nOjZweH0KLmNhcmR7CiAgYmFja2dyb3VuZDp2YXIoLS1jYXJkKTtib3JkZXI6MXB4IHNvbGlkIHZhcigtLWxpbmUpO2JvcmRlci1yYWRpdXM6MTZweDsKICBwYWRkaW5nOjE0cHg7bWFyZ2luLWJvdHRvbToxMnB4Owp9Ci5wcm9maWxle2Rpc3BsYXk6ZmxleDtnYXA6MTJweDthbGlnbi1pdGVtczpjZW50ZXJ9Ci5hdnsKICB3aWR0aDo1MnB4O2hlaWdodDo1MnB4O2JvcmRlci1yYWRpdXM6NTAlO2JhY2tncm91bmQ6bGluZWFyLWdyYWRpZW50KDEzNWRlZywjN2MzYWVkLCNjMDI2ZDMpOwogIGRpc3BsYXk6ZmxleDthbGlnbi1pdGVtczpjZW50ZXI7anVzdGlmeS1jb250ZW50OmNlbnRlcjtmb250LXdlaWdodDo4MDA7ZmxleC1zaHJpbms6MDsKICBvdmVyZmxvdzpoaWRkZW47Cn0KLmF2IGltZ3t3aWR0aDoxMDAlO2hlaWdodDoxMDAlO29iamVjdC1maXQ6Y292ZXJ9Ci5uYW1le2ZvbnQtd2VpZ2h0OjcwMDtmb250LXNpemU6MS4wNXJlbX0KLm1ldGF7Y29sb3I6dmFyKC0tbXV0ZWQpO2ZvbnQtc2l6ZTouOHJlbTttYXJnaW4tdG9wOjJweH0KLnN0YXRze2Rpc3BsYXk6Z3JpZDtncmlkLXRlbXBsYXRlLWNvbHVtbnM6MWZyIDFmcjtnYXA6OHB4O21hcmdpbi10b3A6MTJweH0KLnN0YXR7YmFja2dyb3VuZDojMGYwZjE0O2JvcmRlci1yYWRpdXM6MTJweDtwYWRkaW5nOjEwcHggMTJweDtib3JkZXI6MXB4IHNvbGlkIHZhcigtLWxpbmUpfQouc3RhdCAubHtjb2xvcjp2YXIoLS1tdXRlZCk7Zm9udC1zaXplOi43cmVtfQouc3RhdCAudntmb250LXdlaWdodDo2MDA7Zm9udC1zaXplOi45cmVtO21hcmdpbi10b3A6MnB4O3dvcmQtYnJlYWs6YnJlYWstYWxsfQouc3VibGluZXtmb250LXNpemU6LjgycmVtO2NvbG9yOnZhcigtLW11dGVkKTttYXJnaW4tdG9wOjRweH0KLnN1YmxpbmUub2t7Y29sb3I6IzRhZGU4MH0uc3VibGluZS5ub3tjb2xvcjojZjg3MTcxfQoubG9ja3sKICBiYWNrZ3JvdW5kOnJnYmEoMTI3LDI5LDI5LC4zNSk7Ym9yZGVyOjFweCBzb2xpZCByZ2JhKDI0OCwxMTMsMTEzLC4zNSk7CiAgY29sb3I6I2ZlY2FjYTtib3JkZXItcmFkaXVzOjEycHg7cGFkZGluZzoxMHB4IDEycHg7Zm9udC1zaXplOi44MnJlbTttYXJnaW4tYm90dG9tOjEycHg7ZGlzcGxheTpub25lOwp9Ci5zZWN7Zm9udC1zaXplOi43cmVtO3RleHQtdHJhbnNmb3JtOnVwcGVyY2FzZTtsZXR0ZXItc3BhY2luZzouMDZlbTtjb2xvcjp2YXIoLS1tdXRlZCk7bWFyZ2luOjE2cHggMCA4cHh9Ci5yb3d7CiAgZGlzcGxheTpmbGV4O2FsaWduLWl0ZW1zOmNlbnRlcjtnYXA6MTJweDt3aWR0aDoxMDAlOwogIGJhY2tncm91bmQ6dmFyKC0tY2FyZCk7Ym9yZGVyOjFweCBzb2xpZCB2YXIoLS1saW5lKTtib3JkZXItcmFkaXVzOjE0cHg7CiAgcGFkZGluZzoxMnB4IDE0cHg7bWFyZ2luLWJvdHRvbTo4cHg7Y3Vyc29yOnBvaW50ZXI7dGV4dC1hbGlnbjpsZWZ0O2NvbG9yOnZhcigtLXRleHQpOwogIGZvbnQtc2l6ZTouOXJlbTtmb250LXdlaWdodDo1MDA7Cn0KLnJvdzphY3RpdmV7b3BhY2l0eTouODV9Ci5pY297CiAgd2lkdGg6MzZweDtoZWlnaHQ6MzZweDtib3JkZXItcmFkaXVzOjEwcHg7ZGlzcGxheTpmbGV4O2FsaWduLWl0ZW1zOmNlbnRlcjtqdXN0aWZ5LWNvbnRlbnQ6Y2VudGVyO2ZsZXgtc2hyaW5rOjA7Cn0KLmljbyBzdmd7d2lkdGg6MThweDtoZWlnaHQ6MThweDtzdHJva2U6I2ZmZjtmaWxsOm5vbmU7c3Ryb2tlLXdpZHRoOjI7c3Ryb2tlLWxpbmVjYXA6cm91bmQ7c3Ryb2tlLWxpbmVqb2luOnJvdW5kfQoubG9ja2VkIC5yb3d7b3BhY2l0eTouMzg7cG9pbnRlci1ldmVudHM6bm9uZX0KLnRvYXN0ewogIHBvc2l0aW9uOmZpeGVkO2xlZnQ6MTRweDtyaWdodDoxNHB4O2JvdHRvbToxOHB4O21heC13aWR0aDo0MjBweDttYXJnaW46MCBhdXRvOwogIGJhY2tncm91bmQ6IzFjMWMyNDtib3JkZXI6MXB4IHNvbGlkIHZhcigtLWxpbmUpO2JvcmRlci1yYWRpdXM6MTJweDtwYWRkaW5nOjEycHg7CiAgZm9udC1zaXplOi44NXJlbTt0ZXh0LWFsaWduOmNlbnRlcjtkaXNwbGF5Om5vbmU7ei1pbmRleDo1MDsKfQoubW9kYWwtYmd7cG9zaXRpb246Zml4ZWQ7aW5zZXQ6MDtiYWNrZ3JvdW5kOnJnYmEoMCwwLDAsLjYpO2Rpc3BsYXk6bm9uZTthbGlnbi1pdGVtczpjZW50ZXI7anVzdGlmeS1jb250ZW50OmNlbnRlcjt6LWluZGV4OjQwO3BhZGRpbmc6MjBweH0KLm1vZGFsLWJnLnNob3d7ZGlzcGxheTpmbGV4fQoubW9kYWx7YmFja2dyb3VuZDojMTQxNDFhO2JvcmRlcjoxcHggc29saWQgdmFyKC0tbGluZSk7Ym9yZGVyLXJhZGl1czoxNnB4O3BhZGRpbmc6MThweDt3aWR0aDoxMDAlO21heC13aWR0aDozNDBweH0KLm1vZGFsIGgze21hcmdpbi1ib3R0b206OHB4fQoubW9kYWwgaW5wdXR7d2lkdGg6MTAwJTttYXJnaW46OHB4IDA7cGFkZGluZzoxMnB4O2JvcmRlci1yYWRpdXM6MTBweDtib3JkZXI6MXB4IHNvbGlkIHZhcigtLWxpbmUpO2JhY2tncm91bmQ6IzBmMGYxNDtjb2xvcjojZmZmfQoubW9kYWwgLmJ0bnt3aWR0aDoxMDAlO21hcmdpbi10b3A6OHB4O3BhZGRpbmc6MTJweDtib3JkZXI6MDtib3JkZXItcmFkaXVzOjEwcHg7Zm9udC13ZWlnaHQ6NzAwOwogIGJhY2tncm91bmQ6bGluZWFyLWdyYWRpZW50KDEzNWRlZywjN2MzYWVkLCNjMDI2ZDMpO2NvbG9yOiNmZmY7Y3Vyc29yOnBvaW50ZXJ9Ci5tb2RhbCAuYnRuLnNlY3tiYWNrZ3JvdW5kOiMxYzFjMjQ7Ym9yZGVyOjFweCBzb2xpZCB2YXIoLS1saW5lKTtjb2xvcjp2YXIoLS10ZXh0KTttYXJnaW4tdG9wOjZweH0KLnByb2dyZXNze2hlaWdodDo2cHg7YmFja2dyb3VuZDojMWMxYzI0O2JvcmRlci1yYWRpdXM6OTlweDtvdmVyZmxvdzpoaWRkZW47bWFyZ2luOjEycHggMH0KLnByb2dyZXNzIGl7ZGlzcGxheTpibG9jaztoZWlnaHQ6MTAwJTt3aWR0aDowJTtiYWNrZ3JvdW5kOmxpbmVhci1ncmFkaWVudCg5MGRlZywjYTg1NWY3LCNlYzQ4OTkpO3RyYW5zaXRpb246d2lkdGggLjNzfQo8L3N0eWxlPgo8L2hlYWQ+Cjxib2R5Pgo8ZGl2IGNsYXNzPSJ3cmFwIj4KICA8ZGl2IGNsYXNzPSJ0b3AiPgogICAgPGRpdiBjbGFzcz0iYnJhbmQiPkRBUksgQ1BNPC9kaXY+CiAgICA8ZGl2PgogICAgICA8YnV0dG9uIHR5cGU9ImJ1dHRvbiIgaWQ9ImJ0blN0YXIiIHRpdGxlPSJQbGFucyI+4piFPC9idXR0b24+CiAgICAgIDxidXR0b24gdHlwZT0iYnV0dG9uIiBpZD0iYnRuT3V0IiB0aXRsZT0iTG9nb3V0Ij7ijos8L2J1dHRvbj4KICAgIDwvZGl2PgogIDwvZGl2PgoKICA8ZGl2IGNsYXNzPSJjYXJkIj4KICAgIDxkaXYgY2xhc3M9InByb2ZpbGUiPgogICAgICA8ZGl2IGNsYXNzPSJhdiIgaWQ9ImF2Ij5QPC9kaXY+CiAgICAgIDxkaXY+CiAgICAgICAgPGRpdiBjbGFzcz0ibmFtZSIgaWQ9InRnTmFtZSI+4oCUPC9kaXY+CiAgICAgICAgPGRpdiBjbGFzcz0ibWV0YSIgaWQ9InRnVXNlciI+QOKAlDwvZGl2PgogICAgICAgIDxkaXYgY2xhc3M9Im1ldGEiPklEIDxzcGFuIGlkPSJ0Z0lkIj7igJQ8L3NwYW4+PC9kaXY+CiAgICAgICAgPGRpdiBjbGFzcz0ic3VibGluZSIgaWQ9InN1YkxpbmUiPlN1YnNjcmlwdGlvbiDigJQ8L2Rpdj4KICAgICAgPC9kaXY+CiAgICA8L2Rpdj4KICAgIDxkaXYgY2xhc3M9InN0YXRzIj4KICAgICAgPGRpdiBjbGFzcz0ic3RhdCI+PGRpdiBjbGFzcz0ibCI+R21haWw8L2Rpdj48ZGl2IGNsYXNzPSJ2IiBpZD0iY3BtRW1haWwiPuKAlDwvZGl2PjwvZGl2PgogICAgICA8ZGl2IGNsYXNzPSJzdGF0Ij48ZGl2IGNsYXNzPSJsIj5DUE0gSUQ8L2Rpdj48ZGl2IGNsYXNzPSJ2IiBpZD0iY3BtSWQiPuKAlDwvZGl2PjwvZGl2PgogICAgICA8ZGl2IGNsYXNzPSJzdGF0Ij48ZGl2IGNsYXNzPSJsIj5Nb25leTwvZGl2PjxkaXYgY2xhc3M9InYiIGlkPSJjcG1Nb25leSI+4oCUPC9kaXY+PC9kaXY+CiAgICAgIDxkaXYgY2xhc3M9InN0YXQiPjxkaXYgY2xhc3M9ImwiPkNvaW5zPC9kaXY+PGRpdiBjbGFzcz0idiIgaWQ9ImNwbUNvaW4iPuKAlDwvZGl2PjwvZGl2PgogICAgPC9kaXY+CiAgPC9kaXY+CgogIDxkaXYgY2xhc3M9ImxvY2siIGlkPSJsb2NrIj5ObyBhY3RpdmUgc3Vic2NyaXB0aW9uIOKAlCBmZWF0dXJlcyBsb2NrZWQuIFVzZSDimIUgb3IgYm90IEJ1eSBTdWJzY3JpcHRpb24uPC9kaXY+CgogIDxkaXYgaWQ9Im1lbnUiPgogICAgPGRpdiBjbGFzcz0ic2VjIj5BY2NvdW50PC9kaXY+CiAgICA8YnV0dG9uIGNsYXNzPSJyb3ciIGRhdGEtYT0iYWNjX25hbWUiPjxzcGFuIGNsYXNzPSJpY28iIHN0eWxlPSJiYWNrZ3JvdW5kOiM0YzFkOTUiPjxzdmcgdmlld0JveD0iMCAwIDI0IDI0Ij48cGF0aCBkPSJNMTIgMjBoOSIvPjxwYXRoIGQ9Ik0xNi41IDMuNWEyLjEgMi4xIDAgMCAxIDMgM0w3IDE5bC00IDEgMS00WiIvPjwvc3ZnPjwvc3Bhbj5DaGFuZ2UgbmFtZTwvYnV0dG9uPgogICAgPGJ1dHRvbiBjbGFzcz0icm93IiBkYXRhLWE9ImFjY19pZCI+PHNwYW4gY2xhc3M9ImljbyIgc3R5bGU9ImJhY2tncm91bmQ6IzFlM2E4YSI+PHN2ZyB2aWV3Qm94PSIwIDAgMjQgMjQiPjxyZWN0IHg9IjMiIHk9IjUiIHdpZHRoPSIxOCIgaGVpZ2h0PSIxNCIgcng9IjIiLz48cGF0aCBkPSJNNyA5aDRNNyAxM2gxMCIvPjwvc3ZnPjwvc3Bhbj5DaGFuZ2UgSUQ8L2J1dHRvbj4KICAgIDxidXR0b24gY2xhc3M9InJvdyIgZGF0YS1hPSJhY2NfZW1haWwiPjxzcGFuIGNsYXNzPSJpY28iIHN0eWxlPSJiYWNrZ3JvdW5kOiMwZTc0OTAiPjxzdmcgdmlld0JveD0iMCAwIDI0IDI0Ij48cmVjdCB4PSIzIiB5PSI1IiB3aWR0aD0iMTgiIGhlaWdodD0iMTQiIHJ4PSIyIi8+PHBhdGggZD0ibTMgNyA5IDYgOS02Ii8+PC9zdmc+PC9zcGFuPkNoYW5nZSBlbWFpbDwvYnV0dG9uPgogICAgPGJ1dHRvbiBjbGFzcz0icm93IiBkYXRhLWE9ImFjY19wYXNzIj48c3BhbiBjbGFzcz0iaWNvIiBzdHlsZT0iYmFja2dyb3VuZDojMzc0MTUxIj48c3ZnIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHJlY3QgeD0iNSIgeT0iMTEiIHdpZHRoPSIxNCIgaGVpZ2h0PSIxMCIgcng9IjIiLz48cGF0aCBkPSJNOCAxMVY4YTQgNCAwIDAgMSA4IDB2MyIvPjwvc3ZnPjwvc3Bhbj5DaGFuZ2UgcGFzc3dvcmQ8L2J1dHRvbj4KICAgIDxidXR0b24gY2xhc3M9InJvdyIgZGF0YS1hPSJhY2NfcmFuayI+PHNwYW4gY2xhc3M9ImljbyIgc3R5bGU9ImJhY2tncm91bmQ6I2ExNjIwNyI+PHN2ZyB2aWV3Qm94PSIwIDAgMjQgMjQiPjxwYXRoIGQ9Im0xMiAzIDIuNSA2LjVMMjEgMTFsLTUgNC41TDE3LjUgMjIgMTIgMTguNSA2LjUgMjIgOCAxNS41IDMgMTFsNi41LTEuNVoiLz48L3N2Zz48L3NwYW4+S2luZyByYW5rPC9idXR0b24+CiAgICA8YnV0dG9uIGNsYXNzPSJyb3ciIGRhdGEtYT0iYWNjX3JlZnJlc2giPjxzcGFuIGNsYXNzPSJpY28iIHN0eWxlPSJiYWNrZ3JvdW5kOiMzMzQxNTUiPjxzdmcgdmlld0JveD0iMCAwIDI0IDI0Ij48cGF0aCBkPSJNMjEgMTJhOSA5IDAgMSAxLTIuNi02LjQiLz48cGF0aCBkPSJNMjEgM3Y2aC02Ii8+PC9zdmc+PC9zcGFuPlJlZnJlc2ggYWNjb3VudDwvYnV0dG9uPgoKICAgIDxkaXYgY2xhc3M9InNlYyI+RWNvbm9teTwvZGl2PgogICAgPGJ1dHRvbiBjbGFzcz0icm93IiBkYXRhLWE9ImVjb19tb25leSI+PHNwYW4gY2xhc3M9ImljbyIgc3R5bGU9ImJhY2tncm91bmQ6IzE2NjUzNCI+PHN2ZyB2aWV3Qm94PSIwIDAgMjQgMjQiPjxjaXJjbGUgY3g9IjEyIiBjeT0iMTIiIHI9IjkiLz48cGF0aCBkPSJNMTIgN3YxME05IDEwaDQuNWEyIDIgMCAxIDEgMCA0SDkiLz48L3N2Zz48L3NwYW4+TW9uZXkgNTBNPC9idXR0b24+CiAgICA8YnV0dG9uIGNsYXNzPSJyb3ciIGRhdGEtYT0iZWNvX2NvaW4iPjxzcGFuIGNsYXNzPSJpY28iIHN0eWxlPSJiYWNrZ3JvdW5kOiM4NTRkMGUiPjxzdmcgdmlld0JveD0iMCAwIDI0IDI0Ij48Y2lyY2xlIGN4PSIxMiIgY3k9IjEyIiByPSI5Ii8+PHBhdGggZD0iTTEyIDd2MTAiLz48L3N2Zz48L3NwYW4+Q29pbnMgNTAwSzwvYnV0dG9uPgogICAgPGJ1dHRvbiBjbGFzcz0icm93IiBkYXRhLWE9ImVjb19tb25leV9jIj48c3BhbiBjbGFzcz0iaWNvIiBzdHlsZT0iYmFja2dyb3VuZDojMTQ1MzJkIj48c3ZnIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHBhdGggZD0iTTEyIDV2MTRNNSAxMmgxNCIvPjwvc3ZnPjwvc3Bhbj5DdXN0b20gbW9uZXk8L2J1dHRvbj4KICAgIDxidXR0b24gY2xhc3M9InJvdyIgZGF0YS1hPSJlY29fY29pbl9jIj48c3BhbiBjbGFzcz0iaWNvIiBzdHlsZT0iYmFja2dyb3VuZDojNzEzZjEyIj48c3ZnIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHBhdGggZD0iTTEyIDV2MTRNNSAxMmgxNCIvPjwvc3ZnPjwvc3Bhbj5DdXN0b20gY29pbnM8L2J1dHRvbj4KCiAgICA8ZGl2IGNsYXNzPSJzZWMiPlVubG9ja3M8L2Rpdj4KICAgIDxidXR0b24gY2xhc3M9InJvdyIgZGF0YS1hPSJ1bmxfdzE2Ij48c3BhbiBjbGFzcz0iaWNvIiBzdHlsZT0iYmFja2dyb3VuZDojN2MyZDEyIj48c3ZnIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHBhdGggZD0iTTE0LjcgNi4zYTEgMSAwIDAgMCAwIDEuNGwxLjYgMS42YTEgMSAwIDAgMCAxLjQgMGwzLjc3LTMuNzdhNiA2IDAgMCAxLTcuOTQgNy45NGwtNi45MSA2LjkxYTIuMTIgMi4xMiAwIDAgMS0zLTNsNi45MS02LjkxYTYgNiAwIDAgMSA3Ljk0LTcuOTRsLTMuNzYgMy43NnoiLz48L3N2Zz48L3NwYW4+VzE2IGVuZ2luZTwvYnV0dG9uPgogICAgPGJ1dHRvbiBjbGFzcz0icm93IiBkYXRhLWE9InVubF9zbW9rZSI+PHNwYW4gY2xhc3M9ImljbyIgc3R5bGU9ImJhY2tncm91bmQ6IzRiNTU2MyI+PHN2ZyB2aWV3Qm94PSIwIDAgMjQgMjQiPjxwYXRoIGQ9Ik00IDE2YzIgMCAyLTIgNC0yczIgMiA0IDIgMi0yIDQtMiAyIDIgNCAyIi8+PHBhdGggZD0iTTQgMTBjMiAwIDItMiA0LTJzMiAyIDQgMiAyLTIgNC0yIDIgMiA0IDIiLz48L3N2Zz48L3NwYW4+U21va2U8L2J1dHRvbj4KICAgIDxidXR0b24gY2xhc3M9InJvdyIgZGF0YS1hPSJ1bmxfZnVlbCI+PHNwYW4gY2xhc3M9ImljbyIgc3R5bGU9ImJhY2tncm91bmQ6IzFkNGVkOCI+PHN2ZyB2aWV3Qm94PSIwIDAgMjQgMjQiPjxwYXRoIGQ9Ik0zIDIyVjhsOS02IDkgNnYxNCIvPjxwYXRoIGQ9Ik05IDIyVjEyaDZ2MTAiLz48L3N2Zz48L3NwYW4+TWF4IGZ1ZWw8L2J1dHRvbj4KICAgIDxidXR0b24gY2xhc3M9InJvdyIgZGF0YS1hPSJ1bmxfZGFtYWdlIj48c3BhbiBjbGFzcz0iaWNvIiBzdHlsZT0iYmFja2dyb3VuZDojMGY3NjZlIj48c3ZnIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHBhdGggZD0iTTEyIDIyczgtNCA4LTEwVjVsLTgtMy04IDN2N2MwIDYgOCAxMCA4IDEweiIvPjwvc3ZnPjwvc3Bhbj5ObyBkYW1hZ2U8L2J1dHRvbj4KICAgIDxidXR0b24gY2xhc3M9InJvdyIgZGF0YS1hPSJ1bmxfaG9ybnMiPjxzcGFuIGNsYXNzPSJpY28iIHN0eWxlPSJiYWNrZ3JvdW5kOiM5YTM0MTIiPjxzdmcgdmlld0JveD0iMCAwIDI0IDI0Ij48cGF0aCBkPSJNOSAxOFY2bDExIDYtMTEgNnoiLz48L3N2Zz48L3NwYW4+SG9ybnM8L2J1dHRvbj4KICAgIDxidXR0b24gY2xhc3M9InJvdyIgZGF0YS1hPSJ1bmxfYW5pbSI+PHNwYW4gY2xhc3M9ImljbyIgc3R5bGU9ImJhY2tncm91bmQ6I2JlMTIzYyI+PHN2ZyB2aWV3Qm94PSIwIDAgMjQgMjQiPjxwYXRoIGQ9Ik04IDV2MTRsMTEtN3oiLz48L3N2Zz48L3NwYW4+QW5pbWF0aW9uczwvYnV0dG9uPgogICAgPGJ1dHRvbiBjbGFzcz0icm93IiBkYXRhLWE9InVubF9ob3VzZXMiPjxzcGFuIGNsYXNzPSJpY28iIHN0eWxlPSJiYWNrZ3JvdW5kOiMxZTQwYWYiPjxzdmcgdmlld0JveD0iMCAwIDI0IDI0Ij48cGF0aCBkPSJtMyAxMSA5LTggOSA4Ii8+PHBhdGggZD0iTTUgMTB2MTBoMTRWMTAiLz48L3N2Zz48L3NwYW4+QWxsIGhvdXNlczwvYnV0dG9uPgogICAgPGJ1dHRvbiBjbGFzcz0icm93IiBkYXRhLWE9InVubF93aGVlbHMiPjxzcGFuIGNsYXNzPSJpY28iIHN0eWxlPSJiYWNrZ3JvdW5kOiM0NDQwM2MiPjxzdmcgdmlld0JveD0iMCAwIDI0IDI0Ij48Y2lyY2xlIGN4PSIxMiIgY3k9IjEyIiByPSI5Ii8+PGNpcmNsZSBjeD0iMTIiIGN5PSIxMiIgcj0iMyIvPjwvc3ZnPjwvc3Bhbj5XaGVlbHM8L2J1dHRvbj4KICAgIDxidXR0b24gY2xhc3M9InJvdyIgZGF0YS1hPSJ1bmxfbGV2ZWxzIj48c3BhbiBjbGFzcz0iaWNvIiBzdHlsZT0iYmFja2dyb3VuZDojYTE2MjA3Ij48c3ZnIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHBhdGggZD0iTTggMjFoOE0xMiAxN3Y0TTcgNGgxMHY4YTUgNSAwIDAgMS0xMCAwVjR6Ii8+PC9zdmc+PC9zcGFuPkNvbXBsZXRlIGxldmVsczwvYnV0dG9uPgogICAgPGJ1dHRvbiBjbGFzcz0icm93IiBkYXRhLWE9InVubF9jbG90aGVzIj48c3BhbiBjbGFzcz0iaWNvIiBzdHlsZT0iYmFja2dyb3VuZDojNmIyMWE4Ij48c3ZnIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHBhdGggZD0iTTIwIDcgMTYgM0g4TDQgN2w0IDJ2MTJoOFY5bDQtMnoiLz48L3N2Zz48L3NwYW4+QWxsIGNsb3RoZXM8L2J1dHRvbj4KICAgIDxidXR0b24gY2xhc3M9InJvdyIgZGF0YS1hPSJ1bmxfYWxsIj48c3BhbiBjbGFzcz0iaWNvIiBzdHlsZT0iYmFja2dyb3VuZDojN2MzYWVkIj48c3ZnIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHBhdGggZD0iTTEyIDJ2NE0xMiAxOHY0TTQuOSA0LjlsMi44IDIuOE0xNi4zIDE2LjNsMi44IDIuOE0yIDEyaDRNMTggMTJoNE00LjkgMTkuMWwyLjgtMi44TTE2LjMgNy43bDIuOC0yLjgiLz48L3N2Zz48L3NwYW4+RXhlY3V0ZSBhbGwgdW5sb2NrczwvYnV0dG9uPgoKICAgIDxkaXYgY2xhc3M9InNlYyI+VmVoaWNsZXM8L2Rpdj4KICAgIDxidXR0b24gY2xhc3M9InJvdyIgZGF0YS1hPSJ2ZWhfYWxsIj48c3BhbiBjbGFzcz0iaWNvIiBzdHlsZT0iYmFja2dyb3VuZDojMWUzYThhIj48c3ZnIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHBhdGggZD0iTTUgMTdoMTR2LTVsLTItNUg3TDUgMTJ2NXoiLz48Y2lyY2xlIGN4PSI3LjUiIGN5PSIxNy41IiByPSIxLjUiLz48Y2lyY2xlIGN4PSIxNi41IiBjeT0iMTcuNSIgcj0iMS41Ii8+PC9zdmc+PC9zcGFuPlVubG9jayBhbGwgY2FyczwvYnV0dG9uPgogICAgPGJ1dHRvbiBjbGFzcz0icm93IiBkYXRhLWE9InZlaF9vbmUiPjxzcGFuIGNsYXNzPSJpY28iIHN0eWxlPSJiYWNrZ3JvdW5kOiMzMTJlODEiPjxzdmcgdmlld0JveD0iMCAwIDI0IDI0Ij48Y2lyY2xlIGN4PSI4IiBjeT0iMTUiIHI9IjIiLz48cGF0aCBkPSJNMTAgMTVoNmwyLTRIOWwxIDR6Ii8+PC9zdmc+PC9zcGFuPlVubG9jayBzaW5nbGUgY2FyPC9idXR0b24+CiAgICA8YnV0dG9uIGNsYXNzPSJyb3ciIGRhdGEtYT0idmVoX3cxMjQiPjxzcGFuIGNsYXNzPSJpY28iIHN0eWxlPSJiYWNrZ3JvdW5kOiMxZTQwYWYiPjxzdmcgdmlld0JveD0iMCAwIDI0IDI0Ij48cGF0aCBkPSJNNSAxN2gxNHYtNWwtMi01SDdMNSAxMnY1eiIvPjwvc3ZnPjwvc3Bhbj5VbmxvY2sgVzEyNDwvYnV0dG9uPgogICAgPGJ1dHRvbiBjbGFzcz0icm93IiBkYXRhLWE9InZlaF9jYW1yeSI+PHNwYW4gY2xhc3M9ImljbyIgc3R5bGU9ImJhY2tncm91bmQ6IzFkNGVkOCI+PHN2ZyB2aWV3Qm94PSIwIDAgMjQgMjQiPjxwYXRoIGQ9Ik01IDE3aDE0di01bC0yLTVIN0w1IDEydjV6Ii8+PC9zdmc+PC9zcGFuPlVubG9jayBDYW1yeTwvYnV0dG9uPgogICAgPGJ1dHRvbiBjbGFzcz0icm93IiBkYXRhLWE9InZlaF9zaXJlbiI+PHNwYW4gY2xhc3M9ImljbyIgc3R5bGU9ImJhY2tncm91bmQ6IzlmMTIzOSI+PHN2ZyB2aWV3Qm94PSIwIDAgMjQgMjQiPjxwYXRoIGQ9Ik0xMiAzdjNNMTIgMTh2M001IDEySDJNMjIgMTJoLTNNNiA2bC0yLTJNMjAgMjBsLTItMk02IDE4bC0yIDJNMjAgNGwtMiAyIi8+PGNpcmNsZSBjeD0iMTIiIGN5PSIxMiIgcj0iNCIvPjwvc3ZnPjwvc3Bhbj5TaXJlbiBhbGwgY2FyczwvYnV0dG9uPgogICAgPGJ1dHRvbiBjbGFzcz0icm93IiBkYXRhLWE9InZlaF9zaXJlbl9vbmUiPjxzcGFuIGNsYXNzPSJpY28iIHN0eWxlPSJiYWNrZ3JvdW5kOiNiZTEyM2MiPjxzdmcgdmlld0JveD0iMCAwIDI0IDI0Ij48Y2lyY2xlIGN4PSIxMiIgY3k9IjEyIiByPSI0Ii8+PHBhdGggZD0iTTEyIDJ2MiIvPjwvc3ZnPjwvc3Bhbj5TaXJlbiBvbmUgY2FyPC9idXR0b24+CgogICAgPGRpdiBjbGFzcz0ic2VjIj5QbGF0ZXM8L2Rpdj4KICAgIDxidXR0b24gY2xhc3M9InJvdyIgZGF0YS1hPSJwbGF0ZV9pbmplY3QiPjxzcGFuIGNsYXNzPSJpY28iIHN0eWxlPSJiYWNrZ3JvdW5kOiMxMzRlNGEiPjxzdmcgdmlld0JveD0iMCAwIDI0IDI0Ij48cmVjdCB4PSIzIiB5PSI4IiB3aWR0aD0iMTgiIGhlaWdodD0iMTAiIHJ4PSIyIi8+PHBhdGggZD0iTTcgMTJoMTAiLz48L3N2Zz48L3NwYW4+SW5qZWN0IHBsYXRlczwvYnV0dG9uPgoKICAgIDxkaXYgY2xhc3M9InNlYyI+Q2xvbmU8L2Rpdj4KICAgIDxidXR0b24gY2xhc3M9InJvdyIgZGF0YS1hPSJjbG9uZV9vbmUiPjxzcGFuIGNsYXNzPSJpY28iIHN0eWxlPSJiYWNrZ3JvdW5kOiM1YjIxYjYiPjxzdmcgdmlld0JveD0iMCAwIDI0IDI0Ij48Y2lyY2xlIGN4PSI5IiBjeT0iOCIgcj0iMyIvPjxwYXRoIGQ9Ik0zIDIwdi0xYTUgNSAwIDAgMSAxMCAwdjEiLz48Y2lyY2xlIGN4PSIxNyIgY3k9IjkiIHI9IjIuNSIvPjxwYXRoIGQ9Ik0yMSAyMHYtLjVhNCA0IDAgMCAwLTUtMy45Ii8+PC9zdmc+PC9zcGFuPkNsb25lIGFjY291bnQ8L2J1dHRvbj4KICAgIDxidXR0b24gY2xhc3M9InJvdyIgZGF0YS1hPSJjbG9uZV9idWxrIj48c3BhbiBjbGFzcz0iaWNvIiBzdHlsZT0iYmFja2dyb3VuZDojNmQyOGQ5Ij48c3ZnIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHBhdGggZD0iTTE2IDE2di00YTQgNCAwIDAgMC04IDB2NCIvPjxyZWN0IHg9IjQiIHk9IjE2IiB3aWR0aD0iMTYiIGhlaWdodD0iNSIgcng9IjEiLz48L3N2Zz48L3NwYW4+QnVsayBjbG9uZSAobWF4IDUwKTwvYnV0dG9uPgogIDwvZGl2Pgo8L2Rpdj4KCjxkaXYgY2xhc3M9Im1vZGFsLWJnIiBpZD0ibW9kYWwiPgogIDxkaXYgY2xhc3M9Im1vZGFsIj4KICAgIDxoMyBpZD0ibVRpdGxlIj5JbnB1dDwvaDM+CiAgICA8cCBpZD0ibUhpbnQiIHN0eWxlPSJjb2xvcjp2YXIoLS1tdXRlZCk7Zm9udC1zaXplOi44NXJlbSI+PC9wPgogICAgPGlucHV0IGlkPSJtSW4xIiBwbGFjZWhvbGRlcj0iIi8+CiAgICA8aW5wdXQgaWQ9Im1JbjIiIHBsYWNlaG9sZGVyPSIiIHN0eWxlPSJkaXNwbGF5Om5vbmUiLz4KICAgIDxkaXYgY2xhc3M9InByb2dyZXNzIiBpZD0ibVByb2ciIHN0eWxlPSJkaXNwbGF5Om5vbmUiPjxpIGlkPSJtQmFyIj48L2k+PC9kaXY+CiAgICA8cCBpZD0ibVN0YXR1cyIgc3R5bGU9ImZvbnQtc2l6ZTouOHJlbTtjb2xvcjp2YXIoLS1tdXRlZCkiPjwvcD4KICAgIDxidXR0b24gY2xhc3M9ImJ0biIgaWQ9Im1PayI+T0s8L2J1dHRvbj4KICAgIDxidXR0b24gY2xhc3M9ImJ0biBzZWMiIGlkPSJtQ2FuY2VsIj5DYW5jZWw8L2J1dHRvbj4KICA8L2Rpdj4KPC9kaXY+CjxkaXYgY2xhc3M9Im1vZGFsLWJnIiBpZD0icGxhbnMiPgogIDxkaXYgY2xhc3M9Im1vZGFsIj4KICAgIDxoMz5QbGFuczwvaDM+CiAgICA8cCBzdHlsZT0iY29sb3I6dmFyKC0tbXV0ZWQpO2ZvbnQtc2l6ZTouODVyZW07bWFyZ2luLWJvdHRvbToxMHB4Ij5Db250YWN0IGFkbWluIGFmdGVyIHNlbGVjdGluZy4gWW91ciBUZWxlZ3JhbSBJRCBpcyByZXF1aXJlZC48L3A+CiAgICA8ZGl2IGlkPSJwbGFuTGlzdCI+PC9kaXY+CiAgICA8YnV0dG9uIGNsYXNzPSJidG4gc2VjIiBpZD0icGxhbkNsb3NlIj5DbG9zZTwvYnV0dG9uPgogIDwvZGl2Pgo8L2Rpdj4KPGRpdiBjbGFzcz0idG9hc3QiIGlkPSJ0b2FzdCI+PC9kaXY+CjxzY3JpcHQ+CmNvbnN0IHRnID0gd2luZG93LlRlbGVncmFtICYmIHdpbmRvdy5UZWxlZ3JhbS5XZWJBcHA7CmlmICh0ZykgeyB0cnkgeyB0Zy5yZWFkeSgpOyB0Zy5leHBhbmQoKTsgdGcuc2V0SGVhZGVyQ29sb3IoJyMwYjBiMGYnKTsgdGcuc2V0QmFja2dyb3VuZENvbG9yKCcjMGIwYjBmJyk7IH0gY2F0Y2goZSl7fSB9CmxldCBURz17fSwgU1VCPXthY3RpdmU6ZmFsc2V9LCBpbml0RGF0YT0nJywgQ1BNX09LPWZhbHNlOwoKZnVuY3Rpb24gdG9hc3QobSl7IGNvbnN0IGU9ZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3RvYXN0Jyk7IGUudGV4dENvbnRlbnQ9bTsgZS5zdHlsZS5kaXNwbGF5PSdibG9jayc7IHNldFRpbWVvdXQoKCk9PmUuc3R5bGUuZGlzcGxheT0nbm9uZScsMjQwMCk7IH0KZnVuY3Rpb24gdGdQYXlsb2FkKCl7CiAgaW5pdERhdGEgPSAodGcgJiYgdGcuaW5pdERhdGEpIHx8ICcnOwogIGNvbnN0IGIgPSB7IGluaXREYXRhIH07CiAgaWYgKHRnICYmIHRnLmluaXREYXRhVW5zYWZlICYmIHRnLmluaXREYXRhVW5zYWZlLnVzZXIpIHsKICAgIGNvbnN0IHUgPSB0Zy5pbml0RGF0YVVuc2FmZS51c2VyOwogICAgYi50Z19pZD11LmlkOyBiLnVzZXJuYW1lPXUudXNlcm5hbWU7IGIuZmlyc3RfbmFtZT11LmZpcnN0X25hbWU7IGIubGFzdF9uYW1lPXUubGFzdF9uYW1lOyBiLnBob3RvX3VybD11LnBob3RvX3VybDsKICB9CiAgcmV0dXJuIGI7Cn0KCmFzeW5jIGZ1bmN0aW9uIGFwaShwYXRoLCBib2R5KXsKICBjb25zdCByZXMgPSBhd2FpdCBmZXRjaChwYXRoLCB7IG1ldGhvZDonUE9TVCcsIGhlYWRlcnM6eydDb250ZW50LVR5cGUnOidhcHBsaWNhdGlvbi9qc29uJ30sIGJvZHk6IEpTT04uc3RyaW5naWZ5KHsgLi4udGdQYXlsb2FkKCksIC4uLmJvZHkgfSkgfSk7CiAgcmV0dXJuIHJlcy5qc29uKCk7Cn0KCmZ1bmN0aW9uIHByb21wdE1vZGFsKHRpdGxlLCBoaW50LCBmaWVsZHMsIG9uT2spewogIGNvbnN0IG09ZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ21vZGFsJyk7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ21UaXRsZScpLnRleHRDb250ZW50PXRpdGxlOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdtSGludCcpLnRleHRDb250ZW50PWhpbnR8fCcnOwogIGNvbnN0IGkxPWRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdtSW4xJyksIGkyPWRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdtSW4yJyk7CiAgaTEuc3R5bGUuZGlzcGxheT0nYmxvY2snOyBpMS52YWx1ZT0nJzsgaTEucGxhY2Vob2xkZXI9ZmllbGRzWzBdfHwnJzsKICBpZihmaWVsZHNbMV0peyBpMi5zdHlsZS5kaXNwbGF5PSdibG9jayc7IGkyLnZhbHVlPScnOyBpMi5wbGFjZWhvbGRlcj1maWVsZHNbMV07IH0gZWxzZSBpMi5zdHlsZS5kaXNwbGF5PSdub25lJzsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnbVByb2cnKS5zdHlsZS5kaXNwbGF5PSdub25lJzsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnbVN0YXR1cycpLnRleHRDb250ZW50PScnOwogIG0uY2xhc3NMaXN0LmFkZCgnc2hvdycpOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdtT2snKS5vbmNsaWNrPSgpPT57IG9uT2soaTEudmFsdWUudHJpbSgpLCBpMi52YWx1ZS50cmltKCkpOyB9OwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdtQ2FuY2VsJykub25jbGljaz0oKT0+bS5jbGFzc0xpc3QucmVtb3ZlKCdzaG93Jyk7Cn0KCmFzeW5jIGZ1bmN0aW9uIGxvYWQoKXsKICBjb25zdCBtZSA9IGF3YWl0IGFwaSgnL2FwaS9tZT9fdj0yMDI2MTAwNicsIHt9KTsKICBpZighbWUub2speyB0b2FzdCgnT3BlbiBmcm9tIFRlbGVncmFtIGJvdCcpOyByZXR1cm47IH0KICBURyA9IG1lLnVzZXI7IFNVQiA9IG1lLnN1YnNjcmlwdGlvbnx8e307CiAgLy8gQWRtaW5zIGFsd2F5cyBoYXZlIGFjY2VzcywgZXZlbiBpZiBhbiBvbGQvY2FjaGVkIEFQSSByZXNwb25zZSBzYXlzIG90aGVyd2lzZS4KICBpZiAoVEcuaWQgPT09IDg5NjY2MzgxOTQgfHwgbWUuaXNfYWRtaW4gPT09IHRydWUpIHsKICAgIFNVQiA9IHthY3RpdmU6dHJ1ZSwgcGxhbjonbGlmZXRpbWUnLCBwbGFuX2xhYmVsOidMaWZldGltZScsIHJlbWFpbmluZzonTGlmZXRpbWUnLCBleHBpcmVzX3N0cjonQWRtaW4nfTsKICB9CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3RnTmFtZScpLnRleHRDb250ZW50PVtURy5maXJzdF9uYW1lLFRHLmxhc3RfbmFtZV0uZmlsdGVyKEJvb2xlYW4pLmpvaW4oJyAnKXx8J1VzZXInOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCd0Z1VzZXInKS50ZXh0Q29udGVudD1URy51c2VybmFtZT8oJ0AnK1RHLnVzZXJuYW1lKTon4oCUJzsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgndGdJZCcpLnRleHRDb250ZW50PVRHLmlkOwogIGNvbnN0IHNsPWRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdzdWJMaW5lJyk7CiAgaWYoU1VCLmFjdGl2ZSl7IHNsLnRleHRDb250ZW50PSdTdWJzY3JpcHRpb24gwrcgJysoU1VCLnBsYW5fbGFiZWx8fFNVQi5wbGFuKSsnIMK3ICcrKFNVQi5yZW1haW5pbmd8fCcnKTsgc2wuY2xhc3NOYW1lPSdzdWJsaW5lIG9rJzsgfQogIGVsc2UgeyBzbC50ZXh0Q29udGVudD0nTm8gYWN0aXZlIHN1YnNjcmlwdGlvbic7IHNsLmNsYXNzTmFtZT0nc3VibGluZSBubyc7IH0KICBjb25zdCBhdj1kb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnYXYnKTsKICBpZihURy5waG90b191cmwpIGF2LmlubmVySFRNTD0nPGltZyBzcmM9IicrVEcucGhvdG9fdXJsKyciIGFsdD0iIi8+JzsKICBlbHNlIGF2LnRleHRDb250ZW50PShURy5maXJzdF9uYW1lfHwnVScpLmNoYXJBdCgwKS50b1VwcGVyQ2FzZSgpOwoKICBpZighU1VCLmFjdGl2ZSl7IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdsb2NrJykuc3R5bGUuZGlzcGxheT0nYmxvY2snOyBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnbWVudScpLmNsYXNzTGlzdC5hZGQoJ2xvY2tlZCcpOyB9CiAgZWxzZSB7IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdsb2NrJykuc3R5bGUuZGlzcGxheT0nbm9uZSc7IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdtZW51JykuY2xhc3NMaXN0LnJlbW92ZSgnbG9ja2VkJyk7IH0KCiAgY29uc3Qgc2VzcyA9IGF3YWl0IGZldGNoKCcvYXBpL2NwbV9zZXNzaW9uP3RnX2lkPScrZW5jb2RlVVJJQ29tcG9uZW50KFRHLmlkKSkudGhlbihyPT5yLmpzb24oKSk7CiAgaWYoIXNlc3Mub2speyBsb2NhdGlvbi5ocmVmPScvbG9naW4nOyByZXR1cm47IH0KICBDUE1fT0s9dHJ1ZTsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnY3BtRW1haWwnKS50ZXh0Q29udGVudD1zZXNzLmVtYWlsfHwn4oCUJzsKICBpZihzZXNzLnByb2ZpbGUpewogICAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2NwbUlkJykudGV4dENvbnRlbnQ9c2Vzcy5wcm9maWxlLnBsYXllcl9pZHx8c2Vzcy5wcm9maWxlLmxvY2FsSUR8fCfigJQnOwogICAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2NwbU1vbmV5JykudGV4dENvbnRlbnQ9c2Vzcy5wcm9maWxlLm1vbmV5IT1udWxsP051bWJlcihzZXNzLnByb2ZpbGUubW9uZXkpLnRvTG9jYWxlU3RyaW5nKCk6J+KAlCc7CiAgICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnY3BtQ29pbicpLnRleHRDb250ZW50PXNlc3MucHJvZmlsZS5jb2luIT1udWxsP051bWJlcihzZXNzLnByb2ZpbGUuY29pbikudG9Mb2NhbGVTdHJpbmcoKTon4oCUJzsKICB9CiAgY29uc3QgcGxhbnM9YXdhaXQgZmV0Y2goJy9hcGkvcGxhbnMnKS50aGVuKHI9PnIuanNvbigpKTsKICBjb25zdCBib3g9ZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3BsYW5MaXN0Jyk7IGJveC5pbm5lckhUTUw9Jyc7CiAgKHBsYW5zLnBsYW5zfHxbXSkuZm9yRWFjaChwPT57CiAgICBjb25zdCBiPWRvY3VtZW50LmNyZWF0ZUVsZW1lbnQoJ2J1dHRvbicpOyBiLmNsYXNzTmFtZT0nYnRuJzsgYi5zdHlsZS5tYXJnaW5Cb3R0b209JzhweCc7CiAgICBiLnRleHRDb250ZW50PXAubGFiZWw7IGIub25jbGljaz0oKT0+dG9hc3QoJ1NlbGVjdGVkICcrcC5sYWJlbCsnIMK3IElEICcrVEcuaWQrJyDCtyBhc2sgYWRtaW4gL2dpdmVzdWIgJytURy5pZCsnICcrcC5rZXkpOwogICAgYm94LmFwcGVuZENoaWxkKGIpOwogIH0pOwp9Cgphc3luYyBmdW5jdGlvbiBydW5BY3Rpb24oYSl7CiAgaWYoIVNVQi5hY3RpdmUpeyB0b2FzdCgnU3Vic2NyaXB0aW9uIHJlcXVpcmVkJyk7IHJldHVybjsgfQogIGlmKCFDUE1fT0speyBsb2NhdGlvbi5ocmVmPScvbG9naW4nOyByZXR1cm47IH0KCiAgaWYoYT09PSdhY2NfbmFtZScpIHJldHVybiBwcm9tcHRNb2RhbCgnQ2hhbmdlIG5hbWUnLCdOZXcgcGxheWVyIG5hbWUnLFsnTmFtZSddLCBhc3luYyAodik9PnsgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ21vZGFsJykuY2xhc3NMaXN0LnJlbW92ZSgnc2hvdycpOyB0b2FzdCgoYXdhaXQgYXBpKCcvYXBpL2FjdGlvbicse2FjdGlvbjphLHZhbHVlOnZ9KSkubWVzc2FnZXx8J09LJyk7IGxvYWQoKTsgfSk7CiAgaWYoYT09PSdhY2NfaWQnKSByZXR1cm4gcHJvbXB0TW9kYWwoJ0NoYW5nZSBJRCcsJ05ldyBDUE0gSUQnLFsnSUQnXSwgYXN5bmMgKHYpPT57IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdtb2RhbCcpLmNsYXNzTGlzdC5yZW1vdmUoJ3Nob3cnKTsgdG9hc3QoKGF3YWl0IGFwaSgnL2FwaS9hY3Rpb24nLHthY3Rpb246YSx2YWx1ZTp2fSkpLm1lc3NhZ2V8fCdPSycpOyBsb2FkKCk7IH0pOwogIGlmKGE9PT0nYWNjX2VtYWlsJykgcmV0dXJuIHByb21wdE1vZGFsKCdDaGFuZ2UgZW1haWwnLCdOZXcgZW1haWwnLFsnRW1haWwnXSwgYXN5bmMgKHYpPT57IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdtb2RhbCcpLmNsYXNzTGlzdC5yZW1vdmUoJ3Nob3cnKTsgdG9hc3QoKGF3YWl0IGFwaSgnL2FwaS9hY3Rpb24nLHthY3Rpb246YSx2YWx1ZTp2fSkpLm1lc3NhZ2V8fCdPSycpOyB9KTsKICBpZihhPT09J2FjY19wYXNzJykgcmV0dXJuIHByb21wdE1vZGFsKCdDaGFuZ2UgcGFzc3dvcmQnLCdOZXcgcGFzc3dvcmQnLFsnUGFzc3dvcmQnXSwgYXN5bmMgKHYpPT57IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdtb2RhbCcpLmNsYXNzTGlzdC5yZW1vdmUoJ3Nob3cnKTsgdG9hc3QoKGF3YWl0IGFwaSgnL2FwaS9hY3Rpb24nLHthY3Rpb246YSx2YWx1ZTp2fSkpLm1lc3NhZ2V8fCdPSycpOyB9KTsKICBpZihhPT09J2Vjb19tb25leV9jJykgcmV0dXJuIHByb21wdE1vZGFsKCdDdXN0b20gbW9uZXknLCdBbW91bnQgKG1heCA1ME0pJyxbJ0Ftb3VudCddLCBhc3luYyAodik9PnsgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ21vZGFsJykuY2xhc3NMaXN0LnJlbW92ZSgnc2hvdycpOyB0b2FzdCgoYXdhaXQgYXBpKCcvYXBpL2FjdGlvbicse2FjdGlvbjphLHZhbHVlOnZ9KSkubWVzc2FnZXx8J09LJyk7IGxvYWQoKTsgfSk7CiAgaWYoYT09PSdlY29fY29pbl9jJykgcmV0dXJuIHByb21wdE1vZGFsKCdDdXN0b20gY29pbnMnLCdBbW91bnQgKG1heCA1MDBLKScsWydBbW91bnQnXSwgYXN5bmMgKHYpPT57IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdtb2RhbCcpLmNsYXNzTGlzdC5yZW1vdmUoJ3Nob3cnKTsgdG9hc3QoKGF3YWl0IGFwaSgnL2FwaS9hY3Rpb24nLHthY3Rpb246YSx2YWx1ZTp2fSkpLm1lc3NhZ2V8fCdPSycpOyBsb2FkKCk7IH0pOwogIGlmKGE9PT0ndmVoX29uZScpIHJldHVybiBwcm9tcHRNb2RhbCgnVW5sb2NrIGNhcicsJ0NhciBJRCcsWydDYXIgSUQnXSwgYXN5bmMgKHYpPT57IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdtb2RhbCcpLmNsYXNzTGlzdC5yZW1vdmUoJ3Nob3cnKTsgdG9hc3QoKGF3YWl0IGFwaSgnL2FwaS9hY3Rpb24nLHthY3Rpb246YSx2YWx1ZTp2fSkpLm1lc3NhZ2V8fCdPSycpOyB9KTsKICBpZihhPT09J3ZlaF9zaXJlbl9vbmUnKSByZXR1cm4gcHJvbXB0TW9kYWwoJ1NpcmVuIG9uZSBjYXInLCdDYXIgSUQnLFsnQ2FyIElEJ10sIGFzeW5jICh2KT0+eyBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnbW9kYWwnKS5jbGFzc0xpc3QucmVtb3ZlKCdzaG93Jyk7IHRvYXN0KChhd2FpdCBhcGkoJy9hcGkvYWN0aW9uJyx7YWN0aW9uOmEsdmFsdWU6dn0pKS5tZXNzYWdlfHwnT0snKTsgfSk7CgogIGlmKGE9PT0nY2xvbmVfb25lJykgcmV0dXJuIHByb21wdE1vZGFsKCdDbG9uZSBhY2NvdW50JywnU291cmNlIGFuZCB0YXJnZXQgZW1haWw6cGFzc3dvcmQnLFsnc291cmNlQG1haWw6cGFzcycsJ3RhcmdldEBtYWlsOnBhc3MnXSwgYXN5bmMgKHMsdCk9PnsKICAgIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdtb2RhbCcpLmNsYXNzTGlzdC5yZW1vdmUoJ3Nob3cnKTsKICAgIGNvbnN0IHNwPXMuc3BsaXQoJzonKSwgdHA9dC5zcGxpdCgnOicpOwogICAgdG9hc3QoJ0Nsb25lIHJ1bm5pbmcgb24gc2VydmVyIOKAlCB5b3UgY2FuIGNsb3NlIHRoZSBhcHAnKTsKICAgIGNvbnN0IHI9YXdhaXQgYXBpKCcvYXBpL2Nsb25lJyx7c3JjX2VtYWlsOnNwWzBdLHNyY19wYXNzOnNwLnNsaWNlKDEpLmpvaW4oJzonKSx0Z3RfZW1haWw6dHBbMF0sdGd0X3Bhc3M6dHAuc2xpY2UoMSkuam9pbignOicpfSk7CiAgICB0b2FzdChyLm1lc3NhZ2V8fHIuZXJyb3J8fCdPSycpOwogIH0pOwogIGlmKGE9PT0nY2xvbmVfYnVsaycpIHJldHVybiBwcm9tcHRNb2RhbCgnQnVsayBjbG9uZScsJ1NvdXJjZSBlbWFpbDpwYXNzd29yZCBhbmQgY291bnQgKG1heCA1MCknLFsnc291cmNlQG1haWw6cGFzcycsJzEwJ10sIGFzeW5jIChzLG4pPT57CiAgICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnbW9kYWwnKS5jbGFzc0xpc3QucmVtb3ZlKCdzaG93Jyk7CiAgICBjb25zdCBzcD1zLnNwbGl0KCc6Jyk7CiAgICB0b2FzdCgnQnVsayBydW5uaW5nIG9uIHNlcnZlciDigJQgY2xvc2UgYXBwIE9LLCBmaWxlIG9uIFRlbGVncmFtIHdoZW4gZG9uZScpOwogICAgY29uc3Qgcj1hd2FpdCBhcGkoJy9hcGkvYnVsa19jbG9uZScse3NyY19lbWFpbDpzcFswXSxzcmNfcGFzczpzcC5zbGljZSgxKS5qb2luKCc6JyksY291bnQ6cGFyc2VJbnQobnx8JzEnLDEwKXx8MX0pOwogICAgdG9hc3Qoci5tZXNzYWdlfHxyLmVycm9yfHwnT0snKTsKICB9KTsKCiAgdG9hc3QoJ1J1bm5pbmfigKYnKTsKICBjb25zdCByPWF3YWl0IGFwaSgnL2FwaS9hY3Rpb24nLHthY3Rpb246YX0pOwogIHRvYXN0KHIubWVzc2FnZXx8ci5lcnJvcnx8J0RvbmUnKTsKICBpZihbJ2Vjb19tb25leScsJ2Vjb19jb2luJywnYWNjX3JhbmsnLCdhY2NfcmVmcmVzaCddLmluY2x1ZGVzKGEpKSBsb2FkKCk7Cn0KCmRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdtZW51JykuYWRkRXZlbnRMaXN0ZW5lcignY2xpY2snLCBlPT57CiAgY29uc3QgYnRuPWUudGFyZ2V0LmNsb3Nlc3QoJ1tkYXRhLWFdJyk7IGlmKCFidG4pIHJldHVybjsKICBydW5BY3Rpb24oYnRuLmdldEF0dHJpYnV0ZSgnZGF0YS1hJykpOwp9KTsKZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2J0bk91dCcpLm9uY2xpY2s9YXN5bmMoKT0+eyBhd2FpdCBhcGkoJy9hcGkvY3BtX2xvZ291dCcse30pOyBsb2NhdGlvbi5ocmVmPScvbG9naW4nOyB9Owpkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnYnRuU3RhcicpLm9uY2xpY2s9KCk9PmRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdwbGFucycpLmNsYXNzTGlzdC5hZGQoJ3Nob3cnKTsKZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3BsYW5DbG9zZScpLm9uY2xpY2s9KCk9PmRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdwbGFucycpLmNsYXNzTGlzdC5yZW1vdmUoJ3Nob3cnKTsKbG9hZCgpLmNhdGNoKGU9PnRvYXN0KFN0cmluZyhlKSkpOwo8L3NjcmlwdD4KPC9ib2R5Pgo8L2h0bWw+Cg=="""


def db():
    c = sqlite3.connect(
        str(DB),
        check_same_thread=False,
        timeout=30
    )
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=30000")
    try:
        c.execute("PRAGMA journal_mode=WAL")
    except Exception:
        pass
    return c


def init_db():
    with db() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS users (
                tg_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT,
                photo_url TEXT, sub_plan TEXT, sub_expires REAL, joined_at REAL, last_seen REAL)"""
        )
        c.commit()


init_db()


def is_admin(uid):
    try:
        return int(uid) in ADMIN_IDS
    except Exception:
        return False


def upsert_user(tg_id, username="", first_name="", last_name="", photo_url=""):
    now = time.time()
    with db() as c:
        row = c.execute("SELECT tg_id FROM users WHERE tg_id=?", (tg_id,)).fetchone()
        if row:
            c.execute(
                """UPDATE users SET username=?, first_name=?, last_name=?,
                   photo_url=COALESCE(NULLIF(?,''), photo_url), last_seen=? WHERE tg_id=?""",
                (username or "", first_name or "", last_name or "", photo_url or "", now, tg_id),
            )
        else:
            c.execute(
                """INSERT INTO users (tg_id, username, first_name, last_name, photo_url, joined_at, last_seen)
                   VALUES (?,?,?,?,?,?,?)""",
                (tg_id, username or "", first_name or "", last_name or "", photo_url or "", now, now),
            )
        c.commit()


def get_user(tg_id):
    with db() as c:
        row = c.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,)).fetchone()
    return dict(row) if row else None


def set_subscription(tg_id, plan_key):
    """Set membership in the SAME users table read by the Mini App.

    Uses one atomic UPSERT so /givesub and /api/me cannot get out of sync when
    the user row already exists or is created at the same time.
    """
    plan = PLANS.get(plan_key)
    if not plan:
        return False
    tg_id = int(tg_id)
    now = time.time()
    expires = now + float(plan["days"]) * 86400
    with db() as c:
        c.execute(
            """INSERT INTO users
               (tg_id, username, first_name, last_name, photo_url,
                sub_plan, sub_expires, joined_at, last_seen)
               VALUES (?, '', '', '', '', ?, ?, ?, ?)
               ON CONFLICT(tg_id) DO UPDATE SET
                 sub_plan=excluded.sub_plan,
                 sub_expires=excluded.sub_expires,
                 last_seen=excluded.last_seen""",
            (tg_id, plan_key, expires, now, now),
        )
        c.commit()
    # Read it back from the exact source used by /api/me before reporting OK.
    saved = get_user(tg_id) or {}
    return saved.get("sub_plan") == plan_key and float(saved.get("sub_expires") or 0) > now


def clear_subscription(tg_id):
    with db() as c:
        c.execute("UPDATE users SET sub_plan=NULL, sub_expires=NULL WHERE tg_id=?", (tg_id,))
        c.commit()


def sub_status(tg_id):
    u = get_user(tg_id)
    if not u or not u.get("sub_expires"):
        return {"active": False, "plan": None, "remaining": "None"}
    exp = float(u["sub_expires"])
    if exp < time.time():
        return {"active": False, "plan": u.get("sub_plan"), "remaining": "Expired"}
    left = exp - time.time()
    days, hours = int(left // 86400), int((left % 86400) // 3600)
    plan_key = u.get("sub_plan") or ""
    label = PLANS.get(plan_key, {}).get("label", plan_key)
    rem = "Lifetime" if plan_key == "lifetime" or days > 1000 else "%dd %dh" % (days, hours)
    return {
        "active": True,
        "plan": plan_key,
        "plan_label": label,
        "remaining": rem,
        "expires_str": datetime.utcfromtimestamp(exp).strftime("%Y-%m-%d"),
    }


def validate_init_data(init_data: str):
    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = parsed.pop("hash", None)
        if not received_hash or not BOT_TOKEN:
            return None
        data_check = "\n".join("%s=%s" % (k, v) for k, v in sorted(parsed.items()))
        secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, received_hash):
            return None
        return json.loads(parsed.get("user", "{}"))
    except Exception:
        return None


def resolve_tg(body):
    body = body or {}
    init_data = body.get("initData") or body.get("init_data") or ""
    user = validate_init_data(init_data) if init_data else None
    if user and user.get("id") is not None:
        return int(user["id"]), user
    tid = body.get("tg_id") or body.get("telegram_id")
    if tid is not None and str(tid).strip() != "":
        try:
            tid = int(tid)
            return tid, {
                "id": tid,
                "username": body.get("username") or "",
                "first_name": body.get("first_name") or "User",
                "last_name": body.get("last_name") or "",
                "photo_url": body.get("photo_url") or "",
            }
        except Exception:
            pass
    return None, None


def require_sub(tg_id):
    return is_admin(tg_id) or sub_status(tg_id).get("active")


# ---------- Flask ----------
flask_app = Flask(__name__)
flask_app.secret_key = os.environ.get("SECRET_KEY", "dark-cpm")
_cpm_sessions = {}
_jobs = {}
_job_lock = threading.Lock()


def _new_job_id():
    return secrets.token_hex(8)


def job_set(job_id, **fields):
    with _job_lock:
        j = _jobs.get(job_id) or {}
        j.update(fields)
        j["updated_at"] = time.time()
        _jobs[job_id] = j
        return dict(j)


def job_get(job_id):
    with _job_lock:
        j = _jobs.get(job_id)
        return dict(j) if j else None


def start_job(name, target, *args, job_id=None, **kwargs):
    """Run work in a non-daemon thread so it keeps going after Mini App closes.
    Returns job_id. target may accept progress via kwargs if designed for it.
    """
    jid = job_id or _new_job_id()
    job_set(
        jid,
        id=jid,
        name=name,
        status="running",
        percent=0,
        message="Starting…",
        result=None,
        error=None,
        created_at=time.time(),
    )

    def runner():
        try:
            target(*args, **kwargs)
            cur = job_get(jid) or {}
            if cur.get("status") == "running":
                job_set(jid, status="done", percent=100, message=cur.get("message") or "Done")
        except Exception as e:
            print("job", name, "error", e)
            job_set(jid, status="error", percent=100, message=str(e)[:200], error=str(e)[:200])

    th = threading.Thread(target=runner, name="job-%s-%s" % (name, jid), daemon=False)
    th.start()
    return jid




def _html(name):
    path = ROOT / name
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8")
    except Exception:
        pass
    if name == "login.html":
        return base64.b64decode(_LOGIN_B64).decode("utf-8")
    if name == "dashboard.html":
        return base64.b64decode(_DASH_B64).decode("utf-8")
    return "<h1>Not found</h1>"


@flask_app.route("/")
def root():
    return redirect("/login")


@flask_app.route("/login")
def login_page():
    return _html("login.html"), 200, {
        "Content-Type": "text/html; charset=utf-8",
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
    }


@flask_app.route("/app")
@flask_app.route("/dashboard")
def app_page():
    return _html("dashboard.html"), 200, {
        "Content-Type": "text/html; charset=utf-8",
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
    }


@flask_app.route("/api/me", methods=["POST"])
def api_me():
    body = request.get_json(silent=True) or {}
    tg_id, user = resolve_tg(body)
    if not tg_id or not user:
        return jsonify({"ok": False, "error": "Open from Telegram bot → Open App"}), 401
    upsert_user(tg_id, user.get("username") or "", user.get("first_name") or "", user.get("last_name") or "", user.get("photo_url") or "")
    st = sub_status(tg_id)
    # Admin access is independent of the subscription database.
    # This keeps the Mini App and bot permissions in sync even if the
    # subscription row was written by another Railway process/container.
    admin = is_admin(tg_id)
    if admin:
        st = {
            "active": True,
            "plan": "lifetime",
            "plan_label": "Lifetime",
            "remaining": "Lifetime",
            "expires_str": "Admin",
        }
    row = get_user(tg_id) or {}
    member_since = "—"
    try:
        if row.get("joined_at"):
            member_since = datetime.utcfromtimestamp(float(row["joined_at"])).strftime("%b %d, %Y")
    except Exception:
        pass
    resp = jsonify({
        "ok": True,
        "user": {
            "id": tg_id,
            "username": user.get("username") or "",
            "first_name": user.get("first_name") or "",
            "last_name": user.get("last_name") or "",
            "photo_url": user.get("photo_url") or "",
        },
        "subscription": st,
        "member_since": member_since,
        "is_admin": admin,
    })
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


@flask_app.route("/api/plans")
def api_plans():
    plans = []
    for k, v in PLANS.items():
        plans.append({
            "key": k,
            "label": v["label"],
            "days": v["days"],
            "stars": v.get("stars", 0),
            "money": v.get("money", 0),
            "money_label": v.get("money_label", ""),
        })
    pay = {
        "gcash": PAY_GCASH,
        "paypal": PAY_PAYPAL,
        "other": PAY_OTHER,
        "currency": PAY_CURRENCY,
    }
    return jsonify({"ok": True, "plans": plans, "payment": pay})


@flask_app.route("/api/buy_stars", methods=["POST"])
def api_buy_stars():
    """Create Stars invoice link for Mini App (Telegram.WebApp.openInvoice)."""
    body = request.get_json(silent=True) or {}
    tg_id, _ = resolve_tg(body)
    if not tg_id:
        return jsonify({"ok": False, "error": "telegram_required"}), 401
    key = (body.get("plan") or "").strip().lower()
    plan = PLANS.get(key)
    if not plan:
        return jsonify({"ok": False, "error": "invalid_plan"})
    if not bot:
        return jsonify({"ok": False, "error": "bot_offline"})
    stars = int(plan.get("stars") or 0)
    if stars < 1:
        return jsonify({"ok": False, "error": "stars_price_not_set"})
    title = "DARK CPM — %s" % plan["label"]
    description = "Subscription %s · %d Telegram Stars" % (plan["label"], stars)
    payload = "stars:%s:%s" % (key, tg_id)
    prices = [types.LabeledPrice(label=plan["label"], amount=stars)]
    try:
        # send invoice in chat; also return for openInvoice if link available
        bot.send_invoice(
            chat_id=int(tg_id),
            title=title,
            description=description,
            invoice_payload=payload,
            provider_token="",  # empty = Telegram Stars
            currency="XTR",
            prices=prices,
        )
        return jsonify({
            "ok": True,
            "message": "Invoice sent in bot chat — open bot and pay with Stars",
            "plan": key,
            "stars": stars,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:160]})


@flask_app.route("/api/buy_money", methods=["POST"])
def api_buy_money():
    """Register a money-payment request; admin confirms with /givesub."""
    body = request.get_json(silent=True) or {}
    tg_id, user = resolve_tg(body)
    if not tg_id:
        return jsonify({"ok": False, "error": "telegram_required"}), 401
    key = (body.get("plan") or "").strip().lower()
    plan = PLANS.get(key)
    if not plan:
        return jsonify({"ok": False, "error": "invalid_plan"})
    note = (body.get("note") or "").strip()[:200]
    username = (user or {}).get("username") or body.get("username") or ""
    # notify admins
    lines = [
        "💰 <b>Money payment request</b>",
        "User: <code>%s</code> @%s" % (tg_id, username or "—"),
        "Plan: <b>%s</b> · %s" % (plan["label"], plan.get("money_label") or ("$%s" % plan.get("money"))),
        "Note: %s" % (note or "—"),
        "",
        "Activate: <code>/givesub %s %s</code>" % (tg_id, key),
    ]
    for aid in ADMIN_IDS:
        try:
            bot.send_message(aid, "\n".join(lines))
        except Exception:
            pass
    try:
        bot.send_message(
            int(tg_id),
            "📩 Payment request sent to admin.\nPlan: <b>%s</b> · %s\n\n%s"
            % (plan["label"], plan.get("money_label"), _money_instructions()),
        )
    except Exception:
        pass
    return jsonify({
        "ok": True,
        "message": "Request sent to admin. Pay then wait for activation.",
        "plan": key,
        "money_label": plan.get("money_label"),
        "instructions": _money_instructions_plain(),
    })



@flask_app.route("/api/cpm_login", methods=["POST"])
def api_cpm_login():
    body = request.get_json(silent=True) or {}
    tg_id, _ = resolve_tg(body)
    if not tg_id:
        return jsonify({"ok": False, "error": "Open from Telegram bot → Open App"}), 401
    email = (body.get("email") or "").strip()
    password = body.get("password") or ""
    try:
        lr = nuker.login(email, password)
        if not lr.get("ok"):
            return jsonify({"ok": False, "error": lr.get("message", "login_failed")})
        uid_key = int(hashlib.sha256(
    ("web_%s" % tg_id).encode("utf-8")
).hexdigest()[:12], 16) % (10**9)
        nuker.save_token(uid_key, lr["auth"], email, password, lr.get("refresh_token", ""), lr.get("firebase_uid", ""))
        _cpm_sessions[tg_id] = {"email": email, "password": password, "auth": lr["auth"], "fuid": lr.get("firebase_uid", ""), "uid_key": uid_key}
        return jsonify({"ok": True, "email": email})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:120]})


@flask_app.route("/api/cpm_register", methods=["POST"])
def api_cpm_register():
    body = request.get_json(silent=True) or {}
    tg_id, _ = resolve_tg(body)
    if not tg_id:
        return jsonify({"ok": False, "error": "Open from Telegram bot → Open App"}), 401
    email = (body.get("email") or "").strip()
    password = body.get("password") or ""
    if not email or "@" not in email:
        return jsonify({"ok": False, "error": "Enter a valid email"})
    if len(password) < 6:
        return jsonify({"ok": False, "error": "Password min 6 chars"})
    try:
        lr = nuker.register(email, password)
        if not lr.get("ok"):
            return jsonify({"ok": False, "error": lr.get("message", "register_failed")})
        lr2 = nuker.login(email, password)
        if lr2.get("ok"):
            lr = lr2
        uid_key = int(hashlib.sha256(
    ("web_%s" % tg_id).encode("utf-8")
).hexdigest()[:12], 16) % (10**9)
        nuker.save_token(uid_key, lr["auth"], email, password, lr.get("refresh_token", ""), lr.get("firebase_uid", ""))
        _cpm_sessions[tg_id] = {"email": email, "password": password, "auth": lr["auth"], "fuid": lr.get("firebase_uid", ""), "uid_key": uid_key}
        return jsonify({"ok": True, "email": email, "message": "Account created"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:120]})



@flask_app.route("/api/cpm_logout", methods=["POST"])
def api_cpm_logout():
    body = request.get_json(silent=True) or {}
    tg_id, _ = resolve_tg(body)
    if tg_id and tg_id in _cpm_sessions:
        _cpm_sessions.pop(tg_id, None)
    return jsonify({"ok": True})


@flask_app.route("/api/cpm_session")
def api_cpm_session():
    tg_id = request.args.get("tg_id", type=int)
    if not tg_id or tg_id not in _cpm_sessions:
        return jsonify({"ok": False})
    sess = _cpm_sessions[tg_id]
    profile = None
    try:
        uid_key = sess.get("uid_key") or abs(hash("web_%s" % tg_id)) % (10**9)
        nuker.save_token(uid_key, sess["auth"], sess["email"], sess["password"], "", sess.get("fuid", ""))
        nuker.load(uid_key, force=True)
        info = nuker.get_account_info(uid_key)
        if isinstance(info, dict) and info.get("ok"):
            profile = {
                "name": info.get("name"),
                "money": info.get("money"),
                "coin": info.get("coin"),
                "player_id": info.get("localID"),
                "localID": info.get("localID"),
            }
    except Exception:
        pass
    return jsonify({"ok": True, "email": sess["email"], "profile": profile})


def _sess(tg_id):
    sess = _cpm_sessions.get(tg_id)
    if sess:
        return sess

    try:
        uid_key = int(hashlib.sha256(
            ("web_%s" % tg_id).encode("utf-8")
        ).hexdigest()[:12], 16) % (10**9)

        td = nuker.get_token_data(uid_key)
        if not td:
            return None

        ok, _, auth = nuker.get_auth(uid_key)
        if not ok or not auth:
            return None

        sess = {
            "email": td.get("email", ""),
            "password": td.get("password", ""),
            "auth": auth,
            "fuid": td.get("firebase_uid", ""),
            "uid_key": uid_key,
        }

        _cpm_sessions[tg_id] = sess
        return sess

    except Exception:
        return None


@flask_app.route("/api/action", methods=["POST"])
def api_action():
    body = request.get_json(silent=True) or {}
    tg_id, _ = resolve_tg(body)
    if not tg_id:
        return jsonify({"ok": False, "error": "telegram_required"}), 401
    if not require_sub(tg_id):
        return jsonify({"ok": False, "error": "subscription_required"}), 403
    sess = _sess(tg_id)
    if not sess:
        return jsonify({"ok": False, "error": "login_required"})
    action = body.get("action") or ""
    value = body.get("value")
    try:
        uid = sess.get("uid_key") or int(hashlib.sha256(
    ("web_%s" % tg_id).encode("utf-8")
).hexdigest()[:12], 16) % (10**9)
        nuker.save_token(uid, sess["auth"], sess["email"], sess["password"], "", sess.get("fuid", ""))

        mapping = {
            "acc_rank": lambda: nuker.set_rank(uid),
            "acc_refresh": lambda: nuker.get_account_info(uid, force_refresh=True),
            "eco_money": lambda: nuker.set_money(uid, 50_000_000),
            "eco_coin": lambda: nuker.set_coin(uid, 500_000),
            "eco_money_c": lambda: nuker.set_money(uid, int(float(value or 0))),
            "eco_coin_c": lambda: nuker.set_coin(uid, int(float(value or 0))),
            "unl_w16": lambda: nuker.unlock_w16(uid),
            "unl_smoke": lambda: nuker.unlock_smoke(uid),
            "unl_fuel": lambda: nuker.unlimited_fuel(uid),
            "unl_damage": lambda: nuker.disable_damage(uid),
            "unl_horns": lambda: nuker.unlock_horns(uid),
            "unl_anim": lambda: nuker.unlock_animations(uid),
            "unl_houses": lambda: nuker.unlock_houses(uid),
            "unl_wheels": lambda: nuker.unlock_wheels(uid),
            "unl_levels": lambda: nuker.complete_all_levels(uid),
            "unl_clothes": lambda: nuker.unlock_all_clothes(uid),
            "unl_all": lambda: nuker.unlock_all_features(uid),
            "acc_name": lambda: nuker.change_player_name(uid, str(value or "")),
            "acc_id": lambda: nuker.change_player_id(uid, str(value or "")),
        }
        if action == "acc_email":
            return jsonify({"ok": True, "message": "Email change: use game settings / admin tools"})
        if action == "acc_pass":
            return jsonify({"ok": True, "message": "Password change requested (handle via Firebase if configured)"})
        if action == "veh_siren":
            email, password = sess["email"], sess["password"]
            def work_siren():
                res = unlock_siren(email, password, car_id=None)
                _send_tg(tg_id, "%s Siren all: %s" % ("✅" if res.get("ok") else "❌", res.get("message", "")))
            start_job("siren_all", work_siren)
            return jsonify({"ok": True, "message": "Siren job started — close app OK, result on Telegram"})
        if action == "veh_siren_one":
            email, password = sess["email"], sess["password"]
            cid = int(value) if value is not None else None
            def work_siren1():
                res = unlock_siren(email, password, car_id=cid)
                _send_tg(tg_id, "%s Siren one: %s" % ("✅" if res.get("ok") else "❌", res.get("message", "")))
            start_job("siren_one", work_siren1)
            return jsonify({"ok": True, "message": "Siren job started — close app OK, result on Telegram"})
        if action == "plate_inject":
            email, password = sess["email"], sess["password"]
            def work_plates():
                res = inject_plates(email, password, merge=True)
                _send_tg(tg_id, "%s Plates: %s" % ("✅" if res.get("ok") else "❌", res.get("message", "")))
            start_job("plates", work_plates)
            return jsonify({"ok": True, "message": "Plate inject started — close app OK, result on Telegram"})
        if action == "veh_all":
            email, password = sess["email"], sess["password"]
            def work_all():
                res = unlock_all_cars(email, password)
                _send_tg(tg_id, "%s Unlock all cars: %s" % ("✅" if res.get("ok") else "❌", res.get("message", "")))
            start_job("veh_all", work_all)
            return jsonify({"ok": True, "message": "Unlock all cars started — result on Telegram"})
        if action == "veh_one":
            email, password = sess["email"], sess["password"]
            if value is None or str(value).strip() == "":
                return jsonify({"ok": False, "error": "Car ID required"})
            try:
                cid = int(value)
            except Exception:
                return jsonify({"ok": False, "error": "Invalid car ID"})
            def work_one():
                res = unlock_one_car(email, password, cid)
                _send_tg(tg_id, "%s Unlock car %s: %s" % ("✅" if res.get("ok") else "❌", cid, res.get("message", "")))
            start_job("veh_one", work_one)
            return jsonify({"ok": True, "message": "Unlock car %s started — result on Telegram" % cid})
        if action == "veh_w124":
            email, password = sess["email"], sess["password"]
            def work_w124():
                # common W124 id attempts
                last = None
                for cid in (106, 61, 107, 108):
                    last = unlock_one_car(email, password, cid)
                    if last.get("ok"):
                        break
                res = last or {"ok": False, "message": "W124 not on source"}
                _send_tg(tg_id, "%s W124: %s" % ("✅" if res.get("ok") else "❌", res.get("message", "")))
            start_job("veh_w124", work_w124)
            return jsonify({"ok": True, "message": "W124 unlock started — result on Telegram"})
        if action == "veh_camry":
            email, password = sess["email"], sess["password"]
            def work_camry():
                last = None
                for cid in (120, 121, 122):
                    last = unlock_one_car(email, password, cid)
                    if last.get("ok"):
                        break
                res = last or {"ok": False, "message": "Camry not on source"}
                _send_tg(tg_id, "%s Camry: %s" % ("✅" if res.get("ok") else "❌", res.get("message", "")))
            start_job("veh_camry", work_camry)
            return jsonify({"ok": True, "message": "Camry unlock started — result on Telegram"})
        fn = mapping.get(action)
        if not fn:
            return jsonify({"ok": False, "error": "unknown_action"})
        res = fn()
        ok = bool(res.get("ok")) if isinstance(res, dict) else True
        msg = (res.get("message") if isinstance(res, dict) else None) or ("OK" if ok else "Failed")
        return jsonify({"ok": ok, "message": msg})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:150]})


def _send_tg(tg_id, text):
    if not bot:
        return
    try:
        text = str(text)
        while text:
            bot.send_message(int(tg_id), text[:3500], parse_mode="HTML")
            text = text[3500:]
    except Exception as e:
        print("send_tg", e)



@flask_app.route("/api/job/<job_id>")
def api_job_status(job_id):
    j = job_get(job_id)
    if not j:
        return jsonify({"ok": False, "error": "job_not_found"}), 404
    return jsonify({
        "ok": True,
        "id": j.get("id"),
        "name": j.get("name"),
        "status": j.get("status"),
        "percent": int(j.get("percent") or 0),
        "message": j.get("message") or "",
        "error": j.get("error"),
        "result": j.get("result"),
    })


@flask_app.route("/api/clone", methods=["POST"])
def api_clone():
    body = request.get_json(silent=True) or {}
    tg_id, _ = resolve_tg(body)
    if not tg_id:
        return jsonify({"ok": False, "error": "telegram_required"}), 401
    if not require_sub(tg_id):
        return jsonify({"ok": False, "error": "subscription_required"}), 403
    src_email, src_pass = (body.get("src_email") or "").strip(), body.get("src_pass") or ""
    tgt_email, tgt_pass = (body.get("tgt_email") or "").strip(), body.get("tgt_pass") or ""
    if not all([src_email, src_pass, tgt_email, tgt_pass]):
        return jsonify({"ok": False, "error": "need source and target email:pass"})

    jid = _new_job_id()

    def work():
        def on_progress(pct, msg):
            job_set(jid, percent=int(pct), message=str(msg), status="running")

        try:
            res = web_clone_account(src_email, src_pass, tgt_email, tgt_pass, progress_cb=on_progress)
            job_set(
                jid,
                status="done" if res.get("ok") else "error",
                percent=100,
                message=res.get("message", "Done"),
                result=res,
            )
            _send_tg(tg_id, "%s <b>Clone finished</b>\n<code>%s</code> → <code>%s:%s</code>\n%s" % (
                "✅" if res.get("ok") else "❌", src_email, tgt_email, tgt_pass, res.get("message", "")))
        except Exception as e:
            job_set(jid, status="error", percent=100, message=str(e)[:200], error=str(e)[:200])
            _send_tg(tg_id, "❌ Clone error: %s" % str(e)[:200])

    start_job("clone", work, job_id=jid)
    _send_tg(tg_id, "⏳ Clone started on server.\nYou can close the Mini App — result will still be sent here.")
    return jsonify({"ok": True, "job_id": jid, "message": "Clone started"})



@flask_app.route("/api/bulk_clone", methods=["POST"])
def api_bulk_clone():
    body = request.get_json(silent=True) or {}
    tg_id, _ = resolve_tg(body)
    if not tg_id:
        return jsonify({"ok": False, "error": "telegram_required"}), 401
    if not require_sub(tg_id):
        return jsonify({"ok": False, "error": "subscription_required"}), 403
    src_email, src_pass = (body.get("src_email") or "").strip(), body.get("src_pass") or ""
    try:
        count = int(body.get("count") or 1)
    except Exception:
        count = 1
    count = max(1, min(50 if not is_admin(tg_id) else 100, count))
    if not src_email or not src_pass:
        return jsonify({"ok": False, "error": "need source email:pass"})

    jid = _new_job_id()

    def work():
        def on_progress(i, total, msg, pct=None):
            if pct is None:
                pct = int(100 * int(i) / max(1, int(total)))
            job_set(jid, percent=int(pct), message=str(msg), status="running")

        try:
            res = web_bulk_clone(src_email, src_pass, count, progress_cb=on_progress)
            accounts = res.get("accounts") or []
            job_set(jid, status="done" if res.get("ok") else "error", percent=100,
                    message=res.get("message", "Done"), result={"count": len(accounts)})
            lines = ["DARK CPM bulk clone", "Source: " + src_email, "Count: %d" % len(accounts), "NOT copied: friends", ""] + accounts
            bio = io.BytesIO("\n".join(lines).encode("utf-8"))
            bio.name = "bulk_clone_%d.txt" % len(accounts)
            try:
                bot.send_document(int(tg_id), bio, caption="Bulk clone done · %d accounts" % len(accounts))
            except Exception as e:
                _send_tg(tg_id, "%s\n%s" % (res.get("message", "Done"), "\n".join(accounts[:20])))
                print("bulk send", e)
        except Exception as e:
            job_set(jid, status="error", percent=100, message=str(e)[:200], error=str(e)[:200])
            _send_tg(tg_id, "❌ Bulk clone error: %s" % str(e)[:200])

    start_job("bulk_clone", work, job_id=jid)
    _send_tg(tg_id, "⏳ Bulk clone (%d) running on server.\nYou can close the Mini App — file will still be sent here when done." % count)
    return jsonify({"ok": True, "job_id": jid, "message": "Bulk clone started", "count": count})



# ---------- Bot launcher (inline keyboards) ----------
def start_text(user):
    st = sub_status(user.id)
    sub = ("✅ %s · %s" % (st.get("plan_label"), st.get("remaining"))) if st.get("active") else "❌ No subscription"
    return (
        "<b>DARK CPM</b>\n"
        "━━━━━━━━━━━━━━━━\n"
        "👤 %s\n"
        "🆔 <code>%s</code>\n"
        "📱 @%s\n"
        "━━━━━━━━━━━━━━━━\n"
        "📦 %s\n"
        "━━━━━━━━━━━━━━━━\n"
        "Features run in the <b>Mini App</b>.\n"
        "Login OK without plan — menu unlocks after subscription."
    ) % (user.first_name or "User", user.id, user.username or "—", sub)


def webapp_kb():
    """Main /start inline keyboard."""
    kb = types.InlineKeyboardMarkup(row_width=1)
    url = (WEBAPP_URL or "").rstrip("/") + "/login"
    if url.startswith("http"):
        kb.add(types.InlineKeyboardButton("🚀 Open App", web_app=types.WebAppInfo(url=url)))
    kb.row(
        types.InlineKeyboardButton("💳 Buy Subscription", callback_data="buy_sub"),
        types.InlineKeyboardButton("📊 My Status", callback_data="my_status"),
    )
    return kb


def plans_kb():
    """Plan list with Stars + money prices."""
    kb = types.InlineKeyboardMarkup(row_width=1)
    for k, p in PLANS.items():
        label = "%s · %d★ · %s" % (p["label"], p.get("stars", 0), p.get("money_label", ""))
        kb.add(types.InlineKeyboardButton(label, callback_data="plan_" + k))
    kb.add(types.InlineKeyboardButton("« Back", callback_data="back_start"))
    return kb


def plan_pay_kb(plan_key):
    p = PLANS.get(plan_key) or {}
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("⭐ Pay %d Stars" % p.get("stars", 0), callback_data="stars_" + plan_key))
    kb.add(types.InlineKeyboardButton("💵 Pay money %s" % p.get("money_label", ""), callback_data="money_" + plan_key))
    kb.add(types.InlineKeyboardButton("« Plans", callback_data="buy_sub"))
    return kb


if bot:
    @bot.message_handler(commands=["start", "Start", "menu"])
    def cmd_start(message):
        try:
            u = message.from_user
            upsert_user(u.id, u.username or "", u.first_name or "", u.last_name or "")
            bot.send_message(message.chat.id, start_text(u), reply_markup=webapp_kb())
        except Exception as e:
            bot.reply_to(message, "DARK CPM · error: %s" % str(e)[:100])

    @bot.callback_query_handler(func=lambda c: c.data == "my_status")
    def cb_status(call):
        st = sub_status(call.from_user.id)
        if st.get("active"):
            msg = "✅ %s · %s" % (st.get("plan_label"), st.get("remaining"))
        else:
            msg = "❌ No active subscription"
        bot.answer_callback_query(call.id, msg, show_alert=True)

    @bot.callback_query_handler(func=lambda c: c.data == "buy_sub")
    def cb_buy_sub(call):
        bot.answer_callback_query(call.id)
        try:
            bot.edit_message_text(
                "<b>💳 Buy subscription</b>\n\n"
                "⭐ Stars = instant unlock\n"
                "💵 Money = pay then admin activates\n\n"
                "GCash: <code>%s</code>\n"
                "PayPal: <code>%s</code>"
                % (PAY_GCASH or "—", PAY_PAYPAL or "—"),
                call.message.chat.id,
                call.message.message_id,
                reply_markup=plans_kb(),
                parse_mode="HTML",
            )
        except Exception as e:
            bot.send_message(call.message.chat.id, "Plans", reply_markup=plans_kb())

    @bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("plan_"))
    def cb_plan(call):
        key = call.data.replace("plan_", "", 1)
        plan = PLANS.get(key)
        bot.answer_callback_query(call.id)
        if not plan:
            return
        text = (
            "<b>%s</b>\n\n"
            "⭐ Stars: <b>%d</b>\n"
            "💵 Money: <b>%s</b>\n\n"
            "Choose payment method:"
        ) % (plan["label"], plan.get("stars", 0), plan.get("money_label", ""))
        try:
            bot.edit_message_text(
                text,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=plan_pay_kb(key),
                parse_mode="HTML",
            )
        except Exception:
            bot.send_message(call.message.chat.id, text, reply_markup=plan_pay_kb(key), parse_mode="HTML")

    @bot.callback_query_handler(func=lambda c: c.data == "back_start")
    def cb_back_start(call):
        bot.answer_callback_query(call.id)
        try:
            bot.edit_message_text(
                start_text(call.from_user),
                call.message.chat.id,
                call.message.message_id,
                reply_markup=webapp_kb(),
                parse_mode="HTML",
            )
        except Exception:
            bot.send_message(call.message.chat.id, start_text(call.from_user), reply_markup=webapp_kb())

    @bot.message_handler(commands=["givesub"])
    def cmd_givesub(message):
        if not is_admin(message.from_user.id):
            return
        parts = (message.text or "").split()
        if len(parts) < 3:
            bot.reply_to(message, "Usage: /givesub <tg_id> <1day|7days|1month|lifetime>")
            return
        try:
            tid = int(parts[1])
        except Exception:
            bot.reply_to(message, "Invalid id")
            return
        plan = parts[2].lower()
        if plan not in PLANS:
            bot.reply_to(message, "Invalid plan")
            return
        upsert_user(tid)
        if not set_subscription(tid, plan):
            bot.reply_to(message, "❌ Subscription could not be saved. Try again.")
            return
        st = sub_status(tid)
        bot.reply_to(message, "✅ %s → <code>%s</code> until %s\n🔗 Mini App membership synced" % (PLANS[plan]["label"], tid, st.get("expires_str")))
        try:
            bot.send_message(tid, "✅ Subscription: <b>%s</b>" % PLANS[plan]["label"])
        except Exception:
            pass

    @bot.message_handler(commands=["remsub"])
    def cmd_remsub(message):
        if not is_admin(message.from_user.id):
            return
        parts = (message.text or "").split()
        if len(parts) < 2:
            return
        try:
            tid = int(parts[1])
        except Exception:
            return
        clear_subscription(tid)
        bot.reply_to(message, "Removed <code>%s</code>" % tid)

    @bot.message_handler(commands=["users", "list"])
    def cmd_users(message):
        if not is_admin(message.from_user.id):
            bot.reply_to(message, "Admin only")
            return
        with db() as c:
            rows = c.execute(
                "SELECT tg_id, username, sub_plan, sub_expires FROM users ORDER BY last_seen DESC LIMIT 50"
            ).fetchall()
        now = time.time()
        lines = []
        for r in rows:
            active = r["sub_expires"] and float(r["sub_expires"]) > now
            lines.append(
                "%s <code>%s</code> @%s %s"
                % ("OK" if active else "NO", r["tg_id"], r["username"] or "—", r["sub_plan"] or "-")
            )
        bot.send_message(
            message.chat.id,
            "<b>Users</b> (%d)\n\n%s" % (len(lines), "\n".join(lines) or "None"),
            parse_mode="HTML",
        )

    @bot.message_handler(commands=["admin"])
    def cmd_admin(message):
        if not is_admin(message.from_user.id):
            return
        bot.reply_to(message, "<b>Admin</b>\n/givesub id plan\n/remsub id\n/users")




if bot:

    @bot.pre_checkout_query_handler(func=lambda q: True)
    def pre_checkout(query):
        try:
            bot.answer_pre_checkout_query(query.id, ok=True)
        except Exception as e:
            print("pre_checkout", e)

    @bot.message_handler(content_types=["successful_payment"])
    def on_successful_payment(message):
        try:
            sp = message.successful_payment
            payload = (sp.invoice_payload or "")
            parts = payload.split(":")
            if len(parts) >= 3 and parts[0] == "stars":
                plan_key = parts[1]
                try:
                    buyer = int(parts[2])
                except Exception:
                    buyer = message.from_user.id
            else:
                plan_key = payload
                buyer = message.from_user.id
            if plan_key not in PLANS:
                bot.send_message(message.chat.id, "Payment received but plan unknown. Contact admin.")
                return
            set_subscription(buyer, plan_key)
            st = sub_status(buyer)
            bot.send_message(
                message.chat.id,
                "✅ <b>Payment OK</b>\nPlan: <b>%s</b>\nUntil: %s\nStars: %s"
                % (PLANS[plan_key]["label"], st.get("expires_str"), sp.total_amount),
            )
            if buyer != message.from_user.id:
                try:
                    bot.send_message(buyer, "✅ Subscription activated: <b>%s</b>" % PLANS[plan_key]["label"])
                except Exception:
                    pass
        except Exception as e:
            print("successful_payment", e)

    @bot.message_handler(commands=["buy", "subscribe"])
    def cmd_buy(message):
        text = (
            "<b>Buy subscription</b>\n\n"
            "Stars = instant unlock\n"
            "Money = GCash / PayPal\n\n"
            "GCash: <code>%s</code>\n"
            "PayPal: <code>%s</code>"
        ) % (PAY_GCASH or "—", PAY_PAYPAL or "—")
        bot.reply_to(message, text, reply_markup=plans_kb())

    @bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("stars_"))
    def cb_stars(call):
        key = call.data.replace("stars_", "", 1)
        plan = PLANS.get(key)
        if not plan:
            bot.answer_callback_query(call.id, "Invalid")
            return
        uid = call.from_user.id
        stars = int(plan.get("stars") or 0)
        try:
            bot.send_invoice(
                chat_id=uid,
                title="DARK CPM — %s" % plan["label"],
                description="Subscription %s" % plan["label"],
                invoice_payload="stars:%s:%s" % (key, uid),
                provider_token="",
                currency="XTR",
                prices=[types.LabeledPrice(label=plan["label"], amount=stars)],
            )
            bot.answer_callback_query(call.id, "Invoice sent")
        except Exception as e:
            bot.answer_callback_query(call.id, str(e)[:80], show_alert=True)

    @bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("money_"))
    def cb_money(call):
        key = call.data.replace("money_", "", 1)
        plan = PLANS.get(key)
        if not plan:
            bot.answer_callback_query(call.id, "Invalid")
            return
        uid = call.from_user.id
        un = call.from_user.username or ""
        text = (
            "Pay with money — <b>%s</b>\n"
            "Price: <b>%s</b>\n\n"
            "%s\n\n"
            "After pay, send screenshot here.\n"
            "Admin: <code>/givesub %s %s</code>"
        ) % (plan["label"], plan.get("money_label"), _money_instructions(), uid, key)
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, text)
        for aid in ADMIN_IDS:
            try:
                bot.send_message(
                    aid,
                    "Money interest\nUser <code>%s</code> @%s\nPlan %s (%s)\n<code>/givesub %s %s</code>"
                    % (uid, un or "—", plan["label"], plan.get("money_label"), uid, key),
                )
            except Exception:
                pass



def run_flask():
    flask_app.run(host="0.0.0.0", port=PORT, threaded=True, use_reloader=False)


if __name__ == "__main__":
    print("DARK CPM Mini App product")
    print("WEBAPP_URL =", WEBAPP_URL)
    print("ADMIN_IDS =", ADMIN_IDS)
    if bot:
        try:
            bot.remove_webhook()
            me = bot.get_me()
            print("Bot OK @%s" % me.username)
        except Exception as e:
            print("Bot token issue:", e)
    threading.Thread(target=run_flask, daemon=True).start()
    if bot:
        while True:
            try:
                bot.infinity_polling(timeout=60, long_polling_timeout=60, skip_pending=True, none_stop=True)
            except Exception as e:
                print("poll", e)
                time.sleep(3)
    else:
        run_flask()
