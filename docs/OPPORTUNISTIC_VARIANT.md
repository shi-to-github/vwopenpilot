# 低扭矩机会触发候选

## 来源与目的

本候选把 OpenDBC PR #3129 的机会触发思路移植到设备最可能使用的 Dragonpilot `deprecated-beta2/c6`。它与固定 240 秒强制暂停版并列保存，二者不会同时启用。

公开实现用低输出扭矩近似判断较空闲的转向窗口，并没有直接识别道路是否为直线。本候选保留这个原则，把复位时长按当前验证计划从公开实现的 1.1 秒延长为 2.0 秒。

## 时序

1. 横向控制累计达到 240 秒后开始寻找机会。
2. 输出转向扭矩绝对值不超过最大值的 20%，并连续保持 0.5 秒。
3. 满足条件后发送 HCA standby 和零转向扭矩，共 2.0 秒；50 Hz 下为 100 帧。
4. standby 期间若模型原始转向需求超过 20% 阈值，立即中止并恢复经过限幅的转向输出。
5. 完成完整 2.0 秒后清除本地累计计时并重新寻找下一周期。
6. 若自然零扭矩连续达到 2.0 秒，也视为已经完成一次复位。

高转向需求持续存在时，该候选不会按 240 秒固定切断。累计达到 350 秒时只置内部 `eps_timer_soft_disable_alert` 标志；2023 Dragonpilot 当前没有消费这个新标志，因此还不会向驾驶员显示专用提示，也不会自动软退出。接机前需要讨论是否以及如何接入旧版事件系统。

## 与公开实现的差别

- 公开版本：standby 1.1 秒；本候选：2.0 秒。
- 本候选在 standby 中同时检查模型原始需求，避免输出限幅从零缓慢爬升时延迟发现转向需求增加。
- 本候选只用于 PQ 车型，并保持 `PQ_OPPORTUNISTIC_RESET_ENABLED = False`。
- 没有加入道路曲率、横向误差或车道线质量判断。

## 本地位置

- 工作树：`vendor/dragonpilot-beta2-c6-opportunistic`
- 分支：`codex/pq46-hca-opportunistic-candidate`
- 候选提交：`fbd1134`
- 补丁：`candidate/patches/beta2-c6-opportunistic/0001-vw-pq-stage-opportunistic-HCA-standby-reset-candidat.patch`

