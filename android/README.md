# BandwidthPrediction — 5G 网络带宽测量与信号数据采集（Android 端）

> 📦 本目录是 [5G-Bandwidth-Estimation](../README.md) 仓库的 **Android 采集端**。完整的「数据采集 → 预处理 → XGBoost/LSTM 基线 → LLM 残差预测 → 评估」流程见仓库根目录 README。

![Android](https://img.shields.io/badge/Android-15%2B-3DDC84?logo=android)
![Java](https://img.shields.io/badge/Java-11-007396?logo=openjdk)

> A field measurement tool for 5G bandwidth estimation research: it actively probes uplink/downlink throughput while logging radio signal metrics (LTE/NR RSRP, RSRQ, SINR, CQI, cell identity), GPS, and carrier information at 1 Hz into CSV traces.

面向 **5G 带宽估计（Bandwidth Estimation / Prediction）研究** 的真实链路数据采集工具。App 在前台服务中：

- **主动探测带宽**：通过多路并发 HTTP 流对测试服务器持续打流，实时统计上行/下行吞吐量；
- **同步采集无线环境**：以 1 Hz 频率记录 LTE/NR 小区信号指标（主小区 + Top-3 邻区）、GPS 位置与速度、运营商和网络制式；
- **输出结构化数据集**：所有数据实时写入 CSV，可直接用于带宽预测模型的训练与验证。

---

## 核心功能

| 模块 | 说明 |
| --- | --- |
| 主动带宽探测 | 8 路并发 HTTP 流，每轮 15 秒，循环打流；下行拉取 Nginx 上的大文件，上行向 Python 接收端推流 |
| 吞吐量统计 | 基于 `TrafficStats` UID 计数器计算实时 Mbps，并附带滑动窗口方差 |
| 信号指标采集 | LTE（RSSI/RSRP/RSRQ/SNR/CQI）与 NR（SS-RSRP/SS-RSRQ/SS-SINR/CSI-*/CQI）主小区指标 + 按 RSRP 排序的 Top-3 邻区（SCell）指标 |
| 小区标识 | LTE ECI/EARFCN/PCI、NR NCI/ARFCN/PCI，可关联基站地理位置 |
| 5G 制式判定 | 结合 `getDataNetworkType()` 与 `TelephonyDisplayInfo` 区分 5G SA / 5G NSA / 5G+ / LTE |
| 稳定长时采集 | 前台服务 + WakeLock + 屏幕常亮 + 前台通知，防系统休眠和进程回收 |
| Modem 主动刷新 | 每秒调用 `requestCellInfoUpdate()` 强制刷新 modem 缓存，失效时回退到 3 秒内缓存数据 |
| 数据落盘 | 1 Hz 追加写入 CSV（48 列），带标准 CSV 转义，断电/杀进程不丢已写数据 |

## 系统架构

```
┌──────────────────┐  startForegroundService  ┌───────────────────────────────────┐
│   MainActivity   │ ────────────────────────▶ │        LoggingService (前台服务)    │
│  开始/停止采集     │   LOG_MODE: up / down     │                                   │
│  上/下行选择       │                          │  ┌─ 1Hz 日志循环 (logTask) ───────┐ │
└──────────────────┘                          │  │  getAllCellInfo → 信号/小区    │ │
                                              │  │  GPS 缓存 (500ms 更新)        │ │
                                              │  │  TrafficStats → 吞吐量         │ │
                                              │  │  CsvWriter → CSV 文件          │ │
                                              │  └────────────────────────────────┘ │
                                              │  ┌─ 探测线程 (循环) ────────────────┐ │
                                              │  │  down: 8 × GET  /big.bin        │ │
                                              │  │  up:   8 × POST /sample_upload  │ │
                                              │  └────────────────────────────────┘ │
                                              └───────────────────────────────────┘
                                              ┌───────────────────────────────────┐
        Nginx (80) 大文件下载  ◀────────────── │        测试服务器 (公网 VM)          │
        Python (8081) 上传接收 ◀────────────── │      server/ 目录提供搭建脚本        │
                                              └───────────────────────────────────┘
```

## 采集数据格式

CSV 输出路径：`/storage/emulated/0/Documents/BandwidthLogs/bandwidth_traces.csv`（可通过 `adb pull` 或文件管理器导出）。每行代表 1 秒的完整快照，共 48 列：

| 分组 | 字段 |
| --- | --- |
| 基础信息 | `Timestamp`, `Latitude`, `Longitude`, `Speed`, `Carrier`, `Network Type`, `State` (down/up/idle) |
| LTE 主小区信号 | `LTE_RSSI`, `LTE_RSRP`, `LTE_RSRQ`, `LTE_SNR`, `LTE_CQI` |
| NR 主小区信号 | `NR_SS_RSRP`, `NR_SS_RSRQ`, `NR_SS_SINR`, `NR_CQI`, `NR_CSI_RSRP`, `NR_CSI_RSRQ`, `NR_CSI_SINR` |
| 小区标识 | `LTE_ECI`, `LTE_EARFCN`, `LTE_PCI`, `NR_NCI`, `NR_ARFCN`, `NR_PCI` |
| 吞吐量 | `Downlink Avg(Mbps)`, `Download Variation(Mbps)`, `Uplink Avg(Mbps)`, `Uplink Var(Mbps)` |
| 其他 | `Probe Elapsed Time(ms)` |
| 邻区 SCell ×3 | `SCell{n}_Type/PCI/RSSI/RSRP/RSRQ/SNR`（按 RSRP 降序取前 3 个非注册小区，n=1,2,3） |

## 构建与运行

### 环境要求

- Android Studio（AGP 8.11+）与 **JDK 17+**
- `compileSdk 36`，`minSdk 35`（Android 15 及以上真机）
- 支持 5G 的 SIM 卡与套餐（采集 NR 指标需要；LTE 环境亦可运行）

### 使用步骤

1. 用 Android Studio 打开项目，编译并安装到真机。
2. 首次启动按提示授权：**定位**、**电话状态**（读取运营商/网络制式）、**所有文件访问**（Android 11+ 写 CSV 需要，App 会自动跳转系统设置页）。
3. 在界面选择 `Uplink` 或 `Downlink`，点击 **Start Logging** 开始采集（服务进入前台，通知栏可见）。
4. 测量完成后点击 **Stop Logging**，从 `Documents/BandwidthLogs/` 导出 CSV。

### ⚠️ 开始采集前必须修改测试服务器地址

`app/src/main/java/com/example/bandwidthprediction/LoggingService.java` 中的地址是实验期间的临时公网 VM，**很可能已失效**：

```java
private static final String DL_URL = "http://150.136.250.105/big.bin";          // 下行：Nginx 大文件
private static final String UL_URL = "http://172.190.185.191:8081/sample_upload"; // 上行：Python 接收端
```

替换为你自己的服务器地址，搭建方法见下方「服务端搭建」。

## 服务端搭建

测试带宽必须使用**带宽充足的公网服务器**，否则服务器出口带宽会成为瓶颈。

### 下行（Nginx 大文件）

1. 生成测试文件（建议 5–10 GB）：
   ```bash
   # Linux
   sudo truncate -s 10G /var/www/html/big.bin
   # Windows (PowerShell)
   fsutil file createnew C:\nginx\html\big.bin 10737418240
   ```
2. 使用 `server/nginx_download.conf` 中的配置片段（注意关闭 gzip，避免压缩影响测试结果），开放 80 端口。

### 上行（Python 接收端）

```bash
cd server
python3 upload_sink.py          # 默认监听 0.0.0.0:8081
```

脚本以 chunked 方式接收 App 推送的数据流并丢弃，实时打印接收速率，收到完整请求后返回 `204 No Content`。注意开放 8081 端口（云厂商安全组/防火墙）。

App 使用 HTTP 明文协议（Manifest 已开启 `usesCleartextTraffic`），测试服务器无需配置 HTTPS。

## 项目结构

```
android/                                 # 本目录（Android 采集端）
├── app/
│   └── src/main/
│       ├── java/com/example/bandwidthprediction/
│       │   ├── MainActivity.java      # UI：开始/停止采集，上/下行选择
│       │   ├── LoggingService.java    # 前台服务：1Hz 采集 + 主动带宽探测
│       │   └── CsvWriter.java         # CSV 写入（转义、追加、线程安全）
│       ├── res/                       # 布局、主题、图标
│       └── AndroidManifest.xml
├── server/
│   ├── upload_sink.py                 # 上行带宽测试接收端（Python 标准库，零依赖）
│   └── nginx_download.conf            # 下行带宽测试 Nginx 配置示例
├── gradle/                            # Gradle wrapper 与版本目录
├── build.gradle.kts
├── settings.gradle.kts
└── README.md
```

## 已知限制与说明

- **minSdk 35（Android 15）**：为保证前台服务 `dataSync` 类型与 5G API 行为一致。
- 吞吐量统计为 UID 级 `TrafficStats`（App 全部流量），探测流占总流量的绝大部分，稳态下误差很小。
- `requestCellInfoUpdate()` 可能被 modem 限流（`ERROR_MODEM_ERROR`），代码内置 3 秒缓存回退，但部分机型/运营商的信号刷新频率仍可能低于 1 Hz。
- NR 邻区（SCell）的可读性依赖设备与运营商实现，部分机型仅能读到注册小区。
- 本项目仅用于学术研究；公开数据集时请注意对 GPS/基站位置信息做脱敏处理。

## 后续计划（Roadmap）

- [ ] 数据清洗与分析脚本（缺失值处理、异常探测、可视化）
- [ ] 基于采集数据的带宽预测模型（特征工程 + 传统 ML / 序列模型）
- [ ] 采集参数配置化（流数、时长、采样率、服务器地址）
- [ ] 多运营商/多频段对比测试支持
