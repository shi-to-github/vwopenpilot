# 0.5-monitor 只读提醒版部署记录

2026-10-03，连接 C2 <C2-IP>:8022。安装前两次通过连续五秒的实时 P 挡、静止、控制未接合检查；当前 mode=base，实际控制程序仍为 hca-r2-entry。

本次仅更新 Android 包 nl.vwopenploot.probe 的 APK，版本 0.3 → 0.5-monitor。没有替换车辆控制代码、记录器、后台服务或启动脚本，没有改变巡航模式，没有发送测试 CAN 帧，也没有重启设备。

十二个受保护文件，包括 timer、carcontroller、interface、carstate、cruise、runtime、server、capture、boot 和原生 ui，安装前后 SHA-256 完全一致。设备包管理器确认安装成功，安装后的实际 APK SHA-256 与本地文件一致：

- 旧 APK：122353c7ac795bd58eba2500ab38dc13a8549df3c2bf9a0709e040e8d9964c31。
- 新 APK：1c5e58cdc85ac2fcd4823d151f77de8289d7b026dd7404c54cc0a92dae0421c6。
- 两个 APK 签名证书 SHA-256 均为 a5e5d21ee91526f8ce6eddd80b16bd81c08c9e7a5d5493823b7c4f8e28e8b35a。

Android 服务实际运行，应用记录了 monitor_started 与 inactive 状态。已获取并检查设备实际截图：显示 000.0 / 240 秒、横向未接合、软件计时不等于 EPS 内部计数、车辆日志未录制、提示音可用，以及禁用的提醒确认按钮。停车时的“未录制”是当前状态；本轮没有进行道路录制测试。

界面显示的是当前 r2 的四分钟软件门限，235 秒起提示接管；不是本车已验证的六分钟硬件倒计时。确认按钮只写本地应用事件日志，不改变控制。窗口可拖动。系统音量非零只代表声音通道可用；没有确认驾驶员实际听到提示，也没有验证道路上的提示效果。

本地 JVM 十六个计时、新鲜度、版本和非法值边界检查通过，APK 编译与签名验证通过。修正了 Android 6 不支持 Double.isFinite 的兼容性问题，改用 isNaN/isInfinite。

安装报告、原 APK 和实际截图保存于 device-backups/hca-monitor-install-20261003/，并按用户要求明文压缩归档。设备原 APK 另保存在 /data/pq46_hca_monitor_staging/original-overlay.apk。

回退只读界面可使用 tools/install_c2_hca_monitor.py --ip <C2-IP> --action rollback；该操作同样要求停车和已知控制基线，不改变车辆控制逻辑。
