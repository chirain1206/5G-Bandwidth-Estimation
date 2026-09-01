# 5G-Bandwidth-Estimation

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python)
![PyTorch](https://img.shields.io/badge/PyTorch-2.x-EE4C2C?logo=pytorch)
![XGBoost](https://img.shields.io/badge/XGBoost-2.x-3376C6)
![Android](https://img.shields.io/badge/Android-15%2B-3DDC84?logo=android)

> **5G 网络带宽估计（Bandwidth Estimation）端到端研究项目**：从 Android 真机实地测量采集无线信号与吞吐量数据，到数据预处理、XGBoost / LSTM 基线建模、LLM（LoRA 微调）残差预测，再到完整评估与可视化。

**核心研究问题**：能否仅凭设备可观测的无线信号指标（RSRP/RSRQ/SINR/CQI、RB 分配、调制方式、SCell 等）实时预测下行吞吐量？LLM 是否比传统 ML 模型更擅长捕捉突变事件（切换、CQI 骤降、SCell 变化、突发拥塞）？

---

## 项目流水线

```
┌─────────────────┐   ┌──────────────────┐   ┌──────────────────────────────┐
│  android/        │   │  scripts/         │   │  评估与可视化                  │
│  真机数据采集     │──▶│  清洗 / 合并 /     │──▶│  evaluation/ + figures/       │
│  1Hz 信号+吞吐量  │   │  特征工程 → JSONL  │   │  MAE / RMSE / R² / 对比图      │
└─────────────────┘   └────────┬─────────┘   └──────────────────────────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
        XGBoost 基线      LSTM 基线      LLM 残差预测
        (传统特征)        (时序建模)     Llama-3.1-8B QLoRA
                                        + Gemini 自动生成 CoT
```

## 目录结构

```
5G-Bandwidth-Estimation/
├── android/                 # Android 采集端（真机 1Hz 信号 + 主动带宽探测）
│   ├── app/                 #   详见 android/README.md
│   └── server/              #   打流服务器（Nginx + Python）
├── scripts/                 # 数据预处理 / 训练 / 评估脚本（详见 scripts/README.md）
│   └── cot/                 #   Chain-of-Thought 数据生成与合并
├── evaluation/              # 模型评估结果（CSV）与事件级对比图（PNG）
│   ├── lstm_result/         #   LSTM 模型评估输出
│   ├── lstm_scellsIn_result/
│   └── old_lstm_result/
├── figures/                 # 数据探索与假设验证图表
├── docs/
│   ├── presentations/       # 项目汇报 PPT
│   └── implementation-history/  # LoggingService 历史版本
└── README.md
```

## 各模块说明

### 1. `android/` — 实地测量数据采集

Android 15+ 真机 App：前台服务以 **1 Hz** 记录 LTE/NR 主小区与 Top-3 邻区信号指标、GPS、运营商/制式，同时用 **8 路并发 HTTP 流**主动探测上下行吞吐量，实时写入 48 列 CSV。构建、权限与使用说明见 [android/README.md](android/README.md)。

### 2. `scripts/` — 数据处理与模型训练

| 阶段 | 脚本 | 说明 |
| --- | --- | --- |
| 数据清洗 | `clean_networktype.py` | 清洗 Network Type 标签（5G SA/NSA 判定） |
| 数据合并 | `pre_merge_csvs.py` / `merge_dataset*.py` | 多日、多设备采集 CSV 与 NSG 调制解调器日志的时间对齐合并（`merge_dataset.py` 为最新版，`merge_dataset_v2.py`、`merge_dataset_old.py` 为历史版本） |
| 特征工程 | `preprocess_unified.py` / `preprocess_ucc.py` | 统一特征工程，输出 LLM 训练用 JSONL（prompt = 历史 + 当前信号状态，label = 下一秒吞吐量） |
| 小区信息 | `generate_cellfile.py` | 扫描 trace 生成小区 ID 模板（ECI/PCI → 人工补全经纬度/频段） |
| 基线训练 | `train_xgboost_from_jsonl.py` | XGBoost 吞吐量回归基线（含特征重要性与指标输出） |
| LLM 微调 | `train_llm_unified.py` / `train_lora_llama3_bw.py` | Llama-3.1-8B-Instruct 4-bit QLoRA 微调（TRL SFTTrainer） |
| 模型评估 | `eval_baseline.py` / `eval_checkpoint.py` | 未微调基线 vs 微调 checkpoint 的 MAE/RMSE/R² 评估 |
| 难样本 | `extract_hard_samples.py` / `split_for_cot.py` | 按 XGBoost 残差提取难样本、切分 CoT 生成子任务 |
| CoT 生成 | `cot/auto_cot_generation.py` / `cot/process_merge_cot.py` | 用 Gemini 自动生成 Chain-of-Thought 分析（需 `GOOGLE_API_KEY` 环境变量），按内容哈希对齐真值后合并回训练集 |
| 可视化 | `plot_*.py` / `generate_map.py` / `band_investigation.py` | 信号-吞吐量关系、SCell 贡献、频段分布、事件定位等分析 |
| 打流服务 | `server.py` | FastAPI 版上传/下载测速服务端 |

每个脚本的输入输出与依赖详见 [scripts/README.md](scripts/README.md)。

### 3. `evaluation/` — 评估结果

- `full_performance_comparison.png`：各模型（XGBoost / LSTM / MA / LLM / LLM+residual / LLM+CoT）整体性能对比
- `plot_evt_*.png`：切换、CQI 骤降、SCell 变化、频段切换、波动事件下的模型表现对比
- `eval_application_throughput_full_3_*.csv`：逐样本预测明细（Ground Truth / Predicted / Abs Error / 推理耗时）
- `lstm_result/`、`lstm_scellsIn_result/`、`old_lstm_result/`：LSTM 系列模型的完整评估输出

### 4. `figures/` — 数据探索

数据假设验证与探索性分析图表：信号-吞吐量散点、CQI vs 下行速率、5G 频段分布、SCell 改善幅度、MIMO/RB 分配验证等。

### 5. `docs/` — 汇报材料

- `presentations/group-presentation.pptx`：项目汇报 PPT（含研究动机、方法、结果）
- `implementation-history/`：采集端 `LoggingService` 的迭代历史版本，展示实现演进

## 快速开始

### 采集数据（可选，已有数据可跳过）

1. 按 [android/README.md](android/README.md) 搭建打流服务器、编译安装 App；
2. 真机授权后选择上/下行开始采集，导出 CSV。

### 训练与评估

```bash
# 0. 安装依赖
pip install -r scripts/requirements.txt

# 1. 数据合并与特征工程（生成 JSONL 训练集）
python scripts/pre_merge_csvs.py
python scripts/merge_dataset.py
python scripts/preprocess_unified.py

# 2. XGBoost 基线
python scripts/train_xgboost_from_jsonl.py

# 3. LLM LoRA 微调（需要 GPU + Hugging Face gated 模型访问权限）
python scripts/train_llm_unified.py --data_dir dataset_nsg_5g_only --output_dir predictor_nsg_5g_only

# 4. 评估（基线 vs 微调）
python scripts/eval_baseline.py
python scripts/eval_checkpoint.py

# 5. （可选）生成 CoT 增强训练数据
# $env:GOOGLE_API_KEY="..."   # Google AI Studio 申请的 Gemini API Key
python scripts/cot/auto_cot_generation.py
python scripts/cot/process_merge_cot.py
```

> 注意：基座模型 `meta-llama/Meta-Llama-3.1-8B-Instruct` 是 Hugging Face gated 模型，需先在 HF 官网申请访问权限并用 `huggingface-cli login` 配置 token（不要把 token 写进代码）。

## 数据说明（重要）

本仓库**不包含原始采集数据**：`traces`（GPS 轨迹、UE 调制解调器日志、CoT 训练 JSONL）和原始 CSV 因包含真实位置轨迹与基站级信息，仅保留在本地，未公开上传。

- 仓库内 `evaluation/` 的 CSV 仅含模型预测结果与指标（无 GPS 列）；
- 采集工具与全部预处理/训练脚本完整，可自行采集数据完整复现流程；
- 如需原始数据用于学术合作，可通过 issue 联系。

## 技术栈

- **采集端**：Android 15+ / Java / TelephonyManager & CellInfo API / TrafficStats / 前台服务
- **数据处理**：Python / pandas / NumPy
- **传统基线**：XGBoost / LSTM（PyTorch）
- **LLM**：Meta-Llama-3.1-8B-Instruct、4-bit QLoRA（bitsandbytes + PEFT）、TRL SFTTrainer、FlashAttention-2
- **CoT 生成**：Google Gemini API
- **评估**：MAE / RMSE / R²、matplotlib 事件级对比

## 已知限制

- LLM 微调需要约 24GB+ 显存（4-bit QLoRA 8B 模型）或云 GPU；
- 评估 CSVs 中的 `qwen` 系列为实验期间的 Qwen 模型对比结果，对应训练脚本未包含在本仓库；
- 原始数据未公开，仓库中的结果图表为实验期产物，无法仅凭本仓库文件重新生成全部图表。
