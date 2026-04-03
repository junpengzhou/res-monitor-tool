import subprocess
import re
import time
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime

# 初始化数据存储结构
data = []

# 设置采集次数和间隔
duration_seconds = 60  # 总共采集60秒
interval_seconds = 2  # 每隔2秒采集一次

print("开始采集 Docker 容器资源使用情况...")
start_time = time.time()

try:
    while time.time() - start_time < duration_seconds:
        # 执行 docker stats 命令，获取所有容器的状态（仅一次快照）
        result = subprocess.run(
            ["docker", "stats", "--no-stream", "--format",
             "{{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        lines = result.stdout.strip().split('\n')

        current_time = datetime.now()

        for line in lines:
            if not line:
                continue

            parts = line.split('\t')
            container_id = parts[0][:12]  # 截取前12位作为容器ID
            cpu_percent_str = parts[1].replace('%', '')
            mem_usage_str = parts[2].split('/')[0].replace('MiB', '').replace('GiB', '')

            try:
                cpu_percent = float(cpu_percent_str)
                mem_usage = float(re.findall(r"[\d.]+", mem_usage_str)[0])
            except Exception as e:
                print(f"解析错误: {line}, 错误信息: {e}")
                continue

            data.append({
                'timestamp': current_time,
                'container_id': container_id,
                'cpu_percent': cpu_percent,
                'mem_usage': mem_usage
            })

        time.sleep(interval_seconds)

except KeyboardInterrupt:
    print("\n手动停止采集。")

# 转换为 DataFrame
df = pd.DataFrame(data)

# 保存为 CSV 文件
csv_filename = "docker_stats.csv"
df.to_csv(csv_filename, index=False)
print(f"Docker 资源使用数据已保存至 {csv_filename}")

# 可视化部分
plt.rcParams['font.sans-serif'] = ['Noto Sans CJK JP']
plt.rcParams['axes.unicode_minus'] = False

# 按容器 ID 分组绘图
for container_id in df['container_id'].unique():
    subset = df[df['container_id'] == container_id]

    fig, ax1 = plt.subplots(figsize=(12, 6))

    color = 'tab:blue'
    ax1.set_xlabel('时间')
    ax1.set_ylabel('CPU (%)', color=color)
    ax1.plot(subset['timestamp'], subset['cpu_percent'], label='CPU (%)', color=color, marker='o')
    ax1.tick_params(axis='y', labelcolor=color)

    ax2 = ax1.twinx()
    color = 'tab:red'
    ax2.set_ylabel('内存 (MiB)', color=color)
    ax2.plot(subset['timestamp'], subset['mem_usage'], label='内存 (MiB)', color=color, marker='s')
    ax2.tick_params(axis='y', labelcolor=color)

    fig.tight_layout()
    plt.title(f'Docker 容器 {container_id} 的 CPU 和内存使用情况')
    plt.grid(True)

    image_filename = f"docker_stats_{container_id}.png"
    plt.savefig(image_filename)
    print(f"图表已保存为 {image_filename}")
    plt.close()