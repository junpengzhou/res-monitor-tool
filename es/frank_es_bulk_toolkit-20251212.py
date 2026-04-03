import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from contextlib import contextmanager
from typing import List, Dict, Any


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


@contextmanager
def timer():
    start_time = time.time()
    yield
    end_time = time.time()
    elapsed_time = end_time - start_time
    hours = int(elapsed_time // 3600)
    minutes = int((elapsed_time % 3600) // 60)
    seconds = elapsed_time % 60
    print(f"运行时间：{hours}小时{minutes}分钟{seconds:.2f}秒")


def create_es_client(es_hosts: List[str]) -> Elasticsearch:
    return Elasticsearch(
        es_hosts,
        max_retries=2,
        http_compress=True,
        request_timeout=1800,
        meta_header=False,
    )


def reindex_es(
        es_hosts: List[str],
        index_name: str,
        new_index_name: str,
) -> Dict[str, Any]:
    es = create_es_client(es_hosts)
    result = {
        "success": False,
        "original_index": index_name,
        "new_index": new_index_name,
        "task_id": None,
        "error": None
    }

    # 检查原索引是否存在
    if not es.indices.exists(index=index_name):
        print(f" -> 错误: 索引 {index_name} 不存在")
        result["error"] = f"索引 {index_name} 不存在"
        return result

    # 获取原索引的映射和设置
    old_mapping = es.indices.get_mapping(index=index_name)
    old_settings = es.indices.get_settings(index=index_name)

    # 创建新映射
    new_mapping = old_mapping[index_name]["mappings"]

    to_be_remove_node = [
        "version",
        "creation_date",
        "routing",
        "uuid",
        "provided_name"
    ]

    new_settings = old_settings[index_name]["settings"]
    for node in to_be_remove_node:
        if node in new_settings["index"]:
            del new_settings["index"][node]

    # 修改交易手数的类型为Long类型
    new_mapping["properties"]["volume"]["type"] = "long"

    create_body = {
        "mappings": new_mapping,
        "settings": new_settings
    }
    create_body_json_str = json.dumps(create_body)
    print(f" -> 正在创建新索引: {new_index_name}, body:{create_body_json_str}")

    if not es.indices.exists(index=new_index_name):
        try:
            es.indices.create(index=new_index_name, body=create_body)
            print(f" -> 已创建新索引: {new_index_name}")
        except Exception as un_e:
            print(f" -> 创建索引 {new_index_name} 失败: {un_e}")
            result["error"] = f"创建索引失败: {un_e}"
            return result
    else:
        print(f" -> 索引 {new_index_name} 已存在，无需创建")

    # 执行reindex
    reindex_response = es.reindex(
        body={
            "source": {
                "index": index_name
            },
            "dest": {
                "index": new_index_name
            }
        },
        wait_for_completion=False
    )

    result["task_id"] = reindex_response["task"]
    print(f" -> Reindex 任务已提交，任务ID: {result['task_id']}")
    result["success"] = True

    return result


def external_reindex_es(
        es_hosts: List[str],
        index_name: str,
        new_index_name: str,
        query: Dict[str, Any] = None,
) -> Dict[str, Any]:
    es = create_es_client(es_hosts)
    result = {
        "success": False,
        "original_index": index_name,
        "new_index": new_index_name,
        "task_id": None,
        "error": None
    }

    # 执行reindex
    reindex_response = es.reindex(
        body={
            "source": {
                "index": index_name,
                "query": query
            },
            "dest": {
                "index": new_index_name,
                "version_type": "external"
            },
            "conflicts": "proceed"
        },
        wait_for_completion=False
    )

    result["task_id"] = reindex_response["task"]
    print(f" -> External Reindex 任务已提交，任务ID: {result['task_id']}")
    result["success"] = True

    return result


def switch_aliases(
        es_hosts: List[str],
        old_index: str,
        new_index: str,
        aliases: List[str]
) -> bool:
    es = create_es_client(es_hosts)

    actions = []
    for alias in aliases:
        # 移除旧索引的别名
        if es.indices.exists_alias(name=alias, index=old_index):
            actions.append({
                "remove": {"index": old_index, "alias": alias}
            })
        # 添加新索引的别名
        actions.append({
            "add": {"index": new_index, "alias": alias}
        })

    if actions:
        es.indices.update_aliases(body={"actions": actions})
        print(f" -> 别名切换完成: {aliases} 从 {old_index} 切换到 {new_index}")

    return True


def monitor_reindex_task(es_hosts: List[str], task_id: str) -> Dict[str, Any]:
    es = create_es_client(es_hosts)
    return es.tasks.get(task_id=task_id)


def monitor_reindex_count(
        es_hosts: List[str],
        next_index_name: str,
        prev_index_name: str
) -> None:
    es = create_es_client(es_hosts)
    try:
        new_count = es.count(index=next_index_name)["count"]
        old_count = es.count(index=prev_index_name)["count"]
        print(f" -> 数据验证: 旧索引 {old_count} 条, 新索引 {new_count} 条")
    except Exception as unknown_e:
        traceback.print_exc()
        print(f" -> 数据验证时发生错误: {str(unknown_e)}")


def while_monitor_reindex_task(
        result: Dict[str, Any],
        hosts: List[str]
) -> bool:
    if "task_id" in result and result["task_id"]:
        task_id = result["task_id"]
        print(f" -> 开始监控任务 {task_id} 的状态...")
        while True:
            try:
                task_info = monitor_reindex_task(hosts, task_id)
                if task_info.get("completed", False):
                    print(f" -> 任务 {task_id} 已完成!")
                    print(f" -> 任务详情: {task_info}")
                    break
                else:
                    task_detail = task_info.get('task', {})
                    status = task_detail.get('status', {})
                    description = task_detail.get('description', '无')
                    total = status.get('total', 0)
                    created = status.get('created', 0)
                    updated = status.get('updated', 0)
                    processed = created + updated

                    process_percent = 0
                    if total > 0:
                        process_percent = round((processed / total) * 100, 2)
                    elif processed > 0:
                        process_percent = round((processed / (processed + 1)) * 100, 2)

                    print(
                        f" -> [20s监控检查一次] | [任务 {task_id} 进行中] | "
                        f"[已完成:{process_percent}%] | "
                        f"{description} | "
                        f"详情: {status}"
                    )

                    # 等待20秒后再次检查
                    time.sleep(20)
            except Exception as unknown_e:
                print(f" -> 监控任务时发生错误: {unknown_e}")
                break
    return True


def main_20251213(hosts: List[str]):
    index_mapping = {
        "crs_rebate-v1": {
            "name": "crs-rebate-v2",
            "alias": "crs_rebate-alias"
        },
        "crs-rebate-rank-detail-new-v1": {
            "name": "crs-rebate-rank-detail-v2",
            "alias": "crs-rebate-rank-detail-new-alias"
        },
        "crs-rebate-item-detail-new-v1": {
            "name": "crs-rebate-item-detail-v2",
            "alias": "crs-rebate-item-detail-new-alias"
        },
    }

    for old_index, new_index_dict in index_mapping.items():
        with timer():
            new_index = new_index_dict['name']
            print("=" * 50)
            print(f"开始处理索引, 旧索引:{old_index}, 新索引:{new_index}")
            result: Dict[str, Any] = reindex_es(
                hosts, old_index, new_index
            )
            print(f" => Reindex 结果: {result}")

            # 监控reindex的迁移任务
            while_monitor_reindex_task(result, hosts)

            print(f" => 完成单一索引迁移,旧索引:{old_index}, 新索引:{new_index}")

            print(f" => 开始迁移后别名交割,旧索引:{old_index}, 新索引:{new_index}")
            index_alias = new_index_dict['alias']
            print(f" => 索引的引用别名(程序内使用的别名):{index_alias}")

            switch_aliases(hosts, old_index, new_index, [index_alias])
            print(f" => 结束迁移后别名交割,旧索引:{old_index}, 新索引:{new_index}")

            print(" => 进行数据验证")
            monitor_reindex_count(hosts, new_index, old_index)

            print(f" => 【还没结束】再次reindex,确保迁移过程中后面进入的也数据都有进去！"
                  f" 旧索引:{old_index}, 新索引:{new_index}")

            # 增加查询条件限制，第二次reindex只同步今天的数据进行追加就可以了
            external_query = {
                "bool": {
                    "must": [
                        {
                            "range": {
                                "closeDate": {
                                    "gte": "1765583601000"
                                }
                            }
                        }
                    ]
                }
            }

            two_result: Dict[str, Any] = external_reindex_es(
                hosts, old_index, new_index, external_query
            )
            print(f" => 【还没结束】再次reindex 结果: {two_result}")

            # 监控再次reindex的迁移任务
            while_monitor_reindex_task(two_result, hosts)

            print(f"【单一索引迁移结束】完成迁移, "
                  f"旧索引:{old_index}, 新索引:{new_index}")

            print("=" * 50)


if __name__ == "__main__":
    if sys.version_info < (3, 5):
        raise RuntimeError("Frank提醒, 本脚本需要 Python 3.5 或更高版本才可支持！")

    hosts = [
        "http://8.212.45.69:19200",  # demo环境
        "http://119.23.145.91:59200",  # MT5准生产环境
    ]

    for exec_es_host in hosts:
        print(f"开始处理: {exec_es_host}")
        exec_es_hosts = [exec_es_host]
        main_20251213(exec_es_hosts)
