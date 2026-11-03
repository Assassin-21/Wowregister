# 卡密自动激活与 Vercel / JSONBin 部署

v0.4 的使用流程：用户在 EXE 页面输入卡密 → Vercel 校验卡密和有效期 → 首次绑定当前电脑 → 自动更新 JSONBin → 客户端加密保存卡密。用户不需要复制机器码，也不需要管理员逐台填写。验证接口为 `https://wowregister-license.vercel.app/api/verify`。

Windows 负责录制和点击；Vercel 只运行 `license_server/` 内的授权接口，不运行游戏。JSONBin 保存卡密记录，Vercel 私有 Blob 保存首次绑定及写入锁，不需要 Redis。

## 绑定和校验

- 新卡的 `device_id` 为 `null`，首次成功激活时自动绑定请求电脑。
- JSONBin 的对应记录自动写入 `device_id`、`status: "active"` 和 UTC `activated_at`。
- 同一电脑再次验证可以通过；其他电脑使用同一卡会被拒绝。
- 私有 Blob 使用原子创建保存每张卡的首次绑定；并发请求只能有一个绑定结果。JSONBin 回写在写入锁内重新读取后合并，避免不同卡同时激活时覆盖彼此。
- 旧的预绑定卡继续尊重原 `device_id`。JSONBin 的 `enabled`、`expires_at` 在每次验证时检查。

机器码是 Windows 安装标识 MachineGuid 的 SHA-256 摘要；服务端不接收原始 MachineGuid 或 MAC。重装或克隆 Windows 可能改变或复制安装标识，它不是不可伪造的硬件证明。

## 部署配置

在 Vercel 导入 GitHub 仓库 `Assassin-21/Wowregister`：

- Root Directory：`license_server`
- Framework Preset：`Other`
- 使用提供的 `vercel.json` 和 `package.json`，由 Vercel 安装 Node.js 依赖
- 在该项目连接一个 **Private** Vercel Blob store，使生产环境获得 `BLOB_READ_WRITE_TOKEN`

环境变量只保存到 Vercel，不写入仓库或 EXE：

| 环境变量 | 用途 |
| --- | --- |
| `JSONBIN_BIN_ID` | 私有 Bin ID，24 位十六进制 |
| `JSONBIN_MASTER_KEY` | JSONBin Master Key，仅服务端使用；配置后优先使用 |
| `JSONBIN_ACCESS_KEY` | 未设置 Master Key 时的替代项，必须有目标 Bin 的读取和更新权限 |
| `LICENSE_PEPPER` | 至少 32 字符的服务端随机密钥，必须与签发卡密时一致 |
| `BLOB_READ_WRITE_TOKEN` | 连接私有 Blob store 后由 Vercel 提供，仅服务端使用 |

环境变量或 Blob 连接配置完成后重新部署。生产域名需允许客户端访问 `/api/verify`，不要把 Vercel 账号令牌发给客户端。GET 仅返回健康状态，不能证明实际卡密读写成功；POST 才会验证、绑定和回写。

JSONBin 回写使用 `X-Bin-Versioning: false`，兼容免费账号。开启历史版本功能可能导致免费账号的更新请求被拒绝。

## 签发新卡

增加卡密只需要在 JSONBin 的 `licenses` 中增加记录，无需修改代码、重新打包或重新部署。明文卡密和其索引必须用相同 `LICENSE_PEPPER` 生成，不能随意填写一段字符串作为卡密。

管理员签发工具位于 `tools/issue_licenses.py`，在已配置 Python 开发环境的项目根目录执行；它只在本地生成文件，不会自动更新 JSONBin：

```powershell
.\.venv\Scripts\python.exe tools/issue_licenses.py --count 32 --days 30
```

工具会隐藏输入提示，要求输入与 Vercel 相同的 `LICENSE_PEPPER`。默认生成未绑定卡；如需要兼容预绑定使用，可显式传入 `--device-id "目标电脑的64位机器码"`。`--days 0` 表示无固定到期日。有效期从签发时开始，按 UTC 保存，服务端判断，不从首次激活时重新计算。

输出保存在 Git 忽略的 `data/licensing/`：

- `*_cards.txt`：明文卡密，只发给对应使用者。
- `*_jsonbin.json`：JSONBin 导入数据，以卡密 HMAC-SHA256 摘要作为索引，不含明文卡密。

已有卡密时，将新 `licenses` 条目合并进现有对象，保留原有记录；不要用新文件整体覆盖 Bin。未绑定卡格式如下，索引须使用实际签发结果：

```json
{
  "schema_version": 1,
  "licenses": {
    "64位卡密HMAC摘要": {
      "enabled": true,
      "expires_at": "2026-12-03T00:00:00+00:00",
      "device_id": null
    }
  }
}
```

首次激活后，同一条记录增加机器码、状态和激活时间。`expires_at: null` 表示无固定到期日。已经签发的 32 张卡继续使用原卡密，无需重新生成。

## 客户端激活

成品用户解压 Windows 包后双击 `Wowregister.exe`，输入卡密并点击“验证并激活”。用户电脑无需 Python 或 ChatGPT。请在实际使用的电脑上首次激活，避免把卡绑定到测试电脑。

正式包内置公开验证地址。源码默认读取 `wowregister/default_service.json`；也可用根目录（EXE 则为旁边目录）的 `license_client.json` 或 `WOWREGISTER_LICENSE_URL` 覆盖地址。客户端配置只含公开地址，不需要服务端密钥。

卡密使用 Windows DPAPI 加密保存到 `%LOCALAPPDATA%\Wowregister\license.dat`，默认只能由原 Windows 用户和电脑解密。复制该文件不会解除服务端绑定。

客户端每次启动都在线验证，运行中约每 45 秒后台复核。后台验证异常、网络不可用或超过 120 秒未获得有效复核时停止后续操作。F10 和窗口失焦检查不会等待网络请求返回。停用和到期生效存在复核间隔。

录制、单独回放和组合回放均检查授权；`--help`、机器码显示和录制文件 `--inspect` 可独立使用。源码命令行用户也可运行 `activate_license.cmd` 激活。

## 管理和故障处理

- **停用或调整到期**：在 JSONBin 修改该卡的 `enabled` 或 `expires_at`，无需重新生成 EXE。
- **激活时提示已绑定其他电脑**：该卡已有首次绑定；同一卡不能供不同电脑使用。
- **激活后 JSONBin 尚未同步**：网络或写入失败时客户端不会获得授权。使用同一卡在原电脑重试，服务端会保留首次绑定并补齐 JSONBin 状态。
- **更换电脑**：优先停用旧卡，给新电脑签发新卡。若必须给同一卡换绑，管理员需在停用并确认旧客户端停止后，同时处理 JSONBin 记录及对应私有 Blob 绑定；只改 JSONBin `device_id` 或清空本地缓存不能换绑。
- **清除本机卡密**：`activate_license.cmd --forget` 仅清除本地缓存，不改变服务端绑定。
- **密钥备份**：保管 `LICENSE_PEPPER`；更换它会改变所有卡密索引，旧卡必须迁移。私有 Blob 绑定数据也应按授权数据管理。

不要把明文卡密、签发资料、JSONBin Key 或 Blob token 提交 GitHub、放入客户端包。联网授权、DPAPI 和 EXE 打包不能保证不可破解，机器码也不是硬件身份认证。

## 本地测试

在 `license_server/` 执行 `npm ci`、`npm test`，验证首次激活、重复验证、异机拒绝、同卡并发抢绑、不同卡并发保留和回写失败恢复。测试使用内存存储，不访问真实 JSONBin 或占用用户卡密。客户端测试见仓库 README。
