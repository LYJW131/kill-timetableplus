"""
UIM 登录脚本
通过 RSA 加密密码并完成 UIM 统一身份认证登录
"""
import os
import json
import base64
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pyotp
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

# ============================================================================
# 配置区域
# ============================================================================

# 基础 URL
UIM_BASE_URL = "https://uim.xjtlu.edu.cn"

# API 端点
UIM_AUTH_POLICY_API = f"{UIM_BASE_URL}/esc-sso/api/v3/auth/policy"
UIM_DO_LOGIN_API = f"{UIM_BASE_URL}/esc-sso/api/v3/auth/doLogin"
UIM_OAUTH2_AUTHORIZE_API = f"{UIM_BASE_URL}/esc-sso/oauth2.0/authorize"
UIM_NGW_LOGIN_API = f"{UIM_BASE_URL}/ngw/login"

# OAuth2 配置
OAUTH2_CLIENT_ID = "fab04-6690-39830"

# 重试配置
RETRY_MAX_ATTEMPTS = 3  # 最大重试次数
RETRY_BACKOFF_FACTOR = 2  # 退避因子（秒）
RETRY_STATUS_CODES = [429, 500, 502, 503, 504]  # 需要重试的状态码

# Cookie 文件路径
COOKIE_FILE = Path(__file__).parent / "uim_cookies.json"

# 请求头配置
COMMON_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (darwin) AppleWebKit/537.36 (KHTML, like Gecko) jsdom/30.0.1',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Content-Type': 'application/json',
}

# ============================================================================
# 日志配置
# ============================================================================

try:
    from .logConfig import get_logger
except ImportError:
    from logConfig import get_logger

logger = get_logger("UIMLOGIN")

# ============================================================================
# 工具函数
# ============================================================================

def request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    max_attempts: int = RETRY_MAX_ATTEMPTS,
    backoff_factor: float = RETRY_BACKOFF_FACTOR,
    retry_status_codes: list = None,
    **kwargs
) -> requests.Response:
    """
    带重试机制的请求函数，专门处理 429 等错误
    
    Args:
        session: requests Session 对象
        method: 请求方法 ('GET', 'POST' 等)
        url: 请求 URL
        max_attempts: 最大重试次数
        backoff_factor: 退避因子（每次重试等待时间 = backoff_factor * (2 ** attempt)）
        retry_status_codes: 需要重试的状态码列表
        **kwargs: 传递给 requests 的其他参数
    
    Returns:
        requests.Response 对象
    
    Raises:
        requests.RequestException: 当所有重试都失败时
    """
    if retry_status_codes is None:
        retry_status_codes = RETRY_STATUS_CODES
    
    last_exception = None
    
    for attempt in range(max_attempts):
        try:
            if method.upper() == 'GET':
                response = session.get(url, **kwargs)
            elif method.upper() == 'POST':
                response = session.post(url, **kwargs)
            else:
                response = session.request(method, url, **kwargs)
            
            # 检查是否需要重试
            if response.status_code in retry_status_codes:
                wait_time = backoff_factor * (2 ** attempt)
                
                # 尝试从 Retry-After 头获取等待时间
                retry_after = response.headers.get('Retry-After')
                if retry_after:
                    try:
                        wait_time = max(wait_time, int(retry_after))
                    except ValueError:
                        pass
                
                logger.warning(
                    f"请求返回 {response.status_code}，等待 {wait_time:.1f} 秒后重试 "
                    f"(尝试 {attempt + 1}/{max_attempts})"
                )
                time.sleep(wait_time)
                continue
            
            # 成功或其他非重试状态码
            response.raise_for_status()
            return response
            
        except requests.RequestException as e:
            last_exception = e
            
            # 检查是否是需要重试的状态码错误
            if hasattr(e, 'response') and e.response is not None:
                if e.response.status_code in retry_status_codes:
                    wait_time = backoff_factor * (2 ** attempt)
                    
                    # 尝试从 Retry-After 头获取等待时间
                    retry_after = e.response.headers.get('Retry-After')
                    if retry_after:
                        try:
                            wait_time = max(wait_time, int(retry_after))
                        except ValueError:
                            pass
                    
                    if attempt < max_attempts - 1:
                        logger.warning(
                            f"请求失败 ({e.response.status_code})，等待 {wait_time:.1f} 秒后重试 "
                            f"(尝试 {attempt + 1}/{max_attempts})"
                        )
                        time.sleep(wait_time)
                        continue
            
            # 不是可重试的错误，直接抛出
            if attempt == max_attempts - 1:
                raise
    
    # 所有重试都失败
    if last_exception:
        raise last_exception
    raise requests.RequestException(f"请求 {url} 失败，已重试 {max_attempts} 次")


def get_env_credentials() -> tuple[str, str, str]:
    """
    从环境变量获取登录凭证
    返回：(username, password, otp_url)
    """
    username = os.environ.get("XJTLU_USERNAME")
    password = os.environ.get("XJTLU_PASSWORD")
    otp_url = os.environ.get("XJTLU_OTP_URL")
    
    if not username:
        raise ValueError("环境变量 XJTLU_USERNAME 未设置")
    if not password:
        raise ValueError("环境变量 XJTLU_PASSWORD 未设置")
    if not otp_url:
        raise ValueError("环境变量 XJTLU_OTP_URL 未设置")
    
    return username, password, otp_url


def generate_otp_from_url(otp_url: str) -> str:
    """
    从 OTP URL 生成一次性密码
    
    Args:
        otp_url: otpauth:// 格式的 URL
    
    Returns:
        6位 OTP 验证码
    """
    # 解析 otpauth URL 获取 secret
    parsed = urlparse(otp_url)
    params = parse_qs(parsed.query)
    secret = params.get('secret', [None])[0]
    
    if not secret:
        raise ValueError("OTP URL 中缺少 secret 参数")
    
    # 生成 TOTP
    totp = pyotp.TOTP(secret)
    return totp.now()


def encrypt_password_rsa(password: str, public_key_content: str) -> str:
    """
    使用 RSA-2048 (PKCS#1 v1.5) 加密密码
    
    Args:
        password: 明文密码
        public_key_content: 公钥内容（不含 PEM 头尾标记）
    
    Returns:
        Base64 编码的加密密码
    """
    # 添加 PEM 头尾标记
    pem_key = f"-----BEGIN PUBLIC KEY-----\n{public_key_content}\n-----END PUBLIC KEY-----"
    
    # 加载公钥
    public_key = serialization.load_pem_public_key(
        pem_key.encode('utf-8'),
        backend=default_backend()
    )
    
    # 使用 PKCS#1 v1.5 填充进行加密
    encrypted = public_key.encrypt(
        password.encode('utf-8'),
        padding.PKCS1v15()
    )
    
    # Base64 编码
    return base64.b64encode(encrypted).decode('utf-8')


def save_cookies(cookies: requests.cookies.RequestsCookieJar, extra_cookies: list = None) -> bool:
    """
    保存 TGC cookie 和额外的 cookies 到文件
    
    Args:
        cookies: requests 的 cookie jar（用于提取 TGC）
        extra_cookies: 额外要保存的 cookie 列表
    """
    try:
        cookies_list = []
        
        # 保存名为 TGC 的 cookie
        for cookie in cookies:
            if cookie.name == "TGC":
                cookies_list.append({
                    'name': cookie.name,
                    'value': cookie.value,
                    'domain': cookie.domain,
                    'path': cookie.path,
                    'expires': cookie.expires,
                    'secure': cookie.secure
                })
                logger.success("已保存 TGC cookie")
        # 添加额外的 cookies
        if extra_cookies:
            cookies_list.extend(extra_cookies)
        
        if not cookies_list:
            logger.warning("未找到要保存的 cookie")
            return False
        
        # 确保目录存在
        COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        with open(COOKIE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cookies_list, f, ensure_ascii=False, indent=2)
        
        logger.success("Cookies 已保存")
        return True
        
    except Exception as e:
        logger.error(f"保存 Cookies 失败: {e}")
        return False


# ============================================================================
# UIM 登录类
# ============================================================================

class UimLoginClient:
    """UIM 登录客户端"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(COMMON_HEADERS)
        self.public_key = None
        self.public_key_id = None
    
    def _step1_get_auth_policy(self) -> bool:
        """
        第一步：获取认证策略，包括公钥信息
        
        Returns:
            成功返回 True，失败返回 False
        """
        logger.info("获取认证策略...")
        
        try:
            response = request_with_retry(self.session, 'GET', UIM_AUTH_POLICY_API)
            
            data = response.json()
            logger.debug(f"认证策略响应: {json.dumps(data, ensure_ascii=False, indent=2)}")
            
            # 检查响应码（注意：code 可能是字符串 "0" 或数字 0）
            code = data.get("code")
            if str(code) != "0":
                message = data.get("msg", "未知错误")
                raise Exception(f"获取认证策略失败，错误码: {code}，消息: {message}")
            
            # 提取公钥信息
            param = data.get("data", {}).get("param", {})
            self.public_key = param.get("publicKey")
            self.public_key_id = param.get("publicKeyId")
            
            if not self.public_key or not self.public_key_id:
                raise Exception("响应中缺少公钥信息")
            
            logger.success(f"获取公钥成功，publicKeyId: {self.public_key_id}")
            return True
            
        except requests.RequestException as e:
            logger.error(f"请求认证策略失败: {e}")
            return False
        except Exception as e:
            logger.error(f"处理认证策略失败: {e}")
            return False
    
    def _step2_encrypt_password(self, password: str) -> str:
        """
        第二步：使用公钥加密密码
        
        Args:
            password: 明文密码
        
        Returns:
            加密后的密码
        """
        if not self.public_key:
            raise Exception("公钥未初始化，请先调用 _step1_get_auth_policy")
        
        logger.info("加密密码...")
        encrypted_password = encrypt_password_rsa(password, self.public_key)
        logger.success("密码加密成功")
        
        return encrypted_password
    
    def _step3_do_login(self, username: str, encrypted_password: str) -> dict:
        """
        第三步：执行登录请求
        
        Args:
            username: 用户名
            encrypted_password: 加密后的密码
        
        Returns:
            登录响应数据
        """
        logger.info("执行登录请求...")
        
        payload = {
            "authType": "webLocalAuth",
            "dataField": {
                "username": username,
                "password": encrypted_password,
                "publicKeyId": self.public_key_id
            }
        }
        
        logger.debug(f"登录请求体: {json.dumps(payload, ensure_ascii=False, indent=2)}")
        
        try:
            response = request_with_retry(self.session, 'POST', UIM_DO_LOGIN_API, json=payload)
            
            data = response.json()
            logger.success("登录请求成功")
            
            return data
            
        except requests.RequestException as e:
            logger.error(f"登录请求失败: {e}")
            raise
    
    def _step4_do_otp_login(self, username: str, otp_url: str) -> dict:
        """
        第四步：执行 OTP 二次验证登录
        
        Args:
            username: 用户名
            otp_url: OTP URL
        
        Returns:
            登录响应数据
        """
        logger.info("执行 OTP 二次验证...")
        
        # 生成 OTP
        otp_code = generate_otp_from_url(otp_url)
        logger.info(f"已生成 OTP: {otp_code}")
        
        payload = {
            "authType": "webOtpAuth",
            "dataField": {
                "username": username,
                "password": "",
                "otp": otp_code
            },
            "redirectUri": ""
        }
        
        logger.debug(f"OTP 登录请求体: {json.dumps(payload, ensure_ascii=False, indent=2)}")
        
        try:
            response = request_with_retry(self.session, 'POST', UIM_DO_LOGIN_API, json=payload)
            
            data = response.json()
            logger.success("OTP 登录请求成功")

            return data
            
        except requests.RequestException as e:
            logger.error(f"OTP 登录请求失败: {e}")
            raise
    
    def _step5_get_oauth_code(self) -> str:
        """
        第五步：获取 OAuth2 授权码
        
        Returns:
            OAuth2 授权码
        """
        logger.info("获取 OAuth2 授权码...")
        
        # 构建 OAuth2 授权 URL
        params = {
            'response_type': 'code',
            'client_id': OAUTH2_CLIENT_ID,
            'redirect_uri': UIM_NGW_LOGIN_API
        }
        oauth_url = f"{UIM_OAUTH2_AUTHORIZE_API}?{urlencode(params)}"
        
        for attempt in range(RETRY_MAX_ATTEMPTS):
            try:
                # 禁止自动重定向，手动处理 302
                response = self.session.get(oauth_url, allow_redirects=False)
                
                # 检查是否需要重试（429 等错误）
                if response.status_code in RETRY_STATUS_CODES:
                    wait_time = RETRY_BACKOFF_FACTOR * (2 ** attempt)
                    retry_after = response.headers.get('Retry-After')
                    if retry_after:
                        try:
                            wait_time = max(wait_time, int(retry_after))
                        except ValueError:
                            pass
                    logger.warning(
                        f"获取授权码返回 {response.status_code}，等待 {wait_time:.1f} 秒后重试 "
                        f"(尝试 {attempt + 1}/{RETRY_MAX_ATTEMPTS})"
                    )
                    time.sleep(wait_time)
                    continue
                
                if response.status_code != 302:
                    raise Exception(f"期望 302 重定向，实际状态码: {response.status_code}")
                
                # 从 Location 头提取授权码
                location = response.headers.get('Location', '')
                logger.debug(f"OAuth2 重定向 Location: {location}")
                
                # 解析 URL 获取 code 参数
                parsed = urlparse(location)
                query_params = parse_qs(parsed.query)
                code = query_params.get('code', [None])[0]
                
                if not code:
                    raise Exception(f"未能从 Location 中提取授权码: {location}")
                
                logger.success(f"获取授权码成功: {code[:20]}...")
                return code
                
            except requests.RequestException as e:
                if attempt < RETRY_MAX_ATTEMPTS - 1:
                    wait_time = RETRY_BACKOFF_FACTOR * (2 ** attempt)
                    logger.warning(f"获取授权码请求失败: {e}，等待 {wait_time:.1f} 秒后重试")
                    time.sleep(wait_time)
                else:
                    logger.error(f"获取授权码请求失败: {e}")
                    raise
        
        raise Exception(f"获取授权码失败，已重试 {RETRY_MAX_ATTEMPTS} 次")
    
    def _step6_exchange_code(self, code: str) -> list:
        """
        第六步：用授权码换取最终 cookies
        
        Args:
            code: OAuth2 授权码
        
        Returns:
            需要保存的 cookies 列表
        """
        logger.info("用授权码换取 cookies...")
        
        # 构建请求 URL
        exchange_url = f"{UIM_NGW_LOGIN_API}?code={code}"
        
        for attempt in range(RETRY_MAX_ATTEMPTS):
            try:
                # 禁止自动重定向
                response = self.session.get(exchange_url, allow_redirects=False)
                
                # 检查是否需要重试（429 等错误）
                if response.status_code in RETRY_STATUS_CODES:
                    wait_time = RETRY_BACKOFF_FACTOR * (2 ** attempt)
                    retry_after = response.headers.get('Retry-After')
                    if retry_after:
                        try:
                            wait_time = max(wait_time, int(retry_after))
                        except ValueError:
                            pass
                    logger.warning(
                        f"授权码交换返回 {response.status_code}，等待 {wait_time:.1f} 秒后重试 "
                        f"(尝试 {attempt + 1}/{RETRY_MAX_ATTEMPTS})"
                    )
                    time.sleep(wait_time)
                    continue
                
                if response.status_code != 302:
                    raise Exception(f"期望 302 重定向，实际状态码: {response.status_code}")
                
                location = response.headers.get('Location', '')
                logger.debug(f"授权码交换重定向 Location: {location}")
                
                # 验证重定向到预期地址
                if not location.startswith("/"):
                    logger.warning(f"重定向地址不符合预期: {location}")
                
                # 提取此步骤设置的 cookies
                extra_cookies = []
                for cookie in response.cookies:
                    extra_cookies.append({
                        'name': cookie.name,
                        'value': cookie.value,
                        'domain': cookie.domain,
                        'path': cookie.path,
                        'expires': cookie.expires,
                        'secure': cookie.secure
                    })
                
                logger.success(f"授权码交换成功，获取 {len(extra_cookies)} 个 cookies")
                return extra_cookies
                
            except requests.RequestException as e:
                if attempt < RETRY_MAX_ATTEMPTS - 1:
                    wait_time = RETRY_BACKOFF_FACTOR * (2 ** attempt)
                    logger.warning(f"授权码交换请求失败: {e}，等待 {wait_time:.1f} 秒后重试")
                    time.sleep(wait_time)
                else:
                    logger.error(f"授权码交换请求失败: {e}")
                    raise
        
        raise Exception(f"授权码交换失败，已重试 {RETRY_MAX_ATTEMPTS} 次")

    def login(self, username: str, password: str, otp_url: str) -> dict:
        """
        执行完整的登录流程
        
        Args:
            username: 用户名
            password: 明文密码
            otp_url: OTP URL（用于二次验证）
        
        Returns:
            登录响应数据
        """
        # 第一步：获取认证策略
        if not self._step1_get_auth_policy():
            raise Exception("获取认证策略失败")
        
        # 第二步：加密密码
        encrypted_password = self._step2_encrypt_password(password)
        
        # 第三步：执行登录
        result = self._step3_do_login(username, encrypted_password)
        
        # 检查是否需要 2FA
        redirect = result.get("data", {}).get("redirect", "")
        if "mfaLogin" in redirect:
            logger.info("需要二次验证 (MFA)，继续 OTP 登录...")
            result = self._step4_do_otp_login(username, otp_url)
        
        # 检查登录结果
        code = result.get("code")
        if str(code) != "0":
            raise Exception(f"登录失败，错误码: {code}")
        
        # 第五步：获取 OAuth2 授权码
        oauth_code = self._step5_get_oauth_code()
        
        # 第六步：用授权码换取最终 cookies
        extra_cookies = self._step6_exchange_code(oauth_code)
        
        # 保存 TGC 和最后一步的 cookies
        save_cookies(self.session.cookies, extra_cookies)
        
        return result


# ============================================================================
# 主函数
# ============================================================================

def uim_login() -> bool:
    """
    UIM 登录入口函数（同步版本）
    
    Returns:
        登录成功返回 True，失败返回 False
    """
    try:
        # 获取凭证
        username, password, otp_url = get_env_credentials()
        logger.info(f"开始 UIM 登录，用户: {username}")
        
        # 创建客户端并登录
        client = UimLoginClient()
        result = client.login(username, password, otp_url)
        
        # 检查登录结果
        code = result.get("code")
        if str(code) == "0":
            logger.success("UIM 登录成功！")
            return True
        else:
            logger.warning(f"UIM 登录返回非零代码: {code}")
            return False
    except Exception as e:
        logger.error(f"UIM 登录失败: {e}")
        return False


async def do_login() -> bool:
    """
    异步版本的 UIM 登录入口函数
    与旧版 Playwright 版本保持接口兼容
    
    Returns:
        登录成功返回 True，失败返回 False
    """
    import asyncio
    return await asyncio.to_thread(uim_login)


if __name__ == "__main__":
    result = uim_login()
    if not result:
        exit(1)
