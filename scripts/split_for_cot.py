import os
import math

# ================= 配置区域 =================
# 输入文件名 (请确保这个文件在当前目录下)
INPUT_FILE = "train_hard_top10.jsonl" 
# 输出子文件夹名称
OUTPUT_DIR = "CoT Preparation"
# 每个文件包含多少行 (你设定的50)
CHUNK_SIZE = 50
# ===========================================

def main():
    # 1. 检查输入文件是否存在
    if not os.path.exists(INPUT_FILE):
        print(f" 错误: 找不到文件 '{INPUT_FILE}'")
        print("请检查文件名是否正确，或者文件是否在当前目录下。")
        return

    # 2. 创建输出文件夹
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        print(f" 已创建文件夹: {OUTPUT_DIR}")
    else:
        print(f" 文件夹已存在: {OUTPUT_DIR}")

    # 3. 读取所有数据
    print(f"正在读取 {INPUT_FILE} ...")
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    total_samples = len(lines)
    print(f" 总样本数: {total_samples}")

    # 4. 开始切分
    # 计算需要切成多少份
    num_chunks = math.ceil(total_samples / CHUNK_SIZE)
    
    print(f" 开始切分，每份 {CHUNK_SIZE} 条，共计 {num_chunks} 个文件...")

    for i in range(num_chunks):
        # 计算切片的起始和结束索引
        start_index = i * CHUNK_SIZE
        end_index = min((i + 1) * CHUNK_SIZE, total_samples)
        
        # 获取这一块的数据
        chunk_lines = lines[start_index:end_index]
        
        # 生成文件名 (人类友好的 1-based 索引)
        # 比如 train_1_50.jsonl, train_51_100.jsonl
        file_name = f"train_{start_index + 1}_{end_index}.jsonl"
        file_path = os.path.join(OUTPUT_DIR, file_name)
        
        # 写入小文件
        with open(file_path, 'w', encoding='utf-8') as out_f:
            out_f.writelines(chunk_lines)
            
        print(f"  已保存: {file_path} ({len(chunk_lines)} 条)")

    print("\n 全部完成！")
    print(f"请进入 '{OUTPUT_DIR}' 文件夹查看分割后的文件。")

if __name__ == "__main__":
    main()