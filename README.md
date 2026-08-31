# XJTLU TimetablePlus 抢课

通过 UIM 登录 TimetablePlus，在开抢时间发送选课请求。

## 配置

凭据只放本地 `.env`，不要提交。

```bash
cp .env.example .env
```

填写：

- `XJTLU_USERNAME` / `XJTLU_PASSWORD` / `XJTLU_OTP_URL`：UIM 账号和 OTP
- `TT_IDENTITY`：学号
- `TT_TARGET_TIME`：开抢时间，`YYYY-MM-DD HH:MM:SS`
- `TT_MODULE_IDS` / `TT_ACTIVITY_IDS`：JSON 数组，从选课请求里复制

## 运行

```bash
pip install requests pyotp cryptography urllib3 loguru
python ttEnroll.py
```

或：

```bash
docker compose up --build
```

脚本会在开抢前 5 分钟登录拿 token，准点后发送请求。
