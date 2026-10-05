# 车辆与设备基线

## 已确认

- 车辆：2009 年生产的国产迈腾 B6，PQ46。
- 发动机与变速箱：EA888 2.0T、DQ250 六速 DSG。
- 原车具备普通定速巡航。
- 网关：`7N0 907 530 BL`，来自 B7。
- EPS 诊断显示：`5N1 909 144 J`、`J500__APA-BS KL.089 0503`、编码 `000258`。
- 仪表照片显示：`35D 920 880 A`、`KOMBI H01 0505`。
- Dragonpilot 使用 Passat NMS 或 Sharan 的 PQ 控制逻辑均能建立横向控制。
- C2 界面版本线索：`dragonpilot (LATEST) EON/C2 RELEASE 20230326`，当前版本显示约为 `20230413 deprecated-beta2 c6`。
- 公开分支核对结果：`CHANGELOGS_c2.md` 明确写有 `Latest - EON/C2 Release` 和同步 openpilot `2023.03.26`；`common/version.h` 为 `2023.04.13`；分支头为 `c6efa834...`。三项同时匹配，实际源码极可能来自该分支。
- 症状：持续横向控制数分钟后，C2 和仪表提示接管，自动纠偏停止；开关定速后可以重新工作。
- 目标：先验证 C2 主动发送连续 2.0 秒正常 HCA standby，是否能在不刷 EPS 的情况下复位持续请求计时。

## 接机后确认

- C2 实际 Git remote、分支、提交号及工作区改动。
- 核对界面的 `c6` 是否对应公开 `deprecated-beta2` 头提交 `c6efa8341a77...`；该分支内的 2023-04-13 发布提交为 `cf18a8fb09e8d72aa256872e26fe64e6f535a0bd`。
- NEOS 版本与 SSH 端口。
- 实际车型 fingerprint 是 Passat NMS、Sharan 还是私人新增项。
- 实际 HCA 报文频率、总线位置及 `HCA_Status` 编码。
- 退出前后的软件事件、发送请求和 `LH2_Sta_HCA` 状态。
- 退出后不触碰方向盘时，EPS 和 C2 是否自行恢复，以及恢复所需时间。

Passat NMS 和 Sharan 逻辑都能控制，只能说明两条适配路径与当前车辆的关键 PQ 报文兼容；不能据此假定质量、轴距、转向限幅、最低速度和纵向参数完全相同。因此候选补丁只改 HCA 计时状态，不改车型动力学参数。
