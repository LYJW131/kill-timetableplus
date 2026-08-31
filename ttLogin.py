import os
import sys
import json
import requests
from urllib.parse import urlparse, parse_qs

# 增加能够找到 logConfig 的路径
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__))))

try:
    import uimLogin
except ImportError as e:
    print(f"无法导入 uimLogin: {e}")
    sys.exit(1)

def get_timetable_access_token():
    print("开始获取 TimetablePlus Access Token...")
    
    # 手动加载 .env 到环境变量
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, val = line.split('=', 1)
                    val = val.strip('\'"')
                    os.environ[key] = val
                    
    # 尝试登录 UIM 并获取 cookie
    success = uimLogin.uim_login()
    if not success:
        print("UIM 登录失败，无法继续获取 TimetablePlus Token。")
        return None

    cookie_file = uimLogin.COOKIE_FILE
    if not os.path.exists(cookie_file):
        print("未找到 Cookie 文件，请检查 UIM 登录是否成功保存。")
        return None

    with open(cookie_file, 'r', encoding='utf-8') as f:
        cookies_list = json.load(f)
    
    session = requests.Session()
    # 继承 uimLogin 中的 headers
    session.headers.update(uimLogin.COMMON_HEADERS)
    
    # 加载 Cookies
    for c in cookies_list:
        session.cookies.set(c['name'], c['value'], domain=c['domain'], path=c['path'])

    # 1. 请求 OAuth 授权码 (Client ID 为 TimetablePlus 的专属 ID)
    oauth_url = "https://uim.xjtlu.edu.cn/esc-sso/oauth2.0/authorize?client_id=eee8dfdbbbe72c43da98&redirect_uri=https://timetableplus.xjtlu.edu.cn/auth?return_uri=https://timetableplus.xjtlu.edu.cn/&response_type=code"
    
    print("正在请求 TimetablePlus OAuth 授权码...")
    resp = session.get(oauth_url, allow_redirects=False)
    
    if resp.status_code != 302:
        print(f"获取授权码失败，预期状态码 302，实际返回 {resp.status_code}")
        return None
        
    location = resp.headers.get('Location')
    
    if not location or "code=" not in location:
        print("未能从重定向中获取授权码 (code)。")
        return None
        
    print("成功获取授权码，正在交换 Access Token...")
    
    # 由于可能涉及多个 redirects，我们用 while 循环追踪
    current_url = location
    max_redirects = 5
    redirect_count = 0
    
    while redirect_count < max_redirects:
        resp_redirect = session.get(current_url, allow_redirects=False)
        # print(f"[{redirect_count}] GET {current_url} -> {resp_redirect.status_code}")
        
        next_loc = resp_redirect.headers.get('Location')
        if not next_loc:
            # Maybe the body contains the next redirect in JS?
            print("No next Location header. Response length:", len(resp_redirect.text))
            break
            
        # print(f"[{redirect_count}] Redirected to: {next_loc}")
        
        if "#/access_token=" in next_loc or "access_token=" in next_loc:
            if "#/access_token=" in next_loc:
                hash_part = next_loc.split("#/")[1]
            else:
                hash_part = next_loc.split("#")[1] if "#" in next_loc else next_loc.split("?")[1]
                
            params = parse_qs(hash_part)
            access_token = params.get('access_token', [None])[0]
            if access_token:
                # print("\n==================================================")
                # print(f"成功获取 TimetablePlus Access Token:\n{access_token}")
                # print("==================================================")
                print("成功获取 TimetablePlus Access Token")
                return access_token
        
        # If relative URL, make it absolute?
        if next_loc.startswith('/'):
            # This is a bit simplistic, but usually we stay on timetableplus domain
            current_url = "https://timetableplus.xjtlu.edu.cn" + next_loc
        else:
            current_url = next_loc
            
        redirect_count += 1
        
    print("未能在重定向链中找到 access_token。")
    return None

if __name__ == "__main__":
    print(get_timetable_access_token())
