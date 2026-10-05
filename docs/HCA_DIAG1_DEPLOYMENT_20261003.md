# HCA-r1-diag1 诊断版已部署

2026-10-03 用户要求部署并一直完成到刷入。本次只替换被动记录器，保留 hca-r1 横向逻辑和四分钟门限；PID 冻结与新的中止判据尚未实现。目的为分清暂停时比例、积分、前馈、角度误差及道路需求的贡献。

## 设备和改动

- 实际分支 beta2_sharan2，提交 a6eed9e0c4d9a242db1e35978d2c32fe427491c7。
- 实际指纹 VOLKSWAGEN SHARAN 2ND GEN，实际 lateralTuning=pid，dp_lateral_tune=0，kp=0.6、ki=0.2、kf=0.00006；直接纵向 false。
- 只改变 `/data/pq46/v3_capture.py`，旧 SHA-256 为 `007976e5019bb0624361e36846e68376fa4e335ec8f55a723e2fd23836bd20ba`，新 SHA-256 为 `bc1545f47a7850bf900b715da9f99a9a637d5bba33dfdca861ce3e382796602e`。
- 完整相关 12 文件校验为 HCA_DIAG1_PRESENT，所有控制、UI、启动和服务源文件均保持原哈希；只有记录器不同。
- 已有控制逻辑保持 180 秒搜索、2 秒待机、20% 启动/30% 中止扭矩门限及 240 秒兜底。界面不新增开关，HCA 状态标签仍为 hca-r1，日志 session 标签为 hca-r1-diag1。

## 新记录

controlsState 与 carControl 最高约 20 Hz，保存 PID P/I/F/output、期望角/实际角/误差、期望曲率、软件请求和限幅后输出、控制状态、告警文字/类型。补充实际驾驶员扭矩/转向速率、EPS 故障标志、CAN 有效性；liveParameters 最高 2 Hz。session 保存实际 PID 参数、采样间隔和版本。

carControl.applied 是软件公布的执行输出，不是 EPS 电机实测输出。原始 HCA 与 EPS 帧仍完整保存用于交叉验证。此程序只订阅消息，不发送 CAN。

## 安装与验证经过

4 项本地诊断测试通过，覆盖请求/输出分离、PID 与告警保存、调参记录及私人字段排除、可选元数据失败不阻断记录。

安装前及替换前按固定哈希、更新暂停、分支/提交和原停车检查执行；设备当时 Park、零速度、控制未接合。暂存新旧记录器并保存快照，原子替换。设备检查成功读取实际 PID 和新记录字段，但 SSH 安装命令未在 45 秒内结束，不能仅凭该命令判断完成。随后独立状态查询确认全部预期哈希已安装。

尝试重启时停车检查拒绝。独立实况随后显示车辆已为 D 档、约 29–30 km/h，控制未接合；没有绕过检查或重启 C2。安装前关闭的既有诊断服务以默认 base 恢复，仅恢复被动记录和原界面服务，不重启控制进程。

安装后的记录器独立执行三秒被动采集，退出码 0、stderr 空、session_end 正常。记录含 controlsState 54 条、carControl 54 条、liveParameters 6 条、pq46_status 29 条、CAN 510 条、sendcan 150 条和 Panda 6 条。实际控制器为 pidState，新增字段存在；此段 controls inactive，只验证记录格式和落盘，没有验证暂停期间的 PID 行为。

文件 `/data/pq46/logs/v3-diag1-passive-1190.jsonl` 为 235,402 字节，SHA-256 `7a9242556d6941f8c281e1a56ad8d3f35e5874eb6c2fb83b4819a3d9421c53c4`，已下载核验。最终再次独立查询为 HCA_DIAG1_PRESENT，CAN valid true，服务默认 base。自动录制沿用原 server：原厂定速激活后启动、定速退出一段时间后结束。

安装、检查和原始记录证据在忽略目录 `device-backups/hca-r1-diag1-install-20261003/`。昨晚路测另见 [HCA-r1 复盘](HCA_R1_ROAD_REVIEW_20261003.md)。不能称为新的横向修复已验证，也不预期此次单纯日志增强会减少退出。

## 回退

`tools/manage_c2_hca_diag1.py --ip <IP> --action rollback --parked-ignition` 仅恢复旧记录器；按工具要求停车重启恢复被关闭的诊断服务。需要退横向代码时，先还原诊断记录器，再使用原 r1 管理器。

## 纵向后续讨论

目前有发动机目标速度回读和真实手柄效果证据，但人工短按对应的目标变化并未被模拟帧复现。既有注入帧经 Panda 回显后约 13 ms 出现同计数器原车中性帧，是接收失败的候选原因；不能认定重复帧是唯一原因。

另需核对本车 J527 至发动机 ECU 的巡航专用输入。Ross-Tech 的官方巡航改装说明要求按对应车型电路核对方向柱至发动机的连接，见 [原文](https://wiki.ross-tech.com/wiki/index.php/Cruise_Control_Retrofitting_%281K%29)。该通用说明不能确定中国版本本车的针脚，也不能证明本车 ECU 必须同时核验 CAN 和专用线。

先确定 ECU 实际接受按钮的路径，再谈软件如何避免原车报文冲突；若必须依赖专用输入，纯 CAN 软件方案可能不成立，需要另行讨论独立手柄接口。未证明目标能被改变并可靠回读之前，维持自动发送关闭。
