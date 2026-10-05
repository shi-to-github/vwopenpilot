# 实际 C2 设备基线（2026-10-01）

连接方式：同一 Wi-Fi 内的 SSH，`root` 用户，端口 `8022`。只执行了读取和本地备份；未向 C2 写入文件或更改参数。

| 项目 | 设备读数 |
| --- | --- |
| 系统 | OnePlus3 / EON，Android 6.0.1，Linux `3.18.20-Comma+` |
| Dragonpilot 分支 | `beta2_sharan2` |
| Git 提交 | `a6eed9e0c4d9a242db1e35978d2c32fe427491c7`，提交日期 2023-01-02 |
| 工作区改动 | 仅 `selfdrive/car/volkswagen/interface.py`：Passat NMS 和 Sharan 的 `minSteerSpeed` 从 50 km/h 改为 0 |
| HCA 发送节拍 | `HCA_STEP = 2`，即 50 Hz |
| 现有超时处理 | 持续非零请求到约 118 秒时停用 HCA 一帧，约 20 ms |

最初备份时，设备上的 `carcontroller.py`、`carstate.py`、`pqcan.py`、`values.py` 等 Volkswagen 文件均与公开 `a6eed9e` 提交逐字节相同，只有上述两处 `interface.py` 修改。这个事实仅描述备份时刻。

随后 C2 在 2026-10-01 03:08 UTC 重新检出并重置到 `a6eed9e`，Git reflog 包含 `branch: Reset to FETCH_HEAD`、`checkout`、两次 `reset: moving to HEAD`。重新连接后 `interface.py` 已恢复为原版，NMS/夏朗的 `minSteerSpeed` 再次为 50 km/h，工作区干净。这与 `selfdrive/updated.py` 的强制检出流程吻合；直接覆盖设备文件可能被后续更新清除。

当前代码在 `controlsd.py` 中要求 `vEgo > minSteerSpeed` 才令 `latActive` 为真。`interface.py` 在约 53.6 km/h 以下显示低速转向警告、约 57.2 km/h 以上解除警告（`+1` 和 `+2` 的单位为 m/s）。这与用户观察的约 55 km/h 门槛相符，说明当前软件本身设有低速限制；是否还有 EPS 自身的低速门槛，需要在单独降低该参数后通过日志确认。

完整备份位于 `D:\VWopenploot\device-backups\original-20261001\c2-data-openpilot-params.tar.gz`，已被项目的 `.gitignore` 排除。SHA-256：`386549f620dc91d796eaaad40942f448baf80ca40b2f7e7ab7044c80d348cd43`。压缩包经过完整读取，包含 2,385 个条目、2,080 个文件、131 个参数文件，以及 `/data/params/d` 到 `/data/params/d_tmp` 的链接。单独拷贝的 Volkswagen 文件与压缩包内容逐字节一致。备份目录的 Windows 访问权限仅授予当前用户、管理员和系统账户。

远端 `tar` 在完成时以状态 1 退出，只报告 `.git` 和 `openpilot` 目录“file changed as we read it”。压缩包完整、必需路径齐全，但它不是运行中设备的原子快照；涉及 Git 元数据恢复时还应先做离线校验。

本地精确版本工作树为 `D:\VWopenploot\vendor\dragonpilot-device-a6eed9e`。提交 `ff9cc9b` 保存设备原有两处配置，提交 `1d4a92c` 增加默认关闭的 240 秒后连续 2 秒 HCA standby 候选。已验证 Python 语法、50 Hz 下连续 100 帧 standby、结束后恢复和 disengage 重置。该候选未部署到 C2，也不能由这些离线测试证明车辆会接受复位。

## 接续点

- C2 已在 `<C2-IP>:8022` 重新上线，以 `root` 和本机 `C:\Users\<user>\.ssh\vwopenploot_c2_id_rsa` 密钥连接。重新接机时仍需核对 IP，勿假设地址不变。
- 本地项目主仓库与设备专用工作树均已提交；设备专用候选提交为 `1d4a92c`。
- 设备现运行干净的原始 `a6eed9e`；最初备份保留了更新前的两处 `interface.py` 修改。候选功能默认关闭，C2 上未部署、未开启、未进行道路验证。
- HCA 2 秒测试包只包含 `carcontroller.py` 和新模块，保留当前 50 km/h 软件门槛，以便先单独验证 6 分钟退出问题。包、哈希清单和回退文件位于 `candidate/device-a6eed9e-2s/`。只读预检已在当前 C2 上通过：`READY_TO_INSTALL`、`IsOffroad=1`、`UpdateAvailable=0`、`UpdaterState=idle`。
- `tools/manage_c2_hca_package.py` 提供默认只读状态检查和显式安装/回退命令。安装与回退脚本已在临时 Git 工作树中模拟验证；尚未对真实 C2 执行写入。原厂定速按钮方案目前只在较新的 `c6` 工作树中，尚未移植到实际 `a6eed9e` 基线。
- 最近一次只读检查时更新器一直停在 `checking...`，子进程是 `git ls-remote`。安装工具现在会在该状态拒绝写入。`tools/hold_c2_updates.py` 已准备好将 `DisableUpdates` 暂时设为真，并记录原值供测试结束后恢复；尚未在真实 C2 上执行暂停或恢复。
