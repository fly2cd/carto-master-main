# Carto 侧 MCP 接入与栅格输入契约（第一批）

## 职责和入口

独立 `geospatial-mcp` 负责数据读取、精确统计、坐标转换。Carto 用官方 MCP Python SDK 通过 **stdio 子进程**接入，每次调用建立并关闭会话；不是 HTTP 常驻服务，也不要求宿主注册 MCP。分类语义、颜色、图例、排版、渲染、导出继续属于 Carto。

| Carto capability | MCP 工具 | 本批入口 |
|---|---|---|
| `gis-raster-info` | `geo_raster_info` | `data inspect-raster`，operation=info |
| `gis-raster-statistics` | `geo_raster_statistics` | 同上，operation=statistics |
| `gis-raster-reproject` | `geo_raster_info` → `geo_raster_reproject` → `geo_get_task_info` → `geo_get_artifact_info` → resources/read | 仅 ToolGateway 适配器；无变换 CLI/业务场景 |

数据检查不是新业务路由，不能替代 `create-template` / `generate-map` 或 T1 / TP / G1 / G2 / G3。本批不注册场景、不制作地图。

## 环境与运维配置

1. 先确认 Carto 的真实 Python 3.11+，执行 `carto.py --help`、`carto.py schema check`。
2. 可选客户端依赖为 `mcp>=2.2.0,<3`；需要时由操作员显式安装 `skills/carto-agent/requirements-geospatial.txt` 或开发安装 `.[geospatial]`。不自动安装。
3. 在独立 GIS 环境安装服务 **0.3.0**；`server_python` 必须是能够执行 `-I -B -m geospatial_mcp.server` 的真实绝对解释器路径。握手名称须为 `Geospatial Tools`。不靠 cwd/PYTHONPATH 注入外部源码，不接收请求指定的 Shell、模块或 URL。
4. 操作员维护配置/catalog，显式授权项目、数据根、解释器所在目录，不以整个磁盘作为方便的允许根。

以下是需替换占位符的说明模板，不是运行 Fixture。项目内假设有 `dataset/` 和 `config/`；`config/geospatial.yaml`：

```yaml
schema_version: 1
server_id: geospatial-mcp
server_version: 0.3.0
server_python: "<已确认的 GIS Python 绝对路径>"
tenant_id: my-tenant
project_id: land-cover-project
data_root: dataset
catalog_path: config/datasets.json
allowed_dataset_ids: [land-cover]
limits:
  max_input_bytes: 268435456
  max_artifact_bytes: 16777216
  max_raster_pixels: 16000000
  max_raster_classes: 256
  max_response_bytes: 1048576
  timeout_seconds: 60
```

`config/datasets.json`：

```json
{
  "version": 1,
  "datasets": {
    "land-cover": {"kind": "raster", "path": "landCover.tif"}
  }
}
```

配置中的 data_root/catalog_path 相对项目根解析，catalog 路径相对数据根解析。catalog 的键必须恰好等于 allowed_dataset_ids，文件限定为数据根内 TIFF。每个子进程只收到当前 dataset 的不可变 catalog 快照，不暴露完整 catalog。

服务工作区固定为 `<project>/.carto/geospatial/service`，不能与数据根包含或重叠；不要把整个项目根设为数据根。执行上下文须匹配 tenant/project，环境为 local，分类为 public/internal。路径许可和来源声明都不是业务审批。

## 栅格输入合同

新增 `raster-input.schema.json`，作为 `generate-request.source_bindings` 的互斥分支，原 GeoJSON 分支不变。**结构通过不代表地图管线可消费 TIFF**：本批没有扩展 source-manifest、模板分析、场景数据准备或渲染器。

- 自包含 GeoTIFF；单波段 band=1，8/16/32 位有符号或无符号整数，value_semantics=categorical-integer。
- dataset_id、本地 path、字节数及 SHA256 必须一致；调用前后复核，配置/catalog 漂移拒绝。
- CRS 只允许显式 EPSG 或 null；null 表示确实无 CRS，不是请求自动识别。实际 CRS 必须一致；缺 CRS 可读取/统计，不可重投影。
- mask_policy=embedded：尊重内部掩膜及 NoData，不自动把 0/255 当作无效值，不补 NoData；拒绝已知 `.msk`、`.aux.xml`、`.ovr` 旁车。
- 只接纳 public/project-approved 许可、synthetic/user-provided 来源和 contains_sensitive_coordinates=false；这些声明不等于自动安全认证。
- 不接收类别中文名、颜色、图例、纸张、标题，不关联旁边 CSV 猜类别含义。
- 上限为输入 256 MiB、1600 万像元、256 类；配置只能收紧。统计是全量精确计数，不是抽样。

`config/inspect-land-cover.yaml` 说明模板，须实测替换摘要、字节数和 CRS，不能原样运行：

```yaml
schema_version: 1
operation: statistics
source:
  schema_version: 1
  role: classified-surface
  source_ref:
    id: land-cover-source
    version: 1.0.0
    digest: "sha256:<实测的 64 位十六进制 SHA256>"
  path: dataset/landCover.tif
  format: geotiff
  dataset_id: land-cover
  size_bytes: <实测文件字节数，整数>
  crs: {authority: EPSG, code: "<已核实的 EPSG 编码>"}
  band: 1
  value_semantics: categorical-integer
  mask_policy: embedded
  license: project-approved
  data_nature: user-provided
  contains_sensitive_coordinates: false
```

## 只读检查

从仓库根调用唯一 CLI。以下变量由操作员按真实路径赋值，不猜测本机解释器：

```powershell
& $CartoPython skills/carto-agent/scripts/carto.py data inspect-raster config/inspect-land-cover.yaml `
  --mcp-config config/geospatial.yaml `
  --project-root $ProjectRoot `
  --allowed-root $ProjectRoot --allowed-root $DataRoot --allowed-root $GisPythonDirectory `
  --run-id inspect-land-cover-001 --tenant-id my-tenant --project-id land-cover-project `
  --subject-id operator-id
```

operation 仅限 info/statistics。reproject 在构造适配器、启动进程之前以 `MCP_MUTATION_REQUIRES_WORKFLOW` 拒绝。只读表示不变换原始数据，仍会写入项目内 catalog 快照和证据。

stdout 仅输出状态和 ToolResult（输入/输出摘要、能力版本、时间和证据引用），不展开像元、类别计数或坐标。详情保存在项目受限 JSON 证据中，不应当作普通日志公开。必须核对退出码和 ok，不能把文件存在当作成功。

## 变换与验收证据

未来经授权的场景可通过 `adapter.bind(existing_gateway)` 或 `make_gateway()`，使用明确授予 `gis-raster-reproject` 的已有 ExecutionContext 调用。配置或工具发现都不能替代能力授权、业务门禁；不要直接调用私有 handler 绕过网关。

reproject 必须显式传 parameters：target_crs=EPSG:...、resolution=正数或null、resampling=nearest。第一批只接纳已知 CRS、north-up 输入，不用双线性/三次重采样改变分类码。

验收链：输入摘要 → 精确任务参数/输入/成功状态 → task/artifact ID → 元数据/分辨率 → artifact:// 二进制资源 → 大小/TIFF 签名/SHA256 → 项目内原子只增发布 → 网关成功证据。不跟随服务返回的文件路径或任意 URL。

项目内 `.carto/geospatial/` 包含 catalogs（单 dataset 快照）、service（服务工作区）、artifacts（以 SHA256 命名的 TIFF）、tasks（按摘要保存的任务 JSON）、evidence（ToolResult 引用的 geospatial-result）。结果绑定 source、配置/catalog/工具发现摘要、元数据和可选统计或产物；任务也有本地 task_ref。这些内部文件不进入地图交付包。

## 拒绝及剩余边界

- 只接受 SDK 类型化 structured_content，不从 text/错误字符串猜 JSON。不执行远端工具 JSON Schema；最终由本地 geospatial-wire 校验，SDK 仍解析 MCP 协议模型。
- 缺依赖、服务不匹配、工具缺失、越权、漂移、统计不一致、task/artifact 篡改、超限、超时均失败关闭，不回退直接读取 GIS 的旁路。
- 默认 60 秒、最大 300 秒会话超时，无自动重试；结果不明不得当作尚未执行重新变换。本批没有任务恢复或接管 CLI。
- TIFF 输出最多 16 MiB；结构响应最高 2 MiB。这些是 **SDK 解码后的接收限制**，不是恶意服务的流式内存沙箱。服务解释器、安装、配置和目录必须可信；版本检查不是代码签名，PathGuard 不是对抗任意本机并发进程的 OS 隔离。
- 本节 MCP 适配器信任服务提供地理元数据并核验二进制完整性，不直接解码栅格。第二批 Carto 图体渲染器使用 Rasterio 解码冻结快照并核验元数据/像元统计，但不替代 MCP 基础分析工具。
- 会话退出失败可能留下已校验的 TIFF/任务文件，但没有网关成功证据；残留不能自动导入工作流，不自动清理或重复变换。
- 尚不支持 artifact 再输入、连续栅格、多波段、任意 WKT、矢量分析迁移、分类语义/颜色/图例、场景注册或实际 A4 出图。

第二批底层能力已实现：见 `raster-classification.md`，包括冻结快照、动态澄清、分类名/颜色合同、共享图例、Rasterio + Matplotlib 图体及 A4 横版合成布局测试；尚未接入正式地图场景和交付。MCP 继续只扩展基础数据/分析能力。

## 开发验证

基础测试不要求独立服务；可选集成需显式设置 `CARTO_GEOSPATIAL_TEST_PYTHON` 为已安装服务的真实绝对解释器，测试环境具有 MCP/rasterio/numpy。只创建临时合成 TIFF，不使用用户数据或修改独立项目。

```powershell
& $CartoPython -B -m unittest discover -s skills/carto-agent/scripts/tests -t skills/carto-agent/scripts -p 'test_geospatial_mcp.py' -v
# 显式设置 CARTO_GEOSPATIAL_TEST_PYTHON 后：
& $CartoPython -B -m unittest discover -s skills/carto-agent/scripts/tests -t skills/carto-agent/scripts -p 'test_geospatial_stdio.py' -v
```
