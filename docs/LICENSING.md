# 卡密、电脑绑定与 Vercel / JSONBin 部署

> 当前开发版本已移除录制和回放入口及运行中的卡密检查。以下为保留的授权方案，供后续恢复时参考；目前录制和回放无需部署或激活。单独运行激活工具仍会验证卡密。

2026-11-03。按用户选择仅使用 Vercel + JSONBin 预绑定机器码，无需 Redis。客户端与验证 API 已实现，自动化测试通过；真实 JSONBin、Vercel 与游戏联调仍需账号配置。Windows 负责录制和点击；Vercel 只运行 `license_server/` 内的验证接口，不运行游戏或桌面脚本。

## 绑定方式

先在目标电脑读取机器码，管理员把卡密记录的 `device_id` 设为这串值，之后其他机器会被拒绝。验证服务只读 JSONBin，不允许客户端抢绑、改绑或自动通过未绑定卡；两台电脑同时请求也不能改变管理员保存的绑定。

机器码是 Windows 安装标识 MachineGuid 的 SHA-256 摘要；服务端接收摘要，不接收原始 MachineGuid 或 MAC。选择安装标识是为减少换网卡和切换网络带来的变化。Windows 支持随机 Wi-Fi MAC，单凭 MAC 不适合作为稳定的授权标识，参见[微软说明](https://support.microsoft.com/en-us/windows/experience/connectivity-networking/connect-to-a-wi-fi-network-in-windows)。重装系统或克隆系统可能改变或复制安装标识，管理员需处理换绑；它不是不可伪造的硬件证明。

## 1. 部署验证服务

在 Vercel 导入 GitHub 仓库 `Assassin-21/Wowregister`，设置：

- Root Directory：`license_server`
- Framework Preset：`Other`
- 使用提供的 `vercel.json`；无前端构建命令，无需上传桌面程序
- Python 3.13；服务只使用标准库

服务接口是 `https://你的域名/api/verify`。GET 是不暴露卡密的健康检查；POST 做实际验证。先部署服务，再到目标电脑激活及录制。GET 成功仅说明函数在线，不能证明 JSONBin 配置正确。

在 Vercel 项目 Environment Variables 填入以下配置，不要写进仓库：

| 环境变量 | 用途 |
| --- | --- |
| `JSONBIN_BIN_ID` | 你创建的私有 Bin ID，24 位十六进制 |
| `JSONBIN_ACCESS_KEY` | 只读且仅能访问该 Bin 的 Access Key |
| `LICENSE_PEPPER` | 至少 32 字符的随机服务端密钥；签发卡密与验证服务必须使用相同值 |

可通过密码管理器生成长随机 `LICENSE_PEPPER`。不要把 Vercel / JSONBin 的账号密钥发送到聊天或提交 GitHub。`.env.example` 只提供字段名和占位值；复制后的 `.env` 被 Git 忽略，生产环境使用 Vercel 环境变量。设置后重新部署。

API 公开供客户端 POST 验证；如 Vercel Deployment Protection 拦截客户端，需要为生产域名设置合适访问策略，不能把 Vercel 账号令牌分发到客户端。生产服务应按实际使用配置 Vercel 防火墙请求限流，以保护 JSONBin 配额。

## 2. 新电脑安装及预绑定

1. 克隆/下载 GitHub 仓库，安装 Python 3.11+（安装器勾选 Add to PATH）。
2. 双击 `setup_registration.cmd` 安装录制所需核心依赖。
3. 双击 `show_device_id.cmd`，复制机器码。此操作无需卡密，也不激活本机。
4. 在管理员电脑签发卡密，填入目标电脑机器码。不要误填管理员电脑的机器码。

签发工具在项目根目录执行，仅本地生成文件，不自动修改 JSONBin：

```powershell
.\.venv\Scripts\python.exe tools/issue_licenses.py --count 1 --days 30 --device-id "目标电脑的64位机器码"
```

工具会隐藏输入提示，要求输入与 Vercel 相同的 `LICENSE_PEPPER`。`--days 0` 表示无固定到期日。有效期从签发时开始，按 UTC 保存，服务端判断；不会信任客户端时间。

文件保存于 Git 已忽略的 `data/licensing/`：

- `*_cards.txt`：明文卡密，仅管理员妥善保存和发给使用者。
- `*_jsonbin.json`：JSONBin 导入数据，以 HMAC-SHA256 摘要作为索引，不含明文卡密。

新建 JSONBin 私有 Bin，内容使用生成的 JSON 文件。已有卡密时，把新 `licenses` 条目合并进原有对象，不要用新文件整体覆盖旧卡。格式如下（哈希和机器码均需替换成实际生成值）：

```json
{
  "schema_version": 1,
  "licenses": {
    "64位卡密HMAC摘要": {
      "enabled": true,
      "expires_at": "2026-12-03T00:00:00+00:00",
      "device_id": "64位目标电脑机器码"
    }
  }
}
```

签发时必须提供目标机器码，未绑定卡不会获得授权。接口只允许核对现有记录，不提供管理接口。

## 3. 激活和录制

将根目录 `license_client.example.json` 复制为 `license_client.json`，把 `url` 换成已部署的 HTTPS 验证接口完整地址；它只含地址，不需要任何服务端密钥。也可用环境变量 `WOWREGISTER_LICENSE_URL` 设置。

双击 `activate_license.cmd` 输入卡密，确认成功。卡密用 Windows DPAPI 加密保存到 `%LOCALAPPDATA%\Wowregister\license.dat`，默认只能由原 Windows 用户和电脑解密，参见[微软 DPAPI 文档](https://learn.microsoft.com/en-us/windows/win32/seccrypto/example-c-program-using-cryptprotectdata)。复制该文件到另一电脑不会获得授权。

之后按[注册脚本说明](REGISTRATION.md)录制：F7 对应第一个名字框，F8 对应第二个名字框，F9 记录失败画面。首次先回放一轮。

客户端每次启动都在线验证，不能仅凭缓存启动；运行中约每 45 秒后台复核，授权失败会阻止后续操作。后台检查异常、网络不可用或超过 120 秒未完成有效复核时停止操作。F10 和窗口失焦检查不会等待网络请求返回。撤销和到期检查存在这一复核间隔，并非服务端修改后立即停止。

本独立项目的注册录制和回放均有授权检查；`--help`、机器码显示和录制文件 `--inspect` 可独立使用。项目不包含钓鱼、任务研究或观测面板模块。

## 停用、换绑与边界

- 停用：JSONBin 中把对应卡的 `enabled` 改为 false；调整 `expires_at` 可设到期。空值 null 表示无固定到期。
- 换绑：先停用卡并等待旧客户端复核停止，再由管理员替换 JSONBin 中的 `device_id`，然后重新启用。
- 更换/忘记本机卡密：运行 `activate_license.cmd --forget` 只清除本地缓存；服务端绑定不受影响，再运行激活入口输入新卡。
- `LICENSE_PEPPER` 需要备份；更换它会改变所有卡密索引，原有卡需要迁移，不能随意轮换。

本实现是联网授权和本地卡密加密，不是源码加密，也没有宣称不可破解。持有 Python 源码的人可以修改本地验证或伪造机器码。面向他人分发时应分发构建后的客户端，并管理源仓库访问；打包本身也不能完全防破解。真正不可绕过的控制需要把关键业务放在你掌控的服务器，而本项目点击行为发生在用户电脑。

参考：[Vercel Python 函数](https://vercel.com/docs/functions/runtimes/python/api-directory)、[JSONBin 读取 API](https://jsonbin.io/api-reference/bins/read)。
