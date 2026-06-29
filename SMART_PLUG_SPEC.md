# Smart Bird (GeekOpen) 智能插座 — WA 系统集成规格文档

## 目的

在 WA Unified System 中集成 GeekOpen 智能插座，实现交易前自动断开手机充电、交易后恢复充电。通过 MQTT 协议控制，插座与 WA 系统在同一局域网内通信。

---

## 硬件信息

| 项目 | 值 |
|---|---|
| 设备型号 | GSPM1B-ES（10A转换器插座英规版） |
| MAC 地址 | `8cce4e5148b9` |
| 通信协议 | MQTT（自建 Mosquitto broker） |
| 设备固件版本 | 2.3.2 |
| 设备类型标识 | `GSPM1B-ES` |

---

## MQTT 基础架构

### Broker

在 WA 系统的 `docker-compose.yml` 中新增 MQTT broker 容器（Eclipse Mosquitto），替代当前 Windows 安装的 Mosquitto：

```yaml
mosquitto:
  image: eclipse-mosquitto:2
  container_name: wa-mosquitto
  restart: unless-stopped
  ports:
    - "1883:1883"
  volumes:
    - ./mosquitto/config:/mosquitto/config
    - ./mosquitto/data:/mosquitto/data
    - ./mosquitto/log:/mosquitto/log
```

需要创建 `mosquitto/config/mosquitto.conf`：

```
listener 1883 0.0.0.0
allow_anonymous true
```

### 主题约定

| 方向 | 主题 | 用途 |
|---|---|---|
| WA → 插座 | `GemeOpen/{client_id}/pub` | 发送控制指令给插座 |
| 插座 → WA | `GemeOpen/{client_id}/sub` | 接收插座上报的状态和回复 |

当前 `client_id` = `plug01`（配网时设置）。

**注意**：主题命名从插座角度定义 —— 插座"发布"到 `pub`，"订阅" `sub`。但实际上 WA 发命令要发到 `pub` 主题（插座监听的是 `pub`），WA 监听回复要订阅 `sub` 主题。

### 插座配网参数（当前环境）

| 字段 | 值 |
|---|---|
| MQTT 地址 | `192.168.0.18`（WA 电脑局域网 IP） |
| MQTT 端口 | `1883` |
| 客户ID | `plug01` |
| 用户名 | （空） |
| 密码 | （空） |
| 订阅主题 | `GemeOpen/plug01/sub` |
| 发布主题 | `GemeOpen/plug01/pub` |

---

## MQTT 指令参考

### 1. 控制开关（核心指令）

**开电（通电）：**

```json
{"key": 1, "type": "event"}
```

**关电（断电）：**

```json
{"key": 0, "type": "event"}
```

发送主题：`GemeOpen/plug01/pub`

设备回复（在 `GemeOpen/plug01/sub` 上）：

```json
{
  "commandName": "controller-event",
  "key": 1,
  "mac": "8cce4e5148b9",
  "type": "GSPM1B-ES",
  "source": "command",
  "ip": "192.168.0.33",
  "signal": "-46",
  "ssid": "chew",
  "version": "2.3.2",
  "onState": 1,
  "timerEnable": 1,
  "wifiLock": 0,
  "messageId": ""
}
```

验证成功的标志：回复中 `commandName` = `"controller-event"` 且 `key` 值与发送的一致。

### 2. 查询设备信息

```json
{"type": "info", "messageId": "any-unique-id"}
```

设备回复（`commandName: "info-all"`）：

```json
{
  "source": "command",
  "commandName": "info-all",
  "messageId": "test001",
  "type": "GSPM1B-ES",
  "mac": "8cce4e5148b9",
  "version": "2.3.2",
  "key": 1,
  "keyLock": 0,
  "wifiLock": 0,
  "timerEnable": 1,
  "timerInterval": 15,
  "signal": "-47",
  "onState": 1,
  "ip": "192.168.0.33",
  "ssid": "chew"
}
```

| 字段 | 说明 |
|---|---|
| `key` | 当前通断状态，0=断电，1=通电 |
| `keyLock` | 按键锁，0=关闭，1=开启 |
| `wifiLock` | 配网锁，0=关闭，1=开启 |
| `timerEnable` | 定时上报，0=关闭，1=开启 |
| `timerInterval` | 上报间隔（秒） |
| `signal` | WiFi 信号强度（dBm） |
| `onState` | 上电默认状态：0=记忆，1=关闭，2=开启 |

### 3. 查询电量统计

```json
{"type": "statistic"}
```

设备回复（`commandName: "info-statistic"`）：

```json
{
  "commandName": "info-statistic",
  "current": 0,
  "energy": 0,
  "key": 1,
  "mac": "8cce4e5148b9",
  "messageId": "",
  "power": 0.063,
  "source": "command",
  "voltage": 232.644
}
```

| 字段 | 说明 | 单位 |
|---|---|---|
| `current` | 实时电流 | A |
| `voltage` | 实时电压 | V |
| `power` | 实时功率 | W |
| `energy` | 累计电量（断电不归零，重置归零） | kWh |

### 4. 设置定时上报间隔

```json
{"timerEnable": 1, "timerInterval": 15, "type": "setting"}
```

`timerInterval` 单位秒，范围 5-86400。插座默认会定时上报 `device-timer-task` 消息。

### 5. 设置按键锁（可选，防止人为误触）

```json
{"keyLock": 1, "type": "setting"}
```

锁定后只能通过 MQTT 控制，物理按键无效。解锁：`keyLock: 0`。

### 6. 查询通讯配置

```json
{"type": "protocol"}
```

回复包含当前 MQTT 服务器地址、端口、主题等配置信息。

### 7. 通过 MQTT 远程修改 MQTT 配置

```json
{
  "clientId": "plug01",
  "password": "",
  "port": "1883",
  "protocol": "mqtt",
  "publish": "GemeOpen/plug01/pub",
  "server": "192.168.0.18",
  "subcribe": "GemeOpen/plug01/sub",
  "type": "custom",
  "username": ""
}
```

可用于远程切换 MQTT 服务器地址（如搬迁后 IP 变化），无需物理重新配网。

---

## MQTT 连接与时序行为

### 心跳机制

插座与 MQTT broker 之间的心跳（keepalive）为 **120 秒**。这意味着：

- 插座正常在线时，每 120 秒内会有一次心跳通信
- 如果插座突然断网（WiFi 中断、物理断电等），broker 最多需要 **120 秒**才能判定设备离线
- 心跳只影响"离线检测"，**不影响指令收发速度** — 在线状态下发指令是实时响应的

### 指令响应时序

根据实测和官方文档（响应时间 20-50ms，受网络影响）：

1. WA 发送开关指令到 `GemeOpen/{client_id}/pub`
2. 插座收到后**立即执行**（继电器动作）并回复确认到 `GemeOpen/{client_id}/sub`
3. 回复中 `commandName: "controller-event"` 且 `key` 值反映实际状态

**WA 集成采用"等待确认"模式：**

- `power_off()` 发送断电指令后，**等待插座回复确认 `key=0`**，确认充电已断开后才开始执行交易流程
- `power_on()` 发送通电指令后，**等待插座回复确认 `key=1`**，确认充电已恢复
- 超时上限 5 秒（正常情况下几百毫秒内就会收到回复）
- 超时视为失败，记 warning 但**不阻塞交易** — 充电控制是增强功能，不能因为插座问题导致交易无法执行

### 定时上报消息（噪音过滤）

插座默认每隔 N 秒上报 `device-timer-task` 消息（包含电压、电流、功率等）。这些消息会出现在 `GemeOpen/{client_id}/sub` 主题上。`SmartPlugClient` 在等待指令回复时，必须**按 `commandName` 字段过滤**，只匹配 `"controller-event"` 回复，忽略 `"device-timer-task"` 定时上报。

---

## WA 系统集成设计

### 新增配置项（`.env`）

```env
# Smart Bird 智能插座
MQTT_BROKER_HOST=127.0.0.1
MQTT_BROKER_PORT=1883
```

插座的 `client_id` 和主题关联到 station 级别（每个 station 可以有自己的插座），存入数据库。

### 数据库变更

在 `stations` 表新增字段：

```sql
ALTER TABLE stations
  ADD COLUMN plug_client_id VARCHAR(64) DEFAULT NULL COMMENT '智能插座 MQTT client_id，如 plug01',
  ADD COLUMN plug_enabled TINYINT(1) DEFAULT 0 COMMENT '是否启用智能插座充电控制';
```

### 新增模块：`app/smart_plug.py`

单例 MQTT 客户端，随 WA 系统生命周期启停。

**核心接口：**

```python
class SmartPlugClient:
    async def start(self):
        """连接 MQTT broker，启动消息循环。在 main.py lifespan 中调用。"""

    async def stop(self):
        """断开 MQTT 连接。在 main.py lifespan shutdown 中调用。"""

    async def power_on(self, client_id: str, timeout: float = 5.0) -> bool:
        """通电。发送 {"key":1,"type":"event"} 到 GemeOpen/{client_id}/pub，
        等待 GemeOpen/{client_id}/sub 回复确认 key=1。
        返回 True 表示成功，False 表示超时或失败。"""

    async def power_off(self, client_id: str, timeout: float = 5.0) -> bool:
        """断电。发送 {"key":0,"type":"event"}，等待确认 key=0。"""

    async def get_status(self, client_id: str, timeout: float = 5.0) -> dict | None:
        """查询设备状态。发送 {"type":"info"}，返回设备信息 dict 或 None。"""

    def is_connected(self) -> bool:
        """MQTT broker 连接状态。"""
```

**实现要点：**

- 使用 `paho-mqtt>=1.6.0,<2.0`（paho-mqtt 2.x 改了 callback API，不兼容 1.x 写法）
- MQTT client 在独立线程运行（`loop_start()`），通过 `asyncio.Future` 桥接到 async 世界
- 订阅 `GemeOpen/+/sub` 通配主题，收到回复后从 **topic 字符串解析 `client_id`**（`topic.split("/")[1]`），再查 pending futures 表分发
- 断线自动重连（参考 demo 中的重连逻辑，指数退避，最大 60 秒）
- **`start()` 必须等 SUBACK 才 return** — `on_subscribe` 回调里 set 一个 `asyncio.Event`，`start()` await 该 Event 后再返回。否则第一次 `power_off` 可能在订阅生效之前就发出去，插座回复错过，整个调用会超时
- **所有 `publish` 用 QoS 1** —— 默认 QoS 0 是 fire-and-forget，broker 重启那一刹那的指令会丢；QoS 1 由 broker 重传到收到 PUBACK，代价仅多一个确认包
- **topic 前缀写成常量 `_TOPIC_PREFIX = "GemeOpen"`，并加注释 `# vendor firmware spelling; not a typo`** — 设备厂商叫 GeekOpen 但固件里就拼成 `GemeOpen`（M 不是 K），避免后人当 typo 改掉
- **失败计数器** —— 实例属性 `power_off_failures` / `power_on_failures` / `last_failure_at` / `last_failure_reason`，每次失败时累加+记录，提供给 `/api/monitor/plug-status` 读取

**多插座并发回复匹配：**

回复 payload 里只有 `mac` 没有 `client_id`，所以必须从 topic 解析。核心数据结构：

```python
# key = (client_id, expected_commandName)
# value = asyncio.Future that the caller is awaiting
self._pending: Dict[Tuple[str, str], asyncio.Future] = {}
```

流程：

1. `power_off("plug01")` 调用时，创建 `Future`，注册到 `_pending[("plug01", "controller-event")]`
2. 发送 `{"key":0,"type":"event"}` 到 `GemeOpen/plug01/pub`
3. `on_message` 回调收到消息，从 topic `GemeOpen/plug01/sub` 解析出 `client_id = "plug01"`
4. 解析 payload JSON，取 `commandName`
5. 查 `_pending[("plug01", "controller-event")]`，如果存在则 `future.set_result(payload)`
6. 忽略 `commandName = "device-timer-task"` 的定时上报（不匹配任何 pending future）
7. 调用侧 `await asyncio.wait_for(future, timeout=5.0)` 拿到结果，检查 `key` 值

注意 `on_message` 跑在 paho 的线程里，`future.set_result()` 必须用 `loop.call_soon_threadsafe()`：

```python
def on_message(self, client, userdata, msg):
    client_id = msg.topic.split("/")[1]
    payload = json.loads(msg.payload)
    cmd_name = payload.get("commandName", "")
    key = (client_id, cmd_name)
    fut = self._pending.pop(key, None)
    if fut and not fut.done():
        self._loop.call_soon_threadsafe(fut.set_result, payload)
```

**各指令对应的 `commandName` 映射（用于 pending key）：**

| 方法 | 发送 `type` | 回复 `commandName` |
|---|---|---|
| `power_on` / `power_off` | `"event"` | `"controller-event"` |
| `get_status` | `"info"` | `"info-all"` |
| `get_statistic` | `"statistic"` | `"info-statistic"` |

### 集成到 arm_worker.py

在 `_execute_task()` 方法中，流程开始前断电、流程结束后通电：

```python
async def _execute_task(self, task, bank_code, station_id, password, transaction_id):
    # 查询 station 的插座配置
    station = await database.fetchone(
        "SELECT plug_client_id, plug_enabled FROM stations WHERE id = %s",
        (station_id,))

    plug_id = station["plug_client_id"] if station and station["plug_enabled"] else None

    # 交易开始前：断开充电
    if plug_id:
        ok = await smart_plug_client.power_off(plug_id)
        if not ok:
            logger.warning("[%s] Smart plug power_off failed for %s, continuing anyway", self.name, plug_id)

    try:
        success = await self._run_flow(task, bank_code, station_id, password, transaction_id)
    finally:
        # 交易结束后：恢复充电（无论成功失败）
        if plug_id:
            ok = await smart_plug_client.power_on(plug_id)
            if not ok:
                logger.warning("[%s] Smart plug power_on failed for %s", self.name, plug_id)

    return success
```

**关键设计决策：**

- 插座控制失败**不阻塞**交易 — 只记 warning，继续执行
- 无论交易成功或失败，**都恢复通电** — 在 finally 块中
- 插座控制是 station 级别，不是 arm 级别 — 一个 arm 可能有多个 station，每个 station 对应不同的手机和充电器
- **同一插座的 on/off 天然串行** —— `stations.arm_id INT NOT NULL` 是 N:1（一个 arm 多个 station，但一个 station 只属于一个 arm），且每个 `ArmWorker` 单线程顺序处理任务。所以不存在两个 worker 抢同一个插座的情况，`SmartPlugClient` 不需要做 ref-count 或锁

### 生命周期集成（main.py）

```python
from app.smart_plug import smart_plug_client

@asynccontextmanager
async def lifespan(app):
    # ... 现有启动逻辑 ...
    await smart_plug_client.start()
    await smart_plug_client.bootstrap()    # 兜底恢复：见下文

    yield

    await smart_plug_client.stop()
    # ... 现有关闭逻辑 ...
```

**`bootstrap()` 启动兜底恢复：**

如果 service 在某次交易中途 crash（断电、人手 kill、OOM 等），插座可能停在 `OFF` 状态，下一次该 station 收到任务才会被 finally 块恢复。中间这段时间手机一直不充电。

`bootstrap()` 在 `start()` 之后执行：查询所有 `plug_enabled=1 AND plug_client_id IS NOT NULL` 的 station，对每个 `client_id` 调一次 `power_on`，单个 timeout 5 秒，失败只记 warning 不阻塞启动。

```python
async def bootstrap(self):
    """Startup recovery: ensure all enabled plugs are ON.

    Service crash mid-transaction could leave a plug stuck OFF until the
    next task on that station completes. This makes sure every enabled
    plug is restored to ON at service startup.
    """
    rows = await database.fetchall(
        "SELECT plug_client_id FROM stations "
        "WHERE plug_enabled = 1 AND plug_client_id IS NOT NULL"
    )
    for r in rows:
        client_id = r["plug_client_id"]
        ok = await self.power_on(client_id)
        if not ok:
            logger.warning("[plug-bootstrap] power_on failed for %s", client_id)
    logger.info("[plug-bootstrap] restored %d plug(s)", len(rows))
```

### Settings UI

在 Settings 页面的 Station 编辑区域，新增：

- **插座 Client ID** — 文本框，填 MQTT client_id（如 `plug01`）
- **启用充电控制** — 开关

### Monitor / Dashboard

**基础可观测性（本次实现）：**

插座失败不阻塞交易，所以失败默认是"静默"的 —— 只能靠 log 发现。最低限度的可观测性是一个状态查询 endpoint：

```python
# app/routers/monitor.py
@router.get("/api/monitor/plug-status")
async def plug_status():
    return {
        "connected": smart_plug_client.is_connected(),
        "power_off_failures": smart_plug_client.power_off_failures,
        "power_on_failures": smart_plug_client.power_on_failures,
        "last_failure_at": smart_plug_client.last_failure_at,
        "last_failure_reason": smart_plug_client.last_failure_reason,
    }
```

进程内累加计数器，重启清零（够用 —— 这是 "上次重启以来"的健康指标，不是审计日志）。出问题排查时直接 curl 这个 endpoint 看数。如果将来发现失败常态化，再升级到 DB 持久化或 `plug_events` 表。

**可选增强（不在本次实现范围）：**

- Dashboard arm 卡片显示插座连接状态和当前功率（需要定期 `{"type":"statistic"}` 查询 + WebSocket 推送）
- `stations` 表加 `last_plug_failure_at`，Dashboard 红点
- 新增 `plug_events` 表，记录每次开关历史

---

## 搬迁 / 更换网络的操作

1. 插座需要重新配网（长按按钮进入配网模式）
2. 连接插座热点，填入新 WiFi 信息和新的 MQTT broker IP
3. 或者：如果旧 MQTT 连接还在，可以通过指令 7（远程修改 MQTT 配置）切换到新地址
4. Docker 中的 Mosquitto 容器不需要任何改动

---

## 依赖

| 包 | 用途 |
|---|---|
| `paho-mqtt` | Python MQTT 客户端 |
| `eclipse-mosquitto:2` | Docker MQTT broker |

在 `requirements.txt` 中新增：

```
paho-mqtt>=1.6.0,<2.0
```

---

## 测试验证命令

以下命令可在 WA 电脑的 CMD 中直接测试（需要 Mosquitto 客户端工具）：

```cmd
:: 监听所有消息（QoS 1 订阅，和 WA 集成保持一致）
"C:\Program Files\mosquitto\mosquitto_sub.exe" -h 127.0.0.1 -t "#" -v -q 1

:: 开电（QoS 1）
"C:\Program Files\mosquitto\mosquitto_pub.exe" -h 127.0.0.1 -t "GemeOpen/plug01/pub" -q 1 -m "{\"key\":1,\"type\":\"event\"}"

:: 关电（QoS 1）
"C:\Program Files\mosquitto\mosquitto_pub.exe" -h 127.0.0.1 -t "GemeOpen/plug01/pub" -q 1 -m "{\"key\":0,\"type\":\"event\"}"

:: 查询设备信息
"C:\Program Files\mosquitto\mosquitto_pub.exe" -h 127.0.0.1 -t "GemeOpen/plug01/pub" -q 1 -m "{\"type\":\"info\"}"

:: 查询电量
"C:\Program Files\mosquitto\mosquitto_pub.exe" -h 127.0.0.1 -t "GemeOpen/plug01/pub" -q 1 -m "{\"type\":\"statistic\"}"
```
