#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════╗
║   ⚡ FANTOM CPM TOOLS - TELEGRAM BOT ⚡               ║
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
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8682873022:AAFxpLAfUFZSX6GMC7ZCmVjZb7d7CBhl0Ts")
OWNER_ID = int(os.environ.get("OWNER_ID", "8884756222") or 0)

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

# ══════════ BOT UI ══════════
SESSIONS = {}
def S(uid): return SESSIONS.setdefault(uid, {})

def kb_game():
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(types.InlineKeyboardButton("🚘 CPM1", callback_data="g_cpm1"),
          types.InlineKeyboardButton("🚔 CPM2", callback_data="g_cpm2"))
    return m

def kb_menu(game):
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(types.InlineKeyboardButton("👑 KING RANK", callback_data="act_rank"),
          types.InlineKeyboardButton("🏆 MAX WIN RACE", callback_data="act_race"))
    if game == "cpm2":
        m.add(types.InlineKeyboardButton("💰 SET MONEY", callback_data="act_money"),
              types.InlineKeyboardButton("🔓 UNLOCK EVERYTHING", callback_data="act_unlock"))
        m.add(types.InlineKeyboardButton("✏️ CHANGE NAME", callback_data="act_name"),
              types.InlineKeyboardButton("🎁 DAILY REWARD", callback_data="act_daily"))
    m.add(types.InlineKeyboardButton("📧 CHANGE EMAIL", callback_data="act_email"),
          types.InlineKeyboardButton("🔐 CHANGE PASSWORD", callback_data="act_pass"))
    m.add(types.InlineKeyboardButton("🔄 SWITCH GAME", callback_data="switch"))
    return m

@bot.message_handler(commands=['start'])
def cmd_start(m):
    uid = m.from_user.id
    SESSIONS.pop(uid, None)
    bot.send_message(m.chat.id,
        "⚡ <b>FANTOM CPM TOOLS</b> ⚡\n━━━━━━━━━━━━━━\n"
        "Car Parking Multiplayer 1 & 2\n\n"
        "Choose your game:", reply_markup=kb_game(), parse_mode="HTML")

@bot.callback_query_handler(func=lambda c: c.data in ("g_cpm1", "g_cpm2", "switch"))
def cb_game(c):
    uid = c.from_user.id
    S(uid)["game"] = "cpm1" if c.data in ("g_cpm1",) or (c.data == "switch" and S(uid).get("game") == "cpm2") else "cpm2"
    if c.data == "switch":
        S(uid)["game"] = "cpm2" if S(uid).get("game") == "cpm1" else "cpm1"
    game = S(uid)["game"].upper()
    bot.answer_callback_query(c.id)
    bot.edit_message_text(f"🎮 <b>{game}</b> selected.\n\nSend your account EMAIL:", c.message.chat.id, c.message.message_id, parse_mode="HTML")
    S(uid)["state"] = "email"

@bot.message_handler(func=lambda m: S(m.from_user.id).get("state") in ("email", "pass", "new_email", "new_pass", "new_money", "new_name"))
def on_input(m):
    uid = m.from_user.id
    st = S(uid)
    txt = (m.text or "").strip()
    try: bot.delete_message(m.chat.id, m.message_id)
    except Exception: pass
    if st.get("state") == "email":
        st["email"] = txt
        st["state"] = "pass"
        bot.send_message(m.chat.id, "🔑 Send your PASSWORD:")
        return
    if st.get("state") == "pass":
        st["password"] = txt
        st["state"] = None
        game = st["game"].upper()
        em = st["email"]
        lg = c1_login(em, txt) if st["game"] == "cpm1" else c2_login(em, txt)
        if not lg.get("ok"):
            bot.send_message(m.chat.id, f"❌ <b>LOGIN FAILED</b>\n{lg.get('message','?')}\n\nTry again: /start", parse_mode="HTML")
            SESSIONS.pop(uid, None)
            return
        bot.send_message(m.chat.id,
            f"✅ <b>LOGGED IN - {game}</b>\n📧 <code>{em}</code>\n\nChoose an action:",
            reply_markup=kb_menu(st["game"]), parse_mode="HTML")
        return
    if st.get("state") == "new_email":
        st["state"] = None
        run_action(uid, m.chat.id, "email", txt)
        return
    if st.get("state") == "new_pass":
        st["state"] = None
        run_action(uid, m.chat.id, "pass", txt)
        return
    if st.get("state") == "new_money":
        st["state"] = None
        run_action(uid, m.chat.id, "money", txt)
        return
    if st.get("state") == "new_name":
        st["state"] = None
        run_action(uid, m.chat.id, "name", txt)
        return

@bot.callback_query_handler(func=lambda c: c.data.startswith("act_"))
def cb_act(c):
    uid = c.from_user.id
    st = S(uid)
    act = c.data.replace("act_", "")
    bot.answer_callback_query(c.id)
    if not st.get("email"):
        bot.send_message(c.message.chat.id, "Session expired - /start again")
        return
    if act in ("email", "pass", "money", "name"):
        st["state"] = "new_" + act
        bot.send_message(c.message.chat.id,
            "📧 Send NEW EMAIL:" if act == "email" else
            "🔑 Send NEW PASSWORD (min 6):" if act == "pass" else
            "💰 Send AMOUNT (e.g. 50000000):" if act == "money" else
            "✏️ Send NEW NAME:")
        return
    run_action(uid, c.message.chat.id, act, None)

def run_action(uid, chat_id, act, newval):
    st = S(uid)
    game, em, pw = st["game"], st["email"], st["password"]
    msg = bot.send_message(chat_id, "⏳ <b>WORKING...</b>", parse_mode="HTML")
    def work():
        try:
            if game == "cpm1":
                if act == "rank": r = c1_king_rank(em, pw)
                elif act == "email": r = c1_change_email(em, pw, newval); r["newc"] = ("email", newval) if r.get("ok") else None
                elif act == "pass": r = c1_change_password(em, pw, newval); r["newc"] = ("password", newval) if r.get("ok") else None
                else: r = {"ok": False, "message": "Unknown"}
            else:
                if act == "rank": r = c2_king_rank(em, pw)
                elif act == "race": r = c2_max_race(em, pw)
                elif act == "money": r = c2_set_money_amount(em, pw, newval) if newval else {"ok": False, "message": "?"}
                elif act == "unlock": r = c2_full_unlock_pack(em, pw)
                elif act == "name": r = c2_change_name(em, pw, newval)
                elif act == "daily": r = c2_daily_reward(em, pw)
                elif act == "email": r = c2_change_email(em, pw, newval); r["newc"] = ("email", newval) if r.get("ok") else None
                elif act == "pass": r = c2_change_password(em, pw, newval); r["newc"] = ("password", newval) if r.get("ok") else None
                else: r = {"ok": False, "message": "Unknown"}
        except Exception as e:
            r = {"ok": False, "message": str(e)[:120]}
        if r.get("newc"):
            st[r["newc"][0]] = r["newc"][1]
        icon = "✅" if r.get("ok") else "❌"
        try:
            bot.edit_message_text(f"{icon} <b>{r.get('message','Done')}</b>", chat_id, msg.message_id,
                                  reply_markup=kb_menu(game), parse_mode="HTML")
        except Exception: pass
    threading.Thread(target=work, daemon=True).start()

if __name__ == "__main__":
    if "PASTE_YOUR" in BOT_TOKEN:
        print("!!! Edit BOT_TOKEN in the file (or set env BOT_TOKEN) !!!")
    print("⚡ FANTOM CPM TOOLS bot starting...")
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60, skip_pending=True)
        except Exception as e:
            print("poll:", e)
            time.sleep(3)
