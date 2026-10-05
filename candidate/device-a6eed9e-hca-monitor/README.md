# 只读计时提醒悬浮窗

版本 hca-monitor-0.5，Android 包名沿用 nl.vwopenploot.probe，使用原来的签名。只替换悬浮窗 APK，不改变 C2 的车辆控制程序、Panda、EPS、巡航模式或记录器，也不重启设备。

界面显示当前 r2-entry 软件计时 / 240 秒、横向状态、车辆日志是否正在录制和声音可用状态。235 秒起显示接管提醒，240 秒显示已到软件门限；轮询和处理存在延迟，所以不是精确到墙钟的五秒保证。这里的计时不是 EPS 内部计数，更不是本车已确认的六分钟倒计时。

“确认提醒”只在应用本地写一条日志，不发送 HTTP 写请求、不控制车辆、不暂停纠偏、不触发复位、不恢复辅助。窗口只有 GET /status 请求。收到未知版本或超过一秒的状态时，不显示未经确认的倒计时。

提醒采用文字和短提示音；系统静音时不能保证听见，应用不调整系统音量。窗口可通过拖动时间区域移动。确认收到提醒不等于确认驾驶员已接管。

事件日志：/data/data/nl.vwopenploot.probe/files/hca_monitor_events.jsonl。原有车辆日志仍由 diag1 记录器保存。

构建：tools/build_c2_probe_overlay.py --package monitor。

安装与回退：tools/install_c2_hca_monitor.py --ip <IP> --action install 或 --action rollback。工具要求连续停车、P 挡、控制未接合，固定 APK 与控制文件哈希，并备份旧 APK；不执行车辆控制代码升级。

本地纯 JVM 检查覆盖十六个计时、版本、非有限数及新鲜度边界。APK 编译及签名验证通过不代表已经验证道路提示效果或 EPS 行为。
