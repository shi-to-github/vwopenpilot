# 来源与归属 / Attribution

> **先说清楚：本项目的核心机制不是本项目发现的。**
> "约 360 秒超时 + 约 1 秒 standby 复位"来自 Willem Melching / [I CAN Hack](https://icanhack.nl/blog/vw-part1/) 对 `1K0 909 144 E`（ZF）的逆向；
> "1.1 秒复位窗口"来自 [commaai/opendbc PR #3129](https://github.com/commaai/opendbc/pull/3129)（**Dennis-NL**，Porsche Macan / Audi Q5，10,000 km）的 PQ / MLB 车系结论。
> 本项目的贡献是**适配到本车**（`5N1 909 144 J` / APA-BS，与 1K0 不是同一款）、**定位择机失败的真实瓶颈**、以及**实车证据**。
> 详见 README 的"先行工作与本文贡献"。
>
> **上游现状（2026 年核查）**：#3129 被维护者以"概念成立、实现形态需重构"关闭且未合并，并给出五步计划。第 1 步 [opendbc #3160](https://github.com/commaai/opendbc/pull/3160) 已合并；**第 2 步的 1.1 秒复位逻辑尚未合入**（当前 master 的 `HCAMitigation` 仍只做"同扭矩超时后单帧 −1"，无复位时长常量）。因此本项目并非复制上游已合并代码。

## 开发协助 / Development assistance

本项目的代码、文档与日志分析，是在以下 AI 编程助手的协助下完成的：

| 助手 | 参与部分 |
| --- | --- |
| **DeepSeek** | 状态机实现与重构、证据抽取工具、发布与审核流程 |
| **ChatGPT / Codex** | 仓库历史中大量早期提交的直接作者（`Codex <codex@local>`）、部署与回退工具、日志复盘脚本 |
| **Claude** | 最早期的接入阶段：协助完成 C2 的接入。C2 上车需要先用 VCDS 改编码，这一步不成立，后续研究无从开始 |

需要明确的是：**所有工程决策、实车测试与安全判断都由仓库作者做出并承担**。这些助手在作者指导下编写代码与文档，不是人类共同作者，也不对车辆行为负责。提交历史如实记录了哪些提交由助手直接产生。

The code, documentation and log analysis in this project were produced with the assistance of AI
coding assistants: **DeepSeek** (state machine implementation and refactoring, the evidence
extraction tool, the release and review workflow), **ChatGPT / Codex** (direct author of many early
commits — see `Codex <codex@local>` in the history — plus the deploy/rollback tooling and the
log-review scripts) and **Claude** (the earliest integration stage — helping get the comma two
connected, which required VCDS coding; without it none of the later work was possible).

**Every engineering decision, every on-car test and every safety judgement was made by, and is the
responsibility of, the repository owner.** The assistants wrote code and documentation under that
direction; they are not human co-authors and are not responsible for vehicle behaviour.

---

本项目的补丁、参考实现与对照结论建立在一批公开项目之上。`vendor/` 下的上游源码树**不在本仓库中重新分发**，以下为来源与固定提交（详见 `docs/SOURCE_PINS.md`）。

| 用途 | 上游 | 固定提交 / 版本 | 许可 |
| --- | --- | --- | --- |
| 旧 C2 参考源码 | [dragonpilot/dragonpilot](https://github.com/dragonpilot/dragonpilot) `deprecated-release2` | `1415631d` | MIT |
| 较新 C2 参考源码 | 同上 `deprecated-beta2` | `c6efa834` | MIT |
| 实际设备基线 | 同上 `beta2_sharan2` | `a6eed9e0` | MIT |
| 后期 C2 参考源码 | 同上 `d2` | `f965f86f` | MIT |
| 1.1 秒公开候选实现 | [commaai/opendbc PR #3129](https://github.com/commaai/opendbc/pull/3129)（**Dennis-NL**，Porsche Macan / Audi Q5，10,000 km） | `26612601` | MIT |
| 该方案的重构步骤（已合并） | [commaai/opendbc #3160](https://github.com/commaai/opendbc/pull/3160)（jyoung8607） | 已合并 | MIT |
| `steerTimeLimit` 告警（计划第 3 步，未完成） | [commaai/opendbc #1315](https://github.com/commaai/opendbc/issues/1315) | 未完成 | — |
| 1K0 方向机固件逆向研究 | [I-CAN-hack/pq-flasher](https://github.com/I-CAN-hack/pq-flasher) | `95d28307` | 见上游 |
| C2 系统级恢复工具 | [commaai/eon-neos](https://github.com/commaai/eon-neos) | `8f12ec71` | 见上游 |
| 原厂巡航按钮调速参考 | [openpilotkr/openpilot](https://github.com/openpilotkr/openpilot) `OPKR` | `3ff6dc6` | 见上游 |
| 逆向研究背景 | [I CAN Hack 系列](https://icanhack.nl/blog/vw-part1/)（Willem Melching） | — | 见原文 |

`candidate/patches/` 下的补丁是对 Dragonpilot（MIT，源自 openpilot）源代码的增量修改，因此保留其 MIT 许可与版权归属。Dragonpilot 与 openpilot 的版权归各自作者所有。

本项目其余代码与文档由本仓库作者编写。

---

Patches under `candidate/patches/` are incremental modifications of Dragonpilot source (MIT, itself derived from openpilot), so upstream MIT terms and copyright attribution apply to those portions. The timer mechanism and the 1.1 s window are **not** this project's discovery -- see the prior-art section of the README.
