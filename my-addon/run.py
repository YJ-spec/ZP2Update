import logging
import json
import paho.mqtt.client as mqtt
import requests
import os
import shutil
import time
import threading
import yaml
import socket

# ------------------------------------------------------------
# 🧾 設定日誌格式
# ------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
# ------------------------------------------------------------
# 🔧 先定義功能函式（一定要放在前面）
# ------------------------------------------------------------

def get_local_ip():
    """
    取得本機的 LAN IP（不是 127.0.0.1）
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))  # 不會真的連出去
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def load_ota_index(path="/data/ota_index.yaml"):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        fw_list = data.get("firmwares", [])
        return {fw["id"]: fw for fw in fw_list if "id" in fw}
    except Exception as e:
        logging.error(f"[OTA] 載入 ota_index.yaml 失敗：{e}")
        return {}

# ------------------------------------------------------------
# ⚙️ 讀取 HA 傳入的設定 (options.json)
# ------------------------------------------------------------
with open("/data/options.json", "r") as f:
    options = json.load(f)

# 從環境變數取得 Long-Lived Token
TOPICS = options.get("mqtt_topics", "+/+/data,+/+/control").split(",")
MQTT_BROKER = options.get("mqtt_broker", "core-mosquitto")
MQTT_PORT = int(options.get("mqtt_port", 1883))
MQTT_USERNAME = options.get("mqtt_username", "")
MQTT_PASSWORD = options.get("mqtt_password", "")
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN")
BASE_URL = "http://supervisor/core/api"

HEADERS = {
    "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
    "Content-Type": "application/json",
}
# ------------------------------------------------------------
# 🌐 自動偵測 IP + 固定 8088
# ------------------------------------------------------------
LOCAL_IP = get_local_ip()
OTA_BASE_URL = f"http://{LOCAL_IP}:8088"
# ------------------------------------------------------------
# 📦 設定要用哪個 Firmware Profile
# ------------------------------------------------------------
ZP2_FW_PROFILE = options.get("zp2_fw_profile", "zp2_5_0_20251205_s01")
ZP2_OUTBOUND_SETUP = bool(options.get("zp2_outbound_setup", False))
# ------------------------------------------------------------
# 📂 讀取 ota_index.yaml
# ------------------------------------------------------------
OTA_INDEX = load_ota_index()
CURRENT_FW = OTA_INDEX.get(ZP2_FW_PROFILE)

if not CURRENT_FW:
    logging.error(f"[OTA] 找不到 FW profile：{ZP2_FW_PROFILE}，停用 OTA 功能")
    ZP2_FW_VERSION = None
    ZP2_FW_URL = None
else:
    ZP2_FW_VERSION = CURRENT_FW.get("version")
    rel_path = CURRENT_FW.get("path", "").lstrip("/")
    ZP2_FW_URL = f"{OTA_BASE_URL}/{rel_path}"
    logging.info(
        f"[OTA] 使用 profile={ZP2_FW_PROFILE}, version={ZP2_FW_VERSION}, url={ZP2_FW_URL}"
    )

# ------------------------------------------------------------
# 🧮 感測單位對照表(for ZS2)
# ------------------------------------------------------------
unit_conditions = {
    "ct": "°C",
    "t": "°C",
    "ch": "%",
    "h": "%",
    "p1": "µg/m³",
    "p25": "µg/m³",
    "p10": "µg/m³",
    "v": "ppm",
    "c": "ppm",
    "ec": "ppm",
    "rset": "rpm",
    "rpm": "rpm"
}

# ------------------------------------------------------------
# 🔁 檢查是否需要回傳控制指令(for ZS2)
# ------------------------------------------------------------
def check_and_respond_control(client, topic, message_json):
    parts = topic.split('/')
    if len(parts) < 3:
        return
    device_name, device_mac, message_type = parts

    has_required_payload = (
        message_json.get("Heartbeat") is not None or
        message_json.get("MODEL") is not None
    )

    if has_required_payload:
        control_topic = f"{device_name}/{device_mac}/control"
        control_payload = json.dumps({ "Update": "1" })
        client.publish(control_topic, control_payload)
        logging.info(f"Sent control message to {control_topic}: {control_payload}")

# ------------------------------------------------------------
# 🔗 MQTT 連線成功
# ------------------------------------------------------------
def on_connect(client, userdata, flags, rc):
    logging.info(f"Connected to MQTT broker with result code {rc}")
    for topic in TOPICS:
        client.subscribe(topic)
        logging.info(f"Subscribed to topic: {topic}")

# ------------------------------------------------------------
# 📨 處理 MQTT 訊息
# ------------------------------------------------------------
def on_message(client, userdata, msg):
    payload = msg.payload.decode()
    # logging.info(f"Received message on {msg.topic}: {payload}")

    try:
        # 先解析 JSON
        message_json = json.loads(payload)
        
        # 自動回應
        check_and_respond_control(client, msg.topic, message_json)
        
        # 提取 deviceName 和 deviceMac
        topic_parts = msg.topic.split('/')
        if len(topic_parts) < 3:
            logging.warning(f"Invalid topic format: {msg.topic}")
            return
        device_name = topic_parts[0]    # "ZP2"
        device_mac = topic_parts[1]     # number
        message_type = topic_parts[2]   # "data" or "control"

        fw = message_json.get("FW")

        if device_name != "ZP2" or message_type != "data":
            return
        
        if fw is None:
            logging.info(f"[ZP2] {device_name}/{device_mac} payload 無 FW，跳過")
            return

        if fw != ZP2_FW_VERSION:
            control_topic = f"{device_name}/{device_mac}/control"
            ota_payload = json.dumps({"Ota": ZP2_FW_URL}, separators=(",", ":"))
            threading.Thread(
                target=send_later,
                args=(client, control_topic, ota_payload, fw, 3.0, "OTA"),  # 最後的 1.0 是延遲秒數
                daemon=True,
            ).start()
        else:
            logging.info(f"[ZP2] FW({fw}) == 設定({ZP2_FW_VERSION})，無需更新")
            if ZP2_OUTBOUND_SETUP:
                control_topic = f"{device_name}/{device_mac}/control"
                ota_payload = json.dumps({"System":"reset"}, separators=(",", ":"))
                threading.Thread(
                    target=send_later,
                    args=(client, control_topic, ota_payload, fw, 3.0, "reset"),  # 最後的 1.0 是延遲秒數
                    daemon=True,
                ).start()
            return

        # # "ZP2" # number #"Action"
        threading.Thread(
            target=clear_and_rediscover,
            args=(client, device_name, device_mac, message_json),
            daemon=True
        ).start()

    except json.JSONDecodeError:
        logging.error(f"Failed to decode payload: {payload}")
    except Exception as e:
        logging.error(f"Error processing message: {e}")

def send_later(client, control_topic, ota_payload, fw, delay_sec=1.0, reason="OTA"):
    """延遲一段時間再送控制指令 (OTA 或 System reset 等)"""
    time.sleep(delay_sec)
    client.publish(control_topic, ota_payload)
    logging.info(
        f"[ZP2] ({reason}) 延遲 {delay_sec} 秒後發送到 {control_topic}: {ota_payload} (FW={fw})"
    )


# ------------------------------------------------------------
# 🏗️ 產生 MQTT Discovery Config（文字型）
# ------------------------------------------------------------
def generate_mqtt_discovery_textconfig(device_name, device_mac, sensor_type, sensor_name,format_version):
    """ 根據 MQTT 訊息生成 Home Assistant MQTT Discovery 設定 """
    # 生成 topic (註冊用全小寫)
    topic = f"{str(device_name)}/{str(device_mac)}/data"

    # 基本 config
    config = {
        "name": sensor_name,
        "state_topic": topic,
        # "availability_topic": f"{device_name}/{device_mac}/status",  # ← 新增 LWT 主題
        # "payload_available": "online",                 # LWT 上線訊息
        # "payload_not_available": "offline",            # LWT 離線訊息
        "expire_after": 300,
        "value_template": f"{{{{ value_json.{sensor_name} }}}}",
        "unique_id": f"{device_name}_{device_mac}_{sensor_name}",
        "device": {
            "identifiers": f"{device_name}_{device_mac}",
            "name": f"{device_name}_{device_mac}",
            "model": device_name,
            "manufacturer": device_name,
            # "sw_version": ADDON_VERSION,
            "hw_version": str(format_version) if format_version else "unknown"
        }
    }
    
    # 如果有單位才加上
    if sensor_name in unit_conditions:
        config["unit_of_measurement"] = unit_conditions[sensor_name]

    return config
# ------------------------------------------------------------
# 🔔 延遲 清除註冊 & 重新註冊
# ------------------------------------------------------------
def clear_and_rediscover(client, device_name, device_mac, message_json):
    # 這裡直接用整個 JSON 當作欄位來源
    data_sensors = message_json or {}

    # 如果你不想把某些欄位註冊成 sensor（例如 MODEL），可以在這裡過濾
    # 例如：
    # for k in ["MODEL"]:
    #     data_sensors.pop(k, None)

    format_version = data_sensors.get("FW")

    # ① 清除舊的 discovery
    clear_discovery_for_device(client, device_name, device_mac)

    # ② 等一小下，給 HA 時間處理
    time.sleep(0.7)

    # ③ 再發新的 discovery
    discovery_configs = []

    for sensor, value in data_sensors.items():
        cfg = generate_mqtt_discovery_textconfig(
            device_name, device_mac, "data", sensor, format_version
        )
        discovery_configs.append(cfg)

    for cfg in discovery_configs:
        discovery_topic = (
            f"homeassistant/sensor/"
            f"{str(device_name).lower()}_{str(device_mac).lower()}_{str(cfg['name']).lower()}/config"
        )
        payload = json.dumps(cfg, indent=2)
        client.publish(discovery_topic, payload, retain=True)
        logging.info(f"[rediscover] publish {discovery_topic}")

# ------------------------------------------------------------
# 🔔 清除註冊
# ------------------------------------------------------------
def clear_discovery_for_device(client, device_name, device_mac):
    """
    清掉 HA 裡面這台裝置所有對應的 MQTT Discovery config。
    做法：查 HA 所有 state，找出 sensor.<dev>_<mac>_*，逐一發空的 retain。
    config 相關全部小寫
    """
    dev = str(device_name).lower()
    mac = str(device_mac).lower()
    # dev = device_name
    # mac = device_mac
    prefix = f"sensor.{dev}_{mac}_"

    url = f"{BASE_URL}/states"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=5)
        resp.raise_for_status()
        states = resp.json()
    except Exception as e:
        logging.error(f"[rediscover] 無法取得 HA states，改成只清本次欄位: {e}")
        return False

    cleared = 0
    for s in states:
        eid = s.get("entity_id", "")
        if not eid.startswith(prefix):
            continue

        # sensor.xxx_yyy_zzz -> zzz
        sensor_suffix = eid.split(prefix, 1)[1]
        disc_topic = f"homeassistant/sensor/{dev}_{mac}_{sensor_suffix}/config"
        client.publish(disc_topic, "", retain=True)
        logging.info(f"[rediscover] clear {disc_topic}")
        cleared += 1

    logging.info(f"[rediscover] 已清除 {cleared} 筆舊的 discovery")
    return True
    
# ------------------------------------------------------------
# 🧱 複製 MQTT 橋接設定檔(for 中控橋接觀察數據 預設路徑192.168.51.8)
# ------------------------------------------------------------
# def create_mqtt_bridge_conf():
#     """ 複製 MQTT 桥接配置文件到目标目录 """
#     source_file = '/external_bridge.conf'  # 源文件路徑
#     target_directory = '/share/mosquitto/'  # 目標目錄路徑

#     try:
#         # 確保目標目錄存在，如果不存在就創建
#         os.makedirs(target_directory, exist_ok=True)
        
#         # 複製文件
#         shutil.copy(source_file, target_directory)
        
#         # 記錄成功訊息
#         logging.info(f"File {source_file} has been copied to {target_directory}")
#     except Exception as e:
#         # 錯誤處理，記錄錯誤訊息
#         logging.error(f"Error copying file {source_file} to {target_directory}: {e}")

# ------------------------------------------------------------
# 🚀 主程式
# ------------------------------------------------------------
def main():
    logging.info("Add-on started")

    # create_mqtt_bridge_conf()

    client = mqtt.Client()

    if MQTT_USERNAME and MQTT_PASSWORD:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_forever()  # 持續執行直到 Add-on 被 HA 關閉

if __name__ == "__main__":
    main()
