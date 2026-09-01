# scripts/ — 数据处理与模型训练脚本

本目录包含 5G 带宽预测项目的完整 ML 流水线。所有脚本相互独立（无跨文件 import），按**数据产物**串联。原始采集数据（GPS 轨迹、UE 调制解调器日志）未包含在仓库中，脚本中引用的数据文件需要先自行采集/准备。

## 流水线总览

```
bandwidth_traces_*.csv (App 采集)        *.UE1.json (NSG 调制解调器日志)
        │                                        │
        ▼                                        │
pre_merge_csvs.py (按设备合并) ◀──────────────────┘
        │
        ▼
merge_dataset.py (时间对齐 + 特征提取: MCS/BLER/RB/调制占比/SCell)
        │
        ▼
coalesced_bandwidth_traces.csv
        │
        ├─▶ preprocess_unified.py ──▶ dataset_*/train.jsonl + val.jsonl
        │                                      │
        │        ┌─────────────────────────────┼──────────────────────┐
        │        ▼                             ▼                      ▼
        │   train_xgboost_from_jsonl.py   train_llm_unified.py   extract_hard_samples.py
        │   (XGBoost 基线)                (Llama-3.1 QLoRA)           │
        │                                      │                      ▼
        │                                      ▼               split_for_cot.py
        │                              eval_checkpoint.py            │
        │                                                            ▼
        │                                                   cot/auto_cot_generation.py (Gemini 生成 CoT)
        │                                                            │
        │                                                            ▼
        │                                                   cot/process_merge_cot.py → train_with_cot.jsonl
        ▼
eval_baseline.py (未微调 LLM 零样本基线)
```

## 脚本清单

### 数据预处理与合并

| 脚本 | 功能 | 输入 | 输出 | 依赖 |
| --- | --- | --- | --- | --- |
| `clean_networktype.py` | 统一 Network Type 标签（`5G (NSA)`→`5G` 等） | 含 `Network Type` 列的 CSV | 清洗后 CSV | pandas |
| `pre_merge_csvs.py` | 按设备名合并多份采集 CSV 并排序 | `bandwidth_traces_*.csv` | `bandwidth_traces_MERGED_{device}.csv` | pandas |
| `merge_dataset.py` | **核心**：NSG JSON 与 App CSV 按时间对齐，提取 PCell/SCell、RLC/PHYS 吞吐、MCS/BLER/RB/调制占比等特征 | `bandwidth_traces_MERGED_*.csv` + `*.UE1.json` | `coalesced_bandwidth_traces.csv` | pandas |
| `merge_dataset_v2.py` | 上一代合并实现（MAX_SCELLS=4） | 同上 | 同上 | pandas |
| `merge_dataset_old.py` | 最早版本合并实现（MAX_SCELLS=8，简化） | 同上 | 同上 | pandas |
| `generate_cellfile.py` | 扫描 trace 生成小区 ID 模板，供人工补全经纬度/频段 | 任意 trace CSV | `cell_file_static.csv` | pandas |

### 特征工程（CSV → JSONL）

| 脚本 | 功能 | 输入 | 输出 | 依赖 |
| --- | --- | --- | --- | --- |
| `preprocess_unified.py` | 构造「历史窗口 + 当前网络状态 → 下一秒吞吐」预测 prompt，按会话分层切分 | `coalesced_bandwidth_traces.csv` | `dataset_{mode}_{history}_{window}[_scellsIn]/train.jsonl, val.jsonl` | pandas, sklearn |
| `preprocess_ucc.py` | 旧版：处理 UCC 公开数据集，构造 Llama 微调用 JSONL | `5G-production-dataset/**/*.csv` | `dataset_ucc_llama3_5g_only/train.jsonl, val.jsonl` | pandas, sklearn |

### 训练与评估

| 脚本 | 功能 | 输入 | 输出 | 依赖 |
| --- | --- | --- | --- | --- |
| `train_xgboost_from_jsonl.py` | 从 prompt 正则解析特征，训练 XGBoost 回归基线 | `dataset_*/train.jsonl, val.jsonl` | `predictor_xgboost_*/`（模型、metrics、特征重要性、散点图） | xgboost, sklearn |
| `train_llm_unified.py` | Llama-3.1-8B-Instruct 4-bit QLoRA 微调（TRL SFTTrainer，参数可配置） | `dataset_*/train.jsonl, val.jsonl` | `predictor_*/` LoRA 权重 | torch, transformers, peft, trl |
| `train_lora_llama3_bw.py` | 简化版 QLoRA 微调（固定参数，UCC 数据集） | `dataset_ucc_llama3_5g_only/` | `llama3-5g-predictor/` | 同上 |
| `eval_baseline.py` | 未微调 Llama-3.1-8B 零样本预测评估 | `dataset_nsg_full_3/val.jsonl` | `baseline_nsg_full_3/`（CSV + 散点图） | torch, transformers, sklearn |
| `eval_checkpoint.py` | 加载最新 LoRA checkpoint 评估 | `llama3-5g-predictor/checkpoint-*` + val.jsonl | `eval_result.png` + 控制台指标 | torch, transformers, peft |

### 难样本与 CoT 增强

| 脚本 | 功能 | 输入 | 输出 | 依赖 |
| --- | --- | --- | --- | --- |
| `extract_hard_samples.py` | 按 XGBoost 残差绝对值抽取 top N% 难样本 | `--input_file` JSONL | `{stem}_hard_top{N}.jsonl` + 误差分布图 | numpy, matplotlib |
| `split_for_cot.py` | 把难样本按 50 行/文件切分，供并行 CoT 生成 | `train_hard_top10.jsonl` | `train_1_50.jsonl` 等 | 标准库 |
| `cot/auto_cot_generation.py` | 调用 Gemini 为每个样本生成「Analysis + Final Residual」思维链 | `val_hard_top10.jsonl` | `val_hard_cot.jsonl` | google-generativeai |
| `cot/process_merge_cot.py` | 按 user 内容哈希对齐 CoT 结果，强制真值覆盖，合成完整训练集 | `train_hard_top10.jsonl` + `train_hard_cot.jsonl` + `train.jsonl` | `train_with_cot.jsonl` | hashlib, tqdm |

> `cot/auto_cot_generation.py` 需要环境变量 `GOOGLE_API_KEY`（Google AI Studio 申请），**不要在代码中硬编码密钥**。

### 可视化与分析

| 脚本 | 功能 | 输入 | 输出 |
| --- | --- | --- | --- |
| `plot_cqi_signal_scatter.py` | LTE RSRP/RSRQ/CQI 3D 散点 + 2D 均值热力图 | `coalesced_bandwidth_traces.csv` | `3d_signal_analysis.png`, `heatmap_signal_cqi.png` |
| `plot_cqi_throughput.py` | NR/LTE CQI 与下行吞吐箱线图 | 同上 | `figures/*_CQI_vs_Downlink.png` |
| `plot_SA_scell_contribution.py` | SA 模式主/辅小区物理层吞吐贡献箱线图 | 同上 | `pcell_vs_scell_boxplot.png` |
| `plot_unified.py` | 综合可视化（热力图、RB/MIMO、频段、SCell 贡献等） | 同上 | `figures/` 多张 PNG |
| `band_investigation.py` | 用频段容量 + SCell 变化定位「PCell 稳定但 SCell 突变」关键事件 | 同上 | 控制台统计 |
| `generate_map.py` | folium 生成 GPS 吞吐热力点地图 | 同上 | `5g_dots_map.html` ⚠️ 含真实轨迹，勿公开 |

### 服务端

| 脚本 | 功能 | 依赖 |
| --- | --- | --- |
| `server.py` | FastAPI 测速服务端：`/connection_test` 健康检查、`/sample_upload` 上行接收（204）、`/sample_download` 大文件下载（路径用 `BIG_BIN_PATH` 环境变量配置） | fastapi, uvicorn |

## 使用方式

```bash
pip install -r requirements.txt

# 按流水线顺序执行（数据文件需自行准备）
python pre_merge_csvs.py
python merge_dataset.py
python preprocess_unified.py
python train_xgboost_from_jsonl.py
python train_llm_unified.py --data_dir dataset_nsg_5g_only --output_dir predictor_nsg_5g_only
python eval_baseline.py
python eval_checkpoint.py
```

## 说明

- 基座模型 `meta-llama/Meta-Llama-3.1-8B-Instruct` 是 Hugging Face gated 模型，需先申请访问权限并通过 `huggingface-cli login` 配置 token（不要写入代码）。
- 大部分脚本默认从**当前工作目录**读取数据文件（如 `coalesced_bandwidth_traces.csv`、`dataset_*/`），运行前请把数据放到脚本所在目录或使用脚本提供的路径参数。
- LLM 训练与评估需要 GPU（4-bit QLoRA 8B 模型约 24GB+ 显存）。
