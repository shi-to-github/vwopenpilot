# C2 V3 部署与停车验证（2026-10-02）

用户随后明确要求“开始刷入”，解除此前暂不连接设备的限制。已通过最后已知地址 `<C2-IP>:8022` 完成安装、停车重启及运行验证。默认仍是 base（横向择机＋日志），没有打开自动调速或触发测试按键。道路上的择机复位和按键是否被发动机执行尚未验证。

## 安装中修正的两个设备兼容性问题

1. 原 SCP 暂存目录为 root-only 0700，APK 为 0600，Android 安装服务不能读取。第一次 APK 安装失败后，全部旧 V2 Python/启动文件已恢复并验证一致，旧应用仍为 versionCode 1。安装器改为只把已验哈希的 APK 原子复制到 `/data/local/tmp/pq46-v3-install.apk`、设 0644，安装后清理该副本；暂存目录仍保持私有。再次安装成功，应用 versionCode 3 / versionName 0.3。
2. 这台 EON 的实际编译 CANParser 只有 `vl`、`vl_all` 和更新接口，没有源码中的 `ts_nanos`。已实测 `vl_all` 仅含本次更新解析到的信号，空批次会清空它。因此 carstate 添加兼容路径：收到本批次 Motor_2 目标或 GRA counter 时记下本机单调接收时间，150 ms 未再收到则过期；不能用缓存目标或稳定车速续期。原生 ts_nanos 存在时仍优先使用。安装后的已知 V3 全文件哈希核对通过，补丁仅改变 carstate；替换前再次验证 P 挡、静止、C2 未接合并保存旧 V3 carstate 快照。

## 完成的实际验证

- 安装前和重启前均用 5 秒实时消息确认静止、P 挡、C2 未接合。分支/提交、V2 基线文件、UI 启动钩子、更新保持与待装文件哈希全部通过。旧日志保留。
- 实际车参数为 `VOLKSWAGEN SHARAN 2ND GEN`，`pcmCruise=true`，`openpilotLongitudinalControl=false`。新控制器、状态解析和运行模块可导入/构造；实际发动机和手柄接收记录有效。906 下拨帧仅在内存打包检查（4 bytes、bus 0），未交给 Panda。
- 已执行 C2 本体重启，之后 Android `sys.boot_completed=1`，运行状态显示新 V3 倒计时 180 s、cruise phase idle、mode base。车速 0、P 挡，carState/controlsState 均收到，CAN valid=true，enabled/active=false。后台 8766 与 Android 悬浮窗服务正常。
- 截图确认右侧显示“横向择机＋日志”“寻找窗口倒计时 180s”“开启前车调速”及“试−10”“试+10”“试+1”。原生速度区域仍可见。截图仅保存在忽略的本地设备验证目录。
- 2 秒被动日志正常结束：340 个接收记录（906/210/648 各 100、978 为 40），100 个 sendcan 记录、车况/前车/Panda/运行状态均记录，906 注入帧数为 0。文件 `/data/pq46/logs/v3-install-passive-231922.jsonl`。
- 修正后 99 项主机离线测试全部通过，包括新增 Android APK 公共安装入口与旧编译解析库接收记录/过期测试。

重启时的旧 SSH 连接未自动结束，已仅清理本任务的该连接；新连接已完成上述运行和截图检查。最后一次额外的“读取已安装 APK 文件哈希”尝试连接超时，**该额外 APK 文件哈希核对未完成**；此前已有 staged/inbox 哈希核对、Android 安装成功、versionCode 3 和真实界面确认。不能把这次最后连接超时写成部署回退或没有安装。

## 当前文件与下一步

当前设备部署哈希以 `candidate/device-a6eed9e-v3/manifest.json` 为准，其中 carstate SHA-256 为 `3a549a7c299e168ea5de22ae5f288f465dc0bf8c17a7aa2a6b5eabf481d1c0b3`。本地候选压缩包已同步纳入兼容性修正及 V2 回退文件。`tools/manage_c2_v3_package.py --action status` 可以再读取状态，`--action rollback` 按已知哈希和停车条件恢复 V2，并保留日志；回退后须停车重启。

原始备份仍在 `device-backups/original-20261001`，本次运行检查、截图和修补前清单在 `device-backups/v3-install-20261002`；这些目录不进入 Git/公开压缩包。之后接机要确认届时 IP，不在失联后假定同一地址仍有效。原车是否实际执行调速和新横向择机策略的行驶表现，继续以实际日志验证，不据停车检查宣称成功。
