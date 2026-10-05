# 5N1 APA-BS 与逆向研究方向机对照

## 结论

两者不是同一款方向机，也没有证据表明来自同一制造厂。

- Willem Melching 逆向的对象是 2010 Golf Mk6 上的 `1K0 909 144 E`，诊断组件为 `EPS_ZFLS Kl.184`，研究固件为 2501。`EPS_ZFLS` 指向 ZF Lenksysteme 系列。
- 本车诊断对象是 `5N1 909 144 J`，组件为 `J500__APA-BS KL.089 0503`，公开的同型扫描通常显示硬件 `5N1 909 148 F`、诊断身份 `VDO-001`。
- APA-BS 是 Volkswagen AG Braunschweig 自主开发的 Axially Parallel Actuation 方向机；公开资料将其与 ZF Gen 3 分成两类。
- Volkswagen 官方技术提示也从硬件上区分它们：1K0 示例在方向机内带 G85，5N0/5N1 示例不在方向机内带 G85。

因此，1K0 固件中确认的 `36000 @ 100 Hz` 六分钟计数器和 `100 @ 100 Hz` 一秒 standby 复位，只能作为 5N1 行为的强线索，不能视为已经反汇编验证过 5N1/0503 的内部实现。

## 为什么 C2 standby 方案仍值得验证

- 两种方向机服务于 VW PQ 车辆并接收同类 HCA 请求；Dragonpilot 已能通过当前 5N1 实际控制方向。
- 本车实测退出时间、退出后重新建立控制的行为，与 HCA 持续请求超时高度相似。
- OpenDBC 社区把 PQ 与 MLB 都归入需要约 1.1 秒复位窗口的车型族，并有 MLB 车型超过 10,000 km 的公开测试；这说明该机制并不只存在于研究员拆开的那一个 1K0 零件。
- 我们的第一阶段不刷写 EPS，只让 C2 发送 2.0 秒正常 standby。若 5N1 使用不同的内部计时逻辑，失败结果也不会把未经验证的固件写入方向机。

## 证据与可信度

| 项目 | 结论 | 可信度 |
| --- | --- | --- |
| 逆向对象零件号 | `1K0 909 144 E` | 高，作者直接报告 |
| 本车零件号 | `5N1 909 144 J / APA-BS / 0503` | 高，本车 VCDS 照片 |
| 是否同款 | 否 | 高，零件族、结构、G85 布置和诊断组件均不同 |
| 是否同一制造厂 | 未发现支持证据；现有资料反而指向 ZF 与 VW Braunschweig 两条来源 | 中高 |
| 5N1 是否也需至少 1 秒 standby | 尚未直接逆向确认 | 未确认，待实车验证 |
| 2 秒 standby 是否值得测试 | 是 | 高，改动可逆且直接验证机制 |

## 来源

- I CAN Hack Part 1：https://icanhack.nl/blog/vw-part1/
- I CAN Hack Part 3：https://icanhack.nl/blog/vw-part3/
- Volkswagen 技术提示 TT 45-09-04：https://static.nhtsa.gov/odi/tsbs/2014/MC-10120273-9999.pdf
- APA-BS 技术论文摘要：https://doi.org/10.1007/BF03242151
- OpenDBC PR #3129：https://github.com/commaai/opendbc/pull/3129

