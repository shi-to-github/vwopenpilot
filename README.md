# VWopenpilot - PQ46 / C2 HCA 计时复位研究工程

**中文** · [English](README.en.md)

> ⚠️ **安全声明**：本项目会主动向转向机发送报文，使用前务必先读 [SAFETY.md](SAFETY.md)。
> 来源、上游许可与归属见 [ATTRIBUTION.md](ATTRIBUTION.md)。
> 上游源码树与含私人参数的设备备份**不在本仓库中**。

## 起因 · 经过 · 结果

**起因：** 大众原厂的车道保持能一直用，C2 的车道辅助却在**约 6 分钟**后固定失效 —— 仪表提示接管、纠偏停止；开关一下定速能再用几分钟，然后再次失效。

**原因：** 两者的控制方式根本不同。

- 原车那个车道保持摄像头很老，属于"快压线才短促纠偏"那一类，**只在需要时发一下控制指令**，不连续发送。
- C2 的车道辅助是**连续不断**地发送控制指令。
- 而大众方向机固件里写死了一条限制：**连续控制时间不能超过 360 秒**（正好 6 分钟）。

所以原车的分段式控制永远碰不到这条限制，C2 的连续控制必然在 360 秒撞上它。这不是 C2 的 bug，是控制机制与固件限制的冲突。

**解决办法：** 同一份固件里还有一条 —— **只要控制中断 1 秒以上，360 秒计时器就归零。**

于是本项目的做法是：在 180–300 秒之间，让 C2 挑一段合适的直线，**主动停止控制 1.1 秒**，把计时器清零，然后继续正常开。

安全冗余是：**这 1.1 秒里一旦出现任何需要动方向盘的情况（手扶方向盘、打灯、踩刹车或油门、前方要转弯、车辆偏离车道中心），C2 立即恢复控制，改成等下一个合适时机再停。** 全程只是"晚一点再停"，绝不硬来。

**结果：** 现在这个版本在我车上处于**高可用状态** —— 约 3 小时 34 分钟、约 60 轮复位、**0 次辅助驾驶断连**；择机一般落在 180–220 秒；驾驶员完全感受不到那 1.1 秒。

> **结论：这台车（2009 迈腾 B6，`5N1 909 144 J` 方向机）"辅助驾驶跑几分钟就退出"的问题，已解决。**
> 证据等级：本车实车、驾驶员感知级（约 60 轮复位验证，0 次断连）；该段行程的原始 CAN 日志未取回，帧级复核见 [`evidence/`](evidence/README.md)。

> 360 秒上限与"中断 1 秒归零"来自对大众方向机固件的公开逆向（[I CAN Hack](https://icanhack.nl/blog/vw-part1/)），**不是本项目发现的**；1.1 秒这个取值来自 [opendbc #3129](https://github.com/commaai/opendbc/pull/3129)。**本项目做的是：在这台车上把它跑通、找出为什么之前总是失败、并给出实车证据。**

### 怎么读这个仓库

- **只想搞明白怎么回事** → 读完上面这节就够了；想多看一点看 [路测复盘](docs/R4_ROAD_REVIEW_20261003.md)
- **想看证据** → [`evidence/`](evidence/README.md)：判定规则，以及"决定性日志"的投放位置
- **想改代码 / 想知道每个判断条件从哪来** → [时序与决策链](docs/TIMELINE_AND_DECISION_CHAIN.md)（给 AI 和改代码的人看的，较长）
- **想知道失败长什么样** → [V3 复盘](docs/V3_ROAD_REVIEW_20261002.md)、[r2 复盘](docs/HCA_R2_ROAD_REVIEW_LATEST.md)

## 关于项目名

`VWopenploot` 是把 `openpilot` **打错了** —— 当初建目录时的手误，不是谐音梗。

GitHub 仓库名是 `vwopenpilot`。本地工作目录 `D:\VWopenploot`、Android 悬浮窗包名
`nl.vwopenploot.probe`，以及早期文档里引用的路径仍保留原拼写。这不影响任何功能：
Android 包名在 APK 安装时就固定了，改名等于换一个应用；本地路径改名也没有实际收益。
本文档中引用的每个路径，都对应实际以该名字存在的目录。

目标车辆：2009 年国产迈腾 B6（PQ46），EA888 2.0T、DQ250、普通定速巡航。已知车辆可使用 Dragonpilot 的 Passat NMS 或 Sharan/PQ 控制逻辑。已知 EPS 诊断身份为 `5N1 909 144 J`、`J500__APA-BS KL.089 0503`；网关为 `7N0 907 530 BL`。

**2026-10-03 第一个稳定版：hca-r4-forced（Git tag `stable-1-hca-r4-forced`）。** 实测约 3 小时 34 分、约 60 轮复位、**0 次辅助驾驶断连**；择机复位一般落在 180–220 秒，偶尔 250–300+ 秒，从未超过 300 秒，因此 355 秒强制兜底从未在道路上触发。驾驶员判定 **1.1 秒相比原 2.0 秒是质的提升**：暂停更短、择机窗口更容易满足且无感；1.1 秒被认定对本车 5N1/0503 有效（依据：方向机内部计数累加，若 1.1 秒无效则会在开车约 6 分钟内出现拒绝，而实测 3.5 小时零断连）。**证据等级为驾驶员感知**，该段行程日志未取回，无 978 帧级复核。见 [路测复盘](docs/R4_ROAD_REVIEW_20261003.md) 与 [部署记录](docs/HCA_R4_FORCED_DEPLOYMENT_20261003.md)。

**本地入库：** 源码与文档直接保存于 Git；原始设备备份、实验日志、上游源码及资料包另建立去重归档并纳入同一仓库。按用户后续要求，全部资料采用明文压缩、不加密，未上传到远程。SSH 私钥和应用签名密钥单独保留。范围及核验方法见 [归档说明](docs/LOCAL_REPOSITORY_ARCHIVE_20261003.md)。后文保留历史实验与部署记录，不表示这些候选仍获准部署。

本工程先研究 C2 上的 Dragonpilot HCA 请求状态，再研究通过普通定速手柄按钮修整目标速度。不刷 EPS、不改 ABS、不改 Panda 安全策略。横向使用正常 standby 报文尝试复位 EPS 连续控制计时，调速使用有限按键及发动机目标回读。

**2026-10-03 历史部署：HCA-r2-entry 已安装并停车重启。** 150 秒开始搜索，启动前使用短窗口 RMS 评估请求波动，实际启动仍要求当前低扭矩；保留两秒 standby、立即中止与四分钟兜底。继续使用 diag1 被动记录，调速关闭。见 [新版本部署记录](docs/HCA_R2_ENTRY_DEPLOYMENT_20261003.md)。此前约 34.5 分钟 diag1 日志完成 0 次、三次暂停均中止，见 [本次道路复盘](docs/HCA_DIAG1_ROAD_REVIEW_20261003.md)；r2 的完整暂停效果尚待新的实车记录。

**后续 r2 实车结果：约 27.4 分钟，自动完整重置 0 次，6 次暂停均由请求门限中止，6 次触发新增软件接管门限。** 该修正未达到目标。详见 [r2 最新复盘与回归建议](docs/HCA_R2_ROAD_REVIEW_LATEST.md)。此段曾选择 auto，出现 ECU 回读超时；部署时默认关闭不代表整段日志均为 base。此为升级 r3 前的 r2 复盘。

**本地后续准备：1.1 秒候选已生成、尚未部署。** 同步缩短启动漂移预测与模型评估窗口。跨历史日志发现一次 EPS 先拒绝事件，时序指向约六分钟累计激活；详见 [1.1 秒候选与 EPS 超时证据](docs/EPS_TIMEOUT_AND_1100MS_CANDIDATE.md)。本车 1.1 秒能否复位尚未实测。

此前 V3 路测未达到预期：约 38.7 分钟保存的道路日志中，择机重置完成 0 次，三次暂停均在 0.16–0.42 秒中止，另有四次触发 240 秒接管门限。四组定速请求有 Panda 发送回显，但发动机目标无变化。见 [V3 路测复盘](docs/V3_ROAD_REVIEW_20261002.md)。原版和回退包继续保留。

## 下一步研究方向

**在普通定速巡航上实现 ACC（"低配版 ACC"）—— 研究进行中，尚无实现、未部署。**

本车没有 ACC 雷达。方向是用 C2 模拟原车巡航手柄报文（`GRA_Neu`，`0x38A`）逐次修整原车定速目标，
依据视觉前车做速度跟随。已知四项阻碍（注入帧未被 ECU 接受、同计数器冲突、可能依赖巡航专用硬线、
回读路径缺失）以及方向机自身的低速门槛，详见 [计划文档](docs/ACC_ON_STOCK_CRUISE_PLAN.md)。
当前已部署的稳定版中，调速部分默认 `base` 关闭，不发送任何调速按键。

## 先行工作与本文贡献

本项目的**核心机制不是本项目发现的**，这里写清楚以免误读：

| 结论 | 来源 | 本文做了什么 |
| --- | --- | --- |
| 大众 PQ 方向机在累计约 360 秒 HCA 请求后拒绝控制；一段约 1 秒 standby 可复位该计时 | Willem Melching / [I CAN Hack](https://icanhack.nl/blog/vw-part1/)，对象是 2010 Golf Mk6 的 `1K0 909 144 E`（ZF） | **未照搬**。本车是 `5N1 909 144 J`（APA-BS，VW Braunschweig），与 1K0 不是同一款、不同制造来源、G85 布置也不同。本文先用本车历史日志独立定位出"约 360 秒累计激活" |
| 复位窗口取 **1.1 秒** | [commaai/opendbc PR #3129](https://github.com/commaai/opendbc/pull/3129)（作者 **Dennis-NL**，在 Porsche Macan 与 Audi Q5 上累计行驶 10,000 km）。该 PR 被维护者以"概念成立，但实现形态需要重构"**关闭且未合并**，并给出五步计划 | 在**本车 5N1 / PQ46** 上首次做实车验证：约 3 小时 34 分、约 60 轮、0 次断连 |

> **上游现状（2026 年核查）**：五步计划的第 1 步 [commaai/opendbc #3160](https://github.com/commaai/opendbc/pull/3160)「把 HCA 缓解逻辑重构成独立类」**已合并**；**第 2 步的 1.1 秒复位逻辑尚未合入** —— 当前 opendbc master 的 `HCAMitigation` 仍然只做"同扭矩超时后单帧 −1"，`values.py` 中只有 `STEER_TIME_STUCK_TORQUE = 1.9`，没有复位时长常量。计划中写明第 2 步要把 PQ / MLB 设为 **1.1 秒**、MQB 设为 0.05 秒。
>
> 也就是说：**本项目的复位逻辑不是复制上游已合并的代码**，而是在一台上游未覆盖的车型上、对一个概念已被认可但代码从未合入的方案做的独立实现与实测。

**本文的贡献是适配、定位与实车证据，不是机制发现：**

1. 确认公开的 1K0 结论对本车只是线索而非答案（不同零件族、不同制造来源）。
2. 在 2023 年 Dragonpilot 分支 / EON-C2 / 不改 Panda 安全策略的约束下，把 standby 复位真正实现、部署、回退。
3. **定位出择机失败的真实瓶颈**：r1 十二次仅成三次、diag1 零成三次、r2 零成六次，全部中止在"原始请求超过 90"。改为"持续 0.2 秒达到 270 才中止"后成功率接近 100%。这条上游没有。
4. 给出 1.1 秒对本车有效的**可证伪实车证据**及其边界（驾驶员感知级，无原始 978 帧）。

如果这些数据对上游 PR 有用，欢迎取用。

## 目录

- `vendor/dragonpilot-release2`：2023 年冻结的 C2 `deprecated-release2` 参考源码。
- `vendor/dragonpilot-beta2-c6`：较新的 `deprecated-beta2` / `c6efa834` 参考源码。
- `vendor/dragonpilot-device-a6eed9e`：按实际 C2 提交 `a6eed9e` 建立的工作树，包含设备原有两处修改和默认关闭的 HCA 候选。
- `vendor/dragonpilot-beta2-c6-opportunistic`：同一基线上的低扭矩机会触发候选工作树。
- `vendor/dragonpilot-beta2-c6-cruise`：固定 2 秒 HCA 复位加分级原厂定速按钮候选，所有发送功能默认关闭。
- `vendor/dragonpilot-d2`：后来保留给 C2/EON 的 `d2` 参考源码。
- `vendor/dp-devel`：旧 Dragonpilot 更新记录。
- `vendor/opkr-reference`：现代/起亚原厂 SCC 按钮调速实现参考，不直接部署到大众。
- `vendor/pq-flasher`：1K0 EPS 逆向研究参考，只用于理解机制，不适用于 5N1/0503 刷写。
- `vendor/eon-neos`：C2 系统级 fastboot 恢复工具，只作最后恢复手段。
- `candidate/`：与设备版本无关的待机复位状态机原型。
- `candidate/device-a6eed9e-2s/`：已部署过的 HCA 两秒包及原版回退文件。
- `candidate/device-a6eed9e-v2-probe/`：此前设备上的固定四分钟横向逻辑、单帧按钮探针和旧悬浮窗，作为 V3 回退基线保存。
- `candidate/device-a6eed9e-v3/`：原 V3 横向择机、有限按键前车调速、自动日志和 V2 回退包。
- `candidate/device-a6eed9e-v3-hca-r1/`：此前已部署的横向择机修正包，包含三文件升级及原 V3 回退文件。
- `candidate/device-a6eed9e-v3-hca-r1-diag1/`：已部署的被动诊断记录器及旧记录器回退文件，不改横向控制逻辑。
- `candidate/device-a6eed9e-v3-hca-r2-entry/`：此前启动机会修正版，单文件升级及 r1 timer 回退文件。
- `candidate/device-a6eed9e-v3-hca-r3-staged/`：分阶段择机版（350 秒软退出接管），r4 的回退基线。
- `candidate/device-a6eed9e-v3-hca-r4-forced/`：350 秒纯提示 + 355 秒无条件强制暂停兜底版，回退指向已部署的 r3。
- `evidence/`：帧级道路证据插槽（当前为空），存放由 `tools/extract_hca_evidence.py` 生成的压缩证据包。
- `tools/extract_hca_evidence.py`：从原始行程日志抽取可发布的小体积证据包（978 状态帧 + 计数器 + 带 SHA-256 的来源清单）。
- `docs/TIMELINE_AND_DECISION_CHAIN.md`：**时序与决策链（详细版）** —— 每个时间窗、每个判断条件、两种待机（择机可中止 / 355 秒无条件）、中止原因词表、参数来源、已知不确定项。给 AI 与改代码的人看。
- `docs/ACC_ON_STOCK_CRUISE_PLAN.md`：**下一步研究方向** —— 在普通定速巡航上实现 ACC（"低配版 ACC"），含已具备基础与四项已知阻碍。
- `README.en.md`：英文说明。公开仓库以中文 `README.md` 为默认首页，英文版为 `README.en.md`。
- `tools/manage_c2_hca_r4_forced.py`：r3 至 r4 的固定哈希、停车安装、APK 与文件同步回滚、重启工具。
- `tools/review_hca_r4_logs.py`：只读复盘，逐次判定强制暂停之后是否出现 978 拒绝，并汇总择机首要阻挡原因。
- `tools/manage_c2_hca_r3_staged.py`：r2 至 r3 的固定哈希、停车安装、回退与重启工具。
- `tools/manage_c2_hca_r2_entry.py`：r1 + diag1 至 r2 的固定哈希、停车安装、回退与重启工具。
- `tools/manage_c2_hca_r1.py`：HCA-r1 固定哈希预检、停车安装、回退和重启工具。
- `docs/EPS_COMPARISON.md`：本车 5N1 APA-BS 与公开逆向的 1K0 ZF 方向机对照。
- `docs/EPS_TIMEOUT_AND_1100MS_CANDIDATE.md`：本车 EPS 超时的历史证据与 1.1 秒候选来源。
- `docs/R4_ROAD_REVIEW_20261003.md`：**第一个稳定版**路测复盘（3 小时 34 分、0 次断连、1.1 秒有效的论证与证据边界）。
- `docs/HCA_R4_FORCED_DEPLOYMENT_20261003.md`：350 秒提示 + 355 秒无条件强制暂停的部署与判定方法。
- `docs/HCA_R3_STAGED_DEPLOYMENT_20261003.md`：上一版分阶段择机部署记录。
- `docs/OPPORTUNISTIC_VARIANT.md`：低扭矩窗口候选的参数、行为和待讨论限制。
- `docs/STOCK_CRUISE_BUTTON_CONTROL.md`：Panda 模拟原车定速手柄以及地图预减速的可行性与限制。
- `docs/MAPS_AND_NAVIGATION.md`：区分屏幕导航、目的地搜索和 OSM 后台道路数据，并记录 API 关系。
- `tests/`：离线计时测试。
- `tools/`：接机识别、备份和后续部署工具。
- `tools/check_c2_hca_package.py` 与 `tools/manage_c2_hca_package.py`：只读预检，以及显式安装/回退工具。`tools/hold_c2_updates.py` 可在测试期间暂时停用自动更新并在回退后恢复。
- `device-backups/`：实际 C2 的原始备份；此目录不应上传到公共仓库。

## 基线与历史准备

2026-10-01 已通过 C2 的 SSH 确认实际分支为 `beta2_sharan2`，提交 `a6eed9e0c4d9a242db1e35978d2c32fe427491c7`（2023-01-02）。备份时 `interface.py` 有两处本机改动：Passat NMS 与 Sharan 的 `minSteerSpeed` 均由 50 km/h 改为 0。随后自动更新重新检出同一提交，设备现已恢复原版的 50 km/h 参数。之前推测的 `c6efa834` 不是当前运行版本；相关源码继续保留作参考。

实际代码已备份到 `device-backups/original-20261001/`。压缩包通过完整读取校验，包含 2,385 个条目和 131 个参数文件；目录仅允许当前用户、管理员与系统账户访问。详细记录见 `docs/C2_DEVICE_BASELINE.md`。

公开的 `deprecated-beta2` 与旧 `deprecated-release2` 都会在约 118 秒后仅撤销一帧 HCA。其发送频率为 50 Hz，因此待机大约只有 20 ms。`d2` 的计时结构已经变化，不能与旧分支共用未经适配的补丁。

`deprecated-beta2/c6` 的早期参考工作树保留两个默认关闭的互斥候选：固定版在累计 240 秒后进入 2 秒 standby；机会版从 240 秒开始等待低扭矩达 0.5 秒后暂停，需求升高时中止。实际设备的 `a6eed9e` 已单独适配并部署固定版；本地 V3 的机会策略另加入未来模型、车道条件和接管边界，不能把参考工作树直接用于实际设备。

组合候选 `codex/pq46-hca-cruise-candidate` 建立在固定 2 秒 HCA 版本之上，并增加原厂定速目标修整。它通过 `/data/pq46/stock_cruise_mode` 提供关闭、观察、单次测试和视觉前车自动修整四级模式；配置文件缺失时完全关闭。可重建补丁保存在 `candidate/patches/beta2-c6-hca-cruise/`。

`candidate/hca_reset_model.py` 是离线协议模型，不会向车辆发送报文，也不能直接复制到 C2。它用于验证：在 50 Hz 下，2.0 秒必须产生连续 100 帧 standby；短于阈值的自然零扭矩窗口不能被误判为已经完成计时复位。

## 接机顺序

1. C2 和电脑连接同一 Wi-Fi，在 C2 设置中启用 SSH。
2. 使用 `root` 用户和端口 `8022` 读取设备身份与提交号。
3. 运行 `tools/collect_c2_baseline.ps1`，流式备份完整 `/data/openpilot` 与 `/data/params`。
4. 核验压缩包、SHA-256、Volkswagen 文件和参数目录，再考虑设备专用补丁。

运行示例：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
& "D:\VWopenploot\tools\collect_c2_baseline.ps1" -C2Ip "<C2的IP>" -Port 8022 -User root -Destination "D:\VWopenploot\device-backups\new-baseline"
```

默认密钥路径为当前用户的 `.ssh/vwopenploot_c2_id_rsa`，也可以用 `-IdentityFile` 指定。备份脚本只读取 C2，压缩包包含私人参数，不应公开。

## 离线测试

```powershell
python -m unittest discover -s "D:\VWopenploot\tests" -v
```

当前 C2 运行 HCA-r2-entry 横向控制与 diag1 记录器；完整暂停效果尚待新的实车记录。未运行 `eon-neos` 系统刷写脚本。

## 开发协助

本项目的代码、文档与日志分析，是在以下 AI 编程助手的协助下完成的：

| 助手 | 参与部分 |
| --- | --- |
| **DeepSeek** | 状态机实现与重构、证据抽取工具、发布与审核流程 |
| **ChatGPT / Codex** | 仓库历史中大量早期提交的直接作者（`Codex <codex@local>`）、部署与回退工具、日志复盘脚本 |
| **Claude** | 最早期的接入阶段：协助完成 C2 的接入。C2 上车需要先用 VCDS 改编码，这一步不成立，后续研究无从开始 |

需要明确的是：**所有工程决策、实车测试与安全判断都由仓库作者做出并承担**。这些助手在作者指导下编写代码与文档，不是人类共同作者，也不对车辆行为负责。提交历史如实记录了哪些提交由助手直接产生。详见 [来源与归属](ATTRIBUTION.md)。
