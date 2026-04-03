import os
import subprocess
import sys
from typing import List, Dict, Any
import argparse


def install_requirements():
    req_file = 'requirements.txt'
    if os.path.exists(req_file):
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", req_file])
            print("所有依赖已成功安装。")
        except subprocess.CalledProcessError:
            print("安装依赖失败，请手动检查 requirements.txt 文件或网络连接。")
            sys.exit(1)
    else:
        print(f"未找到 {req_file} 文件。")


try:
    from elasticsearch import Elasticsearch, NotFoundError
    from elasticsearch.helpers import scan, streaming_bulk
except ImportError as e:
    install_requirements()
    from elasticsearch import Elasticsearch, NotFoundError
    from elasticsearch.helpers import scan, streaming_bulk


def update_es_fields(
        es_hosts: List[str],
        es_indices: List[str],
        es_field_defaults: Dict[str, Any],
        es_batch_size: int = 5000,
        es_query: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    为Elasticsearch索引中不存在指定字段的文档添加默认值
    Args:
        es_hosts: ES连接地址列表，如['http://localhost:9200']
        es_indices: 要处理的索引名称列表
        es_field_defaults: 字段默认值字典，如{'limitType': 0, 'status': 1}
        es_batch_size: 每批处理的文档数量，默认5000
        es_query: 自定义查询条件，默认为查找不存在指定字段的文档
    Returns:
        处理结果的统计信息
    """
    es = Elasticsearch(es_hosts)

    # 构建默认查询：查找所有不存在 field_defaults 中任何字段的文档
    if es_query is None:
        must_not_conditions = [{"exists": {"field": field}} for field in es_field_defaults.keys()]
        es_query = {
            "query": {
                "bool": {
                    "must_not": must_not_conditions
                }
            },
            # pref by Frank Zhou 不获取源文档，节省网络带宽
            "_source": False
        }

    update_bulk_results = {}

    for es_index in es_indices:
        print(f"开始处理索引: {es_index}")

        success_count = 0
        failed_count = 0
        actions_bulk = []

        try:
            # pref by Frank Zhou 使用 scan 流式地获取需要更新的文档，避免内存溢出
            for hit in scan(es, index=es_index, query=es_query):
                # 为每个文档构造一个更新动作
                doc_id = hit['_id']
                update_action = {
                    "_op_type": "update",
                    "_index": es_index,
                    "_id": doc_id,
                    "doc": es_field_defaults
                }
                actions_bulk.append(update_action)

                # pref by Frank Zhou 使用 批量加上 streaming_bulk 执行批量更新，并即时处理结果
                if len(actions_bulk) >= es_batch_size:
                    for success, info in streaming_bulk(
                            es, actions_bulk, chunk_size=es_batch_size, raise_on_error=False
                    ):
                        if success:
                            success_count += 1
                        else:
                            failed_count += 1
                            print(f"文档 {doc_id} 更新失败: {info}")

                    print(f"索引 {es_index} 已批量更新: {success_count + failed_count} 个文档")
                    actions_bulk = []

            # fix by Frank 最后一批漏执行问题修复
            if actions_bulk:
                for success, info in streaming_bulk(es, actions_bulk, raise_on_error=False):
                    if success:
                        success_count += 1
                    else:
                        failed_count += 1

        except Exception as unknown_e:
            print(f"处理索引 {es_index} 时发生错误: {str(unknown_e)}", file=sys.stderr)
            update_bulk_results[es_index] = {
                "processed": success_count + failed_count,
                "success": success_count,
                "failed": failed_count
            }
            continue

        total_processed = success_count + failed_count
        update_bulk_results[es_index] = {
            "processed": total_processed,
            "success": success_count,
            "failed": failed_count
        }
        print(f"索引 {es_index} 处理完成: 共处理 {total_processed}, 成功 {success_count}, 失败 {failed_count}")
    return update_bulk_results


def ensure_index_field(
        es_hosts: List[str],
        index_name: str,
        field_name: str,
        field_type: str,
) -> bool:
    """
    确保 Elasticsearch 索引中存在指定的字段。如果字段不存在，则创建它。

    Args:
        es_hosts: Es的地址示例：['http://localhost:9200']
        index_name: 需要检查/更新的索引名称
        field_name: 需要确保存在的字段名
        field_type: 字段的映射定义，例如 "integer"

    Returns:
        bool: 如果字段已存在或成功创建，返回 True；否则返回 False。

    Raises:
        可能会抛出 Elasticsearch 相关的异常（如 ConnectionError, TransportError），调用方应捕获处理。
    """
    es_client = Elasticsearch(es_hosts)

    try:
        if not es_client.indices.exists(index=index_name):
            print(f"索引 '{index_name}' 不存在")
            return False

        current_mapping = es_client.indices.get_mapping(index=index_name)
        index_mapping_properties = current_mapping[index_name]["mappings"].get("properties", {})

        if field_name in index_mapping_properties:
            print(f"索引 '{index_name}' 中已存在字段 '{field_name}'，无需添加")
            return True
        field_mapping_properties = {
            "type": field_type,
        }
        update_body = {
            "properties": {
                field_name: field_mapping_properties
            }
        }
        es_client.indices.put_mapping(index=index_name, body=update_body)
        print(f"成功向索引 '{index_name}' 添加字段 '{field_name}'，映射定义为: {field_mapping_properties}")
        return True
    except NotFoundError:
        print(f"未找到索引或其它资源: {index_name}", file=sys.stderr)
        return False
    except Exception as unknown_e:
        print(f"确保字段时发生未知错误: {unknown_e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    if sys.version_info < (3, 5):
        raise RuntimeError("Frank提醒, 本脚本需要 Python 3.5 或更高版本才可支持！")

    parser = argparse.ArgumentParser(description='Frank的ES操作工具(python)')
    parser.add_argument(
        '-e',
        '--es_hosts',
        nargs='+',
        help='Elasticsearch连接地址列表，例如: http://119.23.145.91:59200'
    )

    args = parser.parse_args()

    hosts = args.es_hosts
    field_name = "linkedAgentIds"
    field_type = "keyword"
    indices = [
        'crm-order-combine-v2',
        'crm-order-combine-limit-v2',
        'sim-order-combine-v2',
        "crm-mt5-orders",
        "crm-mt5-deals",
        "crm-mt5-positions"
    ]
    for index_name in indices:
        ensure_index_field(hosts, index_name=index_name, field_name=field_name, field_type=field_type)
    print(f"""
        === Frank工具输出处理结果汇总：添加字段全部成功！===
        indices: {indices}
        field_name: {field_name}
        field_type: {field_type}
    """)
