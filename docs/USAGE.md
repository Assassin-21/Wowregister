# 组合创建脚本使用及换电脑交接

## 当前版本

当前录制及回放不检查卡密。授权模块保留，尚未恢复。组合入口为项目根目录的 `replay_cycle.cmd`。

## 两种模式

| 模式 | 返回路线文件 | 动作数 | 特别等待 |
| --- | --- | --- | --- |
| 1（默认） | `data/registration/ruleset/macro.json` | 7 | 第 6 步完成后等待 20 秒，再移动并点击第 7 步 |
| 2 | `data/registration/ruleset/macro_1.json` | 8 | 使用通用 ruleset 时间策略 |

两个模式都使用 `data/registration/direct/macro.json`。模式只切换返回路线，不切换 direct 或失败图片。文件名 macro_1 对应模式 2，请按此表选择。

## 开始运行

1. 关闭此前运行的脚本，游戏恢复到 direct 起点：角色列表，尚未点击创建角色。
2. 双击 `replay_cycle.cmd`，输入模式 1 或 2，回车；然后输入轮数，首次建议 1。
3. 切回游戏，松开其他按键，按 F6 开始。运行期间不要移动游戏窗口或手动操作。
4. F10 随时停止；游戏失去焦点、位置、尺寸或 DPI 改变也会停止。

每轮：direct 点击并自动填写两个随机 8–10 位字母名字 → 约每秒 1.5 次回车 → 匹配失败提示 → 执行所选 ruleset 返回路线 → 下一轮 direct。最后一轮也执行返回路线，完成后停在 direct 起点。

F9 提示是“此类角色的创建暂时受到限制。”。匹配黄色文字形状，首次匹配暂停回车，连续两次确认后返回。默认 60 秒不匹配就停止；开始回车前已匹配也停止。这不是成功识别器，停止后需人工核对游戏结果。

命令行可跳过模式及轮数询问（仍需切回游戏按 F6）：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m wowregister.registration.chain --mode 1 --repeat 5
.\.venv\Scripts\python.exe -X utf8 -m wowregister.registration.chain --mode 2 --repeat 5 --timeout 90
```

## 时间规则

- direct 每次点击前随机等待 0.8–1.2 秒；填名步骤保留录制等待。
- ruleset 首次及最后一次点击前随机等待 0.8–1.2 秒。
- ruleset 倒数第三次及倒数第二次点击前随机等待 0.6–0.9 秒。
- ruleset 其他步骤：录制等待加随机 0–0.5 秒。
- `fixed_delay: true` 优先于所有随机规则，因此模式 1 最后一步固定等待 20 秒。
- 鼠标移动、按住及输入耗时另计；每次执行重新随机。

## 修改录制

`record_direct.cmd` 保存 direct；填完两个名字后手动回车，失败提示出现时将鼠标放在提示文字中间按 F9，随后 F6 保存。F7/F8 填名字之前分别点击输入框。没有 F5 操作。

`record_ruleset.cmd` 默认覆盖模式 1 文件。模式 2 录制使用：

```powershell
.\record_ruleset.cmd --output "data/registration/ruleset/macro_1.json"
```

ruleset 从失败弹窗尚未关闭时开始 F6 录制，记录返回与选择流程，到 direct 起点后 F6 保存，不重复录制创建及填名。重新录制会覆盖该文件，固定 20 秒等手动配置需要重新添加。

普通 `replay_direct.cmd` 与 `replay_ruleset.cmd` 仅独立回放，不执行组合自动回车；日常测试使用 `replay_cycle.cmd`。

## 换电脑继续开发

1. 拉取本仓库，安装 Python 3.11+，运行 `setup_registration.cmd` 建立本机 `.venv`。不要复制旧电脑的虚拟环境。
2. 当前录制客户区为 1920×1080，DPI 96。建议桌面分辨率 1920×1080、Windows 缩放 100%，游戏采用一致的无边框全屏和 UI 布局。屏幕物理尺寸不影响坐标，但不支持自动缩放适配。
3. JSON 的 `executable` 当前指向 `D:\Game\魔兽世界无限\World of Warcraft\_forever_\Wow.exe`。新电脑路径不同，需核对真实路径后同步修改 direct 与两份 ruleset，或现场重录；不能只移除窗口校验。
4. 检查 PNG 预览和 JSON 内嵌检查点：程序实际读取 JSON 内的图片，仅改 PNG 不生效。
5. 各模式先测试 1 轮，确认填名、失败识别与返回起点都正确后再增加轮数。

测试：`.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s wowregister/tests -v`。

历史文件 `data/registration/macro.json` 及 `macro.before_checkpoint_*.json` 不参与组合回放。录制目录默认被 Git 忽略，已有跟踪文件仍可提交；新增录制需明确 `git add -f`。不要上传卡密、服务端密钥或本地授权缓存。
