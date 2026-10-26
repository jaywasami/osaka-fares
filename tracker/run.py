"""Daily run: query fares, store them, decide notifications, rebuild the web app data.

    python -m tracker.run                 # normal daily run
    python -m tracker.run --test-message  # also send a Telegram test message
    python -m tracker.run --fake          # random prices, for trying it out offline
"""

import argparse
import csv
import json
import os
import random
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import notify, sources

ROOT = Path(os.environ.get("TRACKER_ROOT", Path(__file__).resolve().parent.parent))
CONFIG = ROOT / "config.json"
DATA = ROOT / "data"
FLIGHTS_CSV = DATA / "flights.csv"
DAILY_CSV = DATA / "daily.csv"
STATE = DATA / "state.json"
SITE_JSON = ROOT / "docs" / "data.json"

TZ = ZoneInfo("Asia/Taipei")
FLIGHT_FIELDS = ["checked_on", "leg", "date", "airline", "depart", "arrive", "price", "lcc", "source"]
DAILY_FIELDS = ["checked_on", "depart_date", "return_date", "total", "out_price", "ret_price", "source"]
WEEKDAYS = "一二三四五六日"


def load_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def md(d: str) -> str:
    """2027-04-03 -> 4/3(六)"""
    x = date.fromisoformat(d)
    return f"{x.month}/{x.day}({WEEKDAYS[x.weekday()]})"


def money(n) -> str:
    return f"NT${int(n):,}"


def pages_url() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" not in repo:
        return ""
    owner, name = repo.split("/", 1)
    return f"https://{owner.lower()}.github.io/{name}/"


def with_link(text: str) -> str:
    url = pages_url()
    return f"{text}\n\n{url}" if url else text


def allowed(f: dict, cfg: dict) -> bool:
    return (not f["overnight"]
            and f["depart"] >= cfg["earliest_departure"]
            and f["arrive"] <= cfg["latest_arrival"])


def fake_source(origin, dest, d, adults, children):
    rnd = random.Random(f"{origin}{dest}{d}{date.today()}")
    flights = []
    for name, base, lcc in [("中華航空", 9800, False), ("長榮航空", 10200, False), ("星宇航空", 11000, False),
                            ("台灣虎航", 6200, True), ("樂桃航空", 5900, True), ("日本航空", 10800, False)]:
        h = rnd.randint(5, 20)
        flights.append({"airline": name, "depart": f"{h:02d}:{rnd.choice(['05', '30', '45'])}",
                        "arrive": f"{h + 3:02d}:{rnd.choice(['10', '40'])}", "overnight": False,
                        "price": int(base * (adults + children * 0.8) * rnd.uniform(0.8, 1.3)),
                        "lcc": lcc, "source": "fake"})
    return flights


class Fetcher:
    """Google Flights first; on failure fall back to Ignav within the same run."""

    def __init__(self, cfg: dict, state: dict, fake: bool):
        self.cfg, self.state, self.fake = cfg, state, fake
        self.used_ignav = False
        self.google_streak = 0  # legs in a row where Google failed every retry
        self.messages: list[str] = []
        self.errors: list[str] = []

    def ignav_allowed(self) -> bool:
        calls = self.state.get("ignav_calls", 0)
        if calls < self.cfg["ignav_free_quota"] or self.cfg["ignav_allow_paid"]:
            return True
        if not self.state.get("quota_exhausted_notified"):
            self.state["quota_exhausted_notified"] = True
            self.messages.append(
                f"⚠️ Ignav 免費額度 {self.cfg['ignav_free_quota']:,} 次已用完，備援已暫停（不會自動付費）。\n"
                "要繼續請決定是否付費（約每 1,000 次 US$2），把 config.json 的 ignav_allow_paid 改成 true。")
        return False

    def get(self, origin: str, dest: str, d: str) -> list[dict]:
        args = (origin, dest, d, self.cfg["adults"], self.cfg["children"])
        if self.fake:
            return fake_source(*args)
        # Google sometimes answers "no flights found" when throttling; retry before using the backup,
        # but stop retrying once it looks blocked outright so the run stays within the job time limit.
        for wait in (0, 10, 25) if self.google_streak < 3 else (0,):
            time.sleep(wait)
            try:
                res = sources.google_flights(*args)
                self.google_streak = 0
                return res
            except sources.SourceError as e:
                err = e
        self.google_streak += 1
        self.errors.append(f"{d} {origin}→{dest}: {err}")
        if not os.environ.get("IGNAV_API_KEY") or not self.ignav_allowed():
            return []
        try:
            res = sources.ignav(*args)
        except sources.SourceError as e:
            self.errors.append(f"{d} {origin}→{dest}: {e}")
            if not str(e).startswith("ignav: HTTP"):  # Ignav does not bill failed (4xx/5xx) requests
                self.state["ignav_calls"] = self.state.get("ignav_calls", 0) + 1
            return []
        self.state["ignav_calls"] = self.state.get("ignav_calls", 0) + 1
        self.used_ignav = True
        calls, cfg = self.state["ignav_calls"], self.cfg
        if calls >= cfg["ignav_warn_at"] and not self.state.get("quota_warned"):
            self.state["quota_warned"] = True
            self.messages.append(
                f"⚠️ Ignav 備援已用 {calls:,} / {cfg['ignav_free_quota']:,} 次免費額度，快用完了。\n"
                "用完後會自動暫停備援；要不要付費（約每 1,000 次 US$2）由你決定。")
        if calls > cfg["ignav_free_quota"] and not self.state.get("paid_notified"):
            self.state["paid_notified"] = True
            self.messages.append("⚠️ 已開始使用 Ignav 付費額度（你已同意 ignav_allow_paid）。")
        return res


def top3(flights: list[dict]) -> list[dict]:
    return sorted(flights, key=lambda f: f["price"])[:3]


def run(args) -> int:
    cfg = load_json(CONFIG, None)
    state = load_json(STATE, {})
    now = datetime.now(TZ)
    today = now.date().isoformat()
    messages: list[str] = []

    if args.test_message:
        ok = notify.send(with_link("✅ 測試訊息：台北—大阪機票追蹤已連上 Telegram。"))
        print("test message sent" if ok else "test message NOT sent")

    if args.ignav_check:
        # One real Ignav call so its response format can be checked in the Actions log.
        d = cfg["first_depart"]
        try:
            raw = sources.ignav_raw(cfg["origin"], cfg["destination"], d, cfg["adults"], cfg["children"])
            its = raw.get("itineraries", [])
            print(f"[ignav-check] {len(its)} itineraries; top-level keys: {sorted(raw)}")
            print("[ignav-check] first itinerary:", json.dumps(its[0] if its else None, ensure_ascii=False)[:1500])
            state["ignav_calls"] = state.get("ignav_calls", 0) + 1
            print("[ignav-check] parsed:", sources.parse_ignav(raw)[:3])
        except sources.SourceError as e:
            print("[ignav-check] failed:", e)
        save_json(STATE, state)
        return 0

    first, last = date.fromisoformat(cfg["first_depart"]), date.fromisoformat(cfg["last_depart"])
    departs = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    active = [d for d in departs if d > now.date()]  # tracked until the day before departure

    finished = not active
    if finished:
        print("All departure dates have passed; tracking is finished.")
    if not cfg["enabled"]:
        print("config.json enabled=false; skipping queries.")
    if finished or not cfg["enabled"]:
        build_site(cfg, state, now, finished=finished)
        save_json(STATE, state)
        github_output("finished", "true" if finished else "false")
        return 0

    fetch = Fetcher(cfg, state, args.fake)
    o, k = cfg["origin"], cfg["destination"]
    new_flights: list[dict] = []
    new_daily: list[dict] = []
    for i, d in enumerate(active):
        dep, ret = d.isoformat(), (d + timedelta(days=cfg["trip_days"])).isoformat()
        legs = {}
        for leg, (a, b, day) in {"out": (o, k, dep), "ret": (k, o, ret)}.items():
            if i or leg == "ret":
                time.sleep(0 if args.fake else cfg["query_delay_seconds"])
            ok = [f for f in fetch.get(a, b, day) if allowed(f, cfg)]
            legs[leg] = top3(ok)
            for f in legs[leg]:
                new_flights.append({"checked_on": today, "leg": leg, "date": day, **{
                    k2: f[k2] for k2 in ("airline", "depart", "arrive", "price", "source")},
                    "lcc": int(f["lcc"])})
        if legs["out"] and legs["ret"]:
            out_p, ret_p = legs["out"][0]["price"], legs["ret"][0]["price"]
            srcs = {legs["out"][0]["source"], legs["ret"][0]["source"]}
            new_daily.append({"checked_on": today, "depart_date": dep, "return_date": ret,
                              "total": out_p + ret_p, "out_price": out_p, "ret_price": ret_p,
                              "source": "+".join(sorted(srcs))})
        print(f"{dep}: out {len(legs['out'])} / ret {len(legs['ret'])} flights"
              + (f", total {new_daily[-1]['total']}" if new_daily and new_daily[-1]["depart_date"] == dep else ""))

    for e in fetch.errors:
        print("[source]", e)

    # A same-day re-run replaces only what it managed to fetch again.
    got_legs = {(r["leg"], r["date"]) for r in new_flights}
    got_days = {r["depart_date"] for r in new_daily}
    old_flights = [r for r in read_csv(FLIGHTS_CSV)
                   if r["checked_on"] != today or (r["leg"], r["date"]) not in got_legs]
    daily_rows = read_csv(DAILY_CSV)
    old_daily = [r for r in daily_rows if r["checked_on"] != today]  # history before today
    kept_today = [r for r in daily_rows if r["checked_on"] == today and r["depart_date"] not in got_days]
    write_csv(FLIGHTS_CSV, FLIGHT_FIELDS, old_flights + new_flights)
    write_csv(DAILY_CSV, DAILY_FIELDS, old_daily + kept_today + new_daily)

    holidays = set(cfg["holidays"])
    tag = lambda d: f"{md(d)}{'（連假）' if d in holidays else ''}"

    # 1. New lows: below every earlier price for that departure date by the threshold.
    prev_min: dict[str, int] = {}
    for r in old_daily:
        t = int(r["total"])
        prev_min[r["depart_date"]] = min(prev_min.get(r["depart_date"], t), t)
    lows = [r for r in new_daily if r["depart_date"] in prev_min
            and r["total"] <= prev_min[r["depart_date"]] * (1 - cfg["new_low_threshold"])]
    if lows:
        lines = [f"{tag(r['depart_date'])} {money(r['total'])}（先前最低 {money(prev_min[r['depart_date']])}）"
                 for r in sorted(lows, key=lambda r: r["total"])]
        messages.append("📉 新低價\n" + "\n".join(lines))

    # 2. Target price: alert again only when the price drops further.
    target = cfg.get("target_price")
    alerted = state.setdefault("target_alerts", {})
    if target:
        hits = [r for r in new_daily if r["total"] < target
                and r["total"] < alerted.get(r["depart_date"], float("inf"))]
        for r in hits:
            alerted[r["depart_date"]] = r["total"]
        if hits:
            messages.append(f"🎯 低於目標價 {money(target)}\n" + "\n".join(
                f"{tag(r['depart_date'])} {money(r['total'])}" for r in sorted(hits, key=lambda r: r["total"])))

    # 3. Weekly report on Monday mornings.
    if now.weekday() == 0 and state.get("weekly_sent_on") != today and new_daily:
        best = sorted(new_daily, key=lambda r: r["total"])[:3]
        messages.append("🗓️ 週報：目前最便宜的 3 個出發日\n" + "\n".join(
            f"{tag(r['depart_date'])} → {md(r['return_date'])} {money(r['total'])}" for r in best))
        state["weekly_sent_on"] = today

    # 4. Failure / fallback warnings.
    if new_daily or kept_today:
        state["fail_days"] = 0
    else:
        if state.get("last_fail_on") != today:  # a same-day re-run is not another day
            state["fail_days"] = state.get("fail_days", 0) + 1
            state["last_fail_on"] = today
        if state["fail_days"] >= 2:
            messages.append(f"🚨 已連續 {state['fail_days']} 天抓不到機票資料，需要檢查。\n"
                            + "\n".join(fetch.errors[:3]))
    if fetch.used_ignav and not state.get("on_fallback"):
        messages.append("🔁 Google Flights 查詢失敗，已切換備援 Ignav 補查"
                        f"（已用 {state.get('ignav_calls', 0):,} / {cfg['ignav_free_quota']:,} 次免費額度）。")
    elif not fetch.used_ignav and state.get("on_fallback") and new_daily:
        messages.append("✅ Google Flights 已恢復，停止使用備援。")
    if new_daily or fetch.used_ignav:
        state["on_fallback"] = fetch.used_ignav
    messages = fetch.messages + messages

    state["last_run"] = now.isoformat(timespec="minutes")
    build_site(cfg, state, now, finished=False)
    save_json(STATE, state)

    for m in messages:
        notify.send(with_link(m))
    github_output("finished", "false")
    return 0


def build_site(cfg: dict, state: dict, now: datetime, finished: bool) -> None:
    daily = read_csv(DAILY_CSV)
    flights = read_csv(FLIGHTS_CSV)
    latest = max((r["checked_on"] for r in daily), default=None)
    holidays = set(cfg["holidays"])

    by_check: dict[str, int] = {}
    for r in daily:
        by_check[r["checked_on"]] = min(by_check.get(r["checked_on"], int(r["total"])), int(r["total"]))
    all_time: dict[str, int] = {}
    for r in daily:
        all_time[r["depart_date"]] = min(all_time.get(r["depart_date"], int(r["total"])), int(r["total"]))

    def leg_flights(leg: str, d: str) -> list[dict]:
        rows = [r for r in flights if r["checked_on"] == latest and r["leg"] == leg and r["date"] == d]
        return [{"airline": r["airline"], "depart": r["depart"], "arrive": r["arrive"],
                 "price": int(r["price"]), "lcc": r["lcc"] == "1"} for r in sorted(rows, key=lambda r: int(r["price"]))]

    days = []
    for r in sorted((r for r in daily if r["checked_on"] == latest), key=lambda r: r["depart_date"]):
        d, rt = r["depart_date"], r["return_date"]
        days.append({
            "depart": d, "return": rt, "total": int(r["total"]), "lowest_ever": all_time[d],
            "holiday": d in holidays, "out": leg_flights("out", d), "ret": leg_flights("ret", rt),
            "link": sources.google_flights_link(cfg["origin"], cfg["destination"], d, rt,
                                                cfg["adults"], cfg["children"]),
        })

    save_json(SITE_JSON, {
        "updated_at": state.get("last_run") or now.isoformat(timespec="minutes"),
        "checked_on": latest,
        "route": f"{cfg['origin']} ⇄ {cfg['destination']}",
        "passengers": f"{cfg['adults']} 大 {cfg['children']} 小",
        "trip_days": cfg["trip_days"],
        "target_price": cfg.get("target_price"),
        "enabled": cfg["enabled"],
        "finished": finished,
        "on_fallback": state.get("on_fallback", False),
        "days": days,
        "history": [{"date": k, "min": v} for k, v in sorted(by_check.items())],
    })


def github_output(key: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--test-message", action="store_true", help="send a Telegram test message")
    p.add_argument("--fake", action="store_true", help="use random prices instead of real sources")
    p.add_argument("--ignav-check", action="store_true", help="make one Ignav call and print its response")
    sys.exit(run(p.parse_args()))


if __name__ == "__main__":
    main()
