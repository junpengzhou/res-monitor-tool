import os
import queue
from locust import HttpUser, task, constant, SequentialTaskSet


class TaskCase(SequentialTaskSet):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.order_id = None
        self.test_login = None

    def on_start(self):
        if hasattr(self.user, 'login_queue') and not self.user.login_queue.empty():
            self.test_login = self.user.login_queue.get()
        else:
            print(
                f"错误: 无法从队列获取登录信息。队列状态: exists={hasattr(self.user, 'login_queue')}, "
                f"empty={getattr(self.user, 'login_queue', queue.Queue()).empty()}"
            )
            self.interrupt()

    def open_order(self):
        """开仓任务"""
        if not hasattr(self, 'test_login'):
            print("未获取到登录信息，跳过开仓")
            return

        post_data = {
            "login": self.test_login,
            "symbol": "AUDUSD",
            "cmd": 1,
            "lots": 1
        }

        with self.client.post("/OpenOrder", json=post_data, catch_response=True) as resp:
            try:
                response_data = resp.json()
                if response_data.get("code") == 0 and "data" in response_data:
                    self.order_id = response_data["data"].get("order")
                    resp.success()
                else:
                    resp.failure(f"开仓请求失败: {resp.text},request_body={post_data}")
            except ValueError as e:
                resp.failure(f"响应不是有效的JSON格式: {resp.text} | 错误: {e}")
            except Exception as unknown_e:
                print(f"开仓出现未知错误: {unknown_e}")
                resp.failure(resp.text)

    def close_order(self):
        """平仓任务"""
        if hasattr(self, 'order_id') and self.order_id != 0:
            post_data = {"order": self.order_id}
            with self.client.post("/CloseOrder", json=post_data, catch_response=True) as resp:
                try:
                    if resp.json().get("code") == 0:
                        resp.success()
                        # 重置order_id
                        self.order_id = 0
                    else:
                        resp.failure(f"平仓请求失败: {resp.text},request_data={post_data}")
                except Exception as e:
                    resp.failure(f"平仓处理异常: {e},request_data={post_data}")
        else:
            print("order_id 不存在或为0，跳过平仓")

    @task
    def open_close_order(self):
        """组合任务：顺序执行开仓和平仓"""
        self.open_order()
        # self.close_order()

    def on_stop(self):
        """停止运行时执行，确保都进行了平仓"""
        if hasattr(self, 'order_id') and self.order_id != 0:
            self.close_order()
        print(f"用户 {getattr(self, 'test_login', 'Unknown')} 测试结束")


class ApiUser(HttpUser):
    # 每个任务执行后固定等待1秒
    wait_time = constant(1)
    # 指定要执行的任务集
    tasks = [TaskCase]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.login_queue = queue.Queue()
        self._init_login_queue()

    def _init_login_queue(self):
        file_path = "test_mt4_follow_mt4_login.txt"
        try:
            with open(file_path, 'r') as file:
                cleaned_lines = [line.strip() for line in file if line.strip()]
                for line in cleaned_lines:
                    try:
                        self.login_queue.put_nowait(int(line))
                    except ValueError:
                        print(f"警告: 文件 '{file_path}' 中的行 '{line}' 无法转换为整数，已跳过")
            if self.login_queue.empty():
                print(f"警告: 文件 '{file_path}' 无有效数据或为空")
        except FileNotFoundError:
            print(f"错误: 文件 '{file_path}' 未找到")
        except Exception as e:
            print(f"读取文件 '{file_path}' 时发生未知错误: {e}")


if __name__ == '__main__':
    # 启动Locust,并填写
    os.system("locust -f social_locust_mt4_follow_mt4.py --host=http://192.168.60.237:26001")
