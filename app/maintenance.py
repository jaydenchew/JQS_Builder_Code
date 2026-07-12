"""Nightly per-arm maintenance window + balance report.

During an arm's configured window (arm_maintenance_configs, per-arm local time
UTC+7/UTC+8):
  1. /process-withdrawal rejects new PAS tasks for that arm (no DB row written,
     PAS is told to resend after the window ends).
  2. The scheduler waits for the arm's running task to finish, pauses the
     worker, runs every active BALANCE flow (flow_templates.transfer_type =
     'BALANCE') for the banks on that arm, OCRs the balance ROI, stores results
     in balance_checks, and posts photo+caption into a daily Slack thread /
     Telegram reply chain (separate credentials from stall notifications).
  3. The worker is always resumed (try/finally), then normal processing continues.

Safety: everything is fail-open. Any error in the window check lets the
withdrawal through; any error in the balance run is logged, recorded as a
fail row, and never propagates. The scheduler task can never crash the app.
"""
import io
import json
import asyncio
import base64
import logging
import datetime as dt

import httpx

from app import database, actions

logger = logging.getLogger(__name__)

DRAIN_TIMEOUT_S = 300       # max wait for the in-flight task to finish
SCHEDULER_TICK_S = 20

_client = None
_running_arms = set()       # arm_ids with a balance run in progress
_scheduler_task = None
_bg_tasks = set()           # keep refs so in-flight runs are never GC'd
_thread_lock = None         # serializes daily-thread creation across arms


def _get_thread_lock():
    global _thread_lock
    if _thread_lock is None:
        _thread_lock = asyncio.Lock()
    return _thread_lock


def _get_client():
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=30)
    return _client


async def close_client():
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None


# ---------------------------------------------------------------- window math

def _parse_hhmm(s):
    h, m = str(s).strip().split(":")
    h, m = int(h), int(m)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError("bad time %r" % s)
    return h, m


def _window_state(cfg, now_utc=None):
    """Return {'occurrence': date, 'win_start_utc': datetime} if now is inside
    the cfg window, else None. Window may span midnight (23:55 -> 00:05).
    All math in the cfg's own timezone (tz_offset hours east of UTC)."""
    now_utc = now_utc or dt.datetime.utcnow()
    tz = dt.timedelta(hours=int(cfg["tz_offset"]))
    local = now_utc + tz
    sh, sm = _parse_hhmm(cfg["start_time"])
    eh, em = _parse_hhmm(cfg["end_time"])
    start_min, end_min = sh * 60 + sm, eh * 60 + em
    now_min = local.hour * 60 + local.minute

    if start_min == end_min:            # zero-length window: never active
        return None
    if start_min < end_min:
        in_win = start_min <= now_min < end_min
        start_date = local.date()
    else:                               # spans midnight
        in_win = now_min >= start_min or now_min < end_min
        start_date = local.date() if now_min >= start_min else local.date() - dt.timedelta(days=1)
    if not in_win:
        return None

    win_start_local = dt.datetime.combine(start_date, dt.time(sh, sm))
    return {"occurrence": start_date, "win_start_utc": win_start_local - tz}


async def get_active_window(arm_id):
    """Used by the withdrawal gate. Returns the config row if the arm is inside
    an enabled maintenance window right now, else None. FAIL-OPEN: any error
    returns None so a broken config can never block real withdrawals.

    Early release requires ALL THREE:
      1. the balance run for this occurrence has COMPLETED (not in progress),
      2. balance_checks rows exist since window start (it actually ran),
      3. local midnight (cfg timezone) has passed — i.e. we are already on the
         day AFTER the window's start day. Without this, a run finishing at
         23:59 would reopen the gate and let tasks move money before the day
         ends, invalidating the photographed end-of-day balance.
    If the run never happened (worker down, no BALANCE flows), the gate stays
    closed until end_time as designed."""
    try:
        cfg = await database.fetchone(
            "SELECT * FROM arm_maintenance_configs WHERE arm_id = %s AND enabled = 1",
            (arm_id,))
        if not cfg:
            return None
        st = _window_state(cfg)
        if not st:
            return None
        if arm_id not in _running_arms and await _already_ran(arm_id, st["win_start_utc"]):
            local_today = (dt.datetime.utcnow() + dt.timedelta(hours=int(cfg["tz_offset"]))).date()
            if local_today > st["occurrence"]:
                return None
        return cfg
    except Exception as e:
        logger.error("maintenance window check failed for arm %s (fail-open): %s", arm_id, e)
        return None


# ---------------------------------------------------------------- balance OCR

def _crop_percent(img, roi):
    h, w = img.shape[:2]
    y1 = int(h * float(roi.get("top_percent", 0)) / 100)
    y2 = int(h * float(roi.get("bottom_percent", 100)) / 100)
    x1 = int(w * float(roi.get("left_percent", 0)) / 100)
    x2 = int(w * float(roi.get("right_percent", 100)) / 100)
    if y1 >= y2 or x1 >= x2:
        return None
    return img[y1:y2, x1:x2]


def _ocr_balance(frame, roi):
    """Rotate frame, crop the balance ROI, OCR digits. Returns
    (screenshot_b64, balance_text, balance_value). Never raises."""
    import cv2
    from app import ocr

    rotated = ocr.rotate_frame(frame)
    _, buf = cv2.imencode(".jpg", rotated)
    screenshot_b64 = base64.b64encode(buf).decode("utf-8")

    text, value = None, None
    try:
        cropped = _crop_percent(rotated, roi) if roi else None
        if cropped is not None and cropped.size > 0:
            res = ocr._ocr_field(cropped, "amount", expected=None)
            text = (res.get("text") or "").strip()[:100] or None
            if text:
                nums = ocr.extract_numbers(text)
                if nums:
                    cand = max(nums, key=lambda s: len(s.replace(".", "")))
                    try:
                        value = float(cand)
                        # Guard DECIMAL(15,2) overflow from OCR garbage
                        if not (0 <= value < 10 ** 13):
                            value = None
                    except ValueError:
                        pass
    except Exception as e:
        logger.warning("balance OCR failed: %s", e)
    return screenshot_b64, text, value


# ---------------------------------------------------------------- flow runner

async def _run_balance_flow(worker, bank_code, station_id, password, pin, flow_id):
    """Run one BALANCE flow on a paused worker's hardware. Returns dict with
    result/screenshot/balance. Supports CLICK, ARM_MOVE, TYPE, SWIPE, PHOTO and
    OCR_VERIFY (treated as the balance capture step). CHECK_SCREEN and
    FIND_AND_* are skipped with a warning — build balance flows without them."""
    steps = await database.fetchall(
        "SELECT * FROM flow_steps WHERE flow_template_id = %s ORDER BY step_number ASC",
        (flow_id,))
    if not steps:
        return {"result": "fail", "message": "no steps in balance flow %d" % flow_id,
                "screenshot": None, "balance_text": None, "balance_value": None}

    fake_tx = {"id": 0, "pin": pin or "", "_amount_format": None}
    screenshot_b64 = None
    balance_text = None
    balance_value = None

    hw = worker._hw
    a, c, ex = worker.arm_client, worker.camera, worker._executor

    await hw(a.open_port)
    await hw(a.motor_lock)
    await hw(a.reset_to_origin)
    try:
        for step in steps:
            atype = step["action_type"]
            sname = step["step_name"]
            if sname == "done":
                break
            logger.info("[maintenance] %s step %s/%s (%s)", bank_code, step["step_number"], sname, atype)

            pre = step.get("pre_delay_ms", 0) or 0

            if atype == "OCR_VERIFY":
                if pre > 0:
                    await asyncio.sleep(pre / 1000.0)
                try:
                    x, y = await actions.lookup_ui_element(bank_code, station_id, step["ui_element_key"])
                    await hw(a.move, x, y)
                    await asyncio.sleep(2)
                except ValueError:
                    logger.warning("[maintenance] no camera pos for %s, capturing from current position", sname)
                frame = await hw(c.capture_fresh_vision)
                if frame is None:
                    raise RuntimeError("camera capture failed at balance OCR step")
                roi = None
                try:
                    cfg = json.loads(step.get("description") or "{}")
                    roi = (cfg.get("field_rois") or {}).get("balance")
                except (json.JSONDecodeError, TypeError):
                    pass
                if roi is None:
                    logger.warning("[maintenance] %s: OCR step has no balance ROI — storing photo only", bank_code)
                loop = asyncio.get_event_loop()
                screenshot_b64, balance_text, balance_value = await loop.run_in_executor(
                    ex, _ocr_balance, frame, roi)
            elif atype in ("CLICK", "ARM_MOVE", "TYPE", "SWIPE", "PHOTO"):
                if pre > 0 and atype != "PHOTO":   # execute_photo sleeps its own pre_delay
                    await asyncio.sleep(pre / 1000.0)
                handler = actions.ACTION_MAP[atype]
                ret = await handler(step, bank_code, station_id, fake_tx, password or "",
                                    arm=a, cam=c, executor=ex)
                if atype == "PHOTO" and isinstance(ret, str):
                    screenshot_b64 = ret
            else:
                logger.warning("[maintenance] skipping unsupported step type %s (%s)", atype, sname)
                continue

            post = step.get("post_delay_ms", 0) or 0
            if post > 0:
                await asyncio.sleep(post / 1000.0)
    finally:
        try:
            await hw(a.reset_to_origin)
            await hw(a.close_port)
        except Exception as e:
            logger.error("[maintenance] arm cleanup failed: %s", e)

    return {"result": "ok", "message": None, "screenshot": screenshot_b64,
            "balance_text": balance_text, "balance_value": balance_value}


async def _find_balance_flow(bank_code, arm_id):
    flow = await database.fetchone(
        "SELECT id FROM flow_templates WHERE bank_code = %s AND arm_id = %s "
        "AND transfer_type = 'BALANCE' AND status = 'active' ORDER BY version DESC LIMIT 1",
        (bank_code, arm_id))
    if not flow:
        flow = await database.fetchone(
            "SELECT id FROM flow_templates WHERE bank_code = %s AND arm_id IS NULL "
            "AND transfer_type = 'BALANCE' AND status = 'active' ORDER BY version DESC LIMIT 1",
            (bank_code,))
    return flow["id"] if flow else None


async def run_arm_maintenance(arm_id, cfg=None, wait_drain=True):
    """Full maintenance run for one arm: pause worker, drain, run all balance
    flows, report, resume. Never raises. Also used by the Run Now button."""
    from app.worker_manager import manager

    if arm_id in _running_arms:
        logger.warning("[maintenance] run already in progress for arm %d", arm_id)
        return {"success": False, "error": "run already in progress"}
    _running_arms.add(arm_id)
    try:
        if cfg is None:
            cfg = await database.fetchone(
                "SELECT * FROM arm_maintenance_configs WHERE arm_id = %s", (arm_id,))
        if not cfg:
            return {"success": False, "error": "no maintenance config for this arm"}

        arm = await database.fetchone("SELECT name FROM arms WHERE id = %s", (arm_id,))
        arm_name = arm["name"] if arm else ("arm_%d" % arm_id)

        worker = manager.get_worker(arm_id)
        if worker is None:
            logger.warning("[maintenance] no running worker for arm %d — skipping balance run", arm_id)
            return {"success": False, "error": "worker not running"}

        # Fix the report date ONCE at run start. Posting happens per bank and a
        # run can outlive the window (drain + several flows); re-deriving the
        # date per post would split one night's report across two threads.
        report_date = _report_date(cfg)

        was_paused = worker._paused
        worker.pause()
        try:
            if wait_drain:
                drained = False
                for _ in range(DRAIN_TIMEOUT_S // 5):
                    busy = await database.fetchone(
                        "SELECT COUNT(*) AS n FROM transactions t "
                        "JOIN stations s ON t.station_id = s.id "
                        "WHERE s.arm_id = %s AND t.status = 'running'", (arm_id,))
                    if (busy["n"] == 0) and worker._current_task is None:
                        drained = True
                        break
                    await asyncio.sleep(5)
                if not drained:
                    logger.error("[maintenance] arm %d did not drain within %ds — aborting run",
                                 arm_id, DRAIN_TIMEOUT_S)
                    return {"success": False, "error": "arm did not become idle in time"}

            rows = await database.fetchall(
                "SELECT ba.bank_code, ba.station_id, ba.password, ba.pin, "
                "ba.account_no, p.name AS phone_name "
                "FROM bank_apps ba JOIN stations s ON ba.station_id = s.id "
                "LEFT JOIN phones p ON ba.phone_id = p.id "
                "WHERE s.arm_id = %s AND ba.status = 'active' ORDER BY ba.id", (arm_id,))
            # One balance run per bank (first app row wins if a bank has several).
            banks_by_code = {}
            for b in rows:
                banks_by_code.setdefault(b["bank_code"], b)
            banks = list(banks_by_code.values())

            ran = 0
            for b in banks:
                flow_id = await _find_balance_flow(b["bank_code"], arm_id)
                if not flow_id:
                    continue
                ran += 1
                try:
                    r = await _run_balance_flow(worker, b["bank_code"], b["station_id"],
                                                b.get("password"), b.get("pin"), flow_id)
                except Exception as e:
                    logger.error("[maintenance] balance flow crashed for %s: %s", b["bank_code"], e)
                    shot = None
                    try:
                        shot = await worker._hw(worker.camera.capture_base64)
                    except Exception:
                        pass
                    r = {"result": "fail", "message": str(e)[:500], "screenshot": shot,
                         "balance_text": None, "balance_value": None}

                await database.execute(
                    "INSERT INTO balance_checks (arm_id, bank_code, result, balance_text, "
                    "balance_value, screenshot_base64, message) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (arm_id, b["bank_code"], r["result"], r["balance_text"],
                     r["balance_value"], r["screenshot"], r["message"]))

                try:
                    await _post_bank_report(cfg, arm_name, b, r, report_date)
                except Exception as e:
                    logger.error("[maintenance] report post failed for %s: %s", b["bank_code"], e)

            logger.info("[maintenance] arm %d (%s): balance run finished, %d flows", arm_id, arm_name, ran)
            if ran == 0:
                return {"success": False, "error": "no BALANCE flows found for this arm's banks"}
            return {"success": True, "flows_run": ran}
        finally:
            if not was_paused:
                worker.resume()
    except Exception as e:
        logger.error("[maintenance] run failed for arm %d: %s", arm_id, e)
        return {"success": False, "error": str(e)}
    finally:
        _running_arms.discard(arm_id)


# ---------------------------------------------------------------- reporting

def _report_date(cfg):
    st = _window_state(cfg)
    if st:
        return st["occurrence"].isoformat()
    tz = dt.timedelta(hours=int(cfg["tz_offset"]))
    return (dt.datetime.utcnow() + tz).date().isoformat()


async def _get_thread(report_date, provider, channel_key):
    row = await database.fetchone(
        "SELECT thread_ref FROM report_threads WHERE report_date = %s AND provider = %s AND channel_key = %s",
        (report_date, provider, channel_key))
    return row["thread_ref"] if row else None


async def _save_thread(report_date, provider, channel_key, thread_ref):
    """INSERT IGNORE + re-read: if two arms race to create today's thread, the
    first insert wins and both use that one (the loser's header message is a
    harmless duplicate)."""
    await database.execute(
        "INSERT IGNORE INTO report_threads (report_date, provider, channel_key, thread_ref) "
        "VALUES (%s, %s, %s, %s)", (report_date, provider, channel_key, thread_ref))
    return await _get_thread(report_date, provider, channel_key)


async def _slack_thread(cfg, report_date):
    """Ensure today's Slack parent message exists. Returns (channel_id, ts).

    Creation is serialized by an asyncio.Lock (single-process app): when several
    arms finish their first bank at the same moment, only one posts the parent —
    the others re-check inside the lock and reuse it. No duplicate headers."""
    token, channel = cfg["slack_bot_token"], cfg["slack_channel"]
    ref = await _get_thread(report_date, "slack", channel)
    if ref and "|" in ref:
        cid, ts = ref.split("|", 1)
        return cid, ts
    async with _get_thread_lock():
        ref = await _get_thread(report_date, "slack", channel)   # re-check under lock
        if ref and "|" in ref:
            cid, ts = ref.split("|", 1)
            return cid, ts
        client = _get_client()
        resp = await client.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": "Bearer %s" % token},
            json={"channel": channel, "text": ":calendar: *%s Balance Report*" % report_date})
        body = resp.json()
        if not body.get("ok", False):
            raise RuntimeError("slack thread create error=%s" % body.get("error"))
        cid, ts = body["channel"], body["ts"]
        stored = await _save_thread(report_date, "slack", channel, "%s|%s" % (cid, ts))
        if stored and "|" in stored:
            cid, ts = stored.split("|", 1)
        return cid, ts


async def _slack_post(cfg, report_date, caption, image_b64):
    token = cfg["slack_bot_token"]
    headers = {"Authorization": "Bearer %s" % token}
    client = _get_client()
    channel_id, ts = await _slack_thread(cfg, report_date)

    if not image_b64:
        resp = await client.post(
            "https://slack.com/api/chat.postMessage", headers=headers,
            json={"channel": channel_id, "thread_ts": ts, "text": caption})
        if not resp.json().get("ok", False):
            raise RuntimeError("slack post error=%s" % resp.json().get("error"))
        return

    photo = base64.b64decode(image_b64)
    up = await client.get(
        "https://slack.com/api/files.getUploadURLExternal", headers=headers,
        params={"filename": "balance.jpg", "length": str(len(photo))})
    up_body = up.json()
    if not up_body.get("ok", False):
        raise RuntimeError("slack getUploadURLExternal error=%s" % up_body.get("error"))
    put = await client.post(up_body["upload_url"],
                            files={"file": ("balance.jpg", io.BytesIO(photo), "image/jpeg")})
    if put.status_code != 200:
        raise RuntimeError("slack upload resp=%d" % put.status_code)
    done = await client.post(
        "https://slack.com/api/files.completeUploadExternal", headers=headers,
        json={"files": [{"id": up_body["file_id"], "title": "balance"}],
              "channel_id": channel_id, "thread_ts": ts, "initial_comment": caption})
    if not done.json().get("ok", False):
        raise RuntimeError("slack completeUploadExternal error=%s" % done.json().get("error"))


async def _telegram_header(cfg, report_date):
    token, chat_id = cfg["telegram_bot_token"], cfg["telegram_chat_id"]
    ref = await _get_thread(report_date, "telegram", str(chat_id))
    if ref:
        return ref
    async with _get_thread_lock():
        ref = await _get_thread(report_date, "telegram", str(chat_id))   # re-check under lock
        if ref:
            return ref
        client = _get_client()
        resp = await client.post(
            "https://api.telegram.org/bot%s/sendMessage" % token,
            data={"chat_id": chat_id, "text": "\U0001F4C5 %s Balance Report" % report_date})
        body = resp.json()
        if resp.status_code != 200 or not body.get("ok", False):
            raise RuntimeError("telegram header resp=%d body=%s" % (resp.status_code, resp.text[:200]))
        mid = str(body["result"]["message_id"])
        stored = await _save_thread(report_date, "telegram", str(chat_id), mid)
        return stored or mid


async def _telegram_post(cfg, report_date, caption, image_b64):
    token, chat_id = cfg["telegram_bot_token"], cfg["telegram_chat_id"]
    client = _get_client()
    header_id = await _telegram_header(cfg, report_date)
    base = "https://api.telegram.org/bot%s" % token
    if image_b64:
        resp = await client.post(
            "%s/sendPhoto" % base,
            data={"chat_id": chat_id, "caption": caption, "reply_to_message_id": header_id},
            files={"photo": ("balance.jpg", io.BytesIO(base64.b64decode(image_b64)), "image/jpeg")})
    else:
        resp = await client.post(
            "%s/sendMessage" % base,
            data={"chat_id": chat_id, "text": caption, "reply_to_message_id": header_id})
    if resp.status_code != 200 or not resp.json().get("ok", False):
        raise RuntimeError("telegram post resp=%d body=%s" % (resp.status_code, resp.text[:200]))


async def _post_bank_report(cfg, arm_name, bank, r, report_date):
    """bank: bank_apps row dict (bank_code, account_no, phone_name).
    report_date is fixed by the caller at run start (see run_arm_maintenance)."""
    ident = " | ".join(
        str(v) for v in (arm_name, bank.get("phone_name"), bank["bank_code"], bank.get("account_no"))
        if v)
    if r["result"] == "ok":
        bal = r["balance_value"]
        bal_str = ("%.2f" % bal) if bal is not None else (r["balance_text"] or "(OCR failed)")
        caption = "%s | Balance: %s" % (ident, bal_str)
    else:
        caption = "%s | FAILED: %s" % (ident, (r["message"] or "?")[:150])

    if cfg.get("slack_enabled") and cfg.get("slack_bot_token") and cfg.get("slack_channel"):
        try:
            await _slack_post(cfg, report_date, caption, r["screenshot"])
        except Exception as e:
            logger.error("[maintenance] slack report failed: %s", e)
    if cfg.get("telegram_enabled") and cfg.get("telegram_bot_token") and cfg.get("telegram_chat_id"):
        try:
            await _telegram_post(cfg, report_date, caption, r["screenshot"])
        except Exception as e:
            logger.error("[maintenance] telegram report failed: %s", e)


async def send_test_report(arm_id):
    """Settings 'Test' button: post a test message into today's thread."""
    cfg = await database.fetchone(
        "SELECT * FROM arm_maintenance_configs WHERE arm_id = %s", (arm_id,))
    if not cfg:
        return {"success": False, "error": "No maintenance config saved for this arm"}
    if not (cfg["slack_enabled"] or cfg["telegram_enabled"]):
        return {"success": False, "error": "No provider enabled"}
    arm = await database.fetchone("SELECT name FROM arms WHERE id = %s", (arm_id,))
    arm_name = arm["name"] if arm else ("arm_%d" % arm_id)
    report_date = _report_date(cfg)
    results = {}
    if cfg["slack_enabled"] and cfg["slack_bot_token"] and cfg["slack_channel"]:
        try:
            await _slack_post(cfg, report_date, "%s | TEST | maintenance report test" % arm_name, None)
            results["slack"] = True
        except Exception as e:
            logger.error("[maintenance] slack test failed: %s", e)
            results["slack"] = False
    if cfg["telegram_enabled"] and cfg["telegram_bot_token"] and cfg["telegram_chat_id"]:
        try:
            await _telegram_post(cfg, report_date, "%s | TEST | maintenance report test" % arm_name, None)
            results["telegram"] = True
        except Exception as e:
            logger.error("[maintenance] telegram test failed: %s", e)
            results["telegram"] = False
    ok = any(results.values())
    return {"success": ok, "results": results}


# ---------------------------------------------------------------- scheduler

async def _already_ran(arm_id, win_start_utc):
    row = await database.fetchone(
        "SELECT COUNT(*) AS n FROM balance_checks WHERE arm_id = %s AND created_at >= %s",
        (arm_id, win_start_utc.strftime("%Y-%m-%d %H:%M:%S")))
    return row["n"] > 0


async def scheduler_loop():
    """Background task: every tick, start a balance run for any enabled arm
    whose window is active and which has not run in this window yet."""
    logger.info("[maintenance] scheduler started")
    while True:
        try:
            cfgs = await database.fetchall(
                "SELECT * FROM arm_maintenance_configs WHERE enabled = 1")
            for cfg in cfgs:
                st = _window_state(cfg)
                if not st:
                    continue
                arm_id = cfg["arm_id"]
                if arm_id in _running_arms:
                    continue
                if await _already_ran(arm_id, st["win_start_utc"]):
                    continue
                logger.info("[maintenance] window active for arm %d — starting balance run", arm_id)
                task = asyncio.ensure_future(run_arm_maintenance(arm_id, cfg=cfg))
                _bg_tasks.add(task)
                task.add_done_callback(_bg_tasks.discard)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("[maintenance] scheduler tick failed: %s", e)
        await asyncio.sleep(SCHEDULER_TICK_S)


def start_scheduler():
    global _scheduler_task
    if _scheduler_task is None or _scheduler_task.done():
        _scheduler_task = asyncio.create_task(scheduler_loop())
    return _scheduler_task


async def stop_scheduler():
    global _scheduler_task
    if _scheduler_task and not _scheduler_task.done():
        _scheduler_task.cancel()
        try:
            await _scheduler_task
        except asyncio.CancelledError:
            pass
    _scheduler_task = None
