# 实际 C2 的 HCA 两秒候选包

适用设备：Dragonpilot `beta2_sharan2`，Git 提交 `a6eed9e0c4d9a242db1e35978d2c32fe427491c7`。本包只替换 `carcontroller.py` 并新增 `hca_timer_reset.py`。`interface.py`、定速按钮、Panda、ABS 与 EPS 均不在本次变更内。车速低于当前软件 `minSteerSpeed` 时仍不会横向控制；这样能先单独验证长时间退出问题。

启用后的候选在累计约 240 秒非零横向请求后，对 50 Hz 的 HCA 报文连续发送 100 帧零扭矩 standby，再恢复请求。两秒内没有主动转向纠偏，也没有新增专门的屏幕提示。当前仅通过离线回放验证报文时序，尚无实车结果。

`manifest.json` 固定了原始和候选文件的 SHA-256。`deploy/` 是待安装文件，`rollback/` 保存与设备原始提交逐字节一致的控制器。安装工具会在设备处于 offroad、没有待处理更新、分支和文件哈希完全匹配时才写入文件；先放入新模块，再原子替换控制器。回退时先恢复原控制器，再删除候选模块。工具不会自动重启 C2。

这台 C2 的更新器曾强制恢复本机改动，并在本次接机时长时间停在 `checking...`。安装工具会拒绝在更新器运行时写入。`hold_c2_updates.py` 可以先把设备原有的 `DisableUpdates` 状态记在设备的 `/data/pq46_hca_staging/update-hold.json`，临时停用更新器；测试结束、回退代码后再恢复原状态。停用期间不会收到 Dragonpilot 更新。

在 PowerShell 中执行：

```powershell
python D:\VWopenploot\tools\hold_c2_updates.py --ip <C2的IP> --action status
python D:\VWopenploot\tools\hold_c2_updates.py --ip <C2的IP> --action pause
python D:\VWopenploot\tools\manage_c2_hca_package.py --ip <C2的IP> --action status
python D:\VWopenploot\tools\manage_c2_hca_package.py --ip <C2的IP> --action install
```

安装后在车辆停稳时重启 C2，重启后先再次运行 `status`。只有输出 `PACKAGE_ALREADY_PRESENT` 才代表候选文件仍在。自动更新曾在同一设备上强制检出并清除本机修改；如果重启后输出 `READY_TO_INSTALL`，说明代码已经被还原，不能把这次行驶当作候选测试。测试期间请持续掌握方向盘；这两秒空窗可能要求驾驶员立即转向。

若 C2 必须在车辆点火时才能供电，所有操作额外传入 `--parked-ignition`。该模式连续读取实时 `carState`、`controlsState` 与 `pandaStates`，仅在 P 挡、零车速、车辆静止、openpilot 未启用且点火在线时放行；车辆一旦不满足条件就拒绝写入。不能只修改 `IsOffroad` 参数绕过校验。回退和恢复更新也可使用同一参数。

2026-10-01 实际设备已按上述模式安装并重启。重启后 `PACKAGE_ALREADY_PRESENT`、`DisableUpdates=1`，运行中的 `controlsd` 正常发布消息；尚未做道路验证。

回退命令：

```powershell
python D:\VWopenploot\tools\manage_c2_hca_package.py --ip <C2的IP> --action rollback
python D:\VWopenploot\tools\hold_c2_updates.py --ip <C2的IP> --action resume
```

回退完成后仍需在车辆停稳时重启并再次核验 `status`。若文件哈希与本包的原版或候选都不匹配，工具会停下，不会覆盖未知改动。
