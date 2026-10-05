# 帧级道路证据插槽 / Evidence slot

**English** · [中文](#中文)

## English

This directory is the drop-in point for **frame-level road evidence**. It is currently **empty**:
the published stable release rests on driver-perception evidence only, and this slot exists so that
gap can be closed without re-interpreting anything else.

### What belongs here

The **compact evidence bundle**, not the raw traces. Raw `v3-*.jsonl` traces run to hundreds of
megabytes per 30 minutes and are not published. Produce the bundle with:

```bash
python tools/extract_hca_evidence.py <trace.jsonl> [more.jsonl ...] --out evidence
```

That writes exactly two files:

| File | Contents |
| --- | --- |
| `hca-windows.jsonl` | every scheduler counter change in the trace, plus the raw 978 `Lenkhilfe_2` HCA status frames inside each pause window |
| `manifest.json` | each source file's name, size and **SHA-256**, whole-trace EPS status histogram, per-pause verdicts, and refusals seen outside any pause |

### What it has to settle

The open question is whether 1.1 s of HCA standby actually resets this rack's counter. The decisive
observation is what the rack reports **after** a completed standby pause, while openpilot keeps
commanding lane keeping:

- `eps_hca_status` **2 or 4** (refused) shortly after a pause resumes → the standby was too short
- no refusal while the cycle runs past ~360 s of accumulated active time → the standby was effective

`manifest.json` carries one `verdict` per pause (`insufficient_standby` /
`no_refusal_in_window`) using that rule, and also lists refusals that happen outside any pause —
those are the original ~360 s hardware timeouts still occurring.

### Provenance and privacy

`manifest.json` records the SHA-256 of every source trace, so a reader can verify that a bundle
came from the raw log it claims to come from, without that log being published. The extractor emits
only whitelisted fields (EPS status, timestamps, scheduler counters); driver inputs, lead-vehicle
data and everything else are dropped.

### Honesty clause

`no_refusal_in_window` means **no refusal was observed in that window**. It is not a claim of
safety, and it does not by itself prove the rack's internal counter was reset.

---

## 中文

这个目录是**帧级道路证据**的投放位置。**目前是空的**：已发布的稳定版只有驾驶员感知级证据，
留出这个插槽是为了在不牵动其它结论的前提下补上那块空白。

### 放什么

放**压缩后的证据包**，不要放原始日志。原始 `v3-*.jsonl` 每 30 分钟就有几百 MB，不予发布。
用以下命令生成：

```bash
python tools/extract_hca_evidence.py <trace.jsonl> [更多.jsonl ...] --out evidence
```

只会产出两个文件：

| 文件 | 内容 |
| --- | --- |
| `hca-windows.jsonl` | 全段所有调度计数器变化，以及每个暂停窗口内 978 `Lenkhilfe_2` 的原始 HCA 状态帧 |
| `manifest.json` | 每个源文件的名称、大小与 **SHA-256**，全段 EPS 状态直方图，逐次暂停的判定，以及暂停之外出现的拒绝 |

### 它能钉死什么

悬而未决的问题是：1.1 秒的 HCA standby 到底有没有复位本车方向机的计数器。决定性观测是
**一次 standby 暂停完成之后、openpilot 仍在持续请求横向控制时**，方向机报什么状态：

- 暂停恢复后不久出现 `eps_hca_status` **2 或 4**（拒绝）→ 说明 standby 太短
- 累计激活时间跑过约 360 秒仍无拒绝 → 说明 standby 有效

`manifest.json` 会按该规则给出每次暂停的 `verdict`（`insufficient_standby` /
`no_refusal_in_window`），并单列**发生在任何暂停之外**的拒绝 —— 那是原来那个约 360 秒硬件超时。

### 来源可追溯与隐私

`manifest.json` 记录每个原始日志的 SHA-256，因此读者可以验证"这份证据包确实出自它声称的那段
日志"，而无需发布日志本身。提取工具只输出白名单字段（EPS 状态、时间戳、调度计数器），
驾驶员输入、前车数据等全部丢弃。

### 诚实条款

`no_refusal_in_window` 的含义是"**该窗口内未观察到拒绝**"，不是安全声明，也不能单独证明
方向机内部计数器已被复位。
