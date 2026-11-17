#!/usr/bin/env python3
import csv, json, os, time
from http.server import BaseHTTPRequestHandler, HTTPServer

ENV_PATH  = os.path.expanduser("~/policy_envelope.json")
RAN_CSV   = os.path.expanduser("~/ran_log.csv")
AUDIT_LOG = os.path.expanduser("~/era_audit.log")
LISTEN    = ("0.0.0.0", 8080)
NO_RIC    = os.environ.get("ERA_NO_RIC", "0") == "1"

# Final experiment policy mode.
#
# dual         : RAN-adaptive KEM + battery-adaptive signature
# battery_only : fixed ML-KEM-1024 + battery-adaptive signature
# ran_only     : RAN-adaptive KEM + fixed ML-DSA-44
ERA_MODE = os.environ.get("ERA_MODE", "").strip().lower()

# Backward compatibility:
# ERA_NO_RIC=1 means battery-only operation.
if NO_RIC:
    ERA_MODE = "battery_only"
elif not ERA_MODE:
    ERA_MODE = "dual"

if ERA_MODE not in {"dual", "battery_only", "ran_only"}:
    raise RuntimeError(f"invalid ERA_MODE={ERA_MODE}")

# index 0 = classical rung (never allowed); higher = stronger
KEM_LADDER = ["X25519", "mlkem768", "mlkem1024"]
SIG_LADDER = ["ecdsa",  "falcon512", "mldsa44"]
KEM_IDX = {g: i for i, g in enumerate(KEM_LADDER)}
SIG_IDX = {g: i for i, g in enumerate(SIG_LADDER)}
THP_HI, BATT_LO = 322.4, 30.0
_server_batt   = {"pct": 100.0, "t": 0.0}
_last_good_ran = {"lvl": 2, "t": 0.0}

def log(m): print(f"[decision] {m}", flush=True)

def load_envelope(tc):
    with open(ENV_PATH) as f: env = json.load(f)
    return env.get(tc, env["default"])

def battery_context(pct): return 1 if pct < BATT_LO else 2

GNB1_NODE = "gnbd_001_001_00019b_0"
GNB2_NODE = "gnbd_001_001_00019c_0"
_ran_snapshot = {}

def read_ran_context():
    global _ran_snapshot

    if ERA_MODE == "battery_only":
        _ran_snapshot = {
            "mode": "battery_only",
            "ran_used": False
        }
        return 2, True

    try:
        with open(RAN_CSV) as f:
            rows = list(csv.DictReader(f))

        # Keep newest telemetry row from each gNB.
        latest = {}

        for row in rows:
            node = row.get("node", "")
            if node not in (GNB1_NODE, GNB2_NODE):
                continue

            try:
                ts = float(row["ts_epoch"])
            except Exception:
                continue

            if node not in latest or ts > float(latest[node]["ts_epoch"]):
                latest[node] = row

        # Both radio legs are required for a path-aware decision.
        if GNB1_NODE not in latest or GNB2_NODE not in latest:
            _ran_snapshot = {
                "reason": "missing_gnb",
                "nodes_seen": list(latest.keys())
            }

            if time.time() - _last_good_ran["t"] <= 180:
                return _last_good_ran["lvl"], True

            return 2, False

        now = time.time()

        age1 = now - float(latest[GNB1_NODE]["ts_epoch"])
        age2 = now - float(latest[GNB2_NODE]["ts_epoch"])

        # ---------------------------------------------------------
        # Dual-gNB directional RAN telemetry
        #
        # Topology:
        #   UE2(client) -- gNB1 -- core -- gNB2 -- UE1(server)
        #
        # UE2 -> UE1 uses:
        #   gNB1 UL + gNB2 DL
        #
        # UE1 -> UE2 uses:
        #   gNB2 UL + gNB1 DL
        #
        # DRB.UEThp* represents carried throughput/activity.
        # We collect all four values now and calibrate the final
        # ERA-Crypto RAN decision rule from measured data.
        # ---------------------------------------------------------

        def metric(row, name):
            try:
                return float(str(row.get(name, "0")).strip("[] "))
            except Exception:
                return 0.0

        dl1 = metric(latest[GNB1_NODE], "DRB.UEThpDl")
        ul1 = metric(latest[GNB1_NODE], "DRB.UEThpUl")

        dl2 = metric(latest[GNB2_NODE], "DRB.UEThpDl")
        ul2 = metric(latest[GNB2_NODE], "DRB.UEThpUl")

        # Directional end-to-end carried-throughput indicators.
        # The slower radio leg bounds each direction.
        forward_thp = min(ul1, dl2)   # UE2 -> UE1
        reverse_thp = min(ul2, dl1)   # UE1 -> UE2

        # Activity observed on either end-to-end direction.
        path_activity = max(forward_thp, reverse_thp)

        # ---------------------------------------------------------
        # Final calibrated RAN decision signal.
        #
        # Metric:
        #   median(last 3 paired path_activity KPM observations)
        #
        # Calibration threshold:
        #   322.4
        #
        # Pairing rule matches calibration:
        #   nearest gNB1/gNB2 samples with <= 5 s timestamp skew.
        # ---------------------------------------------------------

        g1_recent = [
            r for r in rows
            if r.get("node", "") == GNB1_NODE
        ][-12:]

        g2_recent = [
            r for r in rows
            if r.get("node", "") == GNB2_NODE
        ][-12:]

        paired = []

        for a in reversed(g1_recent):
            try:
                ta = float(a["ts_epoch"])
            except Exception:
                continue

            candidates = []

            for b in g2_recent:
                try:
                    tb = float(b["ts_epoch"])
                except Exception:
                    continue

                candidates.append((abs(ta - tb), tb, b))

            if not candidates:
                continue

            skew, tb, b = min(candidates, key=lambda x: x[0])

            if skew > 5.0:
                continue

            a_dl = metric(a, "DRB.UEThpDl")
            a_ul = metric(a, "DRB.UEThpUl")
            b_dl = metric(b, "DRB.UEThpDl")
            b_ul = metric(b, "DRB.UEThpUl")

            f = min(a_ul, b_dl)
            r = min(b_ul, a_dl)
            activity = max(f, r)

            paired.append((ta, tb, activity))

            if len(paired) == 3:
                break

        paired.reverse()

        hist = [x[2] for x in paired]
        filter_ready = len(hist) == 3

        if filter_ready:
            decision_value = sorted(hist)[1]

            ts1 = paired[-1][0]
            ts2 = paired[-1][1]

            pair_age_s = max(
                now - ts1,
                now - ts2
            )

            pair_skew_s = abs(ts1 - ts2)

        else:
            decision_value = 0.0

            ts1 = float(latest[GNB1_NODE]["ts_epoch"])
            ts2 = float(latest[GNB2_NODE]["ts_epoch"])

            pair_age_s = max(
                now - ts1,
                now - ts2
            )

            pair_skew_s = abs(ts1 - ts2)

        # High path activity -> lower-cost allowed KEM rung.
        # Low/idle activity -> higher-cost allowed KEM rung.
        lvl = (
            1
            if (
                filter_ready
                and pair_age_s <= 90
                and decision_value >= THP_HI
            )
            else 2
        )

        _ran_snapshot = {
            "gnb1_dl": dl1,
            "gnb1_ul": ul1,
            "gnb2_dl": dl2,
            "gnb2_ul": ul2,

            "forward_thp": forward_thp,
            "reverse_thp": reverse_thp,
            "path_activity": path_activity,

            "decision_metric": "median3_path_activity",
            "decision_value": decision_value,
            "threshold": THP_HI,
            "filter_ready": filter_ready,
            "filter_samples": list(hist),
            "kpm_pair_ts": [ts1, ts2],
            "kpm_pair_skew_s": round(pair_skew_s, 3),
            "kpm_pair_age_s": round(pair_age_s, 3),

            "gnb1_age_s": round(age1, 3),
            "gnb2_age_s": round(age2, 3)
        }

        if max(age1, age2) <= 90:
            _last_good_ran.update(lvl=lvl, t=now)
            return lvl, True

        if now - _last_good_ran["t"] <= 180:
            _ran_snapshot["fallback"] = "last_good"
            return _last_good_ran["lvl"], True

        return 2, False

    except Exception as ex:
        _ran_snapshot = {"reason": "exception", "error": str(ex)}

        if time.time() - _last_good_ran["t"] <= 180:
            return _last_good_ran["lvl"], True

        return 2, False

def pick(ladder, idx, allowed, floor, desired):
    ai = sorted(idx[g] for g in allowed)
    cand = [i for i in ai if i <= desired]
    ch = ladder[cand[-1] if cand else ai[0]]
    if idx[ch] < idx[floor]: ch = floor
    return ch

def enforce(choice, allowed, floor, idx, tel_ok):
    if not tel_ok and not NO_RIC:
        return sorted(allowed, key=lambda g: idx[g])[-1], "telemetry-missing:conservative"
    if choice not in allowed:
        return sorted(allowed, key=lambda g: idx[g])[-1], f"reject({choice}):outside-envelope"
    if idx[choice] < idx[floor]:
        return floor, f"raise({choice}->{floor}):below-floor"
    return choice, "accepted"

def audit(rec):
    with open(AUDIT_LOG, "a") as f: f.write(json.dumps(rec) + "\n")

class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        try: req = json.loads(self.rfile.read(n) or b"{}")
        except Exception: req = {}
        if self.path.endswith("/server_battery"):
            _server_batt.update(pct=float(req.get("battery_pct", 100)), t=time.time())
            self.send_response(200); self.end_headers(); self.wfile.write(b"{}"); return
        env = load_envelope(req.get("traffic_class", "default"))
        ran_lvl, ran_ok = read_ran_context()
        cbatt = float(req.get("battery_pct", 100)); cb = battery_context(cbatt)
        sb_pct = _server_batt["pct"] if time.time() - _server_batt["t"] < 30 else 100.0
        sb = battery_context(sb_pct)
        # Raw endpoint-battery policy state.
        battery_energy_lvl = min(cb, sb)

        # ran_only ignores battery for signature selection and
        # therefore fixes the desired signature at the high rung.
        energy_lvl = (
            2
            if ERA_MODE == "ran_only"
            else battery_energy_lvl
        )

        sig_reco = (
            req.get("force_sig")
            or pick(
                SIG_LADDER,
                SIG_IDX,
                env["sig_allowed"],
                env["sig_floor"],
                energy_lvl
            )
        )

        sig, sig_res = enforce(
            sig_reco,
            env["sig_allowed"],
            env["sig_floor"],
            SIG_IDX,
            True
        )

        # battery_only ignores RAN for KEM selection and fixes the
        # desired KEM at ML-KEM-1024. Other modes use the RAN level.
        kem_desired_lvl = (
            2
            if ERA_MODE == "battery_only"
            else (ran_lvl if ran_ok else 2)
        )

        kem_reco = (
            req.get("force_group")
            or pick(
                KEM_LADDER,
                KEM_IDX,
                env["kem_allowed"],
                env["kem_floor"],
                kem_desired_lvl
            )
        )

        kem, kem_res = enforce(
            kem_reco,
            env["kem_allowed"],
            env["kem_floor"],
            KEM_IDX,
            ran_ok
        )

        binder = (
            "fixed_high"
            if ERA_MODE == "ran_only"
            else ("server_batt" if sb < cb else "client_batt")
        )

        kem_source = (
            "fixed_high"
            if ERA_MODE == "battery_only"
            else "ran_context"
        )
        rec = {"ts_epoch": time.time(), "t": time.strftime("%H:%M:%S"),
               "ue": req.get("ue"), "client_batt": cbatt,
               "server_batt": round(sb_pct, 1),
               "policy_mode": ERA_MODE,
               "ran_lvl": ran_lvl,
               "ran_context": dict(_ran_snapshot),
               "battery_energy_lvl": battery_energy_lvl,
               "energy_lvl": energy_lvl,
               "kem": kem,
               "sig": sig,
               "kem_result": kem_res,
               "sig_result": sig_res,
               "kem_bound_by": kem_source,
               "sig_bound_by": binder}
        audit(rec)
        note = "" if (kem_res == "accepted" and sig_res == "accepted") else "   <-- NOTE"
        log(f"mode={ERA_MODE} ue={rec['ue']} cb={cbatt}% sb={round(sb_pct,1)}% ran={ran_lvl} "
            f"-> KEM={kem}[{kem_res}] SIG={sig}[{sig_res}] "
            f"(kem={kem_source}, sig={binder}){note}")
        body = json.dumps({"kem": kem, "sig": sig, "kem_reason": kem_res, "sig_reason": sig_res}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass

if __name__ == "__main__":
    try:
        e = load_envelope("default")
        for k in ("kem_allowed", "kem_floor", "sig_allowed", "sig_floor"):
            assert k in e, f"missing '{k}' in envelope"
        for g in e["kem_allowed"]: assert g in KEM_IDX, f"KEM '{g}' not in ladder"
        for g in e["sig_allowed"]: assert g in SIG_IDX, f"SIG '{g}' not in ladder"
        log(f"[PASS] envelope OK: KEM {e['kem_allowed']} floor {e['kem_floor']} | SIG {e['sig_allowed']} floor {e['sig_floor']}")
    except Exception as ex:
        log(f"[FAIL] envelope error: {ex} — fix {ENV_PATH}"); raise
    log(f"[PASS] listening on {LISTEN[0]}:{LISTEN[1]}  ERA_MODE={ERA_MODE} NO_RIC={NO_RIC}")
    HTTPServer(LISTEN, H).serve_forever()
