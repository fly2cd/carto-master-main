# U-P2.0：范围冻结与缺口审计 — 实施说明

## 文档信息

| 项目 | 内容 |
|---|---|
| 阶段 | U-P2.0：范围冻结与缺口审计 |
| 实施日期 | 2026-09-17 |
| 分支 | `U-P2` |
| 状态 | 已完成；后续 U-P2.1～U-P2.7 已按冻结范围实施并验收 |
| 上位计划 | [U-P2 分阶段实施细化计划](../u-p2-implementation-plan.md) |
| 运行代码变更 | 无 |

本阶段只冻结 U-P2 的实施边界和未来协议合同，不创建模板包、渲染器、发布事务、业务候选或 `MapSpecLock`。本文是实施决策记录，不是运行时机器协议；后续运行时只读取 `skills/carto-agent/` 下的 Schema、Policy、注册表和项目产物。

---

## 一、U-P2 决策清单

### 1.1 能力边界

| 决策项 | 冻结结论 | U-P2 验证证据 | 未开放项 |
|---|---|---|---|
| 模板业务创建 | 只开放 `map-scenario`；Brand、Style、Layout 仅参与组合、所有权和兼容性测试 | MapScenario 草稿、验证报告、发布回执、不可变包摘要 | 三类基础模板的业务创建路由 |
| 模板类型 | 保持四类：`map-brand`、`map-style`、`map-layout`、`map-scenario` | Manifest kind 校验和组合测试 | 第五种“地图类型模板” |
| 地图表达定位 | 地图表达属于版本化 `map-types/` 资源目录，由 MapScenario 的 portrayal 契约引用 | 表达目录 Schema、合法/非法样例、编译快照 | 将面分级图、点密度图作为模板 kind |
| 首个场景 | `emergency_mapping` 下的合成城市洪涝研判演示 | 固定 Fixture 端到端测试 | 真实洪涝预测、预警或指挥决策 |
| U-P2 终点 | 候选预览通过 G2 后生成不可变 `MapSpecLock` | candidate/execution digest、预览证据、G2 回执、锁一致性测试 | G3、正式成品检查、交付事务、公开发布 |
| 数据性质 | 仅使用 `simulated` 合成数据 | Fixture 元数据和输出水印/说明检查 | 生产数据、真实应急敏感坐标 |
| 网络 | 首切片离线运行，不允许网络获取数据、瓦片、字体或知识 | 环境指纹、资源清单、网络拒绝测试 | 在线底图和外部地理编码 |
| 原生 GIS | 不读写 QGIS/ArcGIS 工程 | `CAPABILITY_NOT_AVAILABLE`/`SOURCE_UNSUPPORTED` 负向测试 | QGIS/ArcGIS 工程保真编辑 |

### 1.2 来源格式冻结

U-P2 首切片只接受以下输入：

1. 请求和元数据：安全解析的 YAML 或 JSON。
2. 空间数据：GeoJSON `FeatureCollection`。
3. 表格数据：UTF-8 CSV，首行表头，逗号分隔，不执行公式、宏或外部链接。

明确决定：

- **GeoPackage 不进入 U-P2**。原因是当前仓库没有固定 GDAL/OGR 解析依赖、驱动许可证据、数据库对象白名单、路径/连接安全测试和可重放快照实现。
- `qgis-project`、Shapefile、GeoTIFF、数据库、API 实时响应、PDF/SVG/PNG 反向提取均不进入首切片。
- `source-manifest.schema.json` 当前列出的格式不等于 U-P2 已开放能力；U-P2.1 必须通过版本化能力/格式策略限制实际入口。
- 所有文件路径必须先经过允许根校验；SourceManifest 固定内容摘要，不依赖文件修改时间表示业务观测时间。

### 1.3 地图表达冻结

U-P2 注册且实现的地图表达只有两项：

| 表达 ID | 含义 | 数据要求 | 视觉变量 |
|---|---|---|---|
| `choropleth/sequential` | 面要素连续数值顺序分级设色 | Polygon/MultiPolygon；数值字段；单位和空值语义明确 | fill color |
| `proportional-symbol/count` | 点要素非负计数的面积比例符号 | Point；非负 count 字段；单位明确 | symbol area |

辅助资源 `point-symbol/shelter` 是避难点符号资源，不是独立地图表达，也不是模板类型。容量 `100/400/900` 必须按面积比例 `1/4/9` 映射；实现不得误写为半径与容量线性正比。

以下表达在 U-P2 中不注册为可用能力：

- 点密度图 `dot-density/*`；
- 热力图 `heatmap/*`；
- 流向图 `flow/*`；
- 等值线/等值面 `isoline/*`；
- 分级符号图 `graduated-symbol/*`；
- 网络可达性、服务区和洪涝模拟结果推导。

### 1.4 输出与渲染边界冻结

| 项目 | 冻结值 |
|---|---|
| 目标 | `print-a3-landscape-preview` |
| 页面 | 420 × 297 mm，横向 |
| 预览格式 | SVG、PDF、PNG |
| 地图渲染 | 受控 MapLibre Web；地图主体允许以确定性栅格图像嵌入 SVG |
| 页面叠加层 | 标题、图例、比例尺、指北针、说明等 SVG 矢量 overlay |
| PDF 声明 | 仅声明“工程预览 PDF”，不声明全矢量 PDF |
| PNG 声明 | 栅格预览，像素尺寸由页面尺寸与冻结 DPI 确定 |
| 正式交付 | 不属于 U-P2 |

首切片源数据 CRS 固定为 `EPSG:4326`，Web 地图显示 CRS 固定为 `EPSG:3857`。U-P2 不执行面积、距离、洪水传播或服务范围分析；若后续业务需要这些分析，必须新增适用投影/测地算法及误差测试，不能复用显示 CRS 冒充分析 CRS。

### 1.5 分类和符号参数冻结

- 风险率单位：`percent`，有效范围 `[0, 100]`，允许空值。
- 分类：四级分位数，固定实现标识 `quantile-type7@1`。
- 区间：第一段闭区间，其余左开右闭。
- 空值：不参加分类，使用独立无数据纹理并进入图例。
- 容量单位：`person`，整数，最小值 0，不允许空值。
- 容量符号：100 人对应 1.5 mm 半径；面积与容量成正比。
- 排序：分类输入、图层、要素和图例均使用稳定排序；不能依赖文件系统枚举顺序。

---

## 二、洪涝合成 Fixture 设计

### 2.1 文件组成

```text
fixtures/u-p2/flood-demo/
├─ request.yaml
├─ metadata.yaml
├─ regions.geojson
├─ flood-risk.csv
└─ shelters.geojson
```

本阶段只冻结设计，不提前创建这些 U-P2.2/U-P2.3 Fixture 文件。

### 2.2 数据角色

#### `risk_regions`

| 项目 | 冻结值 |
|---|---|
| 几何 | Polygon；合法样例为 9 个互不重叠的合成格网 |
| CRS | EPSG:4326 |
| 主键语义 | `region_id` |
| 实际几何列来源 | `regions.geojson.properties.region_code` |
| 度量语义 | `risk_rate` |
| 实际度量列来源 | `flood-risk.csv.flood_rate_pct` |
| Join | `region_code`，many-to-one 禁止；两侧键唯一；最低覆盖率 1.0 |
| 值域 | 0–100 percent，nullable |
| 时间 | `2026-09-11T08:00:00+08:00`，最大年龄 P1D |
| 合成范围 | 经度 110.0–110.3、纬度 30.0–30.3；不对应真实行政区 |

风险值固定为：R01=5、R02=10、R03=15、R04=20、R05=25、R06=30、R07=35、R08=40、R09=null。固定测试时钟为 `2026-09-11T09:00:00+08:00`，仅由测试宿主注入。

#### `shelters`

| 项目 | 冻结值 |
|---|---|
| 几何 | Point；3 个点，全部位于合成格网范围内 |
| CRS | EPSG:4326 |
| 主键语义 | `shelter_id` |
| 容量语义 | `capacity` |
| 值域 | integer，单位 person，最小值 0，非空 |
| 固定容量 | 100、400、900 |
| 业务限制 | 只表达已给定容量，不推断可达性、服务范围或实际开放状态 |

### 2.3 元数据

`metadata.yaml` 至少记录：

- `data_nature: simulated`；
- 观测时间和时区；
- 每个字段的语义、类型、单位和 nullable；
- CRS 声明及坐标来源为 synthetic-grid；
- 许可为项目内可分发的合成数据；
- Join 键、基数、重复策略和最低覆盖率；
- 禁止把演示结果表述为官方预警或真实风险结论。

### 2.4 异常用例

| 用例 | 预期阻断 |
|---|---|
| 缺失 CRS 或 CRS 不是已允许值 | `CRS_UNRESOLVED` |
| 无效 Polygon、自交或空几何 | `GEOMETRY_INVALID` |
| `region_code` 重复 | `JOIN_KEY_DUPLICATE` |
| CSV 缺少一个必需区域 | `JOIN_COVERAGE_INSUFFICIENT` |
| 风险率使用 0–1 却声明 percent | `DATA_SEMANTICS_INVALID` |
| 风险率小于 0 或大于 100 | `DATA_VALUE_OUT_OF_RANGE` |
| 观测时间超过 P1D | `DATA_STALE` |
| 容量为负数、小数或 null | `DATA_VALUE_OUT_OF_RANGE` |
| 避难点位于批准范围外 | `FEATURE_OUTSIDE_APPROVED_EXTENT` |
| Point 数据绑定为 `risk_regions` | `GEOMETRY_ROLE_MISMATCH` |
| 输入带未知字段、未知操作或公式载荷 | `CONTRACT_SCHEMA_INVALID` 或 `DATA_OPERATION_DENIED` |
| 请求 GeoPackage/QGIS 工程 | `SOURCE_UNSUPPORTED` |

---

## 三、CLI 合同冻结（仅定义，不实现）

旧 TRD 中的 `carto_template.py` 和 `carto_map.py` 只视为历史拟议接口。实际实现必须扩展仓库唯一入口 `carto`，顶层路由名与 `workflows/routing.md` 一致。

### 3.1 通用约束

- 所有业务命令支持 `--json`；stdout 只输出一个结构化结果，stderr 输出进度和诊断。
- 所有外部路径都要求一个或多个 `--allowed-root`，并在读取/写入前完成规范化和允许根校验。
- 写操作必须携带 `--idempotency-key` 或从已校验请求中取得等价键。
- `--help`、`status` 和 `--dry-run` 不改变业务状态。
- 缺少审批时保存 `waiting_approval` 并返回 3，不阻塞终端等待。
- U-P2 不接受 `deliver` 审批，也不提供正式 `render/check/deliver` 命令。

### 3.2 `create-template` 合同

```text
carto create-template analyze --source <path>... --workdir <path> --allowed-root <path>... [--json]
carto create-template brief <workdir> --kind map-scenario --scope <scope> --id <id> --version <semver> --allowed-root <path>... [--json]
carto create-template confirm <workdir> --action brief|publish --approval-receipt <path> --allowed-root <path>... [--json]
carto create-template author <workdir> --allowed-root <path>... --idempotency-key <key> [--json]
carto create-template validate <workdir> --render --target print-a3-landscape-preview --allowed-root <path>... [--json]
carto create-template publish <workdir> --repository <path> --allowed-root <path>... --idempotency-key <key> [--dry-run] [--json]
carto create-template status <workdir> --allowed-root <path>... [--json]
carto create-template resume <workdir> --run <run-id> --allowed-root <path>... [--json]
carto create-template cancel <workdir> --run <run-id> --allowed-root <path>... [--json]
```

U-P2 中 `--kind` 传入其他三类模板时返回 `CAPABILITY_NOT_AVAILABLE`，不得创建半成品包。

### 3.3 `generate-map` 合同

```text
carto generate-map intake --request <path> --project <path> --allowed-root <path>... [--scene emergency_mapping] [--json]
carto generate-map brief <project> --allowed-root <path>... [--json]
carto generate-map confirm <project> --action brief|freeze --approval-receipt <path> --allowed-root <path>... [--json]
carto generate-map prepare-data <project> --mode deterministic --allowed-root <path>... --idempotency-key <key> [--json]
carto generate-map plan <project> --allowed-root <path>... --idempotency-key <key> [--json]
carto generate-map preview <project> --allowed-root <path>... --idempotency-key <key> [--json]
carto generate-map freeze <project> --allowed-root <path>... --idempotency-key <key> [--json]
carto generate-map status <project> --allowed-root <path>... [--json]
carto generate-map resume <project> --run <run-id> --allowed-root <path>... [--json]
carto generate-map cancel <project> --run <run-id> --allowed-root <path>... [--json]
```

`--mode agent_assisted` 在 U-P2 返回 `CAPABILITY_NOT_AVAILABLE`。`run` 聚合命令推迟到 U-P2.7，在细粒度步骤和恢复语义稳定前不提前开放。

### 3.4 结构化输出和返回码

成功和等待态至少包含：

```json
{
  "ok": true,
  "route": "generate-map",
  "run_id": "run-001",
  "status": "waiting_approval",
  "step": "freeze",
  "artifact_ref": "candidate:candidate-001",
  "evidence_ref": "reports/preview-001",
  "required_action": "approve-freeze",
  "retry_from": "freeze"
}
```

错误至少包含 `ok/code/message/route/run_id/step/artifact/evidence_ref/repair_owner/retry_from/retryable`；规则失败另含 `check_id/strength/result_severity`。

返回码固定为：0 成功；2 参数/请求错误；3 等待批准或必需决策；4 协议/数据/验证失败；5 暂时性基础设施失败；6 权限/安全/合规阻断；7 已取消。

---

## 四、协议差异表

下表是 U-P2.1 的输入，不在 U-P2.0 直接修改 Schema。

| 协议 | 当前缺口/过宽项 | U-P2.1 收敛方向 | 风险 |
|---|---|---|---|
| `manifest` | 未声明六契约清单；`files` 与 `checksums` 无等集约束；发布证据和依赖锁缺失 | 固定 MapScenario 必需文件、文件摘要闭包、精确依赖和发布元数据 | 包可漏文件或藏未摘要文件 |
| `scenario` | `embedded` 仅是任意 object；缺 application、适用/禁用条件；所有权段混入数据/交付等 | 嵌入 identity/cartography/layout 必须各自校验；声明恰好六份业务契约和可替换段 | 替换后语义不可验证 |
| `identity` | 资产许可、字体资源摘要和缺字策略不足 | 固定资源引用、许可与字体回退/拒绝规则 | 发布后资源漂移 |
| `cartography` | `symbolization` 和 `defaults` 允许任意嵌套对象 | 改为受信目录引用、版本化参数 Schema 和有限默认值 | 任意结构绕过检查 |
| `layout` | frame `bounds` 复用地理 bbox，无法表达页面坐标；缺方向、安全边距、溢出合同 | 使用页面坐标框；固定 A3 横版、单位、容量和裁切规则 | 图框语义错误 |
| `data-role` | 与 TRD 的映射式示例不一致；缺主键、measure kind、值域、空值策略、Join 基数/重复策略、观测时间角色 | 冻结一种结构并覆盖上述字段 | 不能证明字段语义 |
| `spatial-behavior` | 只允许单个 display CRS；缺源 CRS 白名单、轴顺序、几何修复容差、分析/显示 CRS 分责 | 首切片固定 EPSG:4326→EPSG:3857 并记录转换 | CRS/几何错误被掩盖 |
| `portrayal` | 没有 `map_type`/binding 模型；classification 直接绑定实际字段名；参数只允许标量 | 引用精确表达版本，以字段语义角色绑定；支持受控分类和符号参数 | 模板污染项目字段名 |
| `delivery` | 只有 pdf/png，未说明这些是预览还是正式交付；缺页面方向与栅格/矢量组成声明 | U-P2 定义 preview target，正式 delivery 保留到 U-P3 | 误报正式交付/矢量 PDF |
| `quality-gates` | `params` 未由 checker 参数 Schema 验证；模板可能自行指定 strength/severity | strength/severity/实现归注册表，模板只引用检查器和允许参数 | 模板降低门禁 |
| `template-brief` | `decisions.additionalProperties=true`；没有 open question 必须归零的状态约束 | 类型化 decisions；author 前强制关键问题关闭 | 未决参数进入模板 |
| `source-manifest` | Schema 枚举了 U-P2 未实现格式；缺格式能力版本、数据性质、观测时间/CRS元数据引用 | 入口依据范围策略拒绝未开放格式；固定快照和元数据引用 | “Schema 可写”等同“能力可用” |
| `prepared-data-bundle` | datasets 只有 artifactRef；缺角色、格式、CRS、行数/要素数、字段和 Join 质量摘要 | 增加确定性数据集快照与验收摘要 | 编译器无法验证数据合同 |
| `map-brief` | source plan 不能表达 Join、时效、输出页面和演示限制 | 类型化来源计划、A3 preview target、G1 绑定摘要 | 批准对象不完整 |
| `map-plan` | `decisions` 任意；binding 只有 role/dataset，缺字段、单位、来源和批准 | 类型化字段绑定、表达选择、分类参数、provenance/approval ref | 候选仍有隐式决定 |
| `common.executionSnapshot` | `shared_semantics` 任意 object；目标可宣称 svg/pdf/png 但无能力证明 | 收紧共享语义并绑定表达、渲染器 profile、资源和环境证据 | 锁不能稳定重放 |
| `render-scene` | 底层结构较完整，但尚未固定 A3 页面到 viewport/DPI 的换算和离线资源闭包 | 定义 renderer profile、资源摘要和确定性导出合同 | 同场景产生不同像素结果 |
| 模板索引/依赖锁/发布回执 | 当前没有专用 Schema | U-P2.1 新增三类协议及正反 Fixture | 发布不可发现或不可追溯 |
| 地图表达目录项 | 当前没有专用 Schema | 新增非执行式目录项 Schema；拒绝代码/脚本/动态表达式 | 目录成为代码注入通道 |

### 命名收敛

| 旧称 | 冻结称谓 |
|---|---|
| `choropleth-risk` | `choropleth/sequential` |
| `point-shelter` | `point-symbol/shelter`（符号资源） |
| `graduated-symbol/count` | 不采用；U-P2 不实现分级符号 |
| `proportional-symbol/count` | `proportional-symbol/count`（地图表达） |
| `carto_template.py` | `carto create-template ...` |
| `carto_map.py` | `carto generate-map ...` |

---

## 五、测试矩阵

| 编号 | 后续阶段 | 测试层 | 正向断言 | 负向断言/错误码 | 证据目录 |
|---|---|---|---|---|---|
| T01 | U-P2.1 | Schema | MapScenario 包恰有六契约且 Manifest 文件闭包一致 | 漏文件/多文件：`PACKAGE_FILESET_MISMATCH` | `reports/u-p2/protocol/` |
| T02 | U-P2.1 | Schema | 两项表达目录可通过且无执行载荷 | script/sql/expression：`CATALOG_EXECUTABLE_CONTENT_FORBIDDEN` | `reports/u-p2/protocol/` |
| T03 | U-P2.1 | Compiler | 外部 Brand/Style/Layout 整段替换成功 | 重复 kind 或不兼容：`OWNERSHIP_CONFLICT`/`TEMPLATE_INCOMPATIBLE` | `reports/u-p2/ownership/` |
| T04 | U-P2.2 | Workflow | YAML/JSON 简报与 GeoJSON/CSV 来源完成 analyze→brief→author | GeoPackage/QGIS：`SOURCE_UNSUPPORTED` | `reports/u-p2/template-authoring/` |
| T05 | U-P2.2 | Security | 全部来源位于允许根并固定摘要 | traversal/symlink/junction 越界：`PATH_OUTSIDE_ALLOWED_ROOT` | `reports/u-p2/security/` |
| T06 | U-P2.2 | Data | 9 区、9 行、3 点及元数据通过 | 重复 Join 键：`JOIN_KEY_DUPLICATE` | `reports/u-p2/data/` |
| T07 | U-P2.2 | Data | Join 覆盖率 1.0 | 缺行：`JOIN_COVERAGE_INSUFFICIENT` | `reports/u-p2/data/` |
| T08 | U-P2.2 | Data | 百分数、person、nullable 语义匹配 | 单位/值域错误：`DATA_SEMANTICS_INVALID`/`DATA_VALUE_OUT_OF_RANGE` | `reports/u-p2/data/` |
| T09 | U-P2.3 | Renderer | 受控浏览器完成 WebGL、离线资源和中文字体检查 | 能力缺失：`ADAPTER_CAPABILITY_MISSING` | `reports/u-p2/environment/` |
| T10 | U-P2.3 | Determinism | 同 Scene/Profile/Fixture 输出语义摘要一致 | 环境漂移：`VALIDATION_STALE` | `reports/u-p2/render/` |
| T11 | U-P2.3 | Visual | A3 420×297、四级图例、R09 无数据、3 容量点正确 | 裁切/图例不同步：检查器失败 | `reports/u-p2/render/` |
| T12 | U-P2.4 | Publication | 验证证据绑定包/环境后原子发布 | stale/版本冲突：`VALIDATION_STALE`/`VERSION_CONFLICT` | `reports/u-p2/publication/` |
| T13 | U-P2.5 | Planning | 字段语义映射与实际列名分离，type-7 断点固定 | 绑定歧义：`BINDING_AMBIGUOUS` | `reports/u-p2/planning/` |
| T14 | U-P2.5 | Cartography | 风险分级和容量面积映射符合冻结参数 | 半径线性容量映射：`ENCODING_SEMANTICS_INVALID` | `reports/u-p2/planning/` |
| T15 | U-P2.6 | Approval | G2 精确绑定 candidate/execution/preview/environment | 任一摘要变化：`APPROVAL_INVALID` | `reports/u-p2/freeze/` |
| T16 | U-P2.6 | Immutability | MapSpecLock 与 execution snapshot 完全一致且 create-once | 冻结后改输入：`LOCK_INPUT_DRIFT` | `reports/u-p2/freeze/` |
| T17 | U-P2.7 | Recovery | 两路由从最后有效回执恢复 | 输入/前提漂移阻断：`JOB_INPUT_DRIFT` | `reports/u-p2/recovery/` |
| T18 | U-P2.7 | Regression | 全量 U-P0/U-P1/U-P2 测试通过 | 未解释 skip 不允许验收 | `reports/u-p2/regression/` |

---

## 六、错误码清单

### 6.1 本阶段确认复用的现有错误码

`CAPABILITY_NOT_AVAILABLE`、`SOURCE_UNSUPPORTED`、`APPROVAL_INVALID`、`CONTRACT_SCHEMA_INVALID`、`CONSTRAINT_CONFLICT`、`ADAPTER_CAPABILITY_MISSING`、`RENDER_TIMEOUT`、`INTEGRITY_MISMATCH`、`LICENSE_BLOCKED`、`VALIDATION_STALE`、`VERSION_CONFLICT`、`REQUEST_AMBIGUOUS`、`INTENT_CONFLICT`、`INTENT_UNSUPPORTED`、`INPUT_REQUIRED`、`DATA_ACCESS_DENIED`、`DATA_SNAPSHOT_UNSTABLE`、`DATA_STALE`、`BINDING_AMBIGUOUS`、`CRS_UNRESOLVED`、`TEMPLATE_INCOMPATIBLE`、`LOCK_INPUT_DRIFT`、`DATA_OPERATION_DENIED`、`PATH_OUTSIDE_ALLOWED_ROOT`、`JOB_INPUT_DRIFT`。

### 6.2 U-P2 需补充或标准化的错误码

| 错误码 | 阶段 | repair owner | retryable |
|---|---|---|---|
| `PACKAGE_FILESET_MISMATCH` | compile/publish | template-package | false |
| `CATALOG_EXECUTABLE_CONTENT_FORBIDDEN` | schema/catalog | catalog-owner | false |
| `KIND_BOUNDARY_VIOLATION` | author/compile | template-author | false |
| `GEOMETRY_INVALID` | prepare-data | source-owner | false |
| `GEOMETRY_ROLE_MISMATCH` | plan | data-binding | false |
| `JOIN_KEY_DUPLICATE` | prepare-data | source-owner | false |
| `JOIN_COVERAGE_INSUFFICIENT` | prepare-data | source-owner | false |
| `DATA_SEMANTICS_INVALID` | prepare-data/plan | data-owner | false |
| `DATA_VALUE_OUT_OF_RANGE` | prepare-data | source-owner | false |
| `FEATURE_OUTSIDE_APPROVED_EXTENT` | prepare-data/preview | data-owner | false |
| `ENCODING_SEMANTICS_INVALID` | compile/preview | portrayal | false |
| `TEMPLATE_NOT_VALIDATED` | publish | template-author | false |
| `PUBLISH_COMMIT_UNKNOWN` | publish | repository | true-after-query |
| `RENDER_RESOURCE_MISSING` | render | renderer/resource-owner | false |
| `RENDER_OUTPUT_MISMATCH` | render/validate | renderer | false |
| `PREVIEW_EVIDENCE_INCOMPLETE` | freeze | validation | false |
| `IMMUTABLE_ARTIFACT_CONFLICT` | publish/freeze | repository | false |

U-P2.1 起，新增错误必须进入稳定注册表或等价机器策略；不能只存在于本文。

---

## 七、证据目录与提交边界

### 7.1 证据目录

```text
reports/u-p2/
├─ scope-baseline/
├─ protocol/
├─ ownership/
├─ template-authoring/
├─ data/
├─ security/
├─ environment/
├─ render/
├─ publication/
├─ planning/
├─ freeze/
├─ recovery/
└─ regression/
```

报告不得包含密钥、完整业务数据行、真实行程或应急敏感坐标。Fixture 必须明确标注 synthetic。

### 7.2 子阶段提交边界

- U-P2.0：仅计划、决策、范围策略和实施日志；不改业务运行代码。
- U-P2.1：Schema、Policy、正反 Fixture、协议/所有权测试；不实现编排器。
- U-P2.2：只实现 MapScenario 草稿创建；不发布、不渲染。
- U-P2.3：只实现确定性渲染底座；不发布、不冻结。
- U-P2.4：只实现模板验证与发布；不生成地图锁。
- U-P2.5：只实现地图规划与候选编译；不调用浏览器、不签 G2。
- U-P2.6：只实现预览、G2 与锁；不实现 G3/交付。
- U-P2.7：只整合、恢复和验收，不增加新业务宽度。

---

## 八、范围基线一致性检查

原 `scope-baseline.yaml` 与 U-P2 计划存在三项冲突：

1. 声明 `geopackage`，但当前没有相应依赖、安全和自动测试。
2. 使用 `choropleth-risk`、`point-shelter`，与地图表达/符号资源分类不一致，且遗漏容量比例表达。
3. 输出名称看似正式 A3 成果，未明确 U-P2 仅生成工程预览，也未说明 PDF 不是全矢量。

本阶段将基线升级为 `0.2.0` 并保持 `pending_trusted_approval`。由于对象内容和摘要发生变化，任何旧批准均不得复用；进入能力启用前仍须由指定安全审批人和业务审批人针对新摘要批准。

---

## 九、退出检查

- [x] 来源格式已冻结：请求/元数据 YAML 或 JSON，数据 GeoJSON 和 CSV。
- [x] 表达已冻结：顺序面分级设色和容量面积比例符号。
- [x] 输出已冻结：A3 横版 SVG/PDF/PNG 工程预览，不宣称全矢量 PDF。
- [x] 洪涝 Fixture 的角色、字段、几何、CRS、时间和异常用例已冻结。
- [x] 两条路由的唯一 CLI 合同已定义，但未实现。
- [x] 协议差异、测试矩阵、错误码、证据目录和提交边界已列明。
- [x] 未验证能力已明确列为不开放。
- [x] 维护者确认 U-P2.0，并授权只进入 U-P2.1。
