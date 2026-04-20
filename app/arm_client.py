"""Mechanical arm HTTP API wrapper — class-based for multi-instance support.

ArmClient class: each arm gets its own instance with independent COM port, position, resource.
Module-level functions: backward-compatible wrappers using a default instance (for Builder recorder/stream).
"""
import math
import urllib.request
import time
import logging
from app.config import ARM_SERVICE_URL, ARM_COM_PORT, ARM_Z_DOWN, ARM_MOVE_DELAY, ARM_PRESS_DELAY

logger = logging.getLogger(__name__)


class ArmClient:
    """Per-arm controller instance"""

    def __init__(self, com_port: str = ARM_COM_PORT, service_url: str = ARM_SERVICE_URL,
                 z_down: int = ARM_Z_DOWN, move_delay: float = ARM_MOVE_DELAY,
                 press_delay: float = ARM_PRESS_DELAY):
        self.com_port = com_port
        self.service_url = service_url
        self.z_down = z_down
        self.move_delay = move_delay
        self.press_delay = press_delay
        self._resource = None
        self._pos_x = 0.0
        self._pos_y = 0.0
        self._last_x = 0.0
        self._last_y = 0.0

    def call_arm(self, duankou, hco, daima):
        url = "%s?duankou=%s&hco=%s&daima=%s" % (self.service_url, duankou, hco, daima)
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                result = resp.read().decode("utf-8").strip().strip('"')
                return result
        except Exception as e:
            logger.error("Arm call failed: %s", e)
            return None

    def open_port(self):
        result = self.call_arm(self.com_port, 0, 0)
        if result is None:
            raise RuntimeError("Arm service not responding")
        self._resource = int(result)
        if self._resource <= 0:
            raise RuntimeError("Port open failed (got %d), COM port may be in use" % self._resource)
        logger.info("Port opened: %s, resource=%d", self.com_port, self._resource)
        time.sleep(3)
        return self._resource

    def close_port(self):
        if self._resource is not None:
            self.call_arm(0, self._resource, "x0y0z0")
            time.sleep(1)
            self.call_arm(0, self._resource, 0)
            logger.info("Port closed: %s", self.com_port)
            self._resource = None

    def get_resource(self):
        if self._resource is None:
            raise RuntimeError("Port not opened")
        return self._resource

    def motor_lock(self):
        self.call_arm(0, self.get_resource(), "$1=255")

    def motor_unlock(self):
        self.call_arm(0, self.get_resource(), "$1=100")
        time.sleep(0.3)
        self.call_arm(0, self.get_resource(), "x0.1y0.1")
        time.sleep(0.5)

    def move(self, x, y):
        fx, fy = float(x), float(y)
        self.call_arm(0, self.get_resource(), "x%sy%s" % (x, y))
        dist = math.sqrt((fx - self._last_x) ** 2 + (fy - self._last_y) ** 2)
        wait = max(self.move_delay, dist * 0.015)
        self._pos_x, self._pos_y = fx, fy
        self._last_x, self._last_y = fx, fy
        time.sleep(wait)

    def press(self, z=None):
        if z is None:
            z = self.z_down
        self.call_arm(0, self.get_resource(), "z%d" % z)
        time.sleep(self.press_delay)

    def lift(self):
        self.call_arm(0, self.get_resource(), "z0")
        time.sleep(self.press_delay)

    def click(self, x, y):
        self.move(x, y)
        self.press()
        self.lift()

    def swipe(self, sx, sy, ex, ey):
        self.move(sx, sy)
        self.press()
        # 按下后停 300ms，让屏幕完成 touch-down 识别（落在 Android TAP_TIMEOUT=100ms 与
        # DEFAULT_LONG_PRESS_TIMEOUT=400ms 之间的安全窗口，既够识别也不会误触发长按）。
        time.sleep(0.3)
        # 终点移动 + 抬笔：两条指令连发，中间不 Python-sleep。固件有命令队列，
        # z0 会在 x/y 到位的那一瞬间被 pop 出来执行，既保证笔物理到达终点（slide-to-confirm
        # 等末端敏感控件需要），又没有 Python 侧停顿窗口（swipe gesture 要求抬起前仍在动）。
        # 注意不能用合并指令 "x<ex>y<ey>z0"，那是三轴同步运动，z 会在 x/y 到终点前就上升。
        fx, fy = float(ex), float(ey)
        self.call_arm(0, self.get_resource(), "x%sy%s" % (ex, ey))
        self.call_arm(0, self.get_resource(), "z0")
        dist = math.sqrt((fx - self._last_x) ** 2 + (fy - self._last_y) ** 2)
        wait = max(self.move_delay, dist * 0.015)
        self._pos_x, self._pos_y = fx, fy
        self._last_x, self._last_y = fx, fy
        time.sleep(wait + self.press_delay)

    def reset_to_origin(self):
        self.call_arm(0, self.get_resource(), "x0y0z0")
        self._pos_x, self._pos_y = 0.0, 0.0
        self._last_x, self._last_y = 0.0, 0.0
        time.sleep(1)

    def get_position(self):
        return self._pos_x, self._pos_y

    def is_connected(self):
        return self._resource is not None


# === Module-level default instance (for Builder recorder/stream backward compat) ===

_default = ArmClient()


def call_arm(duankou, hco, daima):
    return _default.call_arm(duankou, hco, daima)

def open_port():
    return _default.open_port()

def close_port():
    return _default.close_port()

def get_resource():
    return _default.get_resource()

def motor_lock():
    return _default.motor_lock()

def motor_unlock():
    return _default.motor_unlock()

def move(x, y):
    return _default.move(x, y)

def press(z=None):
    return _default.press(z)

def lift():
    return _default.lift()

def click(x, y):
    return _default.click(x, y)

def swipe(sx, sy, ex, ey):
    return _default.swipe(sx, sy, ex, ey)

def reset_to_origin():
    return _default.reset_to_origin()

def get_position():
    return _default.get_position()

def is_connected():
    return _default.is_connected()
