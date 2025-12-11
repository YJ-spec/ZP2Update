# ZP2 Integration Add-on 說明文件（精簡版）

## 功能簡介

此 Home Assistant Add-on 用於整合 ZP2 裝置，主要提供兩大功能：

1. 自動比對 ZP2 裝置回報的韌體版本（FW）
2. 若裝置版本與設定不一致，則自動回覆 OTA 更新指令

Add-on 會從 MQTT 接收： ZP2/<MAC>/data


並根據設定中的以下兩個參數判斷是否需要 OTA：

- `ZP2_FW_VERSION`
- `ZP2_FW_URL`


## ZP2 設定說明

Add-on 安裝後，在：

Home Assistant → 設定 → 外掛程式 → **ZP2 Integration** → 設定

你會看到兩個與 ZP2 相關的重要欄位：

### 1. `zp2_fw_version`
指定 ZP2 應該使用的目標韌體版本號。

### 2. `zp2_fw_url`
指定 OTA 時 ZP2 要下載的韌體檔案 URL。
