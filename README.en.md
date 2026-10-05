# VWopenpilot — PQ46 / C2 HCA timer-reset research

**English** · [中文](README.md)

> ⚠️ **This project commands frames to a steering rack in a moving vehicle.** Read
> [SAFETY.md](SAFETY.md) before doing anything with it. It is not a consumer
> driver-assistance product. Prior art, upstream licences and development credits: [ATTRIBUTION.md](ATTRIBUTION.md).

## Why a comma two loses lane keeping after about six minutes

**The symptom.** The car's own lane keeping works indefinitely. The comma two's lane keeping gives up
after roughly **six minutes** — the cluster asks the driver to take over and lateral correction stops.
Cycling the cruise control buys another few minutes, then it happens again.

**Why.** The two send steering requests in fundamentally different ways.

- The stock lane-keep camera is an old one: it nudges the wheel briefly when the car is about to cross
  a line, and does **not** send control requests continuously.
- The comma two sends steering requests **continuously**.
- The Volkswagen steering-rack firmware has a hard limit: **continuous HCA requests may not exceed
  360 seconds** — exactly six minutes.

So the stock car's segmented control can never reach that limit, while the comma two's continuous
control always hits it. This is not a bug in openpilot; it is a conflict between the control style and
a firmware limit.

**The fix.** The same firmware carries a second rule: **interrupt the requests for one second or more
and the 360-second counter resets.**

So this project has the car, between 180 s and 300 s, pick a suitable straight stretch and
**deliberately stop steering for 1.1 seconds**, clearing the counter, then carry on normally.

The safety margin: **during those 1.1 seconds, anything that calls for the wheel — hands on the wheel,
a turn signal, the brake or throttle, a bend ahead, drifting off lane centre — makes the car resume
control immediately**, and it simply waits for the next suitable window. It is always "pause a little
later", never "force it".

**The result.** This version is now in **high-availability daily use** in my car: about 3 h 34 m,
roughly 60 reset cycles, **zero disconnections**; windows are typically found at 180–220 s; the driver
cannot feel the 1.1 seconds.

> **Conclusion: the "lane keeping drops out after a few minutes" problem is solved on this car**
> (2009 VW Magotan B6, `5N1 909 144 J` rack). Evidence grade: real vehicle, driver perception
> (~60 verified reset cycles, zero disconnections). The raw CAN trace from that drive was not
> retrieved; for frame-level confirmation see [`evidence/`](evidence/README.md).

> The 360 s limit and the one-second reset rule come from public reverse engineering of a VW rack
> ([I CAN Hack](https://icanhack.nl/blog/vw-part1/)) — **not** from this project. The 1.1 s figure comes
> from [opendbc #3129](https://github.com/commaai/opendbc/pull/3129). **What this project did is make it
> work on this specific car, find out why earlier attempts kept failing, and produce road evidence.**

### How to read this repository

- **Just want to understand it** → the section above is enough; for a little more, the
  [road review](docs/R4_ROAD_REVIEW_20261003.md)
- **Want the evidence** → [`evidence/`](evidence/README.md): the verdict rules and the slot for the
  decisive frame-level log
- **Want to change the code, or the origin of every threshold** → the
  [timeline and decision chain](docs/TIMELINE_AND_DECISION_CHAIN.md) (written for AI agents and for
  people editing the code; it is long)
- **Want to see what failure looks like** → the [V3](docs/V3_ROAD_REVIEW_20261002.md) and
  [r2](docs/HCA_R2_ROAD_REVIEW_LATEST.md) reviews

## A note on the project name

`VWopenploot` is a **typo** for `openpilot` — the author's slip when creating the directory, not a pun.

The GitHub repository is `vwopenpilot`. The local working directory `D:\VWopenploot`, the Android
overlay package name `nl.vwopenploot.probe`, and paths quoted inside the older documents keep the
original spelling. None of that changes behaviour: an Android package name is fixed when the APK is
installed, so renaming it would mean shipping a different app, and renaming local paths buys nothing.
Every path quoted in these documents refers to a directory that really exists under the name shown.

Current release: **`stable-1-hca-r4-forced`** — a 2009 VW Magotan B6 (PQ46), EA888 2.0T / DQ250
with **plain cruise control** (no ACC radar), running Dragonpilot on a comma two.

## The problem

After a few minutes of continuous lane keeping the car gives up: the cluster asks the driver to
take over and lateral correction stops. Re-engaging cruise restores it for another few minutes.

The cause is in the steering rack, not in openpilot. An EPS racks counts how long HCA (lane
keep) requests have been active, and once that counter reaches its limit the rack refuses
further requests. The counter can be cleared by putting HCA into standby for long enough.

This vehicle's rack is `5N1 909 144 J` / `J500__APA-BS KL.089 0503`.

## What this project does

It resets that counter **purely in software**, by having the car controller command a short HCA
standby burst. No EPS firmware is flashed, ABS is untouched, and the Panda safety policy is
unchanged. The rack keeps its own power assist throughout — only active lane centering pauses.

| Time | Behaviour |
| --- | --- |
| 0–180 s | normal control |
| 180–300 s | look for a suitable window, then command 1.1 s of standby (55 frames at 50 Hz) |
| 300–350 s | three-second countdown, then execute the reservation |
| 350 s | prompt the driver only — **never** a soft disable, or the fallback below could never run |
| 355 s | **unconditional** 1.1 s standby, ignoring every entry, geometry, driver-input and saturation gate |
| 356.1 s | local counter resets, control continues — no soft disable |
| 400 s | insurance soft disable, unreachable on the normal path |

Opportunistic and forced completions are counted separately (`completed` vs `forced_completed`)
so the window-search success rate is never contaminated by the fallback.

## Prior art — the mechanism is not this project's discovery

| Finding | Source | What this project did |
| --- | --- | --- |
| A PQ rack refuses after roughly 360 s of accumulated HCA requests, and about 1 s of standby resets the counter | Willem Melching / [I CAN Hack](https://icanhack.nl/blog/vw-part1/), reverse engineering a `1K0 909 144 E` (ZF) rack from a 2010 Golf Mk6. The firmware compares a 100 Hz counter against the constant `36000` — "exactly our 6 minute timer" — and only resets after the standby counter reaches 100 (1 s). That firmware also carries `MIN_SPEED` = 50 km/h, an internal rack limit below which HCA is forced off | **Not copied.** This car's rack is a `5N1 909 144 J` (APA-BS), a different part family from a different source at a different G85 location. The ~360 s figure was re-derived independently from this car's own historical rejection log |
| The reset window is **1.1 s** | [commaai/opendbc PR #3129](https://github.com/commaai/opendbc/pull/3129) by **Dennis-NL** (Porsche Macan / Audi Q5, 10,000 km). The PR was closed **without being merged**; the maintainer agreed the concept was sound but asked for a different implementation shape, and laid out a five-step plan | First road validation on a **5N1 / PQ46** car: about 3 h 34 m, roughly 60 cycles, zero disconnections |

**Where that upstream plan stands (checked 2026):** step 1 — [commaai/opendbc #3160](https://github.com/commaai/opendbc/pull/3160),
"Refactor HCA mitigation into standalone class" — **was merged**. Step 2, the actual timer-reset
logic, has **not** landed: current opendbc master's `HCAMitigation` still only does the
same-torque single-frame nudge, and `values.py` carries `STEER_TIME_STUCK_TORQUE = 1.9` with no
reset constant. Step 3, the `steerTimeLimit` alert ([#1315](https://github.com/commaai/opendbc/issues/1315)),
is still open.

So this is not a copy of merged upstream code. It is an independent implementation, on a vehicle
upstream does not cover, of a concept the maintainer accepted in principle but that was never merged.

## Result and its evidence grade

**2026-10-03, about 3 h 34 m of driving: roughly 60 reset cycles, zero loss of assist.** Windows
were typically found at 180–220 s, occasionally 250–300+ s, and never past 300 s — so the 355 s
fallback was never exercised on the road.

The rack's counter accumulates across cycles while this project's local counter resets each cycle,
so the two only agree if the standby really resets the rack. Had 1.1 s been insufficient, the
counter would have reached ~360 s during the **second** cycle — a refusal within about six minutes
of setting off, then roughly every three minutes. That is exactly the original symptom. Sixty
cycles without one is therefore about sixty successful resets rather than one.

**Evidence grade: driver perception only.** That drive left no trace, so there are no raw
`Lenkhilfe_2` (978) frames and no software counters behind it. See
[`docs/R4_ROAD_REVIEW_20261003.md`](docs/R4_ROAD_REVIEW_20261003.md) for the full reasoning and
its limits. Frame-level evidence is deliberately left as an open slot — see `evidence/`.

## The finding upstream does not have

The window-search failures in the earlier versions had one dominant cause: aborting a pause as
soon as a **single** frame's requested torque exceeded 90 (out of 300). On this car the model can
call a road straight while the controller still asks for real torque, so that gate discarded large
amounts of usable road. Replacing it with "sustained saturation — 0.2 s continuously at or above
270" moved the opportunistic success rate from 0–25% (3/12, 0/3, 0/6 across three earlier road
tests) to essentially every cycle. 1.1 s compounds this: the shorter pause is far easier to fit
into a window, and the driver cannot feel it.

## Repository layout

- `candidate/` — per-version packages: deploy payloads, rollback payloads and pinned hashes
- `candidate/patches/` — rebuildable patches for the Dragonpilot reference trees
- `docs/` — deployment records and road reviews (**Chinese**)
- `tools/` — device management, log review and evidence extraction
- `tests/` — offline scheduler, installer and geometry tests
- `evidence/` — the slot for frame-level road evidence

## Deep documentation is in Chinese

The detailed material — deployment records, road reviews, the EPS comparison, the cruise-button
probe results — is written in Chinese and deliberately kept in full, including failures. Each
document separates three different kinds of success:

> **installed ≠ software counter completed ≠ the vehicle actually behaved differently**

A failed road test is recorded as a failure. `docs/R4_ROAD_REVIEW_20261003.md` is the current
stable release; `docs/V3_ROAD_REVIEW_20261002.md` and `docs/HCA_R2_ROAD_REVIEW_LATEST.md` are the
failures that led to it.

## Next research direction: ACC-like behaviour on plain cruise control

**In progress, no implementation, nothing deployed.** This car has no ACC radar; the goal is to
obtain ACC-like speed adaptation by having the comma two simulate the stock cruise stalk
(`GRA_Neu`, `0x38A`) and trim the set speed in response to the vision lead vehicle. Plan and known
blockers: [`docs/ACC_ON_STOCK_CRUISE_PLAN.md`](docs/ACC_ON_STOCK_CRUISE_PLAN.md).

Two limits are already established and matter:

- **No braking.** Stock cruise reduces speed by cutting engine torque only. Downhill it cannot
  hold a target, and it cannot respond to a braking lead vehicle.
- **The rack's own low-speed limit.** The 1K0 firmware carries an internal `MIN_SPEED` of
  50 km/h below which HCA is forced off, and this car loses lateral control around 50–55 km/h.
  If the 5N1 rack behaves the same way, no low-speed lateral assistance is possible without
  flashing the rack — which this project will not do. That makes "low-end ACC" a roughly 60 km/h
  and above comfort feature, not a city feature.

## Credits

The code, documentation and log analysis in this project were produced with the assistance of AI
coding assistants:

| Assistant | Contribution |
| --- | --- |
| **DeepSeek** | State machine implementation and refactoring, the evidence-extraction tool, and the release and review workflow |
| **ChatGPT / Codex** | Direct author of many earlier commits (see `Codex <codex@local>` in the history), the deploy/rollback tooling and the log-review scripts |
| **Claude** | The earliest integration stage: helping get the comma two connected at all. Connecting it required VCDS coding changes; without that, none of the later research was possible |

To be explicit: **every engineering decision, every on-car test and every safety judgement was made
by, and is the responsibility of, the repository owner.** The assistants wrote code and documentation
under that direction; they are not human co-authors and are not responsible for vehicle behaviour.
The commit history records which commits were produced directly by an assistant. See
[ATTRIBUTION.md](ATTRIBUTION.md).

## Safety

Read [SAFETY.md](SAFETY.md). Short version: supervised driving only, hands on the wheel, foot over
the brake. Every timing and threshold here was measured on **one specific car** and must not be
assumed valid for another. No affiliation with or endorsement from comma.ai, Dragonpilot,
Volkswagen, ZF or VW Braunschweig.
