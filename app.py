from flask import Flask, jsonify
import requests
import logging
from logging.handlers import RotatingFileHandler
from apscheduler.schedulers.background import BackgroundScheduler
import os
from datetime import datetime

# 初始化Flask应用
app = Flask(__name__)
# 全局变量存储当前IP
current_public_ip = None
# 定义公网IP的获取服务器
services = [
    'https://api.ipify.org',
    'https://icanhazip.com',
    'https://ident.me'
]


def get_public_ip():
    """
    获取当前公网IP地址
    """
    try:

        for service in services:
            try:
                response = requests.get(service, timeout=10)
                if response.status_code == 200:
                    ip = response.text.strip()
                    # 验证IP地址格式
                    if validate_ip_address(ip):
                        app.logger.info(f"成功从 {service} 获取IP: {ip}")
                        return ip
            except requests.RequestException as e:
                app.logger.warning(f"从 {service} 获取IP失败: {str(e)}")
                continue

        app.logger.error("所有IP查询服务均失败")
        return None

    except Exception as e:
        app.logger.error(f"获取公网IP时发生异常: {str(e)}")
        return None


def validate_ip_address(ip):
    """
    验证IP地址格式是否有效
    """
    try:
        parts = ip.split('.')
        if len(parts) != 4:
            return False
        for part in parts:
            if not part.isdigit() or not 0 <= int(part) <= 255:
                return False
        return True
    except Exception as e:
        app.logger.error(f"校验IP时发生异常: {str(e)}")
        return False


# 配置日志
def setup_logging():
    # 当没有logs时候进行创建logs的目录
    if not os.path.exists('logs'):
        os.mkdir('logs')

    # 创建日志处理器
    file_handler = RotatingFileHandler(
        filename='logs/ip_change.log',
        encoding='utf-8',
        mode='a',
        maxBytes=102400,
        backupCount=10
    )
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'))
    file_handler.setLevel(logging.INFO)

    # 设置应用日志
    app.logger.addHandler(file_handler)
    app.logger.setLevel(logging.INFO)


def setup_scheduler():
    """
    设置定时任务调度器
    """
    try:
        # 创建调度器实例
        scheduler = BackgroundScheduler(daemon=True)

        # 添加每分钟执行一次的IP检查任务
        scheduler.add_job(
            id='ip_change_check',
            func=check_ip_change,
            trigger='interval',
            minutes=1,
            max_instances=1
        )

        # 启动调度器
        scheduler.start()
        app.logger.info("IP变更检测定时任务已启动")

    except Exception as e:
        app.logger.error(f"启动定时任务调度器失败: {str(e)}")


def check_ip_change():
    """
    检查公网IP是否变更
    """
    global current_public_ip

    try:
        new_ip = get_public_ip()
        if new_ip is None:
            app.logger.error("无法获取当前公网IP，跳过本次检查")
            return

        # 首次运行，初始化IP
        if current_public_ip is None:
            current_public_ip = new_ip
            app.logger.info(f"初始公网IP已设置: {current_public_ip}")
            return

        # 检查IP是否变更
        if new_ip != current_public_ip:
            # IP发生变更，记录错误日志
            error_message = f"公网IP变更告警: 从 {current_public_ip} 变更为 {new_ip}"
            app.logger.error(error_message)

            # 更新当前IP
            current_public_ip = new_ip

            send_alert_message_of_ip_change(current_public_ip, new_ip)
        else:
            app.logger.info(f"IP检查正常: {current_public_ip}")

    except Exception as e:
        app.logger.error(f"检查IP变更时发生异常: {str(e)}")


def send_alert_message_of_ip_change(prev_ip, new_ip):
    # 发送Microsoft Teams告警（如果有配置的话进行告警）
    teams_webhook_url = os.environ.get('TEAMS_WEBHOOK_URL')
    teams_at_persons = os.environ.get('TEAMS_AT_PERSONS')

    if not teams_webhook_url:
        return

    # 处理需要@的人员
    persons = []
    if teams_at_persons:
        # 支持使用逗号或顿号分隔的多个用户
        persons = teams_at_persons.replace('，', ',').split(',')

    # 构建消息文本
    message_text = ""
    for person in persons:
        message_text += f"<at>{person.strip()}</at> "

    payload = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": "0076D7",
        "summary": "公网IP变更告警",
        "sections": [{
            "activityTitle": f"{message_text}公网IP变更告警",
            "activitySubtitle": f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "activityImage": "https://teamsnodesample.azurewebsites.net/static/img/image5.png",
            "facts": [
                {
                    "name": "旧IP地址",
                    "value": prev_ip
                },
                {
                    "name": "新IP地址",
                    "value": new_ip
                }
            ],
            "markdown": True
        }],
        "potentialAction": [{
            "@type": "OpenUri",
            "name": "查看详细信息",
            "targets": [{
                "os": "default",
                "uri": "http://localhost:5000"
            }]
        }]
    }

    # 如果有需要@的人员，添加mentions字段
    if teams_at_persons:
        mentions = []
        for i, person in enumerate(persons):
            mentions.append({
                "id": i,
                "mentionText": person.strip()
            })
        payload["mentions"] = mentions

    # 最多重试3次
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.post(teams_webhook_url, json=payload, timeout=30)
            if response.status_code == 200:
                app.logger.info("Teams告警发送成功")
                return
            else:
                app.logger.error(f"发送Teams告警失败 (尝试 {attempt + 1}/{max_retries}): {response.text}")
        except Exception as e:
            app.logger.error(f"发送Teams告警时发生异常 (尝试 {attempt + 1}/{max_retries}): {str(e)}")

    app.logger.error(f"发送Teams告警失败，已重试 {max_retries} 次")


# 应用启动初始化
def initialize_app():
    """应用初始化"""
    setup_logging()

    # 启动时立即获取一次IP
    global current_public_ip
    current_public_ip = get_public_ip()

    if current_public_ip:
        app.logger.info(f"应用启动，初始公网IP: {current_public_ip}")
    else:
        app.logger.error("应用启动时无法获取公网IP")

    # 设置定时任务
    setup_scheduler()


initialize_app()


@app.route('/')
def index():
    """首页显示当前IP状态"""
    ip_status = f"当前公网IP: {current_public_ip if current_public_ip else '未获取'}"
    return f'''
    <h1>公网IP监控系统</h1>
    <p>{ip_status}</p>
    <p>最后检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    <p>查看日志文件: logs/ip_change_error.log</p>
    '''


@app.route('/ip')
def get_current_ip():
    """API接口返回当前IP"""
    return {
        'current_ip': current_public_ip,
        'last_check': datetime.now().isoformat(),
        'status': 'success'
    }


@app.route('/health')
def heath():
    return jsonify({"message": "Application is working"}), 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
