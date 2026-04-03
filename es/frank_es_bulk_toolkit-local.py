import json
import os
import subprocess
import sys
from typing import List, Dict, Any
import traceback


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
    es = create_es_client(es_hosts)

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


def delete_es_field(
        es_hosts: List[str],
        prev_index_name: str,
        del_field_names: List[str],
        add_fields: List[dict[str, Any]],
        next_index_name: str,
        wait_for_completion: bool = False,
) -> Dict[str, Any]:
    """
    删除Elasticsearch索引中的指定字段并通过reindex重建索引

    Args:
        es_hosts: ES连接地址列表
        prev_index_name: 要处理的索引名称
        del_field_names: 要删除的字段名
        next_index_name: 新索引名称
        wait_for_completion: 是否等待reindex完成

    Returns:
        reindex操作结果的统计信息
    """
    es = create_es_client(es_hosts)
    result = {
        "success": False,
        "original_index": prev_index_name,
        "new_index": next_index_name,
        "deleted_field": del_field_names,
        "task_id": None,
        "error": None
    }

    # 1. 检查原索引是否存在
    if not es.indices.exists(index=prev_index_name):
        print(f"错误: 索引 {prev_index_name} 不存在")
        result["error"] = f"索引 {prev_index_name} 不存在"
        return result

    # 2. 获取原索引的映射和设置
    old_mapping = es.indices.get_mapping(index=prev_index_name)
    old_settings = es.indices.get_settings(index=prev_index_name)
    print(f"原索引配置留底, mapping: {str(old_mapping)}, settings: {str(old_settings)}")

    if prev_index_name not in old_mapping:
        print(f"错误: 别名存在，但是索引名 {prev_index_name} 不存在")
        result["error"] = f"别名存在，但是索引名 {prev_index_name} 不存在"
        return result

    # 3. 创建新映射（删除指定字段）
    new_mapping = old_mapping[prev_index_name]["mappings"]
    if "properties" in new_mapping:
        next_mapping_properties = new_mapping["properties"]
        # 删除指定的字段集合
        for del_field_name in del_field_names:
            if del_field_name in next_mapping_properties:
                del new_mapping["properties"][del_field_name]
        print(f"已从新映射中删除字段集: {del_field_names}")
    else:
        print(f"字段 {del_field_names} 在原索引中不存在，无需删除")

    # 看看有没有要顺便增加字段的操作
    if add_fields:
        for add_field in add_fields:
            add_field_name = add_field["name"]
            add_field_type = add_field["type"]
            add_field_format = add_field["format"]
            if add_field_name not in new_mapping["properties"]:
                new_mapping["properties"][add_field_name] = {
                    "type": add_field_type
                }
                # 添加上format
                if add_field_format:
                    new_mapping["properties"][add_field_name]["format"] = add_field_format
                print(f"已添加字段: \"{add_field_name}\": {new_mapping["properties"][add_field_name]}")

    # 需要被移除的settings.index下的节点
    to_be_remove_node = [
        "version",
        "creation_date",
        "routing",
        "uuid",
        "provided_name"
    ]

    new_settings = old_settings[prev_index_name]["settings"]
    for node in to_be_remove_node:
        if node in new_settings["index"]:
            del new_settings["index"][node]

    # 4. 创建新索引
    create_body = {
        "mappings": new_mapping,
        "settings": new_settings
    }
    create_body_json_str = json.dumps(create_body)
    print(f"正在创建新索引: {next_index_name}, body:{create_body_json_str}")
    es.indices.create(index=next_index_name, body=create_body)
    print(f"已创建新索引: {next_index_name}")

    # 5. 执行reindex操作，删除字段数据
    reindex_body = {
        "source": {
            "index": prev_index_name
        },
        "dest": {
            "index": next_index_name
        }
    }

    # 执行reindex
    reindex_response = es.reindex(
        body=reindex_body,
        wait_for_completion=wait_for_completion
    )

    if wait_for_completion:
        print(f"Reindex 完成: 处理 {reindex_response['total']} 个文档")
        result["success"] = True
    else:
        result["task_id"] = reindex_response["task"]
        print(f"Reindex 任务已提交，任务ID: {result['task_id']}")
        result["success"] = True

    return result


def reindex_es(
        es_hosts: List[str],
        index_name: str,
        new_index_name: str,
        wait_for_completion: bool = False,
) -> Dict[str, Any]:
    """
    通过reindex重建索引

    Args:
        es_hosts: ES连接地址列表
        index_name: 要处理的索引名称
        new_index_name: 新索引名称
        wait_for_completion: 是否等待reindex完成

    Returns:
        reindex操作结果的统计信息
    """
    es = create_es_client(es_hosts)
    result = {
        "success": False,
        "original_index": index_name,
        "new_index": new_index_name,
        "task_id": None,
        "error": None
    }

    # 1. 检查原索引是否存在
    if not es.indices.exists(index=index_name):
        print(f"错误: 索引 {index_name} 不存在")
        result["error"] = f"索引 {index_name} 不存在"
        return result

    # 2. 获取原索引的映射和设置
    old_mapping = es.indices.get_mapping(index=index_name)
    old_settings = es.indices.get_settings(index=index_name)

    # 3. 创建新映射（删除指定字段）
    new_mapping = old_mapping[index_name]["mappings"]

    # 需要被移除的settings.index下的节点
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

    # 4. 创建新索引
    create_body = {
        "mappings": new_mapping,
        "settings": new_settings
    }
    create_body_json_str = json.dumps(create_body)
    print(f"正在创建新索引: {new_index_name}, body:{create_body_json_str}")
    es.indices.create(index=new_index_name, body=create_body)
    print(f"已创建新索引: {new_index_name}")

    # 5. 执行reindex操作，删除字段数据
    reindex_body = {
        "source": {
            "index": index_name
        },
        "dest": {
            "index": new_index_name
        }
    }

    # 执行reindex
    reindex_response = es.reindex(
        body=reindex_body,
        wait_for_completion=wait_for_completion
    )

    if wait_for_completion:
        print(f"Reindex 完成: 处理 {reindex_response['total']} 个文档")
        result["success"] = True
    else:
        result["task_id"] = reindex_response["task"]
        print(f"Reindex 任务已提交，任务ID: {result['task_id']}")
        result["success"] = True

    return result


def switch_aliases(
        es_hosts: List[str],
        old_index: str,
        new_index: str,
        aliases: List[str]) -> bool:
    """
    切换索引别名，实现零停机时间切换

    Args:
        es_hosts: ES连接地址列表
        old_index: 旧索引名称
        new_index: 新索引名称
        aliases: 别名列表

    Returns:
        操作是否成功
    """
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
        print(f"别名切换完成: {aliases} 从 {old_index} 切换到 {new_index}")

    return True


def append_alias(
        es_hosts: List[str],
        index_name: str,
        alias_name: str) -> bool:
    es = create_es_client(es_hosts)
    actions = [{"add": {"index": index_name, "alias": alias_name}}]
    return es.indices.update_aliases(body={"actions": actions})


def complete_field_deletion(
        es_hosts: List[str],
        prev_index_name: str,
        del_field_names: List[str],
        add_fields: List[dict[str, Any]],
        next_index_name: str) -> Dict[str, Any]:
    """
    完整的字段删除流程：reindex + 别名切换 + 清理

    Args:
        es_hosts: ES连接地址列表
        prev_index_name: 要处理的索引名称
        del_field_names: 要删除的字段名
        next_index_name: 新索引名称

    Returns:
        完整操作结果的统计信息
    """
    result = {
        "success": False,
        "original_index": prev_index_name,
        "new_index": next_index_name,
        "deleted_field": del_field_names,
        "steps": {}
    }

    es = create_es_client(es_hosts)

    # 步骤1: 获取原索引的别名
    aliases = []
    alias_info = es.indices.get_alias(index=prev_index_name)
    for index_data in alias_info.values():
        aliases.extend(list(index_data.get("aliases", {}).keys()))

    # 步骤2: 执行reindex删除字段
    reindex_result = delete_es_field(
        es_hosts=es_hosts,
        prev_index_name=prev_index_name,
        del_field_names=del_field_names,
        add_fields=add_fields,
        next_index_name=next_index_name,
        wait_for_completion=True
    )

    result["steps"]["reindex"] = reindex_result
    if not reindex_result["success"]:
        return result

    # 步骤3: 切换别名
    if aliases:
        alias_result = switch_aliases(es_hosts, prev_index_name, next_index_name, aliases)
        result["steps"]["alias_switch"] = {"success": alias_result}
        if not alias_result:
            print("警告: 别名切换失败，但reindex已完成")

    # 步骤4: 验证新索引数据
    try:
        new_count = es.count(index=next_index_name)["count"]
        old_count = es.count(index=prev_index_name)["count"]
        result["steps"]["validation"] = {
            "old_index_count": old_count,
            "new_index_count": new_count,
            "match": old_count == new_count
        }
        print(f"数据验证: 旧索引 {old_count} 条, 新索引 {new_count} 条")
    except Exception as unknown_e:
        traceback.print_exc()
        print(f"数据验证时发生错误: {str(unknown_e)}")

    # 步骤5: 删除旧索引
    try:
        if es.indices.exists(index=prev_index_name):
            # 确保旧索引没有别名关联后再删除
            if aliases:
                es.options(ignore_status=404).indices.delete_alias(index=prev_index_name, name="*")
            # 删除旧的索引
            es.indices.delete(index=prev_index_name)
            result["steps"]["delete_old_index"] = {"success": True}
            print(f"已删除旧索引: {prev_index_name}")
    except Exception as unknown_e:
        traceback.print_exc()
        print(f"删除旧索引时发生错误: {str(unknown_e)}")
        result["steps"]["delete_old_index"] = {"success": False, "error": str(unknown_e)}

    # 如果索引本身名称没有在别名中，则添加别名进去
    if prev_index_name not in aliases:
        append_alias(es_hosts, next_index_name, prev_index_name)

    result["success"] = True

    return result


def monitor_reindex_task(es_hosts: List[str], task_id: str) -> Dict[str, Any]:
    """
    监控reindex任务进度

    Args:
        es_hosts: ES连接地址列表
        task_id: 任务ID

    Returns:
        任务状态信息
    """
    es = create_es_client(es_hosts)
    return es.tasks.get(task_id=task_id)


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


def main_es_del_add_reindex():
    hosts = [
        "http://192.168.50.208:59200",  # TEST6环境
        # "http://192.168.50.76:19200",  # 测试环境test1
        # "http://8.212.45.69:19200",  # demo环境
        # "http://119.23.145.91:59200",  # MT5准生产环境
    ]
    # 需要删除的字段
    delete_fields = [
        "linkedAgentIds",
        "agentIdChains"
    ]
    # 需要添加的字段
    add_fields = [
        {"name": "agentIdChains", "type": "long", "format": None},
    ]
    # 索引迁移字典
    indices_dict = {
        "sim-mt5-deals": "sim-mt5-deals-v2",
        "crm-mt5-deals": "crm-mt5-deals-v2",
        "crm-mt5-orders": "crm-mt5-orders-v2",
        "sim-mt5-orders": "sim-mt5-orders-v2",
        "crm-mt5-positions": "crm-mt5-positions-v2",
        "sim-mt5-positions": "sim-mt5-positions-v2",
        "crm-order-combine-v2": "crm-order-combine-v2_new",
        "sim-order-combine-v2": "sim-order-combine-v2_new",
    }

    # 删除对应的v2的linkedAgentIds字段，完整流程
    for host in hosts:
        for index_name, new_index_name in indices_dict.items():
            print(f"正在处理索引{host}的{index_name}索引...")
            # 完整流程来进行字段的删除的动作
            complete_field_deletion(
                es_hosts=[host],
                prev_index_name=index_name,
                del_field_names=delete_fields,
                add_fields=add_fields,
                next_index_name=new_index_name,
            )
            print(f"完成处理索引{host}的{index_name}索引！")


def main_rebate_es_del_add_reindex():
    hosts = [
        "http://192.168.50.208:59200",  # TEST6环境
        "http://192.168.50.76:19200",  # 测试环境test1
        "http://8.212.45.69:19200",  # demo环境
        "http://119.23.145.91:59200",  # MT5准生产环境
    ]
    # 需要删除的字段
    delete_fields = [
        "linkedAgentIds",
        "agentIdChains"
    ]
    # 需要添加的字段
    add_fields = [
        {"name": "agentIdChains", "type": "long", "format": None},
    ]
    # 索引迁移字典
    indices_dict = {
        "sim-mt5-deals": "sim-mt5-deals-v2",
        "crm-mt5-deals": "crm-mt5-deals-v2",
        "crm-mt5-orders": "crm-mt5-orders-v2",
        "sim-mt5-orders": "sim-mt5-orders-v2",
        "crm-mt5-positions": "crm-mt5-positions-v2",
        "sim-mt5-positions": "sim-mt5-positions-v2",
        "crm-order-combine-v2": "crm-order-combine-v2_new",
        "sim-order-combine-v2": "sim-order-combine-v2_new",
    }

    # 删除对应的v2的linkedAgentIds字段，完整流程
    for host in hosts:
        for index_name, new_index_name in indices_dict.items():
            print(f"正在处理索引{host}的{index_name}索引...")
            # 完整流程来进行字段的删除的动作
            complete_field_deletion(
                es_hosts=[host],
                prev_index_name=index_name,
                del_field_names=delete_fields,
                add_fields=add_fields,
                next_index_name=new_index_name,
            )
            print(f"完成处理索引{host}的{index_name}索引！")


def main_es_add_rebate_column():
    hosts = [
        "http://192.168.50.208:59200",  # TEST6环境
        "http://192.168.50.76:19200",  # 测试环境test1
        "http://8.212.45.69:19200",  # demo环境
        "http://119.23.145.91:59200",  # MT5准生产环境
    ]
    indices = [
        "crm-order-combine-v2",
        "sim-order-combine-v2",
    ]
    add_fields = {
        "deal": "keyword",
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
=== Frank工具输出处理结果汇总：添加字段成功！===
hosts: {host}
index_name: {index_name}
field_name: {field_name}
field_type: {field_type}
=== Frank工具输出处理结果汇总：添加字段成功！===
                """)


if __name__ == "__main__":
    if sys.version_info < (3, 5):
        raise RuntimeError("Frank提醒, 本脚本需要 Python 3.5 或更高版本才可支持！")
    # main_es_del_add_reindex()
    main_es_add_rebate_column()
