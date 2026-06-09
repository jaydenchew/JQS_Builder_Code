"""Per-arm Slack/Telegram stall notifications.

Sent in addition to the PAS callback when a transaction stalls. Every send is
wrapped so a notification failure can NEVER affect the transaction flow or the
PAS callback (fire-and-forget). Reuses a single AsyncClient like pas_client.
"""
import io
import asyncio
import base64
import logging
import httpx

logger = logging.getLogger(__name__)

_client = None

# Holds references to in-flight background notification tasks so they are not
# garbage-collected mid-flight. Tasks remove themselves on completion.
_bg_tasks = set()


def fire(coro):
    """Schedule a notification coroutine as a background task and return immediately.

    The caller (e.g. the arm worker) never waits on network I/O, so a slow or
    unreachable Slack/Telegram endpoint cannot delay the worker or the next task.
    """
    task = asyncio.ensure_future(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return task


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


def _fmt(info: dict) -> list:
    """Field rows shared by both providers: (label, value)."""
    amount = info.get("amount")
    currency = info.get("currency") or ""
    amount_str = ("%s %s" % (currency, amount)).strip() if amount is not None else "-"
    return [
        ("ARM", info.get("arm")),
        ("Process ID", info.get("process_id")),
        ("Status", info.get("status")),
        ("Time", info.get("time")),
        ("Amount", amount_str),
        ("Pay From Bank", info.get("pay_from_bank")),
        ("Pay To Bank", info.get("pay_to_bank")),
        ("Pay To Account No", info.get("pay_to_account_no")),
        ("Pay To Account Name", info.get("pay_to_account_name")),
    ]


def _telegram_caption(info: dict) -> str:
    lines = ["\U0001F6A8 <b>STALL ALERT</b>", ""]
    for label, value in _fmt(info):
        lines.append("<b>%s:</b> %s" % (label, "-" if value in (None, "") else value))
    return "\n".join(lines)


def _slack_text(info: dict) -> str:
    lines = [":rotating_light: *STALL ALERT*", ""]
    for label, value in _fmt(info):
        lines.append("*%s:* %s" % (label, "-" if value in (None, "") else value))
    return "\n".join(lines)


async def _send_telegram(cfg: dict, info: dict, image_b64):
    token = cfg["telegram_bot_token"]
    chat_id = cfg["telegram_chat_id"]
    caption = _telegram_caption(info)
    client = _get_client()
    base = "https://api.telegram.org/bot%s" % token
    if image_b64:
        photo = base64.b64decode(image_b64)
        resp = await client.post(
            "%s/sendPhoto" % base,
            data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
            files={"photo": ("stall.jpg", io.BytesIO(photo), "image/jpeg")},
        )
    else:
        resp = await client.post(
            "%s/sendMessage" % base,
            data={"chat_id": chat_id, "text": caption, "parse_mode": "HTML"},
        )
    if resp.status_code != 200 or not resp.json().get("ok", False):
        raise RuntimeError("telegram resp=%d body=%s" % (resp.status_code, resp.text[:200]))


async def _send_slack(cfg: dict, info: dict, image_b64):
    token = cfg["slack_bot_token"]
    channel = cfg["slack_channel"]
    text = _slack_text(info)
    client = _get_client()
    headers = {"Authorization": "Bearer %s" % token}

    # Post the text message first; the response gives the resolved channel ID,
    # which the file upload API requires (it does not accept #channel names).
    resp = await client.post(
        "https://slack.com/api/chat.postMessage",
        headers=headers,
        json={"channel": channel, "text": text},
    )
    body = resp.json()
    if not body.get("ok", False):
        raise RuntimeError("slack chat.postMessage error=%s" % body.get("error"))
    channel_id = body.get("channel")

    if not image_b64 or not channel_id:
        return

    photo = base64.b64decode(image_b64)
    length = len(photo)
    up = await client.get(
        "https://slack.com/api/files.getUploadURLExternal",
        headers=headers,
        params={"filename": "stall.jpg", "length": str(length)},
    )
    up_body = up.json()
    if not up_body.get("ok", False):
        raise RuntimeError("slack getUploadURLExternal error=%s" % up_body.get("error"))
    upload_url = up_body["upload_url"]
    file_id = up_body["file_id"]

    put = await client.post(upload_url, files={"file": ("stall.jpg", io.BytesIO(photo), "image/jpeg")})
    if put.status_code != 200:
        raise RuntimeError("slack file upload resp=%d" % put.status_code)

    done = await client.post(
        "https://slack.com/api/files.completeUploadExternal",
        headers=headers,
        json={"files": [{"id": file_id, "title": "Stall screenshot"}], "channel_id": channel_id},
    )
    done_body = done.json()
    if not done_body.get("ok", False):
        raise RuntimeError("slack completeUploadExternal error=%s" % done_body.get("error"))


async def dispatch(cfg: dict, info: dict, image_b64=None):
    """Send stall notification to whichever providers are enabled. Never raises.

    Returns a per-provider result map, e.g. {"telegram": True, "slack": False},
    where True=sent, False=failed. Providers that are not enabled are omitted.
    """
    results = {}
    if cfg.get("telegram_enabled") and cfg.get("telegram_bot_token") and cfg.get("telegram_chat_id"):
        try:
            await _send_telegram(cfg, info, image_b64)
            logger.info("Telegram stall notify sent: process_id=%s arm=%s", info.get("process_id"), info.get("arm"))
            results["telegram"] = True
        except Exception as e:
            logger.error("Telegram stall notify failed: %s", e)
            results["telegram"] = False
    if cfg.get("slack_enabled") and cfg.get("slack_bot_token") and cfg.get("slack_channel"):
        try:
            await _send_slack(cfg, info, image_b64)
            logger.info("Slack stall notify sent: process_id=%s arm=%s", info.get("process_id"), info.get("arm"))
            results["slack"] = True
        except Exception as e:
            logger.error("Slack stall notify failed: %s", e)
            results["slack"] = False
    return results
