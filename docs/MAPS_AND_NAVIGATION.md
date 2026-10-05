# Dragonpilot C2 地图与导航架构

## 三个容易混淆的功能

### 1. 屏幕地图与路线导航（`dp_nav` / `navd`）

这是用户输入目的地以后显示路线和转弯提示的功能。

- EON/C2 默认关闭 `dp_nav`；启动脚本在关闭时运行 `_ui_nonav`，打开后运行带地图的 `_ui`。
- `navd` 读取 `NavDestination`，调用 Mapbox Directions API，发布 `navRoute` 和 `navInstruction`。
- 需要联网。若设备没有可用的 comma 地图凭据，可以启用 Dragonpilot 的本地导航网页服务 `dp_otisserv`。
- `otisserv` 监听 8082 端口。手机与 C2 位于同一网络时，可以访问 `http://<C2_IP>:8082` 搜索和选择目的地。

### 2. 目的地搜索网页（`dp_otisserv`）

这个网页只负责搜索地点并把经纬度写入 `NavDestination`；真正的路线仍由 `navd` 计算。

旧版 Dragonpilot 提供三种搜索界面：

- Mapbox：需要 Mapbox public token；代码还要求填写一个 `sk.` token。
- Google Maps：需要 Google Maps API key。
- 高德地图：需要高德 JavaScript API key 和安全密钥；选择地点后，代码会把 GCJ-02 坐标转换为 WGS-84。

无论使用哪一种搜索界面，这个版本的 `navd` 最终仍然请求 Mapbox Directions。选择高德只改变“怎样找到目的地”，不会自动把路线引擎改成高德。若希望路线也由高德生成，需要另写 route-provider 适配层，并把高德返回的路线、步骤和坐标转换成 `navRoute` / `navInstruction`。

### 3. 后台道路数据（`dp_mapd` / `mapd`）

`mapd` 不需要目的地，也不负责屏幕导航。它根据 GPS 查询车辆周围约 3 km 的 OpenStreetMap 道路，匹配当前道路并输出：

- 当前和前方道路限速；
- 当前和前方弯道的建议速度、距离及方向。

它可以使用公共 Overpass 服务，也可以安装本地 OSM 数据库。远程 OSM 查询不需要个人 API key，但需要网络；本地数据库不依赖行车时联网。

当前 `mapd` 不订阅 `navRoute`。遇到主线与匝道分叉时，它只能根据位置、航向和道路拓扑推测接下来走哪条路，因此可能继续选择主线。要做“按照已选导航路线提前降低匝道速度”，应把 `navRoute` 几何接入弯道选择，不能只打开 `dp_mapd` 就直接发送减速按键。

## 与 PQ46 原厂定速按钮的关系

原版 `SpeedLimitControl` 和 `TurnSpeedControl` 把地图目标交给 OpenPilot 纵向规划器，项目说明也把它们限定在支持 OpenPilot 纵向的车辆。当前 PQ46 使用原厂普通定速，打开这些设置不会自动模拟 `GRA_Neu` 加减速按钮。

本项目可以增加一个适配层：

1. `navd` 或 `mapd` 提供建议速度和生效距离；
2. PQ 巡航目标管理器保存驾驶员上限；
3. 管理器把建议速度限制在原车定速和 EPS 可工作的范围内；
4. 一次发送一个 `GRA_Down_kurz` 或 `GRA_Up_kurz`；
5. 等待原车目标速度确认后再发送下一次。

前车速度修整不依赖地图，适合先实现。地图阶段先只显示和记录建议速度，验证中国道路、主线/匝道匹配和提前距离，再允许它请求按钮操作。

## 已知先例

OPKR 已公开描述 `Cruise Button Spamming`：使用 OpenPilot 目标速度和前车距离调整原车巡航设定，并将 OSM 限速和弯道速度用于按钮调速。该实现主要面向带原厂 SCC/ACC 的现代、起亚和捷尼赛思车型，证明总体控制方式已有实践，但不能直接复制到不带制动 ACC 的 PQ46。

参考：

- https://github.com/openpilotkr/openpilot/tree/OPKR
- https://github.com/dragonpilot/dragonpilot

