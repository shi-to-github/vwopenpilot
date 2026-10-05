# HCA-r1 横向择机修正已部署

2026-10-02，用户明确要求制作并刷入。使用已固定 SSH 身份连接 `<C2-IP>:8022`。完成本地实现、测试、停车检查、三文件升级、重启和真实运行验证。原 V3、V2 及其回退文件继续保留。

## 改动

独立包目录 `candidate/device-a6eed9e-v3-hca-r1/`，只替换三个 Python 源文件，未刷 NEOS、EPS 或 Panda 固件：

| 文件 | 已部署 SHA-256 |
| --- | --- |
| carcontroller.py | `467e466239c5141321409d03dfde13ffe20af01e168fb3a35179f994ee330902` |
| hca_timer_reset.py | `cf5bbf939e230ba9d68343ca1092ccc5524443368eef0745ea1300e3afc692a2` |
| pq46_runtime.py | `e126851c84443785d572c49b7163f7ff0b8c0d8900d2783f9908d559f666807d` |

180 秒开始寻找，低扭矩启动门限由 10% 改为候选 20%；暂停中大的原始请求超过 30% 会立即中止。车道中心启动/中止边界分别为 0.25/0.35 m，并增加中心位置估算变化速率和按剩余暂停时长外推的边界检查。保留未来弯道、置信度、车道余量、换道/转弯意图、驾驶员输入和数据有效性检查。

控制器连续输出 HCA 关闭指令 100 帧（50 Hz，2 秒）才清空本地计时，短失活/中止不清零。计数是软件输出记录，不是 EPS 内部复位确认。240 秒接管兜底保留，临近兜底而无时间完成两秒时不启动暂停。恢复转向仍通过原有变化率与驾驶员扭矩限幅。

新日志记录原始/限幅/输出请求、HCA 使能、搜索/中止原因、已输出关闭时长、车道几何与变化速率、驾驶员扭矩/操作等。按钮界面、调速源文件、低速门限、底层安全策略沿用 V3；重启默认 `base`，调速关闭，无新增操作开关。

## 验证

- 新控制/几何/集成测试 14 项通过。新安装事务测试 9 项通过（包含五项原 V3 事务回归），覆盖错误暂存、无更新暂停/无停车条件拒绝、设备检查失败后的三文件恢复、回退与日志保留。原 V3 回归另执行 45 项通过。
- 安装前两次校验固定 V3 文件、Git 分支/提交、更新暂停和五秒连续 Park、零速度、控制未接合。以正常 API 关闭调速模式与日志服务，保存三文件恢复快照，再原子替换。
- 设备 Python 3.8 成功导入新模块、构造实际 Sharan CarController、读取实际 Cap'n Proto 模型结构。此检查没有发送测试 CAN。
- 安装后完整相关文件状态为 `HCA_R1_PRESENT`，未改文件也校验一致。之后重新检查停车条件并重启。
- 单调时钟由约 1947 秒回到 62 秒，确认真实重启。运行状态 `runtime.hca.version=hca-r1` 且新鲜；原车速度 0、Park、controls enabled/active 均 false、CAN valid true。
- 实际指纹 `VOLKSWAGEN SHARAN 2ND GEN`，`pcmCruise=true`，`openpilotLongitudinalControl=false`，`minSteerSpeed` 约 50 km/h。本次没有改变这些参数。
- 后端 8766 状态模式为 base，Android OverlayService 正在运行。第一次瞬时状态快照 pandaStates alive=false；后续四次独立 Panda 消息均 alive/valid=true、年龄约 0.5–0.7 ms、点火 true、安全模型 volkswagenPq、controlsAllowed=false、safetyTxBlocked=0。
- 三秒被动记录 `/data/pq46/logs/v3-hca-r1-passive-147.jsonl` 正常结束，含 29 条新版本状态、驾驶员和几何字段，零定速注入。169,628 字节，SHA-256 `8fa102b3988bafe16a54c1e02044d02ac53ae96aa94ecaa67c87c0771c98e3b9`，已下载并核验。
- 最初通过 SSH 独立调用记录脚本时未设置 PYTHONPATH，子进程导入 cereal 失败；补上与正常后端一致的 `/data/openpilot` 环境后记录成功。这是检查命令的环境问题，没有修改记录程序。

证据在忽略目录 `device-backups/hca-r1-install-20261002/`：install.txt、reboot.txt、postboot.txt、postboot-files.txt、passive-check.txt、passive-check-retry.txt、被动 trace 与回归测试输出。

## 验证边界及后续

本次确认源码已安装、新进程已运行、停车状态正常、新日志可用。没有驶动车辆或在设备上强制触发转向暂停，尚无本版道路完成率证据。新增几何外推采用模型估算和短时变化率，不是失去纠偏后的精确车辆轨迹预测。

后续看 `completed`、`aborted`、`last_abort_reason`、`start_block_reason`、`off_s` 与原始 HCA/EPS 报文；停车时期的 `natural_resets=1` 不代表道路择机成功。自动定速仍未解决，本次没有再发调速测试序列。

三文件回退工具为 `tools/manage_c2_hca_r1.py --action rollback`，之后停车重启；回退目标是原 V3。原 V3 管理工具会将 r1 视为不同文件，不应直接用它覆盖 r1；先回退到 V3，再按原工具恢复 V2。
