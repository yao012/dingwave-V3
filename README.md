# dingwave-V3 — 钉钉 V3 数据库解密与聊天记录导出

本项目是我为了蒸馏自己的逆向工程 skill 而做的练手项目，实现了钉钉桌面端 **V3 版本**数据库的解密（同时兼容 V2）。

V3 密钥推导思路参考了看雪论坛 [小周学习站](https://bbs.kanxue.com/thread-287455.htm) 同学的逆向分析，在此感谢。

> **声明**：仅供个人学习和数据备份使用，请遵守相关法规。

## V3 解密原理

钉钉桌面端的 `dingtalk.db` 使用 **AES-128-ECB** 按 4096 字节页加密。V2 和 V3 的区别在于密钥推导：

| 版本 | 密钥推导 |
|------|---------|
| V2 | `key = MD5(uid).hex[:16]` |
| V3 | `key = MD5(PBKDF2_SHA1(uid+salt, "666DingT", 1000, 32)).hex[:16]` |

### V3 密钥推导步骤

1. 读取 `{data_dir}/user_config` → Base64 解码 → JSON → 取 `salt` 字段（32位hex）
2. 拼接 `password = uid + salt`（uid 为 9-10 位数字 ID，**不是**文件夹名）
3. `PKCS5_PBKDF2_HMAC_SHA1(password, "666DingT", iterations=1000, dklen=32)` → 32 字节
4. `MD5(32字节).hex()[:16]` → 即为 AES-128 密钥

### V3 的 uid 从哪来？

V3 文件夹名是 20 位 hex（如 `xxxxxxxxxx_v3`），但密钥推导用的 uid 是一个 **9-10 位的短数字 ID**，需要从以下途径获取：

| 平台 | 获取方式 |
|------|---------|
| macOS | 自动从 DingTalk plist 的 `SafeModeKey.safemode_last_crash_uid` 读取 |
| Windows | 从 `globalStorage/storage.db` 解密后查询，或设置环境变量 |
| 通用 | `export DINGTALK_UID=你的数字UID` |

### V3 的 salt 从哪来？

位于 `{uid}_v3/user_config` 文件中，内容是 Base64 编码的 JSON：

```json
{
    "salt": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "salt_md5": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
}
```

## 快速开始

```bash
git clone git@github.com:E2ern1ty/dingwave-V3.git
cd dingwave-V3
pip install -r requirements.txt
python main.py
```

浏览器访问 **http://localhost:8090**

> 工具自动扫描钉钉数据目录，检测 V2/V3 版本并完成解密，大多数情况无需配置。

### 手动指定（自动检测失败时）

```bash
export DINGTALK_UID=123456789
export DINGTALK_DATA_DIR=/path/to/xxxxxxxxxx_v3
python main.py
```

## 功能

- **纯 Python 解密** V2 + V3 数据库（无需 dingwave 等外部工具）
- Web 界面浏览会话和消息，支持搜索、筛选
- 20+ 种消息类型解析（文本、图片、文件、富文本、引用、审批等）
- 图片预览、附件导出、ZIP 打包下载
- 导出 JSON 含 AI 友好的 `content` 字段
- 每 4 小时自动增量同步
- 完全离线，无需云端 API

## 项目结构

```
├── main.py            # 入口（uvicorn 服务器）
├── config.py          # 配置（自动检测 V2/V3、读取 salt、提取 uid）
├── decrypt.py         # 解密核心（V2 MD5 / V3 PBKDF2+MD5，AES-ECB）
├── parser.py          # 消息解析（128 个分片表 tbmsg_000–tbmsg_127）
├── exporter.py        # 导出 JSON + 附件打包
├── attachment.py      # 附件管理
├── scheduler.py       # 定时同步（APScheduler）
├── web/
│   ├── api.py         # FastAPI 路由
│   └── static/        # 前端（HTML/CSS/JS）
└── requirements.txt
```

## 致谢

- [小周学习站 — 钉钉V3版本数据库key逆向](https://bbs.kanxue.com/thread-287455.htm) — V3 密钥推导的逆向分析思路
- [dingwave (p1g3)](https://github.com/p1g3/dingwave) — 钉钉 V2 解密工具，本项目的 V2 解密参考了其实现
- [FastAPI](https://fastapi.tiangolo.com/) / [APScheduler](https://apscheduler.readthedocs.io/)

## 许可证

[MIT](LICENSE)
