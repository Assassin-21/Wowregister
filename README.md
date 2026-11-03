# Wowregister

独立的 Windows 魔兽角色注册操作录制与回放工具，源代码位于 [Assassin-21/Wowregister](https://github.com/Assassin-21/Wowregister)。本项目只包含注册工具、卡密客户端与验证服务，不依赖之前的钓鱼项目，也没有导入旧仓库历史。

支持鼠标左右键点击和步骤间隔录制、两个名字输入框、失败提示图片检查点与有限次数重试。每段名字独立限制为最多 6 个汉字或 12 个英文字母；混合输入按汉字计 2、字母计 1，上限 12。

真实录制和回放需要卡密授权。卡密在 JSONBin 预绑定目标 Windows 机器码；Vercel 部署验证 API，Windows 客户端运行鼠标操作。卡密本地通过 Windows DPAPI 加密保存，启动时及运行中在线核对。

## 新电脑使用

1. 克隆此仓库，或从 GitHub 下载 ZIP 并解压。安装 Python 3.11+，安装器勾选 Add to PATH。
2. 双击 `setup_registration.cmd`。桌面客户端只需 Pillow，不需要安装旧项目。
3. 双击 `show_device_id.cmd` 获取目标电脑机器码，由管理员给卡密预绑定。
4. 按[部署与卡密说明](docs/LICENSING.md)部署验证服务，将 `license_client.example.json` 复制为 `license_client.json` 并填写接口地址，再双击 `activate_license.cmd` 激活。
5. 双击 `record_registration.cmd`，输入两个框的名字，切回注册页面录制完整的失败及返回起点流程。
6. 双击 `replay_registration.cmd`，先回放 1 轮验证，再设置重试次数。

| 热键 | 用途 |
| --- | --- |
| F6 | 开始录制 / 保存录制；开始回放 |
| F7 | 在当前焦点框填写第一段名字 |
| F8 | 在当前焦点框填写第二段名字 |
| F9 | 录制鼠标周围的固定失败提示，必须在关闭失败弹窗前使用 |
| F10 | 停止回放 / 取消本次录制 |

两次填名之前都需要先点击对应输入框。脚本不会自动寻找名字框。切走窗口、移动或缩放窗口也会停止。循环回放必须有失败检查点；匹配不到时会停止后续点击，实际注册结果仍需人工查看。详细录制方法见[注册说明](docs/REGISTRATION.md)。

## Vercel 部署

导入 **本仓库 `Assassin-21/Wowregister`**，Root Directory 设置为 **`license_server`**，Framework Preset 选 **Other**。只部署验证服务，无需在 Vercel 安装游戏或运行桌面客户端。所需环境变量与 JSONBin 配置见[部署说明](docs/LICENSING.md)。

部署服务并完成激活后才能真实录制。当前尚未完成真实服务和游戏联调。卡密授权与本地缓存加密不等于源码防破解。

## 本地验证

在项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s wowregister/tests -v
.\.venv\Scripts\python.exe -m wowregister.registration.record --help
.\.venv\Scripts\python.exe -m wowregister.registration.replay --inspect
```

`--inspect` 需要已有的录制文件，只打印动作，不发送输入。自动化测试使用模拟桌面，Windows DPAPI 测试只验证本地加解密，不访问实际卡密服务或游戏。

录制和签发数据位于本地 `data/`，卡密缓存位于 `%LOCALAPPDATA%\Wowregister\license.dat`。这些数据、虚拟环境、真实配置及服务端密钥不会上传 GitHub。新项目使用独立的卡密缓存、机器码命名空间和 `WOWREGISTER_LICENSE_URL` 环境变量。
