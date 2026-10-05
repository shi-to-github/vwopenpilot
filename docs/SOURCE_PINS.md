# 公开源码固定点

公开源码核验日期：2026-09-21；实际 C2 核验日期：2026-10-01。

| 用途 | 仓库/分支 | 当前固定提交 |
| --- | --- | --- |
| 旧 C2 参考 | `dragonpilot/dragonpilot deprecated-release2` | `1415631df6ad22feb4c0878df07c878e3d5d2afd` |
| 曾用于设备版本推测的参考 | `dragonpilot/dragonpilot deprecated-beta2` | `c6efa8341a77eb55be69dfcf99afc6c62402e2c4` |
| 实际 C2 运行基线 | `beta2_sharan2`，通过设备 SSH 核验 | `a6eed9e0c4d9a242db1e35978d2c32fe427491c7` |
| 2023-04-13 EON/C2 发布提交 | `dragonpilot/dragonpilot deprecated-beta2` | `cf18a8fb09e8d72aa256872e26fe64e6f535a0bd` |
| 后期 C2 参考 | `dragonpilot/dragonpilot d2` | `f965f86fb77f3919b1d558dd279f0614f22c76c4` |
| 旧更新记录 | `dragonpilot/dp-devel master` | `0d8224ef0afb013bb95dc9b0ee44943d4099ef4b` |
| 1.1 秒公开候选实现 | `commaai/opendbc PR #3129` | `2661260180b097e4709f7c63e736b760c7f9a3b5` |
| 1K0 固件研究 | `I-CAN-hack/pq-flasher` | `95d283075714c9476cacc6ef041fd810abc86f8a` |
| C2 系统恢复 | `commaai/eon-neos` | `8f12ec7116883487b9bf0f8a4ee36271538e5274` |
| 原厂巡航按钮调速参考 | `openpilotkr/openpilot OPKR` | `3ff6dc6` |

本地 `vendor` 目录保留上述仓库。它们只是参考版本，实际补丁必须以 C2 备份中的源代码为基线。

本地候选分支：

| 基线 | 本地分支 | 候选提交 | 默认状态 |
| --- | --- | --- | --- |
| deprecated-release2 | `codex/pq46-hca-standby-candidate` | `b6525f5` | 功能关闭 |
| deprecated-beta2 / c6 | `codex/pq46-hca-standby-candidate` | `af8892a` | 功能关闭 |
| deprecated-beta2 / c6 机会版 | `codex/pq46-hca-opportunistic-candidate` | `fbd1134` | 功能关闭 |
| deprecated-beta2 / c6 HCA + 定速按钮 | `codex/pq46-hca-cruise-candidate` | `35644ba` | 两项功能均关闭 |
| d2 | `codex/pq46-hca-standby-candidate` | `39f08ef` | 功能关闭 |
| 实际 C2 / a6eed9e | `codex/pq46-device-a6eed-candidate` | `ff9cc9b` 原有配置；`1d4a92c` HCA 候选 | 功能关闭，未部署 |

固定版候选把 240 秒后连续 2.0 秒 standby 的状态机接入对应控制器，并保持 `PQ_LONG_STANDBY_ENABLED = False`。机会版从 240 秒开始等待低扭矩窗口，保持 `PQ_OPPORTUNISTIC_RESET_ENABLED = False`。设备版本、报文频率与原始行为确认前，不生成开启功能的部署提交。

组合候选增加关闭、观察、单次按钮验证和视觉前车调速四级模式，配置文件缺失时不发送加减速按钮。OPKR 仅用于参考其 Hyundai/Kia 按钮调速状态机；PQ 候选没有复制其依赖原厂 SCC 制动的逻辑。

公开 `deprecated-release2` 的 Volkswagen 控制器在约 118 秒持续非零请求后只发送一帧未使能 HCA；50 Hz 下约为 20 ms。公开 `d2` 已改用另一套计时字段，并增加接近 360 秒限制的提示，不能直接套用旧分支的行号补丁。
