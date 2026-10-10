#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════╗
║   ⚡ ILIJA CPM TOOLS - TELEGRAM BOT ⚡               ║
║   CPM1 + CPM2 · king rank · email/pass · money        ║
╚══════════════════════════════════════════════════════╝
"""
import os, sys, json, base64, struct, time, random, string, threading, warnings
import requests, urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore")

try:
    import telebot
except ImportError:
    print("pip install pyTelegramBotAPI")
    sys.exit(1)

# lijeno ucitavanje - tek kad se koristi (manji CPU pri bootu)
_AES = _pad = _unpad = None
_brotli = None
def _load_crypto():
    global _AES, _pad, _unpad
    if _AES is None:
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import pad, unpad
        _AES, _pad, _unpad = AES, pad, unpad
def _load_brotli():
    global _brotli
    if _brotli is None:
        import brotli
        _brotli = brotli
from telebot import types

# ══════════ CONFIG - STAVI SVOJ TOKEN ══════════
BOT_TOKEN = os.environ.get("8682873022:AAFxpLAfUFZSX6GMC7ZCmVjZb7d7CBhl0Ts", "").strip()
OWNER_ID = int(os.environ.get("OWNER_ID", "8884756222") or 8884756222)

bot = telebot.TeleBot(BOT_TOKEN, threaded=True, num_threads=4)

# ══════════ CPM2 ENGINE (iz FLANKER/DARKROOT fajlova) ══════════
C2_API_KEY = 'AIzaSyCQDz9rgjgmvmFkvVfmvr2-7fT4tfrzRRQ'
C2_CF_BASE = 'https://europe-west1-cpm-2-7cea1.cloudfunctions.net'
C2_VERSION = '1.3.2.3'
C2_CLIENT_HASH = 'F05A72840B40DC4FAADF539C5E38062527AE6422'
C2_OG_BASE = 'https://cpm-2.ogames.kz/api'
C2_OG_KEY = '320b93f3e7f4410aa52ce24da363ad04'
C2_BUNDLE = 'com.olzhas.carparking.multyplayer2'
C2_UA = 'UnityPlayer/2022.3.62f2 (UnityWebRequest/1.0, libcurl/8.10.1-DEV)'
C2_FB_SIGNUP = f'https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={C2_API_KEY}'
C2_FB_LOGIN = f'https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={C2_API_KEY}'
KEY_ADD = '12345678'
IV_ADD = '01234567'
http = requests.Session()

class Crypto:
    def __init__(self, uid):
        _load_crypto()
        self.key = (uid[:8] + KEY_ADD).encode()[:16]
        self.iv = (uid[:8] + IV_ADD).encode()[:16]
    def encrypt(self, s):
        return base64.b64encode(_AES.new(self.key, _AES.MODE_CBC, self.iv).encrypt(_pad(s.encode(), 16))).decode()
    def decrypt(self, s):
        try: return _unpad(_AES.new(self.key, _AES.MODE_CBC, self.iv).decrypt(base64.b64decode(s)), 16).decode()
        except: return None

def _xor_key(uid):
    c = list(uid)
    if len(c) >= 7: c[4], c[6] = c[6], c[4]
    if len(c) >= 9: del c[8]
    if len(c) >= 1: c.append(c[0])
    return ''.join(c).encode()

def mp_encode(data, uid):
    _load_brotli()
    return base64.b64encode(bytes(b ^ _xor_key(uid)[i % len(_xor_key(uid))] for i, b in enumerate(_brotli.compress(data, quality=5)))).decode()

def mp_i32(v): return struct.pack('<i', v)
def mp_u16(v): return struct.pack('<H', v)
def mp_i64(v): return struct.pack('<q', v)
def mp_str(s):
    if s is None: return b'\xff\xff\xff\xff'
    if s == "": return mp_i32(0)
    u = s.encode('utf-8')
    return mp_i32(~len(u)) + mp_i32(len(s)) + u
def mp_int_array(a):
    b = mp_i32(len(a))
    for v in a: b += mp_i32(v)
    return b
def mp_i64_array(a):
    b = mp_i32(len(a))
    for v in a: b += mp_i64(v)
    return b
def mp_dict_ii(d):
    b = mp_i32(len(d))
    for k in sorted(d.keys()): b += mp_i32(k) + mp_i32(d[k])
    return b
def mp_dict_is(d):
    b = mp_i32(len(d))
    for k in sorted(d.keys()): b += mp_i32(k) + mp_str(d[k])
    return b

def gen_device(): return ''.join(random.choice('0123456789abcdef') for _ in range(32))

def c2_headers(token):
    return {"User-Agent": C2_UA, "Content-Type": "application/json; charset=utf-8",
            "X-Unity-Version": "2022.3.62f2", "Authorization": f"Bearer {token}",
            "X-Client-Hash": C2_CLIENT_HASH, "X-Client-Platform": "ANDROID",
            "X-Client-Version": C2_VERSION, "X-Client-DeviceId": gen_device(),
            "X-Api-Key": C2_OG_KEY, "X-Client-Env": "prod", "X-Bundle-Id": C2_BUNDLE}

def cf(fn, payload, token, timeout=30):
    body = json.dumps({"data": payload})
    for attempt in range(3):
        try:
            r = http.post(f"{C2_CF_BASE}/{fn}", headers=c2_headers(token), data=body, timeout=timeout, verify=False)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 + attempt * 2); continue
            return r.json().get("result")
        except Exception:
            if attempt < 2: time.sleep(2 + attempt * 2); continue
            return None
    return None

def c2_login(email, password):
    try:
        r = http.post(C2_FB_LOGIN, json={"email": email, "password": password, "returnSecureToken": True}, timeout=20, verify=False)
        j = r.json()
        if "idToken" in j: return {"ok": True, "token": j["idToken"], "uid": j["localId"]}
        return {"ok": False, "message": j.get("error", {}).get("message", "login failed")}
    except Exception as e:
        return {"ok": False, "message": str(e)[:100]}

def c2_start_session(token):
    oh = {"X-Firebase-Token": token, "X-Client-Platform": "ANDROID", "X-Client-Version": C2_VERSION,
          "X-Client-DeviceId": gen_device(), "X-Api-Key": C2_OG_KEY, "X-Client-Env": "prod",
          "X-Bundle-Id": C2_BUNDLE, "Content-Type": "application/json", "User-Agent": C2_UA,
          "X-Client-Hash": C2_CLIENT_HASH}
    try: http.get(f"{C2_OG_BASE}/check-service/v1/hash/check", headers=oh, timeout=15, verify=False)
    except: pass
    try: http.post(f"{C2_OG_BASE}/check-service/v1/session/start", headers=oh, json={}, timeout=15, verify=False)
    except: pass
    time.sleep(0.4)
    r = cf("MasterMainStartup23_1", "0", token)
    if isinstance(r, dict): return r.get("code", -1)
    return -1

KING_RATING = {"cars": 100000, "car_fix": 100000, "car_collided": 100000, "car_exchange": 100000,
    "car_trade": 100000, "car_wash": 100000, "slicer_cut": 100000, "drift_max": 100000,
    "drift": 100000, "cargo": 100000, "delivery": 100000, "taxi": 100000, "levels": 100000,
    "gifts": 100000, "fuel": 100000, "offroad": 100000, "speed_banner": 100000,
    "reactions": 100000, "police": 100000, "run": 100000, "real_estate": 100000,
    "t_distance": 100000, "treasure": 100000, "block_post": 100000, "push_ups": 100000,
    "burnt_tire": 100000, "passanger_distance": 100000, "time": 9999999999, "race_win": 5000}

def c2_king_rank(email, pw):
    a = c2_login(email, pw)
    if not a.get("ok"): return {"ok": False, "message": "Login failed: " + a.get("message", "?")}
    token, uid = a["token"], a["uid"]
    crypto = Crypto(uid)
    try:
        code = c2_start_session(token)
        if code == 297: return {"ok": False, "message": "Account blocked (297)"}
    except Exception: pass
    time.sleep(0.4)
    all_data = {"general": KING_RATING, "achievements": {k: 5 for k in KING_RATING},
                "race_win": 5000, "level": 120, "score": 999.0, "batches": [5, 15, 25, 45, 60, 120]}
    r1 = cf("SetUserRating22_1", crypto.encrypt(json.dumps(all_data)), token)
    ok_cf = isinstance(r1, dict) and r1.get("code") == 1
    ok_og = False
    try:
        hdrs = {"Content-Type": "application/json", "X-Api-Key": C2_OG_KEY, "X-Client-Version": C2_VERSION,
                "X-Client-Platform": "Android", "X-Firebase-Token": token, "X-Client-DeviceId": gen_device(),
                "X-Client-Env": "prod", "X-Bundle-Id": C2_BUNDLE, "X-Client-Hash": C2_CLIENT_HASH, "User-Agent": C2_UA}
        r2 = http.post(f"{C2_OG_BASE}/progress-service/v1/rating/update", headers=hdrs,
                       data=json.dumps({"data": crypto.encrypt(json.dumps(KING_RATING))}), timeout=20, verify=False)
        ok_og = r2.status_code == 200 and '"code":1' in r2.text
    except Exception: pass
    try: cf("ValidateRank23_1", "0", token)
    except Exception: pass
    return {"ok": bool(ok_cf or ok_og), "message": "KING RANK applied!" if (ok_cf or ok_og) else "Rank write failed - try again"}

def c2_charge_wallet(token, uid, email, password):
    crypto = Crypto(uid)
    cf("SaveAppVersionOnAccountCreated22_1", crypto.encrypt(json.dumps({"version": C2_VERSION})), token)
    time.sleep(0.4)
    cf("GetRewards22_1", crypto.encrypt(""), token)
    time.sleep(0.4)
    cf("SavePlayerRecords22_1", crypto.encrypt("{}"), token)
    time.sleep(0.4)
    wallet = mp_encode(mp_i32(1) + mp_u16(0) + mp_i32(8) + mp_i64(50_000_000), uid)
    ok = False
    for ep in ("SaveWalletData23_1", "SaveWalletData24_1"):
        r = cf(ep, wallet, token)
        if isinstance(r, dict) and r.get("code") == 1: ok = True; break
        time.sleep(0.4)
    entries = {0: mp_str(""), 1: mp_str("PREMIUM"), 2: mp_int_array(list(range(225))), 3: mp_i32(255),
               4: mp_i64(127), 5: mp_i64(127), 6: mp_i32(0)}
    for k in range(19, 30): entries[k] = mp_int_array(list(range(15)))
    entries[30] = mp_int_array(list(range(50)))
    for k in range(31, 42): entries[k] = mp_int_array(list(range(15)))
    entries[42] = mp_int_array(list(range(50)))
    entries[43] = mp_dict_ii({i: 1 for i in range(78)})
    entries[44] = mp_i64((1 << 50) - 1)
    entries[45] = mp_int_array([1,2,3,4,5,6,7,8])
    entries[46] = mp_i64_array([-1, 16777215])
    entries[47] = mp_int_array([1]*110)
    entries[48] = mp_i64(15)
    entries[49] = mp_int_array([6,-1,0,0,0,999999999,0,1,0,0,0])
    entries[50] = mp_int_array([1]*13)
    entries[51] = mp_int_array([0,0,0,0,0])
    entries[52] = mp_dict_is({i: "0#1#2#3#4#5#6" for i in range(5)})
    entries[53] = mp_int_array(list(range(10)))
    full = mp_i32(len(entries))
    for k in sorted(entries.keys()):
        v = entries[k]
        full += mp_u16(k) + mp_i32(len(v)) + v
    for ep in ("SavePlayerRecords23_1", "SavePlayerRecords24_1"):
        r = cf(ep, mp_encode(full, uid), token)
        if isinstance(r, dict) and r.get("code") == 1: break
        time.sleep(0.4)
    return ok

def c2_money(email, pw):
    a = c2_login(email, pw)
    if not a.get("ok"): return {"ok": False, "message": "Login failed: " + a.get("message", "?")}
    try: c2_start_session(a["token"])
    except Exception: pass
    ok = c2_charge_wallet(a["token"], a["uid"], email, pw)
    return {"ok": ok, "message": "50M money + full unlock applied!" if ok else "Wallet write rejected - game may have patched this"}

def c2_change_email(email, pw, new_email):
    a = c2_login(email, pw)
    if not a.get("ok"): return {"ok": False, "message": "Login failed: " + a.get("message", "?")}
    try:
        r = http.post(f"https://identitytoolkit.googleapis.com/v1/accounts:update?key={C2_API_KEY}",
                      json={"idToken": a["token"], "email": new_email, "returnSecureToken": True}, timeout=20, verify=False)
        j = r.json()
        if j.get("email"): return {"ok": True, "message": f"Email changed to {new_email}"}
        return {"ok": False, "message": str(j.get("error", {}).get("message", "failed"))[:90]}
    except Exception as e:
        return {"ok": False, "message": str(e)[:90]}

def c2_change_password(email, pw, new_pw):
    a = c2_login(email, pw)
    if not a.get("ok"): return {"ok": False, "message": "Login failed: " + a.get("message", "?")}
    if len(new_pw) < 6: return {"ok": False, "message": "Password min 6 chars"}
    try:
        r = http.post(f"https://identitytoolkit.googleapis.com/v1/accounts:update?key={C2_API_KEY}",
                      json={"idToken": a["token"], "password": new_pw, "returnSecureToken": True}, timeout=20, verify=False)
        j = r.json()
        if j.get("idToken"): return {"ok": True, "message": "Password changed successfully"}
        return {"ok": False, "message": str(j.get("error", {}).get("message", "failed"))[:90]}
    except Exception as e:
        return {"ok": False, "message": str(e)[:90]}

# ══════════ CPM1 ENGINE ══════════
C1_API_KEY = 'AIzaSyBW1ZbMiUeDZHYUO2bY8Bfnf5rRgrQGPTM'
C1_RANK_URL = "https://us-central1-cp-multiplayer.cloudfunctions.net/SetUserRating4"

def c1_login(email, password):
    try:
        r = http.post(f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={C1_API_KEY}",
                      json={"email": email, "password": password, "returnSecureToken": True}, timeout=20)
        j = r.json()
        if "idToken" in j: return {"ok": True, "token": j["idToken"]}
        return {"ok": False, "message": j.get("error", {}).get("message", "login failed")}
    except Exception as e:
        return {"ok": False, "message": str(e)[:100]}

def c1_king_rank(email, pw):
    a = c1_login(email, pw)
    if not a.get("ok"): return {"ok": False, "message": "Login failed: " + a.get("message", "?")}
    rating = {"RatingData": {"time": 1e22, "cars": 1e16, "car_fix": 1e13, "car_collided": 1e12,
        "car_exchange": 1e13, "car_trade": 1e13, "car_wash": 1e13, "slicer_cut": 1e13,
        "drift_max": 1e14, "drift": 1e14, "cargo": 1e5, "delivery": 1e5, "race_win": 3e20,
        "taxi": 1e10, "levels": 10000990000, "gifts": 1e9, "fuel": 1e10, "offroad": 1e10,
        "speed_banner": 1e9, "reactions": 1e17, "run": 1e9, "real_estate": 1e9,
        "t_distance": 1e10, "treasure": 1e10, "block_post": 1e10, "push_ups": 1e12,
        "burnt_tire": 1e10, "passanger_distance": 1e8}}
    try:
        http.post(C1_RANK_URL, json={"data": json.dumps(rating)},
                  headers={"Content-Type": "application/json", "Authorization": f"Bearer {a['token']}"}, timeout=20)
    except Exception: pass
    return {"ok": True, "message": "KING RANK applied!"}

def c1_change_email(email, pw, new_email):
    a = c1_login(email, pw)
    if not a.get("ok"): return {"ok": False, "message": "Login failed: " + a.get("message", "?")}
    try:
        r = http.post(f"https://identitytoolkit.googleapis.com/v1/accounts:update?key={C1_API_KEY}",
                      json={"idToken": a["token"], "email": new_email, "returnSecureToken": True}, timeout=20)
        j = r.json()
        if j.get("email"): return {"ok": True, "message": f"Email changed to {new_email}"}
        return {"ok": False, "message": str(j.get("error", {}).get("message", "failed"))[:90]}
    except Exception as e:
        return {"ok": False, "message": str(e)[:90]}

def c1_change_password(email, pw, new_pw):
    a = c1_login(email, pw)
    if not a.get("ok"): return {"ok": False, "message": "Login failed: " + a.get("message", "?")}
    if len(new_pw) < 6: return {"ok": False, "message": "Password min 6 chars"}
    try:
        r = http.post(f"https://identitytoolkit.googleapis.com/v1/accounts:update?key={C1_API_KEY}",
                      json={"idToken": a["token"], "password": new_pw, "returnSecureToken": True}, timeout=20)
        j = r.json()
        if j.get("idToken"): return {"ok": True, "message": "Password changed successfully"}
        return {"ok": False, "message": str(j.get("error", {}).get("message", "failed"))[:90]}
    except Exception as e:
        return {"ok": False, "message": str(e)[:90]}

def c2_full_unlock_pack(email, pw):
    a = c2_login(email, pw)
    if not a.get("ok"): return {"ok": False, "message": "Login failed: " + a.get("message", "?")}
    try: c2_start_session(a["token"])
    except Exception: pass
    ok = _write_full_unlock(a["token"], a["uid"])
    return {"ok": ok, "message": "FULL UNLOCK applied (wheels, male, female, brakes, calipers, paints, flags, apartments, animation, kits, slots)!" if ok else "Unlock write rejected"}

def _write_full_unlock(token, uid, name=None):
    entries = {0: mp_str(name or ""), 1: mp_str("PREMIUM"), 2: mp_int_array(list(range(225))), 3: mp_i32(255),
               4: mp_i64(127), 5: mp_i64(127), 6: mp_i32(0)}
    for k in range(19, 30): entries[k] = mp_int_array(list(range(15)))
    entries[30] = mp_int_array(list(range(50)))
    for k in range(31, 42): entries[k] = mp_int_array(list(range(15)))
    entries[42] = mp_int_array(list(range(50)))
    entries[43] = mp_dict_ii({i: 1 for i in range(78)})
    entries[44] = mp_i64((1 << 50) - 1)
    entries[45] = mp_int_array([1,2,3,4,5,6,7,8])
    entries[46] = mp_i64_array([-1, 16777215])
    entries[47] = mp_int_array([1]*110)
    entries[48] = mp_i64(15)
    entries[49] = mp_int_array([6,-1,0,0,0,999999999,0,1,0,0,0])
    entries[50] = mp_int_array([1]*13)
    entries[51] = mp_int_array([0,0,0,0,0])
    entries[52] = mp_dict_is({i: "0#1#2#3#4#5#6" for i in range(5)})
    entries[53] = mp_int_array(list(range(10)))
    full = mp_i32(len(entries))
    for k in sorted(entries.keys()):
        v = entries[k]
        full += mp_u16(k) + mp_i32(len(v)) + v
    ok = False
    for ep in ("SavePlayerRecords23_1", "SavePlayerRecords24_1", "SavePlayerRecords22_1"):
        r = cf(ep, mp_encode(full, uid), token)
        if isinstance(r, dict) and r.get("code") == 1: ok = True; break
        time.sleep(0.4)
    return ok

def c2_set_money_amount(email, pw, amount):
    a = c2_login(email, pw)
    if not a.get("ok"): return {"ok": False, "message": "Login failed: " + a.get("message", "?")}
    try: c2_start_session(a["token"])
    except Exception: pass
    crypto = Crypto(a["uid"])
    cf("SaveAppVersionOnAccountCreated22_1", crypto.encrypt(json.dumps({"version": C2_VERSION})), a["token"])
    time.sleep(0.3)
    cf("SavePlayerRecords22_1", crypto.encrypt("{}"), a["token"])
    time.sleep(0.3)
    try: amount = int(amount)
    except Exception: return {"ok": False, "message": "Invalid amount"}
    if amount < 0 or amount > 999_999_999: return {"ok": False, "message": "Amount 0 - 999,999,999"}
    wallet = mp_encode(mp_i32(1) + mp_u16(0) + mp_i32(8) + mp_i64(amount), a["uid"])
    ok = False
    for ep in ("SaveWalletData23_1", "SaveWalletData24_1"):
        r = cf(ep, wallet, a["token"])
        if isinstance(r, dict) and r.get("code") == 1: ok = True; break
        time.sleep(0.4)
    return {"ok": ok, "message": f"Money set to {amount:,}!" if ok else "Wallet write rejected"}

def c2_change_name(email, pw, new_name):
    a = c2_login(email, pw)
    if not a.get("ok"): return {"ok": False, "message": "Login failed: " + a.get("message", "?")}
    try: c2_start_session(a["token"])
    except Exception: pass
    ok = _write_full_unlock(a["token"], a["uid"], name=str(new_name)[:24])
    return {"ok": ok, "message": f"Name set to '{new_name}' (with full unlock refresh)" if ok else "Name write rejected"}

def c2_max_race(email, pw):
    a = c2_login(email, pw)
    if not a.get("ok"): return {"ok": False, "message": "Login failed: " + a.get("message", "?")}
    try: c2_start_session(a["token"])
    except Exception: pass
    crypto = Crypto(a["uid"])
    rating = dict(KING_RATING)
    r1 = cf("SetUserRating22_1", crypto.encrypt(json.dumps({"general": rating, "race_win": 5000, "level": 120, "score": 999.0})), a["token"])
    ok = isinstance(r1, dict) and r1.get("code") == 1
    return {"ok": ok, "message": "MAX RACE WINS applied!" if ok else "Write failed"}

def c2_daily_reward(email, pw):
    a = c2_login(email, pw)
    if not a.get("ok"): return {"ok": False, "message": "Login failed: " + a.get("message", "?")}
    try: c2_start_session(a["token"])
    except Exception: pass
    crypto = Crypto(a["uid"])
    ok = False
    for ep in ("GetRewards23_1", "GetRewards22_1"):
        r = cf(ep, crypto.encrypt(""), a["token"])
        if isinstance(r, dict) and r.get("code") == 1: ok = True; break
        time.sleep(0.3)
    return {"ok": ok, "message": "Daily reward claimed!" if ok else "No reward available (already claimed or endpoint moved)"}



# ===== CPM1 engine imported from DARK (Mini App / Flask / membership excluded) =====
#!/usr/bin/env python3
"""DARK CPM - Mini App (ALL-IN-ONE: bot + cpm1_core + cpm1_clone + siren + plates)."""


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

SOURCE_ACCOUNT = (os.environ.get("CPM1_SOURCE_EMAIL", "").strip(), os.environ.get("CPM1_SOURCE_PASSWORD", ""))

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
    result = nuker._modify(uid, {"platesData": final}, force_fields={"platesData"})
    if not result.get("ok"):
        return {"ok": False, "message": "Could not save plates: " + str(result.get("message", "unknown error"))}
    return {"ok": True, "message": "Plates injected: %d" % len(final.get("allPlates") or [])}


# ══════════ ILIJA COMBINED BOT UI ══════════
SESSIONS = {}
def S(uid): return SESSIONS.setdefault(uid, {})

def _cpm1_uid(uid, email):
    return int(hashlib.sha256((str(uid) + ':' + email.lower()).encode('utf-8')).hexdigest()[:12], 16) % (10**9)

def kb_game():
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(types.InlineKeyboardButton("🚘 CPM1", callback_data="g_cpm1"),
          types.InlineKeyboardButton("🚔 CPM2", callback_data="g_cpm2"))
    m.add(types.InlineKeyboardButton("🆕 Create CPM2 account", callback_data="create_c2"))
    return m

def kb_menu(game):
    m = types.InlineKeyboardMarkup(row_width=2)
    if game == "cpm1":
        rows = [
            ("👑 KING RANK", "rank"), ("📊 Account info", "info"),
            ("💰 Max money", "money_max"), ("🪙 Max coins", "coin_max"),
            ("💵 Set money", "money_custom"), ("🪙 Set coins", "coin_custom"),
            ("⚡ Unlock W16", "w16"), ("💨 Unlock smoke", "smoke"),
            ("📯 Unlock horns", "horns"), ("⛽ Unlimited fuel", "fuel"),
            ("🛡️ No engine damage", "damage"), ("🎭 Animations", "animations"),
            ("🏠 Unlock houses", "houses"), ("🛞 Unlock wheels", "wheels"),
            ("🏁 Complete levels", "levels"), ("👕 All clothes", "clothes"),
            ("🔓 Unlock feature pack", "unlock_all"), ("🛠️ Fix account", "fix"),
            ("✏️ Change name", "name"), ("🆔 Custom ID", "id"),
            ("🚗 Unlock all cars", "cars_all"), ("🚘 Unlock one car", "car_one"),
            ("🚨 Siren all cars", "siren_all"), ("🚨 Siren one car", "siren_one"),
            ("🔢 Inject plates.json", "plates"), ("📋 Clone from source", "clone"),
            ("📦 Bulk clone (max 50)", "bulk_clone"),
            ("📧 Change email", "email"), ("🔐 Change password", "pass"),
        ]
    else:
        rows = [
            ("👑 KING RANK", "rank"), ("🏆 MAX WIN RACE", "race"),
            ("💰 Set money", "money_custom"), ("🔓 Unlock everything", "unlock"),
            ("✏️ Change name", "name"), ("🎁 Daily reward", "daily"),
            ("📧 Change email", "email"), ("🔐 Change password", "pass"),
        ]
    for label, act in rows:
        m.add(types.InlineKeyboardButton(label, callback_data="act_" + act))
    m.add(types.InlineKeyboardButton("🔄 Switch game", callback_data="switch"))
    return m

@bot.message_handler(commands=['start'])
def cmd_start(m):
    SESSIONS.pop(m.from_user.id, None)
    bot.send_message(m.chat.id,
        "⚡ <b>ILIJA CPM TOOLS</b> ⚡\n━━━━━━━━━━━━━━\nCPM1 + CPM2 tools\n\nChoose your game:",
        reply_markup=kb_game(), parse_mode="HTML")

@bot.callback_query_handler(func=lambda c: c.data in ("g_cpm1", "g_cpm2", "switch"))
def cb_game(c):
    uid=c.from_user.id
    if c.data == "g_cpm1": game="cpm1"
    elif c.data == "g_cpm2": game="cpm2"
    else: game="cpm2" if S(uid).get("game") == "cpm1" else "cpm1"
    S(uid)["game"]=game
    S(uid)["state"]="email"
    bot.answer_callback_query(c.id)
    bot.edit_message_text(f"🎮 <b>{game.upper()}</b> selected.\n\nSend your account EMAIL:", c.message.chat.id, c.message.message_id, parse_mode="HTML")

@bot.callback_query_handler(func=lambda c: c.data == "create_c2")
def cb_create_c2(c):
    bot.answer_callback_query(c.id)
    if c.from_user.id != OWNER_ID:
        bot.send_message(c.message.chat.id, "❌ Account creation is owner-only.")
        return
    S(c.from_user.id)["state"]="create_count"
    bot.send_message(c.message.chat.id, "How many CPM2 accounts? Enter 1–50.")

@bot.message_handler(func=lambda m: S(m.from_user.id).get("state") == "create_count")
def on_create_count(m):
    st=S(m.from_user.id); st["state"]=None
    if m.from_user.id != OWNER_ID:
        bot.reply_to(m, "Access denied."); return
    try: count=int((m.text or "").strip())
    except ValueError: bot.reply_to(m, "Enter a whole number from 1 to 50."); return
    if not 1 <= count <= 50:
        bot.reply_to(m, "Enter a number from 1 to 50."); return
    status=bot.send_message(m.chat.id, f"⏳ Creating {count} CPM2 account(s)…")
    def work():
        made=[]; failed=0
        for _ in range(count):
            email=gen_email(); password=gen_password()
            try:
                rr=http.post(C2_FB_SIGNUP, json={"email":email,"password":password,"returnSecureToken":True}, timeout=20, verify=False)
                data=rr.json()
                if not data.get("idToken"):
                    failed += 1; time.sleep(1); continue
                token=data["idToken"]; game_uid=data["localId"]
                try: c2_start_session(token)
                except Exception: pass
                wallet_ok=c2_charge_wallet(token, game_uid, email, password)
                rank=c2_king_rank(email,password)
                made.append({"email":email,"password":password,"money":bool(wallet_ok),"rank":bool(rank.get("ok"))})
            except Exception:
                failed += 1
            time.sleep(1)
        if not made:
            out="❌ No accounts created. Failed: %d" % failed
        else:
            out="✅ <b>CPM2 accounts created: %d</b>\nFailed: %d\n\n" % (len(made),failed)
            out += "\n\n".join("📧 <code>%s</code>\n🔑 <code>%s</code>\nStatus: %s" % (a['email'],a['password'], 'Rank + wallet' if a['rank'] and a['money'] else ('Wallet' if a['money'] else 'Created')) for a in made)
        try: bot.edit_message_text(out[:3900], m.chat.id, status.message_id, parse_mode="HTML")
        except Exception: bot.send_message(m.chat.id, out[:3900], parse_mode="HTML")
    threading.Thread(target=work, daemon=True).start()

INPUT_STATES=("email","pass","new_email","new_pass","new_money","new_coin","new_name","new_id","car_id","siren_car_id","bulk_count")
@bot.message_handler(func=lambda m: S(m.from_user.id).get("state") in INPUT_STATES)
def on_input(m):
    uid=m.from_user.id; st=S(uid); txt=(m.text or "").strip()
    try: bot.delete_message(m.chat.id,m.message_id)
    except Exception: pass
    state=st.get("state")
    if state=="email":
        if "@" not in txt: bot.send_message(m.chat.id,"❌ Enter a valid email."); return
        st["email"]=txt; st["state"]="pass"; bot.send_message(m.chat.id,"🔑 Send your PASSWORD:"); return
    if state=="pass":
        st["password"]=txt; st["state"]=None; game=st.get("game")
        if game=="cpm1":
            lr=nuker.login(st["email"],txt)
            if lr.get("ok"):
                st["cpm1_uid"]=_cpm1_uid(uid,st["email"])
                nuker.save_token(st["cpm1_uid"],lr["auth"],st["email"],txt,lr.get("refresh_token",""),lr.get("firebase_uid",""))
        else: lr=c2_login(st["email"],txt)
        if not lr.get("ok"):
            bot.send_message(m.chat.id,"❌ <b>LOGIN FAILED</b>\n%s\n\nUse /start to retry." % (lr.get("message","Unknown error")),parse_mode="HTML")
            SESSIONS.pop(uid,None); return
        bot.send_message(m.chat.id,"✅ <b>LOGGED IN — %s</b>\n📧 <code>%s</code>\n\nChoose an action:"%(game.upper(),st["email"]),reply_markup=kb_menu(game),parse_mode="HTML"); return
    if state=="new_email": st["state"]=None; run_action(uid,m.chat.id,"email",txt); return
    if state=="new_pass": st["state"]=None; run_action(uid,m.chat.id,"pass",txt); return
    if state=="new_money": st["state"]=None; run_action(uid,m.chat.id,"money_custom",txt); return
    if state=="new_coin": st["state"]=None; run_action(uid,m.chat.id,"coin_custom",txt); return
    if state=="new_name": st["state"]=None; run_action(uid,m.chat.id,"name",txt); return
    if state=="new_id": st["state"]=None; run_action(uid,m.chat.id,"id",txt); return
    if state=="car_id": st["state"]=None; run_action(uid,m.chat.id,"car_one",txt); return
    if state=="siren_car_id": st["state"]=None; run_action(uid,m.chat.id,"siren_one",txt); return
    if state=="bulk_count": st["state"]=None; run_action(uid,m.chat.id,"bulk_clone",txt); return

@bot.callback_query_handler(func=lambda c: c.data.startswith("act_"))
def cb_act(c):
    uid=c.from_user.id; st=S(uid); act=c.data.replace("act_","",1)
    bot.answer_callback_query(c.id)
    if not st.get("email") or not st.get("password"):
        bot.send_message(c.message.chat.id,"Session expired — /start again."); return
    asks={"email":("new_email","📧 Send NEW EMAIL:"),"pass":("new_pass","🔐 Send NEW PASSWORD (min 6 chars):"),
          "money_custom":("new_money","💰 Send amount (CPM1 max 50,000,000; CPM2 max 999,999,999):"),"coin_custom":("new_coin","🪙 Send amount (max 500,000):"),
          "name":("new_name","✏️ Send NEW NAME:"),"id":("new_id","🆔 Send NEW ID:"),
          "car_one":("car_id","🚘 Send CAR ID (number):"),"siren_one":("siren_car_id","🚨 Send CAR ID for siren (number):"),"bulk_clone":("bulk_count","📦 How many clone accounts? Enter 1–50:")}
    if act in asks:
        st["state"]=asks[act][0]; bot.send_message(c.message.chat.id,asks[act][1]); return
    run_action(uid,c.message.chat.id,act,None)

def run_action(uid,chat_id,act,newval):
    st=S(uid); game=st.get("game"); em=st.get("email",""); pw=st.get("password","")
    msg=bot.send_message(chat_id,"⏳ <b>Working…</b>",parse_mode="HTML")
    def work():
        try:
            if game=="cpm2":
                if act=="rank": r=c2_king_rank(em,pw)
                elif act=="race": r=c2_max_race(em,pw)
                elif act=="money": r=c2_money(em,pw)
                elif act=="money_custom": r=c2_set_money_amount(em,pw,newval)
                elif act=="unlock": r=c2_full_unlock_pack(em,pw)
                elif act=="name": r=c2_change_name(em,pw,newval)
                elif act=="daily": r=c2_daily_reward(em,pw)
                elif act=="email": r=c2_change_email(em,pw,newval)
                elif act=="pass": r=c2_change_password(em,pw,newval)
                else: r={"ok":False,"message":"Unknown CPM2 action"}
            else:
                kid=st.get("cpm1_uid") or _cpm1_uid(uid,em)
                mapping={
                    "rank":lambda:nuker.set_rank(kid), "info":lambda:nuker.get_account_info(kid,force_refresh=True),
                    "money_max":lambda:nuker.set_money(kid,MAX_MONEY), "coin_max":lambda:nuker.set_coin(kid,MAX_COIN),
                    "money_custom":lambda:nuker.set_money(kid,int(newval)), "coin_custom":lambda:nuker.set_coin(kid,int(newval)),
                    "w16":lambda:nuker.unlock_w16(kid), "smoke":lambda:nuker.unlock_smoke(kid),
                    "horns":lambda:nuker.unlock_horns(kid), "fuel":lambda:nuker.unlimited_fuel(kid),
                    "damage":lambda:nuker.disable_damage(kid), "animations":lambda:nuker.unlock_animations(kid),
                    "houses":lambda:nuker.unlock_houses(kid), "wheels":lambda:nuker.unlock_wheels(kid),
                    "levels":lambda:nuker.complete_all_levels(kid), "clothes":lambda:nuker.unlock_all_clothes(kid),
                    "unlock_all":lambda:nuker.unlock_all_features(kid), "fix":lambda:nuker.fix_account(kid),
                    "name":lambda:nuker.change_player_name(kid,str(newval or "")[:24]),
                    "id":lambda:nuker.change_player_id(kid,str(newval or "")),
                    "cars_all":lambda:unlock_all_cars(em,pw), "car_one":lambda:unlock_one_car(em,pw,int(newval)),
                    "siren_all":lambda:unlock_siren(em,pw), "siren_one":lambda:unlock_siren(em,pw,int(newval)),
                    "plates":lambda:inject_plates(em,pw,merge=True),
                    "clone":lambda:web_clone_account(SOURCE_ACCOUNT[0],SOURCE_ACCOUNT[1],em,pw),
                    "bulk_clone":lambda:web_bulk_clone(SOURCE_ACCOUNT[0],SOURCE_ACCOUNT[1],int(newval)),
                    "email":lambda:c1_change_email(em,pw,str(newval)), "pass":lambda:c1_change_password(em,pw,str(newval)),
                }
                if act in ("money_custom","coin_custom"):
                    val=int(newval)
                    lim=MAX_MONEY if act=="money_custom" else MAX_COIN
                    if val<0 or val>lim: r={"ok":False,"message":f"Amount must be 0–{lim:,}"}
                    else: r=mapping[act]()
                elif act in ("cars_all","car_one","siren_all","siren_one","plates","clone","bulk_clone") and (not SOURCE_ACCOUNT[0] or not SOURCE_ACCOUNT[1]):
                    r={"ok":False,"message":"Set CPM1_SOURCE_EMAIL and CPM1_SOURCE_PASSWORD environment variables first."}
                else: r=mapping[act]() if act in mapping else {"ok":False,"message":"Unknown CPM1 action"}
                if act=="info" and r.get("ok"):
                    r={"ok":True,"message":"Name: %s | Money: %s | Coins: %s | ID: %s | Cars: %s"%(r.get("name"),r.get("money"),r.get("coin"),r.get("localID"),r.get("cars"))}
                if act=="bulk_clone" and r.get("ok"):
                    accs=r.get("accounts") or []
                    try:
                        with open(f"fantom_clone_accounts_{uid}.txt","w",encoding="utf-8") as f: f.write("\n".join(accs))
                        with open(f"fantom_clone_accounts_{uid}.txt","rb") as f: bot.send_document(chat_id,f,caption=r.get("message","Clone accounts"))
                    except Exception: pass
                    r={"ok":True,"message":r.get("message","Done")+" (credentials sent as a file if Telegram upload succeeded)."}
            if not isinstance(r,dict): r={"ok":bool(r),"message":str(r)}
        except Exception as e: r={"ok":False,"message":str(e)[:180]}
        icon="✅" if r.get("ok") else "❌"
        out=f"{icon} <b>{r.get('message','Done')}</b>"
        try: bot.edit_message_text(out[:3900],chat_id,msg.message_id,reply_markup=kb_menu(game),parse_mode="HTML")
        except Exception: pass
    threading.Thread(target=work,daemon=True).start()

if __name__ == "__main__":
    print("⚡ ILIJA CPM TOOLS — combined CPM1 + CPM2 starting…")
    if not BOT_TOKEN: raise SystemExit("Set BOT_TOKEN environment variable to your NEW BotFather token first")
    while True:
        try: bot.infinity_polling(timeout=60,long_polling_timeout=60,skip_pending=True)
        except Exception as e:
            print("poll error:",e); time.sleep(3)
