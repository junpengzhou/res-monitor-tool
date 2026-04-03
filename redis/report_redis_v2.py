# -*- coding: utf-8 -*-
# !/usr/bin/env python3
import csv
import os
import struct
import sys
import time
import gc


class RDBParserV12:
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

        try:
            file_size = os.path.getsize(self.rdb_file)
            print(f"文件大小: {file_size / 1024 / 1024:.2f} MB")

            with open(self.rdb_file, 'rb', buffering=65536) as f:
                # 检查文件头
                magic = f.read(5)
                if magic != b'REDIS':
                    raise ValueError("不是有效的RDB文件")

                # 读取版本
                version_bytes = f.read(4)
                version = int(version_bytes)
                print(f"RDB版本: {version}")

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
                                      f"速度: {speed:.1f} MB/s, 已处理键: {self.key_count}")
                                last_progress_time = time.time()
                                last_key_count = self.key_count

                        opcode = self._read_byte_safe(f)
                        if opcode is None:
                            break

                        if opcode == 0xFF:  # EOF
                            break
                        elif opcode == 0xFE:  # 选择数据库
                            self._skip_database_selection(f)
                        elif opcode == 0xFD:  # 过期时间（秒）
                            self._skip_expire_time(f)
                        elif opcode == 0xFC:  # 过期时间（毫秒）
                            self._skip_expire_time_ms(f)
                        elif opcode == 0xFB:  # 辅助字段
                            self._skip_aux_field(f)
                        elif opcode == 0xFA:  # 模块辅助数据
                            self._skip_module_data(f)
                        elif opcode == 0:  # String类型
                            self._process_string_value(f)
                        else:
                            # 跳过非String类型
                            self._skip_value_by_type(f, opcode)

                        # 定期刷新统计到文件
                        if self.key_count % flush_interval == 0 and self.key_count > 0:
                            self._flush_prefix_stats()
                            gc.collect()

                    except EOFError:
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
                except:
                    pass

        elapsed_time = time.time() - start_time
        print(f"\n解析完成，耗时: {elapsed_time:.2f} 秒")
        print(f"总键数: {self.key_count}")
        print(f"String类型键数: {self.string_key_count}")
        print(f"总大小: {self.total_size / 1024 / 1024:.2f} MB")
        print(f"解析错误数: {parse_errors}")

        if self.string_key_count == 0:
            print("没有找到String类型的键")
        else:
            print(f"报告已保存: {self.output_file}")

    def _process_string_value(self, f):
        """处理String类型的值"""
        try:
            # 读取键
            key_bytes = self._read_string_safe(f, "key")
            if not key_bytes:
                return

            # 读取值长度
            value_len = self._read_length_safe(f)
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
                key_str = "binary_key"

            # 按前缀统计
            self._process_string_key(key_str, total_size)

            # 跳过值内容，避免占用内存
            if value_len > 0:
                f.seek(value_len, 1)

        except Exception as e:
            # 跳过错误键
            return

    def _skip_database_selection(self, f):
        """跳过数据库选择"""
        self._read_length_safe(f)  # 读取数据库编号并忽略

    def _skip_expire_time(self, f):
        """跳过过期时间（秒）"""
        self._read_uint32_safe(f)  # 读取并忽略

    def _skip_expire_time_ms(self, f):
        """跳过过期时间（毫秒）"""
        self._read_uint64_safe(f)  # 读取并忽略

    def _skip_aux_field(self, f):
        """跳过辅助字段"""
        # 读取两个字符串并忽略
        self._read_string_safe(f, "aux_key")
        self._read_string_safe(f, "aux_value")

    def _skip_module_data(self, f):
        """跳过模块数据"""
        module_id = self._read_length_safe(f)
        module_data_len = self._read_length_safe(f)
        if module_data_len is not None and module_data_len > 0:
            f.seek(module_data_len, 1)  # 跳过模块数据

    def _skip_value_by_type(self, f, value_type):
        """根据类型跳过值"""
        try:
            # 读取键（跳过）
            key = self._read_string_safe(f, "skip_key")
            if not key:
                return

            # 根据值类型跳过值
            if value_type == 1:  # List
                length = self._read_length_safe(f)
                if length is None:
                    return
                for _ in range(length):
                    self._skip_string_safe(f)

            elif value_type == 2:  # Set
                length = self._read_length_safe(f)
                if length is None:
                    return
                for _ in range(length):
                    self._skip_string_safe(f)

            elif value_type == 3:  # Sorted Set
                length = self._read_length_safe(f)
                if length is None:
                    return
                for _ in range(length):
                    self._skip_string_safe(f)  # 跳过成员
                    # 跳过分数
                    score_bytes = f.read(1)
                    if not score_bytes:
                        return
                    if score_bytes[0] == 0xFF:  # 特殊编码
                        f.seek(8, 1)
                    elif score_bytes[0] == 0xFE:
                        f.seek(4, 1)
                    else:
                        f.seek(-1, 1)
                        self._skip_string_safe(f)  # 分数是字符串

            elif value_type == 4:  # Hash
                length = self._read_length_safe(f)
                if length is None:
                    return
                for _ in range(length):
                    self._skip_string_safe(f)  # 跳过field
                    self._skip_string_safe(f)  # 跳过value

            elif value_type == 9:  # ZipList
                ziplist_len = self._read_length_safe(f)
                if ziplist_len is None:
                    return
                f.seek(ziplist_len, 1)

            elif value_type == 10:  # IntSet
                intset_len = self._read_length_safe(f)
                if intset_len is None:
                    return
                f.seek(intset_len, 1)

            elif value_type == 13:  # List (Quicklist)
                length = self._read_length_safe(f)
                if length is None:
                    return
                for _ in range(length):
                    ziplist_len = self._read_length_safe(f)
                    if ziplist_len is None:
                        return
                    f.seek(ziplist_len, 1)

            else:
                # 其他类型，尝试读取长度并跳过
                length = self._read_length_safe(f)
                if length is not None and length > 0:
                    f.seek(length, 1)

        except Exception as e:
            # 跳过错误
            return

    def _read_byte_safe(self, f):
        """安全读取一个字节"""
        try:
            byte = f.read(1)
            if not byte:
                return None
            return byte[0]
        except:
            return None

    def _read_length_safe(self, f):
        """安全读取长度编码 - 修复版本"""
        try:
            byte = self._read_byte_safe(f)
            if byte is None:
                return None

            # 6位长度 (00xxxxxx)
            if (byte & 0xC0) == 0:
                return byte & 0x3F

            # 14位长度 (01xxxxxx xxxxxxxx)
            elif (byte & 0xC0) == 0x40:
                next_byte = self._read_byte_safe(f)
                if next_byte is None:
                    return None
                return ((byte & 0x3F) << 8) | next_byte

            # 32位长度 (0xC4)
            elif byte == 0xC4:
                return self._read_uint32_safe(f)

            # 64位长度 (0xC5)
            elif byte == 0xC5:
                return self._read_uint64_safe(f)

            # 特殊编码
            elif byte == 0xC0:  # 压缩字符串表示0？
                return 0
            elif byte == 0xC1:  # 1字节整数
                next_byte = self._read_byte_safe(f)
                return next_byte
            elif byte == 0xC2:  # 2字节整数
                data = f.read(2)
                if len(data) < 2:
                    return None
                return struct.unpack('<H', data)[0]
            elif byte == 0xC3:  # 4字节整数
                return self._read_uint32_safe(f)

            # 压缩字符串编码 (10xxxxxx) - 这是错误的！0x80-0xBF在Redis RDB中表示整数编码，不是字符串长度
            # 在Redis RDB中，整数有特殊的编码方式，0x80-0xBF表示带符号的整数
            elif (byte & 0xC0) == 0x80:
                # 这是整数编码，不是字符串长度编码
                # 0x80 表示接下来的1字节是8位有符号整数
                # 0x81 表示接下来的2字节是16位有符号整数
                # 0x82 表示接下来的4字节是32位有符号整数
                # 0x83 表示接下来的8字节是64位有符号整数
                # 0x84-0xBF 保留
                len_type = byte & 0x3F
                if len_type == 0:  # 8位整数
                    data = f.read(1)
                    if len(data) < 1:
                        return None
                    return struct.unpack('b', data)[0]  # 有符号字节
                elif len_type == 1:  # 16位整数
                    data = f.read(2)
                    if len(data) < 2:
                        return None
                    return struct.unpack('<h', data)[0]  # 有符号短整型
                elif len_type == 2:  # 32位整数
                    data = f.read(4)
                    if len(data) < 4:
                        return None
                    return struct.unpack('<i', data)[0]  # 有符号整型
                elif len_type == 3:  # 64位整数
                    data = f.read(8)
                    if len(data) < 8:
                        return None
                    return struct.unpack('<q', data)[0]  # 有符号长整型
                else:
                    # 无效的整数编码
                    return None

            # 其他特殊编码
            elif byte == 0x00:  # 字符串结束标记？
                return 0

            return 0
        except:
            return None

    def _read_string_safe(self, f, description=""):
        """安全读取字符串，限制大小"""
        try:
            length = self._read_length_safe(f)
            if length is None or length < 0:
                return b''
            if length > 100 * 1024 * 1024:  # 限制字符串不超过100MB
                print(f"警告: 跳过过大{description} ({length}字节)")
                f.seek(length, 1)
                return b''
            return f.read(length)
        except:
            return b''

    def _skip_string_safe(self, f):
        """安全跳过字符串，返回长度但不读取内容"""
        try:
            length = self._read_length_safe(f)
            if length is None or length < 0:
                return 0
            if length > 0:
                f.seek(length, 1)
            return length
        except:
            return 0

    def _read_uint32_safe(self, f):
        """安全读取32位无符号整数"""
        try:
            data = f.read(4)
            if len(data) < 4:
                return None
            return struct.unpack('<I', data)[0]
        except:
            return None

    def _read_uint64_safe(self, f):
        """安全读取64位无符号整数"""
        try:
            data = f.read(8)
            if len(data) < 8:
                return None
            return struct.unpack('<Q', data)[0]
        except:
            return None


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
