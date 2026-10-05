# hca-r4-forced

> **stable-1-hca-r4-forced —— 项目第一个稳定版。**
> 2026-10-03 实测约 3 小时 34 分、约 60 轮复位、**0 次辅助驾驶断连**。择机复位一般落在 180–220 秒，偶尔 250–300+ 秒，**从未超过 300 秒**，因此 355 秒强制兜底从未在道路上触发。驾驶员判定 **1.1 秒相比原 2.0 秒是质的提升**：暂停更短、择机窗口更容易满足，且驾驶员无感。
> 证据等级：**驾驶员感知**（该段行程日志未取回，无 978 帧级复核）。见 [路测复盘](../../docs/R4_ROAD_REVIEW_20261003.md)。
> 冻结动作只包含文档与 Git tag，**未修改任何一行车辆控制代码**，设备上的实际文件与哈希不变。

在已部署的 hca-r3-staged 之上加**固定时刻兜底**：即使择机一次都没成功，每轮也保证一次完整的 1.1 秒 standby 送到方向机。

## 时序

| 时刻 | 行为 |
| --- | --- |
| 0–180 s | 正常控制 |
| 180–300 s | 择机寻找窗口（与 r3 相同，`completed`/`aborted` 统计不变） |
| 300–350 s | 预告流程，三秒倒数后择机执行（与 r3 相同） |
| **350 s** | **提示驾驶员准备接管**：悬浮窗变红 + 短提示音。**只提示，不软退出**，横向控制继续 |
| **355 s** | **无条件强制暂停**：忽略道路几何、预测、驾驶员输入、饱和中止全部门限，连发 55 帧 standby（50 Hz = 1.1 秒） |
| **356.1 s** | 强制暂停完成：`forced_completed++`、`cycle++`、本地计时清零，**继续正常控制**（不软退出） |
| ~360 s | 若 1.1 秒无效，978 `Lenkhilfe_2` 的 `eps_hca_status` 会出现 2/4（拒绝），驱动自行处理 |
| 400 s | 纯保险：仅当强制暂停因异常始终无法完成时才触发 `steerTempUnavailable` 软退出。正常路径每轮 356.1 s 就清零，永远到不了 |

暂停期间方向机**助力一直存在**，驾驶员随时可手动转向；只有真正断开横向接合（`lat_active=false`）才会中止强制暂停，此时计入 `forced_aborted` 并在下一周期重试。

## 怎么读结论

软件计数器不是方向机内部计数器。强制暂停清零本地计时**不证明**方向机接受了这次复位。唯一判据是强制暂停恢复之后 978 的原始状态：

- 356.1 s 之后约 4–5 秒出现 `eps_hca_status` 2/4 → **1.1 秒不足**
- 平安越过 ~360 s → **1.1 秒有效**

## 与 r3 的差异

- 350 s 由「软退出接管」改为**纯提示**。这是硬约束：软退出会让 `lat_active=false`，355 s 的强制暂停将永远不会发生。
- 新增 355 s 无条件暂停与 350 s 提示。
- 新增计数器 `forced_completed` / `forced_aborted` / `forced_prompts`；`completed` 仍只统计**择机**成功，两条证据互不污染。
- `takeover_required` 从 350 s 移到 400 s 纯保险。
- 只替换 2 个 Python 文件 + 悬浮窗 APK（`hca_timer_reset.py`、`v3_server.py`）；`carcontroller.py`、`pq46_runtime.py`、`interface.py`、`pqcan.py`、`carstate.py` 等保持 r3 哈希不变。

## 部署与回退

```powershell
python tools/manage_c2_hca_r4_forced.py --ip <IP> --action status
python tools/manage_c2_hca_r4_forced.py --ip <IP> --action install --parked-ignition
python tools/manage_c2_hca_r4_forced.py --ip <IP> --action reboot --parked-ignition
```

`rollback/` 保存的是**当前已部署的 hca-r3-staged** 原件，因此回退一键回到 r3，不需要先退到 r2。安装前校验 12 个受保护文件哈希与已安装 APK 哈希；失败时同时恢复文件与 APK。

本地 15 项调度测试通过（覆盖 350 不软退出、355 无条件、恰好 55 帧、强制不污染择机统计、真实断开才中止、UI 不回应仍执行、时钟跳变）。
