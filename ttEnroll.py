import time
import json
import hashlib
import requests
from datetime import datetime
import sys
import os

from ttLogin import get_timetable_access_token

# ==========================================
# 配置参数 (支持从环境变量或 .env 读取)
# ==========================================
# 尝试加载 .env 如果有的话
env_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(env_path):
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                val = val.strip('\'"')
                os.environ[key] = val

TARGET_TIME_STR = os.environ.get("TT_TARGET_TIME")
IDENTITY = os.environ.get("TT_IDENTITY")

# 抢课请求 URL（与 TimetablePlus 当前选课页一致：普通课 peAct=false）
ENROLL_URL = f"https://timetableplus.xjtlu.edu.cn/actapi/api/enrollment/{IDENTITY}/Enroll/Payload?essAct=false&peAct=false"

# 要抢的课程数据
MODULE_IDS_ENV = os.environ.get("TT_MODULE_IDS")
ACTIVITY_IDS_ENV = os.environ.get("TT_ACTIVITY_IDS")

if not MODULE_IDS_ENV:
    print("错误: 必须在环境变量或 .env 中配置 TT_MODULE_IDS。")
    sys.exit(1)

try:
    MODULE_IDS = json.loads(MODULE_IDS_ENV)
except json.JSONDecodeError:
    print("错误: TT_MODULE_IDS 环境变量格式错误，请使用 JSON 数组格式。")
    sys.exit(1)

if not ACTIVITY_IDS_ENV:
    print("错误: 必须在环境变量或 .env 中配置 TT_ACTIVITY_IDS。")
    sys.exit(1)

try:
    ACTIVITY_IDS = json.loads(ACTIVITY_IDS_ENV)
except json.JSONDecodeError:
    print("错误: TT_ACTIVITY_IDS 环境变量格式错误，请使用 JSON 数组格式。")
    sys.exit(1)

def generate_signature(identity, activity_ids, timestamp_ms, module_ids):
    """
    签名算法：raw = "XLU" + identity + JSON.stringify(activityIds) + timestamp + JSON.stringify(moduleIds)
    token = md5(raw + raw)
    """
    activity_ids_str = json.dumps(activity_ids, separators=(',', ':'))
    module_ids_str = json.dumps(module_ids, separators=(',', ':'))
    
    raw_str = f"XLU{identity}{activity_ids_str}{timestamp_ms}{module_ids_str}"
    # 前端现为 md5(raw + raw)
    sign_token = hashlib.md5((raw_str + raw_str).encode('utf-8')).hexdigest().lower()
    return sign_token

def get_headers(access_token):
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Authorization": f"Bearer {access_token}",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "Content-Type": "application/json",
        "Host": "timetableplus.xjtlu.edu.cn",
        "Origin": "https://timetableplus.xjtlu.edu.cn",
        "Pragma": "no-cache",
        "Referer": "https://timetableplus.xjtlu.edu.cn/",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
        "sec-ch-ua": '"Not=A?Brand";v="99", "Google Chrome";v="151", "Chromium";v="151"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"'
    }

def main():
    try:
        target_time_obj = datetime.strptime(TARGET_TIME_STR, "%Y-%m-%d %H:%M:%S")
        target_timestamp = target_time_obj.timestamp()
    except ValueError:
        print("时间格式错误，请使用 'YYYY-MM-DD HH:MM:SS'")
        sys.exit(1)
        
    # 提前 5 分钟获取 token
    auth_time = target_timestamp - 5 * 60
    
    now = time.time()
    if now < auth_time:
        wait_seconds = auth_time - now
        print(f"[{datetime.now()}] 等待 {wait_seconds:.2f} 秒后开始获取 Token...")
        time.sleep(wait_seconds)
    else:
        print(f"[{datetime.now()}] 已经到达或超过提前 5 分钟的节点，立即开始获取 Token...")
        
    # 重试不超过三次获取 token
    access_token = None
    for attempt in range(1, 4):
        print(f"[{datetime.now()}] 尝试获取 Token (第 {attempt} 次)...")
        try:
            # 这里的 get_timetable_access_token 会输出很多 log
            access_token = get_timetable_access_token()
            if access_token:
                print(f"[{datetime.now()}] Token 获取成功！")
                break
        except Exception as e:
            print(f"[{datetime.now()}] 获取 Token 发生异常: {e}")
            
        if attempt < 3:
            time.sleep(2)
            
    if not access_token:
        print(f"[{datetime.now()}] 获取 Token 失败，程序退出。")
        sys.exit(1)
        
    # 目标时间后 100ms
    execute_time = target_timestamp + 0.1
    now = time.time()
    if now < execute_time:
        wait_seconds = execute_time - now
        print(f"[{datetime.now()}] 准备抢课，等待准点 ({TARGET_TIME_STR} + 100ms)，还需 {wait_seconds:.2f} 秒...")
        time.sleep(wait_seconds)
        
    # 开始发送抢课请求
    headers = get_headers(access_token)
    session = requests.Session()
    
    for attempt in range(1, 6):
        # 13 位毫秒级时间戳
        current_timestamp_ms = int(time.time() * 1000)
        
        # 计算签名 token
        sign_token = generate_signature(IDENTITY, ACTIVITY_IDS, current_timestamp_ms, MODULE_IDS)
        
        payload = {
            "moduleIds": MODULE_IDS,
            "activityIds": ACTIVITY_IDS,
            "timestamp": current_timestamp_ms,
            "token": sign_token
        }
        
        print(f"[{datetime.now()}] 发送第 {attempt} 次抢课请求。时间戳: {current_timestamp_ms}")
        
        try:
            resp = session.post(ENROLL_URL, json=payload, headers=headers, timeout=10)
            print(f"[{datetime.now()}] 响应状态码: {resp.status_code}")
            print(f"[{datetime.now()}] 响应内容: {resp.text}")
            
            if resp.status_code == 200:
                print(f"[{datetime.now()}] 抢课请求发送成功 (HTTP 200 OK)！")
                break
            else:
                print(f"[{datetime.now()}] 请求返回非 200 状态码，准备重试...")
        except Exception as e:
            print(f"[{datetime.now()}] 请求发生网络异常: {e}")
            
        if attempt < 5:
            # 等待 100ms 再重试
            time.sleep(0.1)

    print(f"[{datetime.now()}] 抢课脚本执行完毕。")

if __name__ == "__main__":
    main()
