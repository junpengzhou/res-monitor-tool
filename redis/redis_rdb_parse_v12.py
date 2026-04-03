# -*- coding: utf-8 -*-
# !/usr/bin/env python3
import csv
import gc
import os
import struct
import sys
import time


class RDBParserV12:
    """支持Redis 7.0+ RDB版本12的解析器，只处理String类型并按前缀归类"""

    def __init__(self, rdb_file, output_file=None, min_prefix_length=3):
        self.rdb_file = rdb_file
        self.output_file = output_file or f"prefix_report_{int(time.time())}.csv"
        self.min_prefix_length = min_prefix_length

        # 前缀统计字典
        self.prefix_stats = {}

        # 文件句柄
        self.csv_file = None
        self.csv_writer = None

        # 统计信息
        self.key_count = 0
        self.string_key_count = 0
        self.total_size = 0
        self.current_db = 0

    def _initialize_csv_writer(self):
        """初始化CSV写入器"""
        # 确保输出目录存在
        output_dir = os.path.dirname(self.output_file)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        # 打开文件并写入表头
        self.csv_file = open(self.output_file, 'w', newline='', encoding='utf-8')
        fieldnames = ['key_prefix', 'key_count', 'size_bytes', 'size_kb']
        self.csv_writer = csv.DictWriter(self.csv_file, fieldnames=fieldnames)
        self.csv_writer.writeheader()
        self.csv_file.flush()
        print(f"初始化CSV写入器，输出文件: {self.output_file}")

    def _extract_prefix(self, key):
        """提取键的前缀，取最后一个冒号之前的所有字符作为前缀"""
        try:
            if not key:
                return "empty"

            # 如果键中包含冒号，取最后一个冒号之前的部分作为前缀
            if ':' in key:
                # 找到最后一个冒号的位置
                last_colon_idx = key.rfind(':')
                if last_colon_idx > 0:
                    # 确保冒号不在开头
                    prefix = key[:last_colon_idx]
                    return prefix
                elif last_colon_idx == 0:
                    # 以冒号开头的键
                    return "colon_start"

            # 如果没有冒号，尝试其他分隔符
            for delimiter in ['_', '-', '.', '|', ';']:
                if delimiter in key:
                    parts = key.split(delimiter)
                    if len(parts) > 1:
                        # 返回除最后一部分之外的所有部分
                        prefix = delimiter.join(parts[:-1])
                        if len(prefix) >= self.min_prefix_length:
                            return prefix

            # 如果键较长，取前几个字符作为前缀
            if len(key) > 10:
                return key[:8] + "..."

            return "no_prefix"

        except Exception as e:
            return "error"

    def _process_string_key(self, key, size):
        """处理String类型的键，按前缀归类"""
        self.key_count += 1
        self.string_key_count += 1
        self.total_size += size

        # 提取前缀
        prefix = self._extract_prefix(key)

        # 更新前缀统计
        if prefix in self.prefix_stats:
            self.prefix_stats[prefix]['count'] += 1
            self.prefix_stats[prefix]['size'] += size
        else:
            self.prefix_stats[prefix] = {
                'count': 1,
                'size': size
            }

        # 每处理1000个键，清理一次内存并输出进度
        if self.key_count % 1000 == 0:
            gc.collect()  # 强制垃圾回收
            print(f"已处理 {self.key_count} 个键，其中String类型: {self.string_key_count}")

    def _flush_prefix_stats(self):
        """将前缀统计刷新到CSV文件"""
        if not self.csv_writer or not self.prefix_stats:
            return

        try:
            # 按前缀排序
            sorted_prefixes = sorted(self.prefix_stats.items(),
                                     key=lambda x: x[1]['size'],
                                     reverse=True)

            for prefix, stats in sorted_prefixes:
                self.csv_writer.writerow({
                    'key_prefix': prefix,
                    'key_count': stats['count'],
                    'size_bytes': stats['size'],
                    'size_kb': round(stats['size'] / 1024, 2)
                })

            self.csv_file.flush()
            print(f"已刷新 {len(self.prefix_stats)} 个前缀统计到文件")

            # 清空统计，避免内存累积
            self.prefix_stats.clear()

        except Exception as e:
            print(f"写入CSV文件时出错: {e}")

    def parse(self):
        """解析RDB文件，只处理String类型，其他类型完全忽略"""
        print(f"开始解析RDB文件: {self.rdb_file}")
        print(f"最小前缀长度: {self.min_prefix_length}")
        print("注意: 只处理String类型键，其他类型完全忽略")

        # 初始化CSV写入器
        self._initialize_csv_writer()

        start_time = time.time()
        parse_errors = 0
        bytes_processed = 0
        flush_interval = 10000  # 每处理10000个键刷新一次
        last_progress_time = start_time
        last_key_count = 0
        unknown_opcodes = {}

        try:
            file_size = os.path.getsize(self.rdb_file)
            print(f"文件大小: {file_size / 1024 / 1024:.2f} MB")

            with open(self.rdb_file, 'rb') as f:
                # 检查文件头
                magic = f.read(5)
                if magic != b'REDIS':
                    raise ValueError("不是有效的RDB文件")

                # 读取版本
                version_bytes = f.read(4)
                version = int(version_bytes)
                print(f"RDB版本: {version}")

                # 记录开始位置
                data_start_pos = f.tell()
                print(f"数据开始位置: {data_start_pos}")

                # 读取文件直到结束
                while True:
                    try:
                        # 检查进度
                        current_pos = f.tell()
                        if current_pos - bytes_processed > 10 * 1024 * 1024:  # 每10MB输出一次进度
                            bytes_processed = current_pos
                            progress = (current_pos / file_size) * 100
                            elapsed = time.time() - start_time
                            if elapsed > 0:
                                speed = current_pos / elapsed / 1024 / 1024
                                if time.time() - last_progress_time > 0:
                                    keys_per_sec = (self.key_count - last_key_count) / (
                                            time.time() - last_progress_time)
                                else:
                                    keys_per_sec = 0
                                print(f"进度: {progress:.1f}% ({current_pos}/{file_size}), "
                                      f"速度: {speed:.1f} MB/s, 已处理键: {self.key_count}, "
                                      f"每秒: {keys_per_sec}")
                                last_progress_time = time.time()
                                last_key_count = self.key_count

                        # 读取操作码
                        byte = f.read(1)
                        if not byte:
                            print("到达文件末尾")
                            break

                        opcode = byte[0]

                        # 调试信息：显示操作码
                        if opcode not in [0xFF, 0xFE, 0xFD, 0xFC, 0xFB, 0xFA, 0xF8, 0xF9, 0x00, 0x01, 0x02, 0x03, 0x04]:
                            if opcode not in unknown_opcodes:
                                unknown_opcodes[opcode] = 1
                                print(f"遇到未知操作码: 0x{opcode:02x} (位置: {current_pos})")
                            else:
                                unknown_opcodes[opcode] += 1

                        if opcode == 0xFF:  # EOF
                            print(f"读取到EOF标记，位置: {current_pos}")
                            break
                        elif opcode == 0xFE:  # 选择数据库
                            # 读取数据库编号
                            db_number = self._read_length(f)
                            if db_number is not None:
                                self.current_db = db_number
                                print(f"切换到数据库: {db_number}")
                        elif opcode == 0xFD:  # 过期时间（秒）
                            # 读取4字节过期时间
                            expire_data = f.read(4)
                            if len(expire_data) < 4:
                                break
                            # 记录过期时间，下一个字节应该是值类型
                            continue
                        elif opcode == 0xFC:  # 过期时间（毫秒）
                            # 读取8字节过期时间
                            expire_data = f.read(8)
                            if len(expire_data) < 8:
                                break
                            # 记录过期时间，下一个字节应该是值类型
                            continue
                        elif opcode == 0xFB:  # 辅助字段
                            # 读取两个字符串
                            aux_key = self._read_string(f)
                            aux_value = self._read_string(f)
                            if aux_key and aux_value:
                                try:
                                    aux_key_str = aux_key.decode('utf-8', errors='ignore')
                                    aux_value_str = aux_value.decode('utf-8', errors='ignore')
                                    print(f"辅助信息: {aux_key_str} = {aux_value_str}")
                                except:
                                    pass
                        elif opcode == 0xFA:  # 模块辅助数据
                            # 跳过模块数据
                            module_id = self._read_length(f)
                            module_data_len = self._read_length(f)
                            if module_data_len is not None and module_data_len > 0:
                                f.seek(module_data_len, 1)
                        elif opcode == 0xF8:  # LRU空闲时间
                            # 读取8字节LRU
                            lru_data = f.read(8)
                            if len(lru_data) < 8:
                                break
                        elif opcode == 0xF9:  # LFU频率
                            # 读取1字节LFU
                            lfu_data = f.read(1)
                            if len(lfu_data) < 1:
                                break
                        elif opcode == 0:  # String类型
                            self._process_string_value(f)
                        elif opcode in [0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D,
                                        0x0E, 0x0F]:
                            # 非String类型，跳过
                            self._skip_non_string_value(f, opcode)
                        else:
                            # 未知操作码，尝试跳过
                            print(f"警告: 遇到未知操作码 0x{opcode:02x}，尝试跳过...")
                            # 尝试读取一个字符串作为键，然后读取长度并跳过
                            try:
                                key = self._read_string(f)
                                if key:
                                    # 尝试读取长度
                                    length = self._read_length(f)
                                    if length is not None and length > 0:
                                        f.seek(length, 1)
                                        print(f"跳过了未知类型 0x{opcode:02x} 的键")
                                    else:
                                        # 如果无法读取长度，尝试读取下一个字节
                                        pass
                                else:
                                    # 如果无法读取键，可能格式错误
                                    print(f"无法跳过未知操作码 0x{opcode:02x}")
                                    break
                            except Exception as e:
                                print(f"跳过未知操作码时出错: {e}")
                                break

                        # 定期刷新统计到文件
                        if self.key_count % flush_interval == 0 and self.key_count > 0:
                            self._flush_prefix_stats()
                            gc.collect()

                    except EOFError:
                        print("读取过程中遇到EOF")
                        break
                    except Exception as e:
                        parse_errors += 1
                        if parse_errors <= 5:
                            print(f"解析错误: {e}")
                        elif parse_errors == 6:
                            print("... 后续解析错误将被静默处理")
                        continue

        except Exception as e:
            print(f"解析过程中发生严重错误: {e}")
            import traceback
            traceback.print_exc()

        finally:
            # 最后刷新剩余的前缀统计
            self._flush_prefix_stats()

            # 确保CSV文件被正确关闭
            if self.csv_file:
                try:
                    self.csv_file.flush()
                    self.csv_file.close()
                except Exception as un_e:
                    print(f"无法关闭CSV文件 {str(un_e)}")
                    pass

        elapsed_time = time.time() - start_time
        print(f"\n解析完成，耗时: {elapsed_time:.2f} 秒")
        print(f"总键数: {self.key_count}")
        print(f"String类型键数: {self.string_key_count}")
        print(f"总大小: {self.total_size / 1024 / 1024:.2f} MB")
        print(f"解析错误数: {parse_errors}")

        if unknown_opcodes:
            print(f"遇到的未知操作码: {list(unknown_opcodes.keys())}")

        if self.string_key_count == 0:
            print("没有找到String类型的键")
        else:
            print(f"报告已保存: {self.output_file}")

    def _process_string_value(self, f):
        """处理String类型的值"""
        try:
            # 读取键
            key_bytes = self._read_string(f)
            if not key_bytes:
                return

            # 读取值长度
            value_len = self._read_length(f)
            if value_len is None or value_len < 0:
                return

            # 计算总大小
            key_size = len(key_bytes)
            value_size = value_len
            total_size = key_size + value_size

            # 解码键
            try:
                key_str = key_bytes.decode('utf-8', errors='ignore')
                if len(key_str) > 1000:  # 截断过长的键名
                    key_str = key_str[:1000] + "..."
            except:
                print(f"无法解码键: {key_bytes[:20]}...")
                key_str = "binary_key"

            # 按前缀统计
            self._process_string_key(key_str, total_size)

            # 跳过值内容，避免占用内存
            if value_len > 0:
                f.seek(value_len, 1)

        except Exception as e:
            print(f"处理String键时发生错误: {e}")
            # 跳过错误键
            return

    def _skip_non_string_value(self, f, value_type):
        """根据类型跳过值，返回是否成功"""
        try:
            # 读取键
            key = self._read_string(f)
            if not key:
                return False

            # 根据值类型跳过
            if value_type == 1:  # List
                length = self._read_length(f)
                if length is None:
                    return False
                for _ in range(length):
                    self._skip_string(f)

            elif value_type == 2:  # Set
                length = self._read_length(f)
                if length is None:
                    return False
                for _ in range(length):
                    self._skip_string(f)

            elif value_type == 3:  # Sorted Set
                length = self._read_length(f)
                if length is None:
                    return False
                for _ in range(length):
                    self._skip_string(f)  # 跳过成员
                    # 读取分数
                    score_bytes = f.read(1)
                    if not score_bytes:
                        return False
                    if score_bytes[0] == 0xFF:  # 特殊编码
                        f.seek(8, 1)
                    elif score_bytes[0] == 0xFE:
                        f.seek(4, 1)
                    else:
                        f.seek(-1, 1)
                        self._skip_string(f)  # 分数是字符串

            elif value_type == 4:  # Hash
                length = self._read_length(f)
                if length is None:
                    return False
                for _ in range(length):
                    self._skip_string(f)  # 跳过field
                    self._skip_string(f)  # 跳过value

            elif value_type == 9:  # ZipList
                ziplist_len = self._read_length(f)
                if ziplist_len is None:
                    return False
                f.seek(ziplist_len, 1)

            elif value_type == 10:  # IntSet
                intset_len = self._read_length(f)
                if intset_len is None:
                    return False
                f.seek(intset_len, 1)

            elif value_type == 13:  # List (Quicklist)
                length = self._read_length(f)
                if length is None:
                    return False
                for _ in range(length):
                    ziplist_len = self._read_length(f)
                    if ziplist_len is None:
                        return False
                    f.seek(ziplist_len, 1)

            elif value_type == 20:  # Stream
                # Stream是Redis 5.0引入的
                # 跳过Stream的ID
                f.seek(16, 1)  # 16字节的Stream ID
                # 跳过条目数量
                entries = self._read_length(f)
                if entries is None:
                    return False
                # 跳过每个条目
                for _ in range(entries):
                    # 跳过ID
                    f.seek(16, 1)
                    # 跳过字段数量
                    num_fields = self._read_length(f)
                    if num_fields is None:
                        return False
                    # 跳过每个字段
                    for _ in range(num_fields):
                        self._skip_string(f)  # 跳过field
                        self._skip_string(f)  # 跳过value
                # 跳过消费者组
                groups = self._read_length(f)
                if groups is None:
                    return False
                for _ in range(groups):
                    # 跳过组名
                    self._skip_string(f)
                    # 跳过最后传递的ID
                    f.seek(16, 1)
                    # 跳过待处理条目
                    pending = self._read_length(f)
                    if pending is None:
                        return False
                    for _ in range(pending):
                        f.seek(16, 1)  # 消费者ID
                        f.seek(8, 1)  # 传递时间
                        deliveries = self._read_length(f)
                        if deliveries is None:
                            return False
                        f.seek(deliveries, 1)  # 跳过传递计数
                    # 跳过消费者
                    consumers = self._read_length(f)
                    if consumers is None:
                        return False
                    for _ in range(consumers):
                        self._skip_string(f)  # 消费者名
                        f.seek(8, 1)  # 最后一次活动时间
                        pending = self._read_length(f)
                        if pending is None:
                            return False
                        for _ in range(pending):
                            f.seek(16, 1)  # 待处理消息ID

            else:
                # 其他类型，尝试读取长度并跳过
                length = self._read_length(f)
                if length is not None and length > 0:
                    f.seek(length, 1)
                else:
                    # 不知道如何跳过，尝试读取下一个字节
                    return True

            return True

        except Exception as e:
            print(f"跳过非String类型时出错: {e}, 类型: 0x{value_type:02x}")
            return False

    def _read_length(self, f):
        """读取Redis RDB长度编码 - 更简单的实现"""
        try:
            first_byte = f.read(1)
            if not first_byte:
                return None

            b = first_byte[0]

            # 调试信息
            # print(f"读取长度字节: 0x{b:02x}")

            # 6位长度 (00xxxxxx)
            if (b & 0xC0) == 0x00:
                return b & 0x3F

            # 14位长度 (01xxxxxx)
            elif (b & 0xC0) == 0x40:
                next_byte = f.read(1)
                if not next_byte:
                    return None
                return ((b & 0x3F) << 8) | next_byte[0]

            # 32位长度
            elif b == 0xC0:
                return -1
            elif b == 0xC1:
                next_byte = f.read(1)
                if not next_byte:
                    return None
                return next_byte[0]
            elif b == 0xC2:
                return -1
            elif b == 0xC3:
                return 0
            elif b == 0xC4:
                data = f.read(4)
                if len(data) < 4:
                    return None
                return struct.unpack('<I', data)[0]
            elif b == 0xC5:
                data = f.read(8)
                if len(data) < 8:
                    return None
                return struct.unpack('<Q', data)[0]

            # 压缩字符串/整数编码 (10xxxxxx 或 1100xxxx)
            # 对于RDB版本12，我们简化处理：如果是0x80-0xBF，可能是LZF压缩或整数编码
            # 我们只关心长度，所以尝试读取实际数据长度
            elif (b & 0xC0) == 0x80 or (b & 0xF0) == 0xC0:
                # 简化处理：如果是压缩或整数编码，我们跳过
                # 实际应该根据编码类型读取，但这里我们返回0
                return 0

            # 其他编码，返回None表示错误
            return None

        except Exception as e:
            print(f"_read_length错误: {e}")
            return None

    def _read_string(self, f):
        """读取字符串 - 简化版本"""
        try:
            length = self._read_length(f)
            if length is None or length < 0:
                return b''
            if length > 100 * 1024 * 1024:  # 限制字符串不超过100MB
                print(f"警告: 跳过过大字符串 ({length}字节)")
                f.seek(length, 1)
                return b''
            if length == 0:
                return b''
            return f.read(length)
        except Exception as e:
            print(f"_read_string错误: {e}")
            return b''

    def _skip_string(self, f):
        """跳过字符串"""
        try:
            length = self._read_length(f)
            if length is None or length < 0:
                return 0
            if length > 0:
                f.seek(length, 1)
            return length
        except Exception as e:
            print(f"_skip_string错误: {e}")
            return 0


def main():
    if len(sys.argv) < 2:
        print(f"用法: {sys.argv[0]} <rdb文件> [输出文件]")
        print(f"示例: {sys.argv[0]} dump.rdb report.csv")
        print(f"注意: 本工具只分析String类型键，并按前缀归类统计")
        sys.exit(1)

    rdb_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None

    if not os.path.exists(rdb_file):
        print(f"文件不存在: {rdb_file}")
        sys.exit(1)

    # 添加内存监控
    import signal

    def signal_handler(signum, frame):
        print(f"\n收到信号 {signum}，程序将退出...")
        sys.exit(1)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print(f"开始解析，只处理String类型键")
    print(f"按Ctrl+C可中断程序")

    parser = RDBParserV12(rdb_file, output_file)
    parser.parse()


if __name__ == '__main__':
    main()
