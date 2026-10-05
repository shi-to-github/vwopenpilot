# HCA-r1-diag1 被动诊断版

在已部署 hca-r1 上只替换 `/data/pq46/v3_capture.py`，不修改任何车辆控制源文件或阈值。没有冻结 PID 积分、移除扭矩中止条件或延长四分钟门限。

新增约最高 20 Hz 的 controlsState / carControl 记录：PID P/I/F、角度误差、期望与实际角度、请求与实际软件输出、曲率、控制状态和告警；增加低频 liveParameters 与车况字段。session 头标记 `trace_version=hca-r1-diag1` 并记录实际控制器类型、调参及采样间隔，不记录 VIN、位置或影像。

沿用现有自动日志启动和轮转方式。开启原厂定速后自动记录，不需要新开关；HCA 运行标签仍为 hca-r1。纵向自动发送保持关闭。

`tools/manage_c2_hca_diag1.py` 提供固定哈希的 status/install/rollback/reboot。升级和回退按原有停车与更新暂停条件执行。旧 r1 管理器会拒绝新的记录器哈希，回退顺序为先本工具还原记录器，再按旧 r1 工具回退横向代码。

见 [部署记录](../../docs/HCA_DIAG1_DEPLOYMENT_20261003.md)。
