import redis
import pandas as pd
from collections import defaultdict
import time
from datetime import datetime
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class RedisKeyAnalyzer:
    def __init__(self, host='localhost', port=6379, password=None, db=0):
        """
        初始化Redis连接
        :param host: Redis主机地址
        :param port: Redis端口
        :param password: Redis密码
        :param db: Redis数据库编号
        """
        try:
            self.redis_client = redis.Redis(
                host=host,
                port=port,
                password=password,
                db=db,
                socket_connect_timeout=10,
                socket_timeout=30,
                decode_responses=True
            )
            # 测试连接
            self.redis_client.ping()
            logger.info("Redis连接成功")
        except Exception as e:
            logger.error(f"Redis连接失败: {e}")
            raise

    def safe_scan_keys(self, pattern='*', batch_size=5000, sleep_interval=0.01):
        """
        安全扫描Key，使用SCAN命令避免阻塞
        :param pattern: 键模式匹配
        :param batch_size: 每次扫描的批大小
        :param sleep_interval: 批次间的休眠时间（秒）
        :return: 键列表生成器
        """
        cursor = 0
        total_scanned = 0

        try:
            while True:
                cursor, keys = self.redis_client.scan(
                    cursor=cursor,
                    match=pattern,
                    count=batch_size
                )

                for key in keys:
                    yield key
                    total_scanned += 1

                if cursor == 0:
                    # 扫描完成, 退出循环
                    break

                if sleep_interval and sleep_interval > 0:
                    # 避免对Redis造成压力，小睡一下
                    time.sleep(sleep_interval)

                # 每扫描50000个key打印进度
                if total_scanned % 50000 == 0:
                    logger.info(f"已扫描 {total_scanned} 个key")

        except Exception as e:
            logger.error(f"扫描Key时发生错误: {e}")
            raise

    def analyze_key_memory(self, key):
        """
        分析单个Key的内存使用情况
        :param key: 键名
        :return: 内存信息字典
        """
        try:
            # 获取Key的类型
            key_type = self.redis_client.type(key)

            # 获取内存使用量（字节）
            memory_usage = self.redis_client.memory_usage(key)

            # 获取TTL
            ttl = self.redis_client.ttl(key)

            # 根据Key类型获取额外信息
            extra_info = self._get_extra_key_info(key, key_type)

            # 分析Key的层级结构
            hierarchy = self._analyze_key_hierarchy(key)

            return {
                'key': key,
                'type': key_type,
                'memory_usage_bytes': memory_usage or 0,
                'memory_usage_mb': round((memory_usage or 0) / (1024 * 1024), 4),
                'ttl_seconds': ttl,
                'ttl_human': self._format_ttl(ttl),
                'hierarchy_level': hierarchy['level'],
                'hierarchy_path': hierarchy['path'],
                **extra_info
            }

        except Exception as e:
            logger.warning(f"分析Key {key} 时出错: {e}")
            return None

    def _get_extra_key_info(self, key, key_type):
        """
        根据Key类型获取额外信息
        """
        extra_info = {}
        try:
            if key_type == 'string':
                # 字符串长度
                length = self.redis_client.strlen(key)
                extra_info = {'value_length': length}

            elif key_type == 'list':
                # 列表长度
                length = self.redis_client.llen(key)
                extra_info = {'list_length': length}

            elif key_type == 'set':
                # 集合大小
                length = self.redis_client.scard(key)
                extra_info = {'set_size': length}

            elif key_type == 'zset':
                # 有序集合大小
                length = self.redis_client.zcard(key)
                extra_info = {'zset_size': length}

            elif key_type == 'hash':
                # 哈希字段数量
                length = self.redis_client.hlen(key)
                extra_info = {'hash_fields': length}

        except Exception as e:
            logger.debug(f"获取Key {key} 的额外信息失败: {e}")

        return extra_info

    def _analyze_key_hierarchy(self, key):
        """
        分析Key的层级结构
        """
        # 常见的分隔符
        separators = [':', '.', '-', '_', '/']

        for sep in separators:
            if sep in key:
                parts = key.split(sep)
                return {
                    'level': len(parts),
                    'path': sep.join(parts[:2]) if len(parts) > 1 else parts[0]
                }

        # 没有明显层级结构
        return {'level': 1, 'path': key}

    def _format_ttl(self, ttl):
        """
        格式化TTL为可读格式
        """
        if ttl == -1:  # 没有设置过期时间
            return "永不过期"
        elif ttl == -2:  # Key不存在
            return "Key不存在"
        else:
            # 转换为天、小时、分钟、秒
            days = ttl // (24 * 3600)
            hours = (ttl % (24 * 3600)) // 3600
            minutes = (ttl % 3600) // 60
            seconds = ttl % 60

            if days > 0:
                return f"{days}天{hours}小时"
            elif hours > 0:
                return f"{hours}小时{minutes}分钟"
            elif minutes > 0:
                return f"{minutes}分钟{seconds}秒"
            else:
                return f"{seconds}秒"

    def generate_space_report(self, sample_size=100000, max_keys=None):
        """
        生成空间分析报告
        :param sample_size: 采样大小（如果Key太多可以采样）
        :param max_keys: 最大分析Key数量（None表示无限制）
        """
        logger.info("开始生成Redis空间分析报告...")

        # 存储分析结果
        results = []
        hierarchy_stats = defaultdict(lambda: {
            'count': 0,
            'total_memory_bytes': 0.0,
            'total_memory_mb': 0.0,
            'avg_memory_mb': 0.0,
            'no_ttl_count': 0
        })

        type_stats = defaultdict(lambda: {
            'count': 0,
            'total_memory_bytes': 0,
            'total_memory_mb': 0
        })

        analyzed_count = 0
        start_time = time.time()

        try:
            for key in self.safe_scan_keys():
                if max_keys and analyzed_count >= max_keys:
                    break

                # 采样控制
                if analyzed_count < sample_size or sample_size == 0:
                    key_info = self.analyze_key_memory(key)
                    if key_info:
                        results.append(key_info)

                        # 统计层级信息
                        hierarchy_path = key_info['hierarchy_path']
                        hierarchy_stats[hierarchy_path]['count'] += 1
                        hierarchy_stats[hierarchy_path]['total_memory_bytes'] += key_info['memory_usage_bytes']
                        hierarchy_stats[hierarchy_path]['total_memory_mb'] += key_info['memory_usage_mb']

                        # 没有TTL
                        if key_info['ttl_seconds'] == -1:
                            hierarchy_stats[hierarchy_path]['no_ttl_count'] += 1

                        # 统计类型信息
                        key_type = key_info['type']
                        type_stats[key_type]['count'] += 1
                        type_stats[key_type]['total_memory_bytes'] += key_info['memory_usage_bytes']
                        type_stats[key_type]['total_memory_mb'] += key_info['memory_usage_mb']

                analyzed_count += 1

                # 进度显示
                if analyzed_count % 1000 == 0:
                    elapsed = time.time() - start_time
                    logger.info(f"已分析 {analyzed_count} 个Key, 耗时: {elapsed:.2f}秒")

        except Exception as e:
            logger.error(f"生成报告时发生错误: {e}")

        # 计算平均内存
        for path in hierarchy_stats:
            stats = hierarchy_stats[path]
            if stats['count'] > 0:
                stats['avg_memory_mb'] = stats['total_memory_mb'] / stats['count']

        elapsed_time = time.time() - start_time
        logger.info(f"分析完成! 总共分析 {analyzed_count} 个Key, 耗时: {elapsed_time:.2f}秒")

        return {
            'detailed_results': results,
            'hierarchy_stats': dict(hierarchy_stats),
            'type_stats': dict(type_stats),
            'summary': {
                'total_keys_analyzed': analyzed_count,
                'analysis_time_seconds': elapsed_time,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        }

    def export_to_excel(self, report, filename_prefix='redis_space_analysis'):
        """
        导出分析结果到Excel文件
        """
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{filename_prefix}_{timestamp}.xlsx"

            with pd.ExcelWriter(filename, engine='openpyxl') as writer:
                # 1. 详细Key信息表
                if report['detailed_results']:
                    df_detailed = pd.DataFrame(report['detailed_results'])
                    df_detailed.to_excel(writer, sheet_name='Key详细信息', index=False)

                # 2. 层级统计表
                hierarchy_data = []
                for path, stats in report['hierarchy_stats'].items():
                    hierarchy_data.append({
                        '层级路径': path,
                        'Key数量': stats['count'],
                        '总内存(MB)': round(stats['total_memory_mb'], 2),
                        '平均内存(MB)': round(stats['avg_memory_mb'], 2),
                        '无TTL的Key数量': stats['no_ttl_count'],
                        '无TTL比例(%)': round((stats['no_ttl_count'] / stats['count']) * 100, 2) if stats[
                                                                                                        'count'] > 0 else 0
                    })

                df_hierarchy = pd.DataFrame(hierarchy_data)
                df_hierarchy = df_hierarchy.sort_values('总内存(MB)', ascending=False)
                df_hierarchy.to_excel(writer, sheet_name='层级统计', index=False)

                # 3. 类型统计表
                type_data = []
                for key_type, stats in report['type_stats'].items():
                    type_data.append({
                        '数据类型': key_type,
                        'Key数量': stats['count'],
                        '总内存(MB)': round(stats['total_memory_mb'], 2),
                        '平均内存(MB)': round(stats['total_memory_mb'] / stats['count'], 2) if stats['count'] > 0 else 0
                    })

                df_type = pd.DataFrame(type_data)
                df_type = df_type.sort_values('总内存(MB)', ascending=False)
                df_type.to_excel(writer, sheet_name='类型统计', index=False)

                # 4. 汇总表
                summary_data = [{
                    '分析时间': report['summary']['timestamp'],
                    '分析Key数量': report['summary']['total_keys_analyzed'],
                    '分析耗时(秒)': round(report['summary']['analysis_time_seconds'], 2),
                    '建议清理优先级': '按层级统计表中的"总内存"和"无TTL比例"排序，优先处理内存占用大且无TTL的Key'
                }]

                df_summary = pd.DataFrame(summary_data)
                df_summary.to_excel(writer, sheet_name='分析汇总', index=False)

            logger.info(f"分析结果已导出到: {filename}")
            return filename

        except Exception as e:
            logger.error(f"导出Excel失败: {e}")
            raise


def main():
    """
    主函数 - 使用示例
    """
    # Redis连接配置
    redis_config = {
        'host': '192.168.50.227',  # Redis服务器地址
        'port': 6379,  # Redis端口
        'password': 'wejoin@135246',  # Redis密码（如果没有则为None）
        'db': 0  # 数据库编号
    }

    try:
        # 创建分析器实例
        analyzer = RedisKeyAnalyzer(**redis_config)

        # 生成空间分析报告
        # sample_size: 采样大小（0表示分析所有Key）
        # max_keys: 最大分析Key数量（None表示无限制，生产环境建议先采样）
        report = analyzer.generate_space_report(
            sample_size=50000,  # 先采样5万个Key进行测试
            max_keys=100000  # 最多分析10万个Key
        )

        # 导出到Excel
        excel_file = analyzer.export_to_excel(report)

        print(f"\n=== 分析完成 ===")
        print(f"导出文件: {excel_file}")
        print(f"分析Key数量: {report['summary']['total_keys_analyzed']}")
        print(f"耗时: {report['summary']['analysis_time_seconds']:.2f}秒")

        # 打印一些关键发现
        print(f"\n=== 关键发现 ===")

        # 内存占用最大的前5个层级
        hierarchy_stats = report['hierarchy_stats']
        top_memory = sorted(hierarchy_stats.items(),
                            key=lambda x: x[1]['total_memory_mb'],
                            reverse=True)[:5]

        print("内存占用最大的前5个层级:")
        for i, (path, stats) in enumerate(top_memory, 1):
            print(f"{i}. {path}: {stats['total_memory_mb']:.2f}MB "
                  f"({stats['count']}个Key, 无TTL: {stats['no_ttl_count']})")

        # 无TTL比例最高的层级
        high_no_ttl = sorted([(path, stats) for path, stats in hierarchy_stats.items()
                              if stats['count'] > 10],  # 过滤掉太小的分组
                             key=lambda x: (x[1]['no_ttl_count'] / x[1]['count']),
                             reverse=True)[:5]

        print(f"\n无TTL比例最高的前5个层级:")
        for i, (path, stats) in enumerate(high_no_ttl, 1):
            no_ttl_ratio = (stats['no_ttl_count'] / stats['count']) * 100
            print(f"{i}. {path}: {no_ttl_ratio:.1f}%无TTL "
                  f"({stats['no_ttl_count']}/{stats['count']}个Key)")

    except Exception as e:
        logger.error(f"执行分析失败: {e}")


if __name__ == "__main__":
    main()
