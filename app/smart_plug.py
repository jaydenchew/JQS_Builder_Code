"""Smart Bird (GeekOpen GSPM1B-ES) smart plug MQTT client.

Singleton paho-mqtt client wired into the FastAPI lifespan. Used by
ArmWorker to cut phone charging before a transaction and restore it
after, regardless of success / stall / cancellation.

Topic prefix is "GemeOpen" — that's the vendor firmware spelling, not
a typo. Do not "fix" it.

Spec: .agent/plans/SMART_PLUG_SPEC.md
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
import paho.mqtt.client as mqtt
from app.config import MQTT_BROKER_HOST, MQTT_BROKER_PORT
from app import database

logger = logging.getLogger(__name__)

_TOPIC_PREFIX = "GemeOpen"  # vendor firmware spelling; not a typo
_SUB_WILDCARD = "%s/+/sub" % _TOPIC_PREFIX
_CMD_POWER = "controller-event"
_CMD_INFO = "info-all"
_QOS = 1

# paho keepalive — matches the plug firmware's 120s heartbeat so a dead
# socket is detected within one keepalive interval.
_MQTT_KEEPALIVE_S = 120


class SmartPlugClient:
    """Singleton MQTT client for GeekOpen smart plugs.

    Threading model: paho runs its network loop in a background thread
    (loop_start). on_message / on_subscribe callbacks therefore execute
    OFF the asyncio loop and must use loop.call_soon_threadsafe() to
    interact with any asyncio primitive (Future, Event).
    """

    def __init__(self):
        self._client: mqtt.Client | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._connected = False
        self._subscribed: asyncio.Event | None = None
        # (client_id, expected_commandName) -> Future awaiting that reply
        self._pending: dict[tuple[str, str], asyncio.Future] = {}
        self.power_off_failures = 0
        self.power_on_failures = 0
        self.last_failure_at: str | None = None
        self.last_failure_reason: str | None = None

    # === public lifecycle ===

    async def start(self):
        """Connect to MQTT broker and wait for the subscription to be
        acknowledged. Non-fatal: if the broker is unreachable, paho will
        keep retrying in the background; power_off/on will fail with
        is_connected()==False until the broker comes back.
        """
        self._loop = asyncio.get_running_loop()
        self._subscribed = asyncio.Event()
        client = mqtt.Client()
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_subscribe = self._on_subscribe
        client.on_message = self._on_message
        client.reconnect_delay_set(min_delay=1, max_delay=60)
        # connect_async + loop_start is the documented paho pattern for
        # "broker may be down at startup": loop_start runs loop_forever with
        # retry_first_connection=True so paho keeps reconnecting in the
        # background until the broker comes up. connect() (blocking) leaves
        # the client in an undefined state on first-failure and is not
        # guaranteed to retry.
        try:
            client.connect_async(
                MQTT_BROKER_HOST, MQTT_BROKER_PORT, keepalive=_MQTT_KEEPALIVE_S)
        except Exception as e:
            logger.error(
                "Smart plug MQTT connect_async to %s:%d failed: %s. "
                "Plug control disabled.",
                MQTT_BROKER_HOST, MQTT_BROKER_PORT, e)
            return
        client.loop_start()
        self._client = client
        try:
            await asyncio.wait_for(self._subscribed.wait(), timeout=5.0)
            logger.info("Smart plug MQTT connected to %s:%d",
                        MQTT_BROKER_HOST, MQTT_BROKER_PORT)
        except asyncio.TimeoutError:
            logger.warning(
                "Smart plug MQTT subscribe timeout (5s) — broker may be down; "
                "paho will keep retrying in background")

    async def stop(self):
        if self._client is None:
            return
        try:
            self._client.disconnect()
            self._client.loop_stop()
        except Exception as e:
            logger.warning("Smart plug MQTT shutdown error (ignored): %s", e)
        self._client = None
        self._connected = False

    async def bootstrap(self):
        """Startup recovery: ensure all enabled plugs are ON.

        Service crash mid-transaction could leave a plug stuck OFF until
        the next task on that station completes. This makes sure every
        enabled plug is restored to ON at service startup. Query errors
        (e.g. plug_* columns not migrated yet) are logged and skipped
        so a partial deployment can still bring the service up.
        """
        try:
            rows = await database.fetchall(
                "SELECT plug_client_id FROM stations "
                "WHERE plug_enabled = 1 AND plug_client_id IS NOT NULL")
        except Exception as e:
            logger.warning("[plug-bootstrap] query failed (skipping): %s", e)
            return
        for r in rows:
            client_id = r["plug_client_id"]
            ok = await self.power_on(client_id)
            if not ok:
                logger.warning("[plug-bootstrap] power_on failed for %s", client_id)
        logger.info("[plug-bootstrap] restored %d plug(s)", len(rows))

    # === public command API ===

    async def power_on(self, client_id: str, timeout: float = 5.0) -> bool:
        return await self._send_event(client_id, key=1, timeout=timeout)

    async def power_off(self, client_id: str, timeout: float = 5.0) -> bool:
        return await self._send_event(client_id, key=0, timeout=timeout)

    async def get_status(self, client_id: str, timeout: float = 5.0) -> dict | None:
        return await self._send_query(
            client_id, payload={"type": "info"},
            expect_cmd=_CMD_INFO, timeout=timeout)

    def is_connected(self) -> bool:
        return self._connected and self._client is not None

    # === paho callbacks (run in paho's network thread) ===

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._connected = True
            client.subscribe(_SUB_WILDCARD, qos=_QOS)
            logger.info("Smart plug MQTT connected (rc=%d)", rc)
        else:
            self._connected = False
            logger.error("Smart plug MQTT connect failed (rc=%d)", rc)

    def _on_disconnect(self, client, userdata, rc):
        was_connected = self._connected
        self._connected = False
        if rc != 0 and was_connected:
            logger.warning(
                "Smart plug MQTT unexpectedly disconnected (rc=%d); "
                "paho will auto-reconnect", rc)

    def _on_subscribe(self, client, userdata, mid, granted_qos):
        if self._loop is not None and self._subscribed is not None:
            self._loop.call_soon_threadsafe(self._subscribed.set)

    def _on_message(self, client, userdata, msg):
        try:
            parts = msg.topic.split("/")
            if len(parts) < 3 or parts[0] != _TOPIC_PREFIX:
                return
            sender_id = parts[1]
            payload = json.loads(msg.payload)
            cmd = payload.get("commandName", "")
            key = (sender_id, cmd)
            fut = self._pending.pop(key, None)
            if fut is not None and not fut.done() and self._loop is not None:
                self._loop.call_soon_threadsafe(fut.set_result, payload)
        except Exception as e:
            logger.warning("Smart plug on_message error: %s", e)

    # === internals ===

    async def _send_event(self, client_id: str, key: int, timeout: float) -> bool:
        """Send {"key": 0|1, "type": "event"}, await controller-event reply.

        Contract: returns True iff the reply's key matches the requested
        state. ANY other outcome (not connected, publish error, timeout,
        mismatched reply, unexpected exception from paho or json) bumps
        the failure counter and returns False. CancelledError is the only
        thing that can escape — it must propagate so worker shutdown can
        complete.
        """
        if not self.is_connected():
            self._record_failure(key, "not connected")
            return False
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        pkey = (client_id, _CMD_POWER)
        self._pending[pkey] = fut
        try:
            topic = "%s/%s/pub" % (_TOPIC_PREFIX, client_id)
            # Compact separators match the plug's own wire format
            # ({"key":1,"type":"event"}) — verified against firmware in
            # diagnostic test. Default separators add spaces and were
            # never verified against the device's JSON parser.
            payload = json.dumps(
                {"key": key, "type": "event"}, separators=(",", ":"))
            info = self._client.publish(topic, payload, qos=_QOS)
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                self._record_failure(key, "publish rc=%d" % info.rc)
                return False
            try:
                reply = await asyncio.wait_for(fut, timeout=timeout)
            except asyncio.TimeoutError:
                self._record_failure(key, "timeout waiting for controller-event")
                return False
            if reply.get("key") != key:
                self._record_failure(
                    key, "reply key=%s, expected %d" % (reply.get("key"), key))
                return False
            return True
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self._record_failure(key, "unexpected: %s" % e)
            return False
        finally:
            self._pending.pop(pkey, None)

    async def _send_query(self, client_id: str, payload: dict,
                          expect_cmd: str, timeout: float) -> dict | None:
        """Same contract as _send_event but returns the reply dict (or None)."""
        if not self.is_connected():
            return None
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        pkey = (client_id, expect_cmd)
        self._pending[pkey] = fut
        try:
            topic = "%s/%s/pub" % (_TOPIC_PREFIX, client_id)
            info = self._client.publish(
                topic, json.dumps(payload, separators=(",", ":")), qos=_QOS)
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                return None
            try:
                return await asyncio.wait_for(fut, timeout=timeout)
            except asyncio.TimeoutError:
                return None
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("Smart plug query unexpected error for %s: %s", client_id, e)
            return None
        finally:
            self._pending.pop(pkey, None)

    def _record_failure(self, key: int, reason: str):
        if key == 0:
            self.power_off_failures += 1
        else:
            self.power_on_failures += 1
        self.last_failure_at = datetime.now(timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S")
        self.last_failure_reason = reason


smart_plug_client = SmartPlugClient()
