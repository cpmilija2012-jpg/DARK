import uuid, re, struct, base64, zlib
# Clone helpers extracted from MARKCPM1TOOLS
from cpm1_core import *
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
        if progress_cb: progress_cb(i, "done")
        return t_email, t_pass

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
        email, pw = clone_task(rec, cars, i, [], src["login"]["auth"], src["login"].get("firebase_uid"))
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
    return {"ok": True, "message": "Created %d full-clone accounts" % len(accounts), "accounts": accounts}


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
