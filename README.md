# Wowregister

## Windows 成品

下载 [Windows ZIP 包](https://github.com/Assassin-21/Wowregister/raw/refs/heads/main/release_files/Wowregister-Windows-x64.zip)，解压后双击 `Wowregister.exe` 即可。用户无需安装 Python 或 ChatGPT。程序会打开本地操作页面，提供卡密激活、模式 1/2、运行轮数、启动、停止和运行日志。

输入卡密并点击激活，首次会自动识别机器码、绑定当前电脑并更新 JSONBin 状态。然后选择模式和轮数，点击“启动脚本”，切回游戏按 F6 开始；F10 停止。使用结束点击“退出工具”。v0.4.1 正式包内置验证接口 `https://license.wowazeroth.online/api/verify`。游戏盘符可以不同，客户区仍需为 1920×1080、DPI 96。

开发者运行源码页面可双击 `start_register.cmd`。构建正式 EXE：先安装 `requirements-build.txt`，再运行 `python tools/build_exe.py`，产物在 `dist/`。仅将白名单中的三个有效录制 JSON、页面和公开接口地址加入 EXE，服务端密钥和签发资料不打包。

最新操作入口及模式 1/2、时间规则、换电脑交接见 [使用说明](docs/USAGE.md)。

独立的 Windows 魔兽角色注册操作录制与回放工具，源代码位于 [Assassin-21/Wowregister](https://github.com/Assassin-21/Wowregister)。本项目只包含注册工具、卡密客户端与验证服务，不依赖之前的钓鱼项目，也没有导入旧仓库历史。

支持鼠标左右键点击和步骤间隔录制、两个名字输入框、失败提示图片检查点与有限次数重试。每段名字独立限制为最多 6 个汉字或 12 个英文字母；混合输入按汉字计 2、字母计 1，上限 12。

v0.4 支持首次激活自动绑定电脑，管理员不需要预先收集机器码。录制、单独回放和组合回放均有卡密检查，包括等待 F6 和运行中的周期复核。授权失败会停止后续操作。EXE 页面支持激活并加密保存卡密。

## 新电脑录制或开发

只运行成品的用户使用上面的 Windows 包即可，以下步骤用于修改或重新录制操作。

1. 克隆此仓库，或从 GitHub 下载 ZIP 并解压。安装 Python 3.11+，安装器勾选 Add to PATH。
2. 双击 `setup_registration.cmd`。桌面客户端只需 Pillow，不需要安装旧项目。
3. 先运行 `activate_license.cmd` 激活。再双击 `record_registration.cmd`，自动生成两个 8–10 位英文字母名字，切回注册页面录制完整的失败及返回起点流程。
4. 双击 `replay_registration.cmd`，先回放 1 轮验证，再设置重试次数。

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

验证服务使用 JSONBin 保存卡密启用、到期与激活状态，使用 Vercel 私有 Blob 的原子创建保存首次绑定，避免两台电脑同时激活同一张卡。服务端密钥只放在 Vercel，不分发到 EXE。游戏操作流程仍需按现场环境核对。卡密授权与本地缓存加密不等于源码防破解。

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

服务端自动绑定与并发测试：在 `license_server/` 执行 `npm ci`、`npm test`。这些测试使用内存存储，不消耗真实卡密。

录制和签发数据位于本地 `data/`，卡密缓存位于 `%LOCALAPPDATA%\Wowregister\license.dat`。经确认的录制配置已跟踪 Git；签发资料、虚拟环境、真实私有配置及服务端密钥仍被忽略。新项目使用独立的卡密缓存、机器码命名空间和 `WOWREGISTER_LICENSE_URL` 环境变量。

默认回放每轮重新生成两个 8–10 位英文字母名字，首字母大写，其余小写。F7/F8 仍用于记录两个填名动作，之前须分别点击输入框。命令行显式指定名字时使用指定值。失败截图应仅覆盖固定提示文字，避开角色名字，否则随机换名会影响匹配。

## 当前联调版本（2026-11-03）

组合回放入口为 `replay_cycle.cmd`，或 EXE 页面：direct 填随机双名字 → 每秒约 1.5 次回车 → 匹配黄色失败提示 → ruleset 返回起点。F6 开始，F10 停止；首次先跑 1 轮。当前已启用卡密检查。

按仓库所有者要求，此次提交包含 `data/registration/` 下的现有录制 JSON 和检查点 PNG。`direct/macro.json` 与 `ruleset/macro.json` 是组合流程使用的文件；根目录 `macro.json` 为旧录制，`macro.before_checkpoint_*.json` 为错误检查点替换前的历史备份，不用于当前组合回放。JSON 内嵌图片与 PNG 预览已一同保存。其他 data 内容仍默认忽略。

录制环境：游戏客户区 1920×1080、DPI 96。换电脑需核对 Windows 缩放、游戏布局及检查点匹配，当前不自动适配分辨率。EXE 页面允许游戏安装盘符不同；命令行回放仍严格校验录制路径，详见使用说明。

时间策略：direct 点击前随机 0.8–1.2 秒；ruleset 首尾点击前随机 0.8–1.2 秒，倒数第三及倒数第二次随机 0.6–0.9 秒，其余步骤保留录制等待并增加 0–0.5 秒。移动鼠标及按住时间另计。
