# HCA-r4-forced 部署记录：350 秒提示 + 355 秒无条件强制暂停

用户要求：在 350 秒仍未成功重置时提示驾驶员接管，355 秒**直接**开始 1.1 秒停止；停止完成后开始接管并重置计时器。用途是实测本车 5N1 的 1.1 秒是否真实可用，同时继续统计择机成功率，供下一轮择时逻辑优化。

已部署并停车重启，实际运行核验通过。**行驶中的复位效果与 1.1 秒是否有效仍待下一段日志验证，不能由安装成功或本地检查称为已解决。**

## 一处必须澄清的语义

讨论中"接管"指的是**驾驶员接管**（手握方向盘、脚搭刹车），不是 C2 软退出。由此得到一条硬约束：

> 350 秒**不能**触发 `steerTempUnavailable`。软退出会让 `CC.latActive=False`，状态机走 `lateral_inactive` 分支，355 秒的强制暂停**永远不会发生**。

r3 的行为正是 `takeover_required = elapsed >= deadline(350)`，因此本次把它从 350 秒移到 400 秒纯保险，350 秒改为**只发提示**。这是本次改动的核心。

## 改动

只替换两个 Python 文件与悬浮窗 APK，其余 10 个受保护文件保持 r3 哈希：

| 文件 | 目标 | 新 SHA-256 |
| --- | --- | --- |
| hca_timer_reset.py | `/data/openpilot/selfdrive/car/volkswagen/` | `d2ff04d18f175f325eb7650bca388dd8ceea9c5f6c72d9d12265b2b51ba92b05` |
| v3_server.py | `/data/pq46/` | `4b0e1979a950b21dc6675770ae6c8a1f8a9507258cc8972501e192b41fe95e3d` |
| overlay.apk | Android 包 `nl.vwopenploot.probe` | `bdab3df05a5281297ae95aeda9453378564d8298e8e339175dd59a548df11251` |

`carcontroller.py`、`pq46_runtime.py`、`interface.py`、`pqcan.py`、`carstate.py`、`pq46_cruise.py`、`pq_stock_cruise_probe.py`、`v3_capture.py`、`boot_overlay.py`、`ui` 全部未改；横纵向参数、PID、Panda 安全策略、EBS/EPS 固件均未触碰。调速仍默认 base 关闭。

### 时序

| 时刻 | 行为 | 与 r3 的差异 |
| --- | --- | --- |
| 0–180 s | 正常控制 | 不变 |
| 180–300 s | 择机，`completed`/`aborted` 统计不变 | 不变 |
| 300–350 s | 预告与三秒倒数 | 不变 |
| **350 s** | 提示（悬浮窗变红 + 音量 25 短提示音），**不软退出** | **由软退出改为纯提示** |
| **355 s** | 无条件强制暂停：忽略几何/预测/驾驶员输入/饱和全部门限，连发 55 帧 standby | **新增** |
| **356.1 s** | `forced_completed++`、`cycle++`、本地计时清零，继续正常控制 | **新增** |
| 400 s | 纯保险软退出（正常路径永远到不了） | `takeover_required` 由 350 s 移至此处 |

强制暂停期间方向机助力一直存在，驾驶员可随时手动转向；**只有真正断开横向接合才会中止**，此时计入 `forced_aborted` 并在下一周期重试。启动暂停时把 `off_frames` 归零，保证样本恰好 55 帧。计数器 `forced_completed` / `forced_aborted` / `forced_prompts` 与择机的 `completed` / `aborted` 完全分离，避免污染择机成功率统计。

## 本地验证

15 项调度测试通过（`tests/test_c2_hca_r4_forced.py`），整仓 190 项通过。覆盖：

- 350 s 进入 `forced_prompt` 且 `takeover_required=False`、控制继续输出、只提示一次
- 355 s 即使 `window_ok=False`、`driver_input=True`、`continue_ok=False`、`delayed_ok=False` 仍强制启动
- 恰好 55 帧后 `forced_completed=1`、`completed=0`、`cycle=2`、`elapsed=0`
- 上一个控制帧扭矩为 0 时仍恰好 55 帧
- 强制暂停期间忽略驾驶员输入与饱和（请求 295 也不中止）
- 只有 `lat_active=False` 才中止，计入 `forced_aborted` 而非 `aborted`
- 强制完成前 `takeover_required` 恒为 False
- 时钟跳变进入提示窗与强制窗仍按序执行
- 择机路径与中止计数与 r3 一致
- UI 全程不回应提示音时强制暂停仍执行
- 择机预约窗在约 344.9 s 关闭（`insufficient_time_for_reset`）

APK 用原证书重编，签名 SHA-256 仍为 `a5e5d21ee91526f8ce6eddd80b16bd81c08c9e7a5d5493823b7c4f8e28e8b35a`，versionCode 4→5、versionName 0.4-r3→0.5-r4，与原包同签名，可原地覆盖安装。

## 安装与重启

IP `<C2-IP>`。安装前状态 `HCA_R3_STAGED_BASELINE`、`IsOffroad=0`、`DisableUpdates=1`，停车守卫（P 挡、零速、控制未接合、点火在线）通过，分支 `beta2_sharan2` / `a06eed9e` 核验通过。

安装过程先停 `8766` 后端与日志，保存 r3 原件快照，再原子替换两个文件并安装 APK，逐项回读哈希。设备侧烟雾检查（**不发送 CAN**）通过：

```json
{"smoke": true, "version": "hca-r4-forced", "car": "VOLKSWAGEN SHARAN 2ND GEN",
 "prompt_probe": "forced_prompt", "forced_probe": "forced_standby",
 "cruise_mode": "base", "CAN_transmitted_by_smoke": false}
```

构造真实 `CarController` 后断言 `seek=9000 / prompt=17500 / forced=17750 / required=55 / backstop=20000`，并在内存中实际驱动状态机验证 350 s 只提示、355 s 强制启动，均通过。

重启前 `boot_s≈153`，重启后 `boot_s≈50.9`，确认发生新启动。重启后独立查询仍为 `HCA_R4_FORCED_PRESENT`，APK 哈希为新的 `bdab3df0…`，更新保持未被清除。

## 运行态核验

`/data/pq46/v3_status.json` 状态年龄 0.098 秒（新鲜），实际运行参数：

```
version=hca-r4-forced  phase=inactive  elapsed_s=0.0
seek=180  notice=300  prompt=350  forced=355  backstop=400  standby=1.1
forced_prompt=false  forced_pause=false  takeover_required=false
completed=0  forced_completed=0  forced_aborted=0  aborted=0
```

`notice_ready=true` 表示新版悬浮窗心跳有效、`audio_ready` 可用，同时反证悬浮窗已接受 `hca-r4-forced` 版本串（版本不符时会显示"等待当前版本状态"并拒绝回传）。

被动采集 3 秒正常退出：869 条记录，含 `session` / `session_end`；29 条 `pq46_status`（带全部新字段）、54 条 `controlsState`、54 条 `carControl`、509 条 `can`、151 条 `sendcan`、6 条 `pandaStates`。978 `Lenkhilfe_2` 状态均为 3（ready，停车未接合）。

设备 `screencap` 在此 EON 上因 `libskia.so` 符号缺失无法使用（Android 6 系统库问题，与本次部署无关），因此本轮界面证据使用运行态 `notice_ready` 与状态字段，未取得设备截图。

## 怎么判定 1.1 秒是否有效

软件计数器不是方向机内部计数器；强制暂停清零本地计时**不证明**方向机接受复位。唯一判据是 978 原始状态：

- 356.1 s 之后约 4–5 秒出现 `eps_hca_status` 2/4（拒绝）→ **1.1 秒不足**
- 平安越过约 360 s → **1.1 秒有效**

新增只读复盘工具：

```powershell
python tools/review_hca_r4_logs.py <trace.jsonl> [--json out.json] [--window-s 25]
```

它逐条列出每次 `forced_completed` 之后 25 秒窗口内的 978 状态分布，给出 `insufficient_1.1s` 或 `no_refusal_in_window` 判定；同时输出 `start_block_reasons` 分布（择机首要阻挡原因）与暂停外出现的拒绝（原 ~360 秒硬件超时）。下一段日志可直接据此决定是否回退到 2.0 秒或调整择时门限。

安装、重启与运行核验的原始输出保存于忽略目录 `device-backups/hca-r4-forced-install-20261003/`（`install.txt`、`runtime-verify.txt`、`v3-r4-passive.jsonl`）。该目录不进入 Git。

## 回退

```powershell
python tools/manage_c2_hca_r4_forced.py --ip <IP> --action rollback --parked-ignition
python tools/manage_c2_hca_r4_forced.py --ip <IP> --action reboot --parked-ignition
```

`rollback/` 保存的是**当前已部署的 hca-r3-staged** 原件（两个文件 + APK），回退一键回到 r3，不需要先退 r2。恢复文件与 APK 的哈希都固定；事务失败时同时回滚文件与 APK。

## 边界

- 本次只证明源码已安装、新进程已运行、停车状态正常、新界面心跳有效、被动日志字段完整。
- **没有道路证据**：355 秒强制暂停是否真的让方向机接受复位、1.1 秒是否足够、择机成功率，都要等下一段行驶日志。
- 与 r3 相比 350–356 s 期间不再有 C2 主动软退出，这段（含假设的 360 秒极限）依赖驾驶员按提示接管；这是用户明确接受的上界。
