# HCA 待机复位候选补丁计划

## 第一阶段范围

只验证“正常 standby 是否能清除目标 5N1/0503 的持续 HCA 计时”。候选时序为累计 240 秒后发送连续 2.0 秒 standby。2.0 秒是验证参数，不是已经测得的目标 EPS 最短复位时间。

第一阶段不改以下内容：车型 fingerprint、方向机固件、最低速度、转向最大扭矩、Panda 安全策略、ABS、油门或制动控制。

## 报文行为

进入候选复位时，C2 继续运行感知、车辆状态解析和 CAN 周期任务。仅 Volkswagen 转向报文进入正常 standby：HCA inactive，输出转向扭矩为零。不能用 `sleep(2)` 阻塞控制线程，也不能停止整个 CAN 发送进程。

50 Hz 下 2.0 秒对应连续 100 个转向报文；若实际版本使用其他频率，必须按其 `HCA_STEP` / `STEER_STEP` 和控制周期重新计算。

## 候选代码结构

根据设备界面信息，当前最可能的实际基线已经缩小为 `deprecated-beta2` 头提交 `c6efa834...`。该分支仍保留 118 秒单帧撤销逻辑，同时已经包含 Passat NMS 与 Sharan 两个 PQ 车型定义。工程仍保留下面两类结构说明，以便识别设备上的私人修改。

### deprecated-beta2/c6 的两个验证候选

- 固定版：累计 240 秒后直接发送 2.0 秒 standby，用于最简单、结果最明确的机制验证。
- 机会版：累计 240 秒后等待输出扭矩低于最大值 20% 并持续 0.5 秒，再发送 2.0 秒 standby；standby 中模型原始转向需求升高则中止。

两个版本互斥且默认关闭。机会版在持续高扭矩、始终找不到窗口时不会固定切断；350 秒内部提示标志尚未接入 2023 Dragonpilot 的用户事件系统。

### deprecated-release2

- 字段：`hcaEnabledFrameCount`、`hcaSameTorqueCount`。
- 原行为：约 118 秒后 `hcaEnabled=False` 一帧，然后立即把本地计数清零。
- 适配方向：把单帧事件改为显式 reset 状态；reset 期间对外发送 standby 和零扭矩；完成后同时处理 `apply_steer_last`，避免恢复时内部限幅状态与实际输出不一致。

### d2

- 字段：`hca_frame_timer_running`、`hca_frame_same_torque`、`eps_timer_soft_disable_alert`。
- 原行为：零输出即清本地持续计时，接近时限触发提示。
- 适配方向：区分“短暂零输出”与“已完成长 standby”；短于验证阈值的零输出不能直接当成目标 EPS 已复位。

## 离线通过条件

- 50 Hz 时连续输出恰好至少 100 帧 standby。
- reset 期间输出扭矩始终为零。
- 0.5 秒自然零扭矩不会清除累计计时。
- 2.0 秒连续自然 standby 可以清除模型累计计时。
- latActive 取消后状态清零。
- 在 20、50、100 Hz 下持续时间换算一致。
- 源码可以编译，原有 Volkswagen 测试无回归。

## 设备到手后才执行

1. 对实际工作区做完整备份和 SHA256 清单。
2. 对比实际 `carcontroller.py`、`pqcan.py`、`values.py` 与两个公开候选族。
3. 生成仅针对实际提交的单独 Git commit 和反向补丁。
4. 在车辆断开时完成导入、编译和进程启动检查。
5. 先记录原始退出事件，再做台架或封闭环境机制验证。
