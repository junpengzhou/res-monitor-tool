# -*- coding: utf-8 -*-
import json
import os
from typing import List, Union

import jsonpath


def read_json_file(filename: str) -> dict:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(current_dir, filename)

    with open(file_path, 'r', encoding='utf-8') as file:
        return json.load(file)


def extract_values_by_jsonpath(data: dict, json_path: str) -> List[Union[int, float]]:
    matches = jsonpath.jsonpath(data, json_path)
    if matches is False:
        return []
    return [value for value in matches if isinstance(value, (int, float))]


def process_json_with_jsonpath(filename: str, json_path: str) -> any:
    data = read_json_file(filename)
    values = extract_values_by_jsonpath(data, json_path)
    return values


if __name__ == "__main__":
    try:
        data_json_result = process_json_with_jsonpath("data.json", "$.data.records[*].rebateAmount")

        data_json_result_sum = sum(data_json_result)

        print(f"根据条目计算出来的返佣金额总和: {data_json_result_sum}")

        statistics_json_result = process_json_with_jsonpath("statistics.json", "$.data.amount")

        statistics_json_result_sum = sum(statistics_json_result)
        print(f"根据统计数据计算出来的返佣金额总和: {statistics_json_result_sum}")

        assert data_json_result_sum == statistics_json_result_sum
        print("数据一致性测试通过")

    except FileNotFoundError:
        print("未找到指定的JSON文件")
    except Exception as e:
        print(f"处理过程中出现错误: {e}")
