# 安全声明 / Safety Notice

## 中文

这是一个**个人研究项目**，对象是一台 2009 年国产大众迈腾 B6（PQ46），配合 comma two（C2）上的 Dragonpilot。

**它会给转向机发送报文。** 具体做法是在正常驾驶中主动发出一段约 1.1 秒的 HCA standby（50 Hz 下 55 帧），其间**没有主动车道居中**，只有方向机原有的助力。驾驶员始终可以手动转向，但这段时间车辆不会自我纠偏。

如果你要在自己车上使用，请注意：

1. **必须有人监督驾驶。** 双手放在方向盘上、脚搭在刹车上，随时准备接管。
2. 本项目**不刷写** EPS 固件、**不改** ABS、**不改** Panda 安全策略。这些边界是刻意的。
3. 本项目**与 comma.ai、dragonpilot、大众、ZF、VW Braunschweig 均无关联**，未获其背书。
4. 仓库中的参数（180 / 300 / 350 / 355 秒、1.1 秒、扭矩门限等）是针对**这一台车**测出来的，**不能假定适用于任何其他车**。本车方向机为 `5N1 909 144 J` / `J500__APA-BS KL.089 0503`，与公开逆向的 1K0 ZF 方向机**不是同一款**。
5. 最关键的结论——"1.1 秒足以复位本车方向机计时"——**证据等级是驾驶员感知**（约 3 小时 34 分、约 60 轮复位、0 次断连），该段行程的原始 CAN 日志未取回，**没有帧级复核**。请按这个可信度引用。
6. **不要**把这个仓库当成可用的消费级驾驶辅助产品。出问题是你自己的责任。

## English

Personal research project on a 2009 VW Magotan B6 (PQ46) with Dragonpilot on a comma two.

**It sends frames to the steering rack.** During a reset it commands roughly 1.1 s of HCA standby (55 frames at 50 Hz), during which there is **no active lane centering** — only the rack's own power assist. The driver can always steer manually, but the car will not correct itself during that window.

- A supervising driver is mandatory: hands on the wheel, foot over the brake.
- **No** EPS firmware flashing, **no** ABS changes, **no** Panda safety-policy changes. Those limits are deliberate.
- Not affiliated with or endorsed by comma.ai, dragonpilot, Volkswagen, ZF, or VW Braunschweig.
- All timings and torque thresholds were measured on **one specific car** and must not be assumed valid for any other.
- The headline result ("1.1 s resets this rack's timer") is **driver-perception grade evidence**: one 3 h 34 m drive, about 60 reset cycles, zero disconnections, with **no raw CAN trace retained** for frame-level confirmation.
- Do not treat this as a usable driver-assistance product.

---

## 本仓库不包含什么 / What is deliberately not published

研究仓库里还有一些**不适合公开**的材料，公开副本已排除：

| 排除项 | 原因 |
| --- | --- |
| `device-backups/` | 原车完整备份与道路日志，**含私人参数**、SSH 连接信息与车辆标识 |
| `archive/` | 上述材料的去重明文归档（约 1.7 GB） |
| `vendor/` | 第三方上游源码树，本仓库不重新分发 |
| `artifacts/` | 打包产物与部署压缩包 |
| `candidate/**/overlay/keys/` | Android 应用签名 keystore |
| SSH 私钥 | 从未进入版本库 |

公开副本另外做了脱敏：本机 Windows 用户名、内网 IP、微信临时文件路径均已替换为占位符。
