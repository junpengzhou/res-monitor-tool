#!/usr/bin/env python3
import json
import logging
import sys
import time
from datetime import datetime

import psutil


class SystemIOMonitor:
    def __init__(self, log_file="frank_io_monitor.log", interval=10, threshold_alert=True):
        """
        初始化监控器

        Args:
            log_file: 日志文件路径
            interval: 监控间隔(秒)，默认10秒
            threshold_alert: 是否启用阈值警报
        """
        self.logger = None
        self.interval = interval
        self.threshold_alert = threshold_alert
        self.log_file = log_file

        # 初始化前一次的快照用于计算差值
        self.prev_disk_io = None
        self.prev_net_io = None
        self.prev_time = None
        self.thresholds = {
            'memory_percent': 80,  # 内存使用率阈值%
            'disk_read_bytes_per_sec': 104857600,  # 磁盘读取速率阈值100MB/s
            'disk_write_bytes_per_sec': 104857600,  # 磁盘写入速率阈值100MB/s
            'swap_usage_percent': 70,  # 交换空间使用率阈值%
            'io_wait_percent': 30,  # IO等待时间阈值%
        }

        self.setup_logging()

    def setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(self.log_file),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger('FrankIOMonitor')

        self.logger.info("=" * 60)
        self.logger.info("Frank磁盘和内存IO监控启动")
        self.logger.info(f"监控间隔: {self.interval}秒")
        self.logger.info(f"日志文件: {self.log_file}")
        self.logger.info("=" * 60)

    def get_disk_io_stats(self):
        current_disk_io = psutil.disk_io_counters()
        current_time = time.time()

        if self.prev_disk_io is None or self.prev_time is None:
            self.prev_disk_io = current_disk_io
            self.prev_time = current_time
            return {'read_bytes_ps': 0, 'write_bytes_ps': 0, 'read_count_ps': 0, 'write_count_ps': 0}

        time_delta = current_time - self.prev_time

        # 计算每秒速率
        read_bytes_ps = (current_disk_io.read_bytes - self.prev_disk_io.read_bytes) / time_delta
        write_bytes_ps = (current_disk_io.write_bytes - self.prev_disk_io.write_bytes) / time_delta
        read_count_ps = (current_disk_io.read_count - self.prev_disk_io.read_count) / time_delta
        write_count_ps = (current_disk_io.write_count - self.prev_disk_io.write_count) / time_delta

        # 更新前一次状态
        self.prev_disk_io = current_disk_io
        self.prev_time = current_time

        return {
            'read_bytes_ps': read_bytes_ps,
            'write_bytes_ps': write_bytes_ps,
            'read_count_ps': read_count_ps,
            'write_count_ps': write_count_ps
        }

    @staticmethod
    def get_memory_stats():
        virtual_memory = psutil.virtual_memory()
        swap_memory = psutil.swap_memory()

        return {
            'memory_total_gb': virtual_memory.total / (1024 ** 3),
            'memory_used_gb': virtual_memory.used / (1024 ** 3),
            'memory_available_gb': virtual_memory.available / (1024 ** 3),
            'memory_percent': virtual_memory.percent,
            'swap_total_gb': swap_memory.total / (1024 ** 3),
            'swap_used_gb': swap_memory.used / (1024 ** 3),
            'swap_percent': swap_memory.percent,
            'swap_in_ps': swap_memory.sin if hasattr(swap_memory, 'sin') else 0,
            'swap_out_ps': swap_memory.sout if hasattr(swap_memory, 'sout') else 0
        }

    @staticmethod
    def get_cpu_io_wait():
        cpu_times = psutil.cpu_times_percent(interval=1)
        return getattr(cpu_times, 'iowait', 0)

    @staticmethod
    def get_disk_usage():
        # 监控根目录和常见的数据目录
        partitions = []
        for partition in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(partition.mountpoint)
                partitions.append({
                    'device': partition.device,
                    'mount_point': partition.mountpoint,
                    'total_gb': usage.total / (1024 ** 3),
                    'used_gb': usage.used / (1024 ** 3),
                    'free_gb': usage.free / (1024 ** 3),
                    'percent': usage.percent
                })
            except PermissionError:
                continue

        return partitions

    def check_thresholds(self, metrics):
        alerts = []

        # 内存使用率检查
        if metrics['memory_percent'] > self.thresholds['memory_percent']:
            alerts.append(f"内存使用率过高: {metrics['memory_percent']:.1f}% > {self.thresholds['memory_percent']}%")

        # 磁盘IO速率检查
        disk_io = metrics['disk_io']
        if disk_io['read_bytes_ps'] > self.thresholds['disk_read_bytes_per_sec']:
            alerts.append(
                f"磁盘读取速率过高: {disk_io['read_bytes_ps'] / 1048576:.1f}MB/s > {self.thresholds['disk_read_bytes_per_sec'] / 1048576}MB/s")

        if disk_io['write_bytes_ps'] > self.thresholds['disk_write_bytes_per_sec']:
            alerts.append(
                f"磁盘写入速率过高: {disk_io['write_bytes_ps'] / 1048576:.1f}MB/s > {self.thresholds['disk_write_bytes_per_sec'] / 1048576}MB/s")

        # 交换空间检查
        if metrics['memory']['swap_percent'] > self.thresholds['swap_usage_percent']:
            alerts.append(
                f"交换空间使用率过高: {metrics['memory']['swap_percent']:.1f}% > {self.thresholds['swap_usage_percent']}%")

        # IO等待时间检查
        if metrics['io_wait_percent'] > self.thresholds['io_wait_percent']:
            alerts.append(f"IO等待时间过长: {metrics['io_wait_percent']:.1f}% > {self.thresholds['io_wait_percent']}%")

        return alerts

    @staticmethod
    def format_metrics_for_log(metrics, alerts):
        log_data = {
            'timestamp': datetime.now().isoformat(),
            'memory': {
                'used_gb': metrics['memory']['memory_used_gb'],
                'available_gb': metrics['memory']['memory_available_gb'],
                'percent': metrics['memory']['memory_percent'],
                'swap_percent': metrics['memory']['swap_percent']
            },
            'disk_io': {
                'read_mb_ps': metrics['disk_io']['read_bytes_ps'] / 1048576,
                'write_mb_ps': metrics['disk_io']['write_bytes_ps'] / 1048576,
                'read_count_ps': metrics['disk_io']['read_count_ps'],
                'write_count_ps': metrics['disk_io']['write_count_ps']
            },
            'io_wait_percent': metrics['io_wait_percent'],
            'alerts': alerts,
            'disk_usage': [{
                'mount_point': part['mount_point'],
                'percent': part['percent']
            } for part in metrics['disk_usage'][:2]]  # 只记录前两个分区
        }

        return json.dumps(log_data)

    def run_monitoring(self, duration_hours=24):
        """
        运行监控循环
        Args:
            duration_hours: 监控持续时间(小时)
        """
        self.logger.info(f"开始监控，计划运行 {duration_hours} 小时")
        end_time = time.time() + duration_hours * 3600

        try:
            while time.time() < end_time:
                metrics = {
                    'disk_io': self.get_disk_io_stats(),
                    'memory': self.get_memory_stats(),
                    'io_wait_percent': self.get_cpu_io_wait(),
                    'disk_usage': self.get_disk_usage()
                }

                # 检查阈值
                alerts = []
                if self.threshold_alert:
                    alerts = self.check_thresholds(metrics)

                # 记录日志
                log_entry = self.format_metrics_for_log(metrics, alerts)
                self.logger.info(log_entry)

                # 如果有警报，额外记录警告日志
                if alerts:
                    for alert in alerts:
                        self.logger.warning(f"ALERT: {alert}")

                # 等待下一个监控间隔
                time.sleep(self.interval)

        except KeyboardInterrupt:
            self.logger.info("监控被用户中断")
        except Exception as e:
            self.logger.error(f"监控过程中发生错误: {str(e)}")
        finally:
            self.logger.info("RabbitMQ IO监控停止")


def main():
    """主函数"""
    monitor_config = {
        'log_file': '/var/log/rabbitmq_io_monitor.log',
        'interval': 10,
        'threshold_alert': True
    }
    monitor = SystemIOMonitor(**monitor_config)
    monitor.run_monitoring(duration_hours=24)


if __name__ == "__main__":
    main()
