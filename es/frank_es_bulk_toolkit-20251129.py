import argparse
import os
import subprocess
import sys
from typing import List


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


def ensure_index_field(
        es_hosts: List[str],
        index_name: str,
        field_name: str,
        field_type: str,
) -> bool:
    es_client = create_es_client(es_hosts)

    try:
        if not es_client.indices.exists(index=index_name):
            print(f"{es_hosts}, 索引 '{index_name}' 不存在")
            return False

        current_mapping = es_client.indices.get_mapping(index=index_name)

        print(f"mapping是：{str(current_mapping)}")
        actual_index_names = list(current_mapping.keys())
        real_index_name = actual_index_names[0] if len(actual_index_names) > 0 else index_name
        index_mapping_properties = current_mapping[real_index_name]["mappings"].get("properties", {})

        if field_name in index_mapping_properties:
            print(f"{es_hosts}, 索引 '{index_name}'/'{real_index_name}' 中已存在字段 '{field_name}'，无需添加")
            return True
        field_mapping_properties = {
            "type": field_type,
        }
        update_body = {
            "properties": {
                field_name: field_mapping_properties
            }
        }
        es_client.indices.put_mapping(index=real_index_name, body=update_body)
        print(
            f"{es_hosts}, 成功向索引 '{real_index_name}' 添加字段 '{field_name}'，映射定义为: {field_mapping_properties}")
        return True
    except NotFoundError:
        print(f"{es_hosts}, 未找到索引或其它资源: {index_name}", file=sys.stderr)
        return False


def create_es_client(es_hosts: List[str]) -> Elasticsearch:
    """
    创建带超时配置的 Elasticsearch 客户端
    """
    return Elasticsearch(
        es_hosts,
        http_compress=True,
        request_timeout=1800,
        meta_header=False,
    )


def main_es_add_order_column(hosts: List[str]):
    indices = [
        "sim-mt5-deals",
        "crm-mt5-deals",
        "crm-mt5-orders",
        "sim-mt5-orders",
        "crm-mt5-positions",
        "sim-mt5-positions",
        "crm-order-combine-v2",
        "sim-order-combine-v2",
    ]
    add_fields = {
        "userType": "keyword",
        "agentIdChains": "long",
        "userRelChainPath": "keyword",
    }
    for host in hosts:
        for index_name in indices:
            for field_name, field_type in add_fields.items():
                # 确保索引名称存在
                ensure_index_field(
                    [host],
                    index_name=index_name,
                    field_name=field_name,
                    field_type=field_type
                )
                print(f"""
=== Frank工具输出处理结果汇总：【订单】添加字段成功！===
hosts: {host}
index_name: {index_name}
field_name: {field_name}
field_type: {field_type}
=== Frank工具输出处理结果汇总：【订单】添加字段成功！===
                """)


def main_es_add_rebate_column(hosts: List[str]):
    indices = [
        "crs-rebate-rank-detail-new-alias",
        "crs_rebate-alias",
    ]
    add_fields = {
        "userRelChainPath": "keyword",
        "userType": "keyword",
        "rebateAgentIdChains": "long",
        "agentIdChains": "long",
    }
    for host in hosts:
        for index_name in indices:
            for field_name, field_type in add_fields.items():
                # 确保索引名称存在
                ensure_index_field(
                    [host],
                    index_name=index_name,
                    field_name=field_name,
                    field_type=field_type
                )
                print(f"""
=== Frank工具输出处理结果汇总：【返佣】添加字段成功！===
hosts: {host}
index_name: {index_name}
field_name: {field_name}
field_type: {field_type}
=== Frank工具输出处理结果汇总：【返佣】添加字段成功！===
                """)


def main_es_add_fin_column(hosts: List[str]):
    indices = [
        "pay-withdrawal-info",
        "pay-internal-transfer-info",
        "pay-deposit-info",
    ]
    add_fields = {
        "agentId": "long",
        "userType": "keyword",
        "userRelChainPath": "keyword",
        "agentIdChains": "long",
    }
    for host in hosts:
        for index_name in indices:
            for field_name, field_type in add_fields.items():
                # 确保索引名称存在
                ensure_index_field(
                    [host],
                    index_name=index_name,
                    field_name=field_name,
                    field_type=field_type
                )
                print(f"""
=== Frank工具输出处理结果汇总：【资金】添加字段成功！===
hosts: {host}
index_name: {index_name}
field_name: {field_name}
field_type: {field_type}
=== Frank工具输出处理结果汇总：【资金】添加字段成功！===
                """)


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

    exec_es_hosts = args.es_hosts

    main_es_add_order_column(exec_es_hosts)
    main_es_add_rebate_column(exec_es_hosts)
    main_es_add_fin_column(exec_es_hosts)
