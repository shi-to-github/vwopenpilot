# 本地入库与原始资料归档

用户于 2026-10-03 要求保存所有代码、文档、实验数据及研究资料。仓库位于 D:/VWopenploot；未配置远程仓库，本轮只做本地 Git 提交，不向任何网站上传车辆日志、备份或代码。

代码、文档、测试、候选与回退文件直接进入 Git。历史实验候选保留用于审查，不因入库而变成可刷入版本；R3 的限制和审查状态见 HCA_R3_STAGED_LOCAL_REVIEW.md。

原先被忽略的 vendor、device-backups、artifacts 由 tools/archive_project_materials.py 建立内容寻址归档，保存到 archive/20261003。相同内容去重，大文件按 64 MiB 分块，压缩后的对象和完整文件 SHA-256 均记录在 index.json。原始材料仍留在原来的目录，归档不删除、不移动它们。

vendor 保存本机现有的源码与资源文件，以及符号链接目标、仓库 HEAD 和分支。内嵌 .git 的对象库不重复归档；该归档是完整工作文件快照，不是每个上游仓库的全部 Git 历史。公开资料来源仍由 SOURCE_PINS.md、EPS_COMPARISON.md 等文档中的链接追溯。

用户后续明确要求“不加密”，归档任务已停止并改为纯 gzip 明文压缩，包括原始约 592 MB 的 C2 全量备份与全部道路日志。不需要密码、恢复密钥、Windows 账户绑定或 cryptography 包。此前生成的未使用归档密钥已移除；没有生成加密资料对象。

设备 SSH 私钥没有进入仓库；应用签名 keystore 与上游自带的独立私钥文件排除，位置和原因写入 index.json，原文件仍保留。原始设备全量备份容器保持逐字节完整，包含私人参数，因此本次仅本地保存，不上传到公共或远程仓库。

可再验证归档：python tools/archive_project_materials.py --verify-only。验证按块解压，再重建每个文件 SHA-256，结果保存在 verification.json。所有对象 encoding 都是 gzip，没有加密格式。

恢复单个文件：python tools/read_archived_material.py --path <index.json 中的相对路径> --output <新的目标文件>。不指定 --output 时只显示元数据，不打印原始内容；恢复会核验所有块和完整文件哈希，且不会覆盖已有文件。

Git 保存直接源码与归档对象后，新增本地快照标签，方便后续追溯。实际提交号、文件数量、字节量及部署结果以最终提交和 verification.json 为准；本说明不预先宣称归档或部署成功。

SSH 的 IP、端口、用户名、公钥与本机密钥路径说明已明文保存到 C2 /data/pq46/ssh-connection-info.json，并在本地安装记录中保存同一份 JSON；没有复制 SSH 私钥，也没有更改设备的 SSH 授权或车辆控制逻辑。

早期两张用户上传的 VCDS 图片，其原始临时文件已不在此前提供的路径，因此未能复制原图；路径与缺项保存在 VEHICLE_PHOTO_INVENTORY.json。此前识别的 EPS / 仪表身份仍在车辆资料文档中。归档范围是当前实际存在的本地材料，不能宣称恢复了已消失的临时照片。

## 实际核验结果

本次归档保存 14,261 个文件，原始总量 5,082,905,683 字节，去重后 4,902 个对象共 1,774,675,130 字节。所有对象均为不加密的 gzip。逐文件重建后的完整 SHA-256 全部匹配，核验结果保存在 archive/20261003/verification.json。

另外通过 read_archived_material.py 实际取回 SSH 公钥连接说明 JSON，与原文件逐字节哈希一致；该读取工具没有打印文件原始内容。归档 index.json 的 SHA-256 为 4d346f7b264b5b13cb221668c9255c922b4107a4f355be81ab09d0619f351a82。

## 里程碑刷新（2026-10-05，稳定版发布之后）

在 `stable-1-hca-r4-forced` 发布、公开仓库上线之后，对同一归档目录做了一次原地刷新，把新增的
非 Git 材料（r4 的打包产物、r4 装机与被动日志证据）纳入。因为对象库是内容寻址的，旧内容全部命中
已有对象，**新增存储仅约 1.6 MB**：

| 项目 | 20261003 首次 | 2026-10-05 刷新 |
| --- | ---: | ---: |
| 文件数 | 14,261 | **14,276** |
| 原始总量 | 5,082,905,683 B | **5,084,994,084 B** |
| 去重对象数 | 4,902 | **4,917** |
| 去重后存储 | 1,774,675,130 B | **1,776,281,388 B** |

逐文件重建后的完整 SHA-256 **全部匹配**。`verification.json` 的 `verified_utc` 为
`2026-10-05T12:07:12Z`，刷新后 `index.json` 的 SHA-256 为
`a40eb77128fa44591af6b2251755246c13091e3393865baaf5351d0db4a4a8a8`。归档仍然**不加密**。

## 隐私清单：这些内容一律不得上传

对 `device-backups/original-20261001` 里的原始设备备份做过条目级核查，实际包含：

| 条目 | 值 / 性质 | 风险 |
| --- | --- | --- |
| `params/d_tmp/IMEI` | 真实 IMEI | 🔴 **最强个人标识**：中国 SIM 实名校验，IMEI 可直接关联到人 |
| `params/d_tmp/HardwareSerial` | 设备序列号 | 🟡 设备唯一标识 |
| `params/d_tmp/CarParamsPersistent`、`LiveTorqueCarParams` | 车辆配置 | 🟡 可反推车型与配置 |
| `params/d_tmp/GithubSshKeys` | `authorized_keys` 条目（**公钥**，带 `from=` 来源限制） | 🟢 不是私钥 |
| `params/d_tmp/DongleId` | 值为 `UnregisteredDevice` | 🟢 **没有真实 dongle id**，拿不到 comma connect 数据 |
| `params/d_tmp/GithubUsername` | 值为默认的 `openpilot` | 🟢 无害 |
| 行程日志、事件日志 | 驾驶数据（不含 GPS / 影像 / VIN） | 🟡 行为数据 |

**结论：备份里没有 SSH 私钥，也没有可用的设备云身份；但含真实 IMEI 与设备序列号，属于个人标识。**
因此 `archive/` 与 `device-backups/` 只保留在本机；公开仓库已将其排除，并在 `SAFETY.md` 里说明。

> 补充说明：`archive_project_materials.py` 的私钥排除逻辑只扫描**文件本身**的前 8192 字节。
> 对 `.tar.gz` 这类容器它看到的是 gzip 头，**不会**检查容器内部，所以"完整设备备份容器"是
> 整体保留的 —— 这正是工具文档里写明的 "containers remain local"。也正是不加密归档
> **只能留在本机、不得上传**的原因。

