# HCA-r2-entry 部署记录

用户授权修复择机并部署供后续测试。本次针对上一段 diag1 路测中启动条件被短暂请求波动反复打断的问题，不改变暂停中的即时中止逻辑。

## 改动

搜索起点由 180 秒提前至 150 秒。新增 0.4 秒（20 帧）启动评估窗口：请求与限幅值 RMS 均不超过 60、请求绝对峰值不超过 90；真正开始暂停的当前请求和限幅值仍须都不超过 60。RMS 保留符号变化的能量，正负大请求不会相互抵消。

启动前约 0.75 秒道路条件确认保留；短暂 60–90 请求波动在窗口合格时不清掉这段确认记录。窗口不合格或道路条件不满足仍阻止启动。历史记录在非有限值、驾驶员操作、重试、控制退出及开始/中止暂停时清除。

暂停仍为连续 100 帧 standby（2 秒），请求超过 90、未来弯道、模型过期、偏离及驾驶员操作立即中止。5 秒重试间隔、240 秒接管兜底、PID 参数、道路几何门限均不改。没有更改 EPS 固件或 Panda 安全策略，也没有启用自动定速。

## 文件与验证

实际设备 beta2_sharan2 / a6eed9e0c4d9a242db1e35978d2c32fe427491c7，指纹 VOLKSWAGEN SHARAN 2ND GEN。仅替换 `/data/openpilot/selfdrive/car/volkswagen/hca_timer_reset.py`：

- 旧 SHA-256：cf5bbf939e230ba9d68343ca1092ccc5524443368eef0745ea1300e3afc692a2。
- 新 SHA-256：c7fdca2e5b4908c92a114704a27326a5705e6ea334c4250bb39477c3160c0b7c。
- 其他 11 个相关文件沿用 r1 + diag1 哈希，包括记录器、控制器、界面、启动与巡航代码。

本地 10 项控制测试通过，覆盖波动下启动、符号不抵消、91 峰值不能平均掉、当前值仍必须低、驾驶员及道路阻止、恰好 100 帧待机、立即中止与原有限幅恢复、非有限值及计时门限。4 项安装回退测试通过，覆盖哈希预检、原子安装、回退保留诊断版、错误恢复及停车/更新暂停要求。diag1 4 项记录回归通过。

对刚才保存的道路日志进行近似启动对照：旧策略 3 个计时周期找到首次候选，新策略 4 个；其中一个旧策略可启动的周期新策略未找到。使用观测计时和已记录轨迹、20 Hz 请求及 10 Hz 几何数据映射至 50 Hz，不能当作严格控制回放。此结果没有预测暂停两秒能否完成，不能据此保证下一段路测不退出。

## 安装

IP <C2-IP>。两次停车检查确认 Park、零速度、控制未接合；更新暂停与固定分支/提交核验通过。新旧文件暂存并保存旧 timer 快照，原子替换，实际设备 CarController 构造及模型 schema 检查通过，检查程序未发送 CAN。

安装退出码 0，独立核验 12 文件状态为 HCA_R2_ENTRY_PRESENT。随后再次停车检查通过，系统重启已请求。重启前 boot_s 约 1310，重启后独立哈希查询 boot_s 约 111，确认发生新启动。

重启后实时检查 boot_s 178.58：Park、零速度、standstill、控制未接合，carState、controlsState、pandaStates 均 alive/valid，CAN valid，Panda 无故障。服务默认 base，控制状态版本 hca-r2-entry、搜索 150 秒、窗口 0.4 秒，状态年龄约 0.038 秒，证明控制进程已加载新策略。

三秒被动采集正常退出，stderr 空，session_end 正常。包含 30 条新版本状态、52 条 controlsState、52 条 carControl、6 条 liveParameters 和 6 条 pandaStates；新增窗口字段存在。该检查不发送 CAN，仅订阅正在运行系统的消息。日志 `/data/pq46/logs/v3-r2-entry-passive-178.jsonl` 为 237,061 字节，SHA-256 `f6c41d076bc2e2dcbc7f253786c480584bc6c3beb678942c5d73ee4d47a40abb`。停车时的 natural_resets 计数不作为行驶中 EPS 复位成功证据。

安装与检查原始证据保存于忽略目录 `device-backups/hca-r2-entry-install-20261003/`，道路对照保存于 `device-backups/hca-diag1-road-review-20261003/r2-entry-shadow.json`。回退文件和 manifest 保存在 `candidate/device-a6eed9e-v3-hca-r2-entry/`。

## 使用与回退

沿用默认“横向择机＋日志”模式与自动被动记录，不需要另开测试按钮。运行 HCA 状态版本是 hca-r2-entry；记录器 session 标签仍为 hca-r1-diag1，因为记录器没有再替换。新增 entry_window_s、entry_history_samples、entry_raw_rms、entry_limited_rms、entry_peak、seek_after_s 字段供下一段复盘。

停车回退：`python tools/manage_c2_hca_r2_entry.py --ip <IP> --action rollback --parked-ignition`，随后用同一管理器停车重启。它恢复 hca-r1 timer、保留 diag1。若要退回更早包，先退 r2，再按 diag1 与 r1 管理器的基线要求逐层恢复。没有运行系统级 fastboot 刷写。

部署及静态验证不等于道路修复已证实。暂停期间大请求仍可能中止；没有足够机会时仍要求接管。下一段日志应检查启动、完成、中止原因、240 秒兜底和 EPS 状态，而不能仅凭界面显示版本判断成功。
