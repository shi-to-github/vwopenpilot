# 时序与决策链（详细版）

> **这份文档是给 AI / 代理 / 要改代码的人看的。** 人类读者只需要 README 开头的「起因 · 经过 · 结果」。
> 本文描述的是**已部署在车上的 `hca-r4-forced`** 状态机；源文件
> `candidate/device-a6eed9e-v3-hca-r4-forced/deploy/hca_timer_reset.py` 是唯一权威，本文与它不一致时以源码为准。

## 0. 为什么需要状态机

方向机固件对"**连续** HCA 请求"计时，累计到约 360 秒即拒绝继续执行。本项目的全部逻辑就是：
在计时撞线之前，主动制造一次 **≥1 秒的连续 standby**，让固件把计时器清零，然后继续正常控制。

由此产生唯一一个真正困难的问题：**什么时候停止这 1.1 秒是安全的。** 状态机的每一处判断都服务于它。

## 1. 时间轴总览

| 区间 | 帧数（50 Hz） | 相位 `phase` | 行为 | 控制是否在输出 |
| --- | --- | --- | --- | --- |
| 0–180 s | 0–9000 | `active` | 正常横向控制，不寻找窗口 | ✅ 是 |
| 180–300 s | 9000–15000 | `seeking` | 寻找窗口，条件满足即执行 1.1 s 暂停 | ✅ 是（除暂停的 1.1 s） |
| 300–350 s | 15000–17500 | `late_seeking` → `awaiting_notice` → `countdown` | 三秒倒数预约；倒数期间**仍在控制** | ✅ 是（倒数期间也是） |
| 350–355 s | 17500–17750 | `forced_prompt` | **只提示**"准备接管 + 5 秒后强制暂停" | ✅ 是 |
| 355 s | 17750 | `forced_standby` | **无条件**连发 55 帧 standby | ❌ 暂停中 |
| 356.1 s | 17805 | `forced_reset_complete` | 本地计时清零，继续正常控制 | ✅ 是 |
| 400 s | 20000 | `takeover_required` | 纯保险软退出；正常路径到不了 | — |

关键常数（`HcaTimerReset.__init__`，`message_hz = 50`）：

| 常数 | 秒 | 帧 | 含义 |
| --- | --- | --- | --- |
| `seek` | 180 | 9000 | 开始寻找窗口 |
| `warn` | 300 | 15000 | 进入"三段倒数"阶段 |
| `prompt` | 350 | 17500 | 只提示，不软退出 |
| `forced` | 355 | 17750 | 无条件强制暂停 |
| `backstop` | 400 | 20000 | 纯保险软退出 |
| `required`（standby） | 1.1 | 55 | 一次待机的帧数 |
| `notice_required` | 3 | 150 | 倒数长度 |
| `quiet_required` | 0.75 | 38 | 条件须连续满足的确认时长 |
| `retry_required` | 5 | 250 | 中止后的退避 |
| `threshold` | — | 90 | 入场/执行扭矩门限（300 的 30%） |
| `saturation_threshold` | — | 270 | 持续饱和中止门限（300 的 90%） |
| `saturation_required` | 0.2 | 10 | 饱和须持续多久才中止 |

## 2. 两种待机，行为完全不同（**最容易搞错的一点**）

### 2.1 择机暂停 —— 每一帧都重新判断，随时可中止

源码 `update()` 的 standby 分支（`if self.standby:` → `if self.forced_active:` 之后）：

```
每帧检查，命中任一条件立即 abort()，并在**同一帧**恢复正常转向输出（emit(safe_output, enabled)）
```

| 中止条件 | `last_abort_reason` | 说明 |
| --- | --- | --- |
| 驾驶员输入 | `driver_steering` / `left_blinker` / `right_blinker` / `brake` / `gas` / `can_invalid` | 只踩刹车、打灯、摸方向盘都会立刻中止 |
| 扭矩值非法 | `nonfinite_torque` | NaN / inf 保护 |
| 请求持续饱和 | `sustained_saturation` | 原始请求 ≥270 且**持续 0.2 秒**才中止（单帧尖峰不中止） |
| 道路/模型条件变差 | `model_stale` / `future_turn_demand` / `lane_center_error` / `lane_margin_or_confidence` / `lane_change_or_turn` / `outward_center_motion` / `projected_center_margin` / `motion_history_missing` | 由 `pq46_runtime.motion_gate(continuing=True)` 给出 |
| 兜底时限 | `deadline` | 400 秒保险，正常路径不可达 |

中止后 `retry = 250 帧（5 秒）`，即**等 5 秒再找下一次机会**；中止不清零 `elapsed`（累计计时继续走）。

### 2.2 355 秒强制暂停 —— 无任何中止条件

```
if self.forced_active:
    self.standby += 1
    return self.emit(0, False, planned=True, forced=True)
```

不检查几何、不检查预测、不检查驾驶员输入、不检查饱和。**唯一能提前结束它的，是真正的断开横向接合**
（`lat_active=False`，走上面的 `not lat_active` 分支，计入 `forced_aborted` 并在下一周期重试）。

这是刻意的：兜底存在的意义就是"保证每轮至少有一次完整的 1.1 秒样本送到方向机"。
这条分支在 2026-10-03 那次 3 小时 34 分的行程里**一次都没有触发过**（择机全在 300 秒前成功）。

## 3. 择机阶段的完整决策链

`update()` 在 `seeking` / `late_seeking` 阶段的 `reason` 判定，**按顺序**取第一个命中项 ——
它同时是"为什么这次没能启动"的日志字段 `start_block_reason`：

| 顺序 | 条件 | `start_block_reason` | 备注 |
| --- | --- | --- | --- |
| 1 | 到保险时限 | `deadline` | 400 秒，正常不可达 |
| 2 | 还没到 180 秒 | `before_seek` | |
| 3 | 驾驶员在操作 | `driver_steering` 等 | |
| 4 | 扭矩非法 | `nonfinite_torque` | |
| 5 | 上次中止的 5 秒退避未过 | `retry_backoff` | |
| 6 | 窗口不合格 | `future_turn_demand` / `lane_center_error` / … / `prediction_gate` | 300 秒前用当前预测，之后用"三秒后"的预测 |
| 7 | 300 秒后界面/音频不可用 | `notice_ui_unavailable` | 系统静音时不会执行"无声的晚期暂停" |
| 8 | 300 秒前请求过高 | `entry_demand_high` | `|raw| > 90` 或 `|limited| > 90` |
| 9 | 剩余时间不够 | `insufficient_time_for_reset` | `elapsed + 55 + 200 ≥ 17500` → 约 **344.9 秒**后不再新开预约 |
| — | 以上都不命中 | `''`，`confirming_window` | `quiet` 累加，连续 0.75 秒即执行 |

计时到 `quiet_required`（0.75 秒）后分两路：

- **300 秒前** → 直接 `begin_pause()`，进入择机暂停（2.1 节）。
- **300 秒后** → 不直接暂停，而是**创建预约**：`notice_id` = `<origin>-<n>`，相位 `awaiting_notice`。
  然后：
  1. 悬浮窗播放短提示音并回传 → `countdown` 开始；
  2. 倒数取 `max(剩余帧, 3 秒 − 已过去时间)`，即**帧数与墙钟同时满足**，防止快跑；
  3. 倒数期间**横向控制一直在输出**（倒数不是暂停）；
  4. 1 秒内没有回传 → `cancel_notice('notice_not_delivered')`；界面/音频不可用 → `notice_ui_unavailable`；
     预约窗口变化 → `cancel_notice(delayed_reason 或 'reserved_window_changed')`；
  5. 倒数结束的那一刻再复核一次：`window_ok` 且 `|raw| ≤ 90` 且 `|limited| ≤ 90` 才真正 `begin_pause()`，
     否则 `cancel_notice(window_reason 或 'execution_window_changed')`。

**这套"300 秒后改为预约 + 三秒倒数"的设计意图**：越接近时限越不能碰运气，所以要提前告知驾驶员、
并给一个可取消的窗口，而不是在最后一刻静默地在弯道里停 1.1 秒。

## 4. 计数器与它们的含义

| 计数器 | 何时 +1 | 说明 |
| --- | --- | --- |
| `completed` | **择机**暂停恰好跑满 55 帧 | 择机成功率的唯一依据 |
| `forced_completed` | **355 秒强制**暂停跑满 55 帧 | 与择机分开统计，互不污染 |
| `aborted` | 择机暂停被中止 | 配合 `last_abort_reason` |
| `forced_aborted` | 强制暂停被真正的断开打断 | 正常路径应为 0 |
| `natural_resets` | 连续 55 帧自然失活 | 含人工接管后的失活，**不等于**择机成功 |
| `forced_prompts` | 350 秒提示发出一次 | 每周期至多 1 |
| `notice_cancelled` | 预约被取消 | 配合 `last_abort_reason` |
| `cycle` | 每次暂停完成 | 从 1 开始 |
| `off_frames` / `off_s` | 连续 disabled 帧 | 是**命令**时长，不是方向机计时 |

> **必须反复强调**：`completed` / `forced_completed` 只证明"程序打算并且确实发送了 55 帧 standby"，
> **不证明方向机内部计时器被清零**。判定只能看 978 `Lenkhilfe_2` 的原始状态 —— 见
> `evidence/README.md` 与 `tools/review_hca_r4_logs.py`。

## 5. 参数来源（每个数字都不是拍脑袋）

| 参数 | 取值 | 来源 |
| --- | --- | --- |
| 360 秒上限 | — | Willem Melching 对 1K0 方向机固件的逆向：常量 `36000` @ 100 Hz |
| 中断 ≥1 秒归零 | 1 s | 同一份逆向：`HCA_TIMER_03` 到 100 才复位 |
| 本项目取 1.1 秒 | 55 帧 | opendbc PR #3129（PQ/MLB 车系）；本车实测有效 |
| 180 秒开始找 | 9000 帧 | 经验值：留出足够冗余，又不至于太早反复停 |
| 300 秒进入倒数 | 15000 帧 | 同上，给驾驶员留反应时间 |
| 350 秒只提示 | 17500 帧 | r4 改动：**不能软退出**，否则 355 秒兜底永远不会发生 |
| 355 秒强制 | 17750 帧 | 为"择机全失败"准备的确定性样本 |
| 400 秒保险 | 20000 帧 | 纯保险，正常不可达 |
| 90 入场门限 | 30% | r1 起沿用 |
| 270 持续中止 | 90% × 0.2 秒 | **r3 起的关键修正**：取消"单帧 90 即中止"，改为持续饱和才中止 |

## 6. r1 → r4 的关键演化（为什么之前老是失败）

| 版本 | 择机尝试 | 完整完成 | 主要中止原因 |
| --- | ---: | ---: | --- |
| V3 | 3 | 0 | 0.16–0.42 秒即中止 |
| hca-r1 | 12 | 3 | 8 次 `large_raw_demand`（单帧请求 >90） |
| r1-diag1 | 3 | 0 | 2 次 `large_raw_demand`，1 次 `future_turn_demand` |
| r2-entry | 6 | 0 | **6 次全部** `large_raw_demand` |
| **r4-forced** | ~60 | 近乎全部 | — |

**结论**：真正的瓶颈不是"找不到直路"，而是"**单帧请求超过 90 就中止**"这条门限过于激进。
模型认为直行并不等于控制器请求低（30 秒长窗口内发出扭矩中位数 33、最大 129）。
改成"持续 0.2 秒达到 270 才中止"后成功率接近 100%。这条发现上游没有。

## 7. 已知不确定项

1. **1.1 秒是否足够复位本车方向机** —— 仅有驾驶员感知级证据（3 小时 34 分、约 60 轮、0 断连），
   该段行程日志未取回，无 978 帧级复核。`evidence/` 就是为补这一项留的插槽。
2. **本车 5N1 是否与逆向的 1K0 同构** —— 零件族、制造来源、G85 布置都不同，360 秒这个值在本车是
   用历史日志**独立定位**出来的，不是照搬。
3. **355 秒强制分支未在道路上验证过** —— 它从未触发。
4. **低速门槛归属** —— 1K0 固件内有 `MIN_SPEED = 50 km/h`，本车约 50–55 km/h 以下横向不可用，
   但**无法区分**是 openpilot 的 `minSteerSpeed` 参数还是方向机自身限制。
5. **"原车是分段控制"是推断，不是抓包结论** —— 已确证的事实是"原车车道保持能一直用、C2 必在约
   360 秒失效"，以及"固件只对**连续**请求计时、中断 ≥1 秒即归零"。由此推出"原车摄像头是短促纠偏、
   不连续发送"是合理推断，但本项目**没有抓过原车车道保持摄像头自己的帧**来直接证实这一点。

## 8. 验证这套逻辑的命令

```bash
# 离线：状态机行为（15 项，覆盖 350 不软退出、355 无条件、恰好 55 帧、强制不污染择机统计、时钟跳变）
python -m unittest tests.test_c2_hca_r4_forced -v

# 行驶日志：逐次判定强制/择机暂停之后是否出现 978 拒绝
python tools/review_hca_r4_logs.py <trace.jsonl> [--json out.json]

# 行驶日志 → 可发布的小体积证据包
python tools/extract_hca_evidence.py <trace.jsonl> --out evidence

# 设备状态（只读）
python tools/manage_c2_hca_r4_forced.py --ip <IP> --action status
```

## 9. 相关文档

- README 开头的「起因 · 经过 · 结果」——**人类入口**
- `candidate/device-a6eed9e-v3-hca-r4-forced/deploy/hca_timer_reset.py` ——**唯一权威源码**
- `docs/EPS_TIMEOUT_AND_1100MS_CANDIDATE.md` —— 360 秒在本车上的定位过程
- `docs/EPS_COMPARISON.md` —— 为什么 1K0 的结论对本车只是线索
- `docs/R4_ROAD_REVIEW_20261003.md` —— 稳定版路测与证据边界
- `evidence/README.md` —— 帧级证据插槽与判定规则
