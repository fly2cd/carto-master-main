# 地图制图智能体模板创建路由技术设计

## 文档信息

| 项目 | 内容 |
|---|---|
| 状态 | 实施建议稿，尚未实现 |
| 版本 | 1.1 |
| 更新日期 | 2026-09-11 |
| 适用对象 | 地图制图智能体、模板设计器、GIS 渲染适配器、模板治理工具 |
| 领域设计依据 | [地图模板体系设计](carto-template-dsg.md) |
| 配套实施计划 | [分阶段实施计划](implement-plan.md) |
| 核心产物 | 声明式模板包、验证证据、预览产物、不可变版本及发布记录 |

本版将技术实现收敛为“模块化单体内核 + 声明式模板包 + 确定性编译校验 + 独立渲染适配器”。保留四类模板，将单个 MapScenario 统一为六份业务契约；六种规则标签不再作为数值优先级；取消通用动态加载图；以统一发布操作替代独立安装、注册事务。

本次只更新 TRD。配套文档中尚存的八契约清单、规则优先级、动态加载单元和旧 CLI，应在实施前按本版对齐，不应视为并行可选实现。本文的目录、命令和接口均是 Carto Agent 的拟实现设计，不表示仓库已经提供这些能力。

> **U-P2 实施冻结说明（2026-09-17）**：U-P2 只开放 MapScenario 创建，来源限安全解析的 YAML/JSON、GeoJSON 和 UTF-8 CSV；实际 CLI 使用唯一入口 `carto create-template ...`。本文中更宽的来源和旧 `carto_template.py` 命令保留为后续目标，不属于 U-P2 已开放合同。详细决定见 [U-P2.0 实施说明](impl-log/U-P2.0说明文档.md)。

## 一、结论与设计取舍

地图模板创建是独立路由 `Create Map Template`，四个互斥子路由根据“稳定复用什么”选择：

- `create-map-brand`：地图身份模板，复用组织身份。
- `create-map-style`：制图表达规范，复用表达判断与视觉默认。
- `create-map-layout`：地图版式模板，复用品牌中性的版面或视口结构。
- `create-map-scenario`：制图场景方案，复用明确业务场景及其集成规则。

四个子路由只是同一流程的作者策略，不是四套编排系统。公共流程固定为：

```text
来源分析 → 简报确认 → 模板编写 → 校验与样例渲染 → 发布
```

地图必须保留数据含义、坐标参考系、量测、图层依赖、符号映射、多尺度、交付、许可和行业标准等专业约束。简化的是执行机制，不是这些约束。

| 保留 | 简化为 | 首期不建设 |
|---|---|---|
| 四类模板及分段所有权 | 一个编排器、四个作者策略 | 四套重复流程或微服务 |
| 六种规则语义 | 注册检查器、Schema、显式参数及字段绑定 | 任意表达式解释器、通用冲突求解器 |
| 确认边界与按需上下文 | 小契约一次解析，大资源延迟加载 | 动态触发器图及收敛循环 |
| 可复现执行 | 契约 → MapPlan → MapSpecLock | Markdown 与 YAML 双重执行权威 |
| 可恢复与安全发布 | 作业状态 + 当前步骤、单一发布入口 | 安装与注册分别对外提交 |
| 企业治理 | 可信审批、隔离、不可变版本、审计、备份 | 首期全引擎支持、完整 GIS 镜像能力 |

`MapStyle` 中文固定为“制图表达规范”；`MapScenario` 中文固定为“制图场景方案”，使用 `map-scenario`、`scenarios/`、`scenario.yaml`。不提供地图侧 `MapDeck` 等兼容别名。

## 二、目标、非目标与首期边界

### 2.1 目标

1. 从文字、参考地图、GIS 工程、样式和品牌材料创建可移植模板。
2. 以机器契约保存执行约束，以 Design Spec 解释设计理由。
3. 发布前完成适用的数据、空间、表达、视觉、许可与目标引擎验证。
4. 支持库级复用和项目私有使用，保持版本、证据与审批可追溯。
5. 未确认时只发现候选；确认后按需提供模型上下文和渲染资源。
6. 首个生产闭环采用 MapLibre Web + SVG overlay，覆盖“城市洪涝风险研判”场景，并由受控浏览器按交付合同派生可编辑 SVG、PDF 或 PNG。

### 2.2 非目标

- 不在创建路由中生产最终业务地图，Fixture 地图仅用于验证。
- 不修改参考文件，不把完整 GIS 工程自动判为场景模板。
- 不在模板中冻结当前业务数据路径、时间快照、具体范围或数据驱动断点。
- 不以 PNG、PDF、SVG 外观推断不可见的字段、CRS 或空间精度。
- 不允许适配器静默改变地图语义。
- 不把地图表达、符号、行业标准或交付配置增加为第五类模板。
- 不承诺首期提供移动端、ArcGIS、三维场景或完整 `mirror` 支持。

首期支持能力必须由版本化兼容清单和验证证据共同证明。原生工程解析可以只覆盖明确支持的 QGIS 子集；遇到未知插件、脚本或样式表达式必须报告，不自动执行。

## 三、领域对象与唯一执行权威

| 对象 | 职责 | 是否执行权威 |
|---|---|---|
| 模板包 | Manifest、业务契约、原型、必要资产和固定依赖的可移植集合 | 通过其契约提供规则 |
| Design Spec | 意图、来源、理由、适用与禁用条件、审查提示 | 不是参数解析来源 |
| 业务契约 | 可复用的数据、空间、表达和交付约束 | 是，发布后不可变 |
| 原型 | 展示完整地图结构和容量的中性示例 | 仅声明为绑定的结构元数据受约束 |
| Fixture | 合成或获准匿名化的小型验证数据 | 仅用于测试 |
| MapPlan | 当前项目模板选择、字段绑定、范围、目标及待决项 | 可修改的项目决策 |
| MapSpecLock | 预检、能力协商、预览及必要审批通过后的执行快照 | 当前运行的唯一冻结输入 |
| 验证报告 | 对指定内容和环境执行检查的证据 | 证明验证结果，不定义业务规则 |

```text
模板契约 + 固定依赖
        ↓ 确认、解析所有权
真实数据 + MapPlan
        ↓ 预检、预览、修订、必要审批
MapSpecLock
        ↓ 确定性适配编译与渲染
地图产物 + 诊断 + 审计证据
```

机器强制值只在契约中维护。Design Spec 的参数表宜从契约生成；人工撰写的理由通过字段路径引用契约，不重复维护一套参数。发现解释与契约冲突时必须修订并复验，不能让模型猜测哪份为准。

## 四、总体架构与目录

### 4.1 五个实现模块

| 模块 | 内部职责 | 主要输出 |
|---|---|---|
| 工作流编排 `workflow` | 路由、来源分析、简报、确认、四种作者策略、步骤恢复 | 作业记录、已批准简报、模板草稿 |
| 契约编译 `compiler` | Schema、固定依赖、所有权、标准适用性、参数归一化、目标选择 | `CompiledTemplate`、冲突清单 |
| 统一校验 `validation` | 注册检查器、Fixture、样例渲染、覆盖矩阵、统一报告 | 验证证据、预览、失败修复位置 |
| 渲染适配器 `adapters` | 能力探测、渲染包编译、隔离执行、产物检查 | 地图产物和引擎诊断 |
| 模板仓库 `repository` | 不可变包、发布、安装、发现、版本状态、审计引用 | 精确版本根目录、发布记录 |

这些是代码模块，不要求分别部署为服务。首期采用一个应用进程和受控浏览器渲染工作进程；共享部署按需使用数据库和对象存储，保持相同接口。审批、鉴权和审计属于各操作边界，不额外引入模板领域微服务。

模型可以提出简报、契约草稿和修复建议；发布权限、Schema 校验、空间计算、数值分类、哈希与门禁通过状态由确定性程序控制，不能由模型自报通过。

### 4.2 拟实现代码目录

`skills/carto-agent/` 是独立地图能力目录，不写入 `skills/ppt-master/`：

```text
skills/carto-agent/
├─ SKILL.md
├─ workflows/
│  ├─ routing.md
│  ├─ create-template.md
│  └─ create-template/              # 四类策略只记录差异
├─ references/
│  ├─ template-contracts.md
│  ├─ cartographic-quality.md
│  └─ renderer-capabilities.md
├─ scripts/
│  ├─ carto_template.py             # 单一 CLI
│  └─ carto_core/
│     ├─ workflow/
│     ├─ compiler/
│     ├─ validation/
│     ├─ adapters/webmap_renderer.py
│     ├─ adapters/svg_compositor.py
│     ├─ adapters/renderer_probe.py
│     └─ repository/
├─ schemas/
│  ├─ manifest.schema.json
│  ├─ template-brief.schema.json
│  ├─ identity.schema.json
│  ├─ cartography.schema.json
│  ├─ layout.schema.json
│  ├─ scenario.schema.json
│  ├─ data-role.schema.json
│  ├─ spatial-behavior.schema.json
│  ├─ portrayal.schema.json
│  ├─ delivery.schema.json
│  ├─ quality-gates.schema.json
│  └─ map-spec-lock.schema.json
├─ policies/
│  ├─ checker-registry.yaml         # 检查器元数据，不含任意执行表达式
│  └─ baselines/                    # 版本化平台质量基线
└─ templates/
   ├─ brands/<id>/<version>/
   ├─ styles/<id>/<version>/
   ├─ layouts/<id>/<version>/
   ├─ scenarios/<id>/<version>/
   ├─ delivery-profiles/
   ├─ map-types/
   ├─ symbols/
   ├─ standards/
   └─ indexes/                      # 发现视图，见第十二节
```

模板创建作业和地图生成项目分开：

```text
<build-workdir>/
├─ sources/
├─ analysis/
├─ template_brief.yaml
├─ approvals/
├─ staging/package/                # 待发布模板包
├─ reports/<validation-id>/
├─ previews/<validation-id>/
├─ steps/                          # 步骤回执
└─ run-state.json

projects/<project-id>/carto/
├─ sources/
├─ data/
├─ templates/installed/<kind>/<id>/<version>/
├─ plan/map-plan.yaml
├─ locks/<lock-id>/map-spec-lock.yaml
├─ output/<lock-id>/
├─ reports/
└─ run-state.json
```

上述目录是实施目标，本次文档更新不创建它们。实际增加 Carto 代码前须调整仓库入口及测试位置规则；当前仓库的既有测试目录限制仍然有效，不在文档任务中绕过。

## 五、路由判定

### 5.1 顶层边界

| 用户目标 | 路由 |
|---|---|
| 创建跨项目复用的地图规则或场景模板 | `create-template` |
| 用数据生产业务地图 | `generate-map` |
| 保留原生工程并编辑其中内容 | `edit-native-map` |
| 新增表达、符号或行业标准条目 | `curate-catalog` |

本 TRD 只实现创建路由及其与地图生成的交接协议，不展开其他路由的完整实现。

### 5.2 四种作者策略

| 类型 | 拥有 | 不拥有 | 包内业务契约 |
|---|---|---|---|
| MapBrand | 组织色板、字体、Logo、署名风格 | 风险色语义、CRS、图层、业务数据、地图结构 | `identity.yaml` |
| MapStyle | 视觉层级、标注、概化与表达原则、低优先级默认 | 固定业务应用、组织身份、固定画布 | `cartography.yaml` |
| MapLayout | 中性画布、地图框、标题、图例槽、附图槽、容量与响应布局 | 业务图层、专题编码、实际地理范围 | `layout.yaml` |
| MapScenario | 场景合同、数据角色、空间行为、业务表达、集成身份和结构 | 当前项目数据、实际范围、最终分类断点 | 第十节六份契约 |

先判断用户是否明确只复用身份、表达规范或中性结构；否则，若存在与数据角色、结构或身份关联的重复业务场景，选择 MapScenario。仍有歧义时只询问“要复用哪个范围”，不根据文件格式或源工程完整度猜测。

身份、表达规范和版式的独立作者策略不能生成虚假的场景契约。Brand 和 Style 不需要地图原型，但其资产、字体、规则及依赖仍须验证。

## 六、来源模型与创建模式

### 6.1 来源登记

| 来源 | 可提取内容 | 限制 |
|---|---|---|
| QGIS 等原生工程 | 图层、CRS、布局、渲染器、数据引用 | 只承诺受支持版本和特性 |
| 样式文件 | 符号、过滤、标签、比例尺和表达式 | 未审查表达式不得直接执行 |
| SVG、PDF、PNG 等地图成品 | 可见结构、文字和视觉事实 | 不证明隐藏数据和空间精度 |
| 地理数据、CSV | 几何、字段、CRS、分布和质量 | 默认不进入发布包 |
| 文档、直接文本、品牌资产 | 用途、受众、规则、身份和许可 | 记录事实与建议的区别 |

每项来源记录规范化路径或 URI、媒体类型、内容哈希、提取器版本、许可、时间和可信程度。结论标记为 `fact`、`decision`、`suggested` 或 `derived`。敏感路径只保存在受控作业记录中，日志和发布包使用脱敏标识。

### 6.2 创建模式

| 模式 | 含义 | 首期范围 |
|---|---|---|
| `standard` | 依据目标建立紧凑、代表性的规则和原型 | 正式支持 |
| `fidelity` | 保留参考的主要设计语言，仍移除业务数据 | 受支持输入子集，列明差异 |
| `mirror` | 保留源工程中已证明可解析的语义与依赖身份 | 延后，不自动承诺 |

只有已具备闭合解析和回归验证的适配器才能接受 `mirror`。仅有截图或 PDF 时最多采用 `fidelity`。不支持的模式必须返回能力错误，由用户修订简报，不得静默降级。

## 七、作业状态、审批与发布事务

### 7.1 简化状态模型

作业使用两个正交字段，不为每个中间文件创建状态：

```yaml
status: running
step: validate
attempt: 1
run_id: urban-flood-risk-20260911
input_fingerprint: sha256:<digest>
last_receipt: steps/author.json
```

- `status`：`pending`、`running`、`waiting_approval`、`failed`、`succeeded`、`cancelled`。
- `step`：`analyze`、`brief`、`author`、`validate`、`publish`。
- 包生命周期另用 `draft`、`validated`、`published`，由作业或仓库记录维护，不写回已发布包。

每步回执保存输入指纹、产物哈希、工具版本、起止时间和结果。恢复时复查指纹，只有全部前提仍成立才复用；从最早受影响的步骤重跑。取消和失败都不能使半成品进入发现目录。

### 7.2 可信审批

简报确认绑定：批准人、认证来源、权限、批准动作、简报摘要、目标作用域、环境和时间。自动化可以使用受信审批系统签发的回执，但必须验证签发方、签名或服务端记录、授权范围、有效期及防重放标识。

内容哈希只能证明“批准的是哪份内容”，不能证明“谁批准了它”。任意上传一个含哈希的文件、手填用户名、打印确认标记或传入 `--yes` 均不能代替审批。

发布审批与简报审批分开：前者还绑定最终包摘要、验证证据摘要及目标库。身份权限由平台校验，模型无权签发通过。单用户本地模式可以信任已登录的操作系统用户并记录显式确认，但必须说明该信任边界，不能宣称具备多人职责分离。共享企业库应按角色控制创建、审查、发布权限；是否强制双人复核由部署政策规定。

### 7.3 单一发布事务

外部只提供 `publish`，内部完成包落地和注册。唯一键为 `namespace + kind + id + version`，其中本地可使用固定命名空间。

1. 校验权限、审批、包摘要、有效验证证据、依赖和目标冲突。
2. 将完整包及证据持久化到不可变位置，完成文件系统持久化屏障或对象存储写入确认，并读回校验后才准备公开。
3. 在注册表事务内提交版本记录、证据与审批引用；提交成功即为对发现端可见的时点。
4. 返回发布回执；更新发现视图失败可以重试，不重新发布或改写包。

相同幂等键和相同摘要返回已有结果；不同摘要占用相同版本必须拒绝。不能认为“目录原子重命名 + 索引原子替换”天然构成一个整体事务。

| 部署 | 一致性策略 |
|---|---|
| 本地库 | 单写者锁下先落地完整包，再原子替换单份该类型索引；只有索引中的记录可被发现。崩溃遗留的未引用包不可见，可重试接管 |
| 共享企业库 | 数据库注册表是权威，唯一约束与事务负责发布；对象存储或文件库先完成持久化，JSON 索引仅为可重建视图 |
| 项目私有 | 包完整落地后原子更新项目安装记录，不改全局库；继续使用相同摘要和证据规则 |

网络超时后先按幂等键查询提交结果。并发修改需版本检查或比较交换，不能“最后写入覆盖”。弃用、撤回与回滚修改注册表选择状态，不修改既有版本；旧项目保留已固定版本，已撤回版本是否允许继续执行由安全政策决定。

## 八、创建路由完整流程

### Step 1：来源分析

- 校验意图、kind 候选、命名空间、ID、版本及 `library/project` 作用域。
- 项目作用域须有已初始化项目；库路径和工作区均解析为允许根下的绝对路径。
- 登记来源，按格式启用一个受支持分析器，输出事实、资产、依赖和未知特性清单。
- 允许分析用户明确提供的参考材料；候选模板正文仍受确认边界约束。

输出 `analysis/source_manifest.yaml`、`analysis/observations.yaml` 及按需分析报告，不创建最终库目录。

### Step 2：生成并确认简报

简报包含 kind、ID、版本、用途、受众、可复用意图、禁用场景、创建模式、作用域、正式交付目标、实验意向、数据角色、空间适用范围、目标引擎、来源许可和未决项。

仅在用户明确确认且审批回执有效后允许编写。批准后可记录 `[CARTO_TEMPLATE_BRIEF_CONFIRMED]` 作为审计标签，但标签本身不是凭据。候选发现和 Manifest 可先读；完整规范、内部契约、原型和资产要在确认后读取。

### Step 3：编写模板

- 在 `<build-workdir>/staging/package/` 创建草稿；选择唯一 kind 作者策略。
- 生成第九、十节规定的 Manifest、契约、必要资产和完整原型。
- 固定依赖版本及摘要，生成 `dependencies.lock.yaml`。
- Brand/Style 不生成地图原型；Layout/Scenario 使用合成数据展示完整地图或视图。
- MapBrand 仅使用 `primary/accent/surface/ink` 等身份 token；水体、风险级别不是身份 token。
- 印刷结构分别声明物理尺寸与 SVG 逻辑坐标。例如 A3 横向为 420 × 297 mm，`viewBox` 可以为 4200 × 2970，不能混用两种单位。

### Step 4：统一校验与样例渲染

`validate --render` 一次编排：

```text
语法/Schema → 文件/依赖完整性 → kind/所有权 → 数据/空间/表达语义
→ 目标能力协商 → Fixture 渲染 → 视觉/性能/产物检查 → 验证证据
```

静态失败时不启动昂贵渲染。Brand/Style 输出规范和资产检查报告；Layout/Scenario 在每个正式目标上验证原型及必要边界 Fixture。

预览、报告和 Fixture 执行锁写入作业目录，不回写模板包。验证前后复核包摘要，避免验证期间内容被改写。证据绑定包摘要、依赖摘要、Fixture 摘要、基线及检查器版本、适配器和环境指纹；证据摘要按排除摘要字段自身的规范化证据清单计算。报告中的 `blocker/error` 非零不能通过。

修复在拥有问题的层完成，校验器不直接改契约。包、依赖、验证数据或相关环境变更后，原证据失效；至少重跑受影响的验证，首期允许完整重跑以降低实现复杂度。

### Step 5：发布并交接

验证通过、发布审批有效后执行第七节事务。返回精确的带版本包路径、摘要、验证结果、预览和证据位置、发布状态与未支持项。

地图生成仍需确认本次制图合同及模板选择；不能用创建简报的批准替代业务地图的确认。地图生成接收精确包版本，不接收裸名称或内层 `templates/` 目录。

## 九、模板包规范

### 9.1 通用结构与摘要

```text
<template-root>/
├─ manifest.yaml
├─ templates/design_spec.md
├─ contracts/
├─ prototypes/                    # MapLayout/MapScenario 按需
├─ components/                    # 有复用组件才创建
├─ assets/                        # 有实际资产才创建
├─ fixtures/                      # 验证数据，不供业务运行绑定
├─ dependencies.lock.yaml
└─ checksums.sha256
```

空的可选目录不创建。报告和预览保存于作业证据目录或发布证据存储，不混入运行时输入。原型可随包发布，但不会自动成为业务地图。

`runtime_files` 是允许业务运行读取的内容白名单；Manifest、依赖锁和校验清单是安装器读取的包元数据，不需重复列入该白名单。`checksums.sha256` 覆盖包内全部文件，包括非运行时 Fixture，但不包含自身。对按规范化相对路径排序的“路径 + 文件摘要”清单计算 `package_digest`，存入验证报告和注册表，避免 Manifest 自包含哈希循环。

`dependencies.lock.yaml` 固定直接及传递依赖的 ID、精确版本、摘要和来源。依赖解析在构建时完成，发布和项目安装时验证；运行时不重新寻找“最新可用版本”。依赖锁与文件摘要属于包基础设施，不计为业务契约。

### 9.2 Manifest 示例

以下为城市洪涝场景包的示意清单，`<digest>` 须由构建工具替换为真实摘要：

```yaml
schema_version: 1
kind: map-scenario
id: urban-flood-risk
version: 1.0.0
display_name: 城市洪涝风险研判图
summary: 面向应急研判的城市洪涝风险制图场景方案
keywords: [洪涝, 风险, 应急, 城市]
creation_mode: standard
license: CC-BY-4.0
spatial_applicability:
  geometry: [Polygon, MultiPolygon, Point]
  scale_denominator: [10000, 500000]
targets:
  print-a3:
    status: supported
    adapter: maplibre-web
    engine_version_range: ">=3.6,<4.0"
experimental_intents: [web-dashboard]
dependencies:
  - id: choropleth/sequential
    version: 1.2.0
    digest: sha256:<digest>
  - id: proportional-symbol/count
    version: 1.0.0
    digest: sha256:<digest>
dependency_lock: dependencies.lock.yaml
runtime_files:
  - templates/design_spec.md
  - contracts/scenario.yaml
  - contracts/data.schema.yaml
  - contracts/spatial-behavior.yaml
  - contracts/portrayal.yaml
  - contracts/delivery.yaml
  - contracts/quality-gates.yaml
  - prototypes/01_risk_overview.svg
  - assets/logos/agency-logo.svg
prototypes:
  - id: risk_overview
    path: prototypes/01_risk_overview.svg
resources:
  - id: agency-logo
    path: assets/logos/agency-logo.svg
    media_type: image/svg+xml
validation_fixtures:
  - id: flood-risk-base
    data:
      risk_regions: fixtures/risk-regions.geojson
      shelters: fixtures/shelters.geojson
    metadata: fixtures/dataset-metadata.yaml
```

Manifest 只保存发现元数据、固定引用和正式目标声明，不保存规则全文，不提供可执行 `trigger`。契约文件集合由 kind 的 Schema 确定，不通过目录扫描推测；资源由精确 ID 引用。

`experimental_intents` 仅记录未交付意向，不参与可用能力检索，也不能被生产任务选为输出目标。将其转为正式目标必须补齐契约、适配器、Fixture 和验证证据，并发布新版本。Manifest 的版本范围表达兼容声明，具体运行仍固定实际引擎版本和环境指纹；不得将单一版本的测试解释为对整个范围的充分验证。

### 9.3 人读说明、结构与强制参数

Design Spec 说明设计意图、适用性、来源、默认选择理由和审查重点。可执行参数必须在业务契约或固定依赖中有唯一字段归属；编译器不从自然语言提取强制规则。

固定槽位、页面尺寸和容量属于 `layout` 分段；SVG 是中性结构原型，不再独立定义一套坐标真值。绑定的槽位元数据应由布局契约生成或逐项校验。仅作参考的几何允许适配，但不能改变数据语义、被绑定的结构和必需信息。

## 十、六份场景契约与规则执行

### 10.1 数量、位置与所有权

MapScenario 的 `contracts/` 恰好包含六份业务契约：

| 文件 | 内容 | 实例化后的去向 |
|---|---|---|
| `scenario.yaml` | 应用合同、内置身份、表达规范、版式及可替换分段 | 场景目标和所有权结果 |
| `data.schema.yaml` | 数据角色、字段、单位、几何、关联、时效和许可前提 | 真实字段与快照绑定 |
| `spatial-behavior.yaml` | CRS、量测、范围、尺度、概化、空间有效性 | 真实 CRS、范围和尺度策略 |
| `portrayal.yaml` | 图层依赖、显示顺序、数据编码、符号、标签、图例 | 实际图层和数据到符号映射 |
| `delivery.yaml` | 输出目标、媒介、图册、响应与交互参数 | 目标特定执行参数 |
| `quality-gates.yaml` | 质量基线引用、已注册检查器和允许参数 | 检查计划；结果写报告 |

合并关系：

- 原 `spatial.yaml` 与 `multiscale.yaml` 合为 `spatial-behavior.yaml`。
- 原 `layer-graph.yaml` 与 `encoding-bindings.yaml` 合为 `portrayal.yaml`。

加上其他三类模板各自的 `identity.yaml`、`cartography.yaml`、`layout.yaml`，整个系统共九种业务契约文件类型，而不是每个模板都有九份。MapScenario 的内置身份、表达和版式放在 `scenario.yaml`，复用相应 Schema 定义，不再额外复制三份文件。

Manifest、依赖锁、Schema、平台检查器注册表、质量报告和 MapSpecLock 都不计入这六份契约。Brand、Style、Layout 的通用门禁由平台根据 kind 和交付目标施加，不为满足数量统一而创建空的 `quality-gates.yaml`。

### 10.2 场景契约

`scenario.yaml` 持有场景目标、适用条件、禁用条件和三个完整内置分段：

```yaml
application:
  audience: 城市应急指挥中心
  decision_goal: 识别高风险区域并核对避难资源覆盖
  required_roles: [risk_regions, shelters]
  excluded_uses: [法定灾害预警发布, 工程测量]
embedded:
  identity: {}       # 此处简写；实际须符合 identity Schema
  cartography: {}    # 实际须符合 cartography Schema
  layout: {}         # 实际须符合 layout Schema
replaceable_segments: [identity, cartography, layout]
```

上述片段仅说明结构，不是可通过 Schema 的完整文件。独立模板可以整段替换内置分段，但不能删除场景所必需的数据角色、预警语义或交付义务；替换后不兼容应报错，而不是从被替换分段偷偷补字段。

### 10.3 数据契约

`data.schema.yaml` 是数据角色的领域配置，以 `data-role.schema.json` 校验，并非直接把业务数据当作 JSON Schema 文档：

```yaml
roles:
  risk_regions:
    geometry: [Polygon, MultiPolygon]
    primary_key: region_id
    fields:
      region_id: {type: string, nullable: false}
      risk_rate:
        type: number
        measure_kind: rate
        unit: percent
        minimum: 0
        maximum: 100
        nullable: true
    null_policy: explicit-no-data
  shelters:
    geometry: [Point]
    primary_key: shelter_id
    fields:
      shelter_id: {type: string, nullable: false}
      capacity: {type: integer, unit: person, minimum: 0, nullable: false}
freshness:
  maximum_age: P1D
  timestamp_role: observation_time
license_policy: redistributable-or-project-local
```

时效字段可以来自可信数据集元数据，不得用文件复制时间代替观测时间。存在 Join 时必须声明关联角色、键、基数、重复处理和覆盖率要求；无关联操作时不运行 Join 检查。人口绝对量不得绑定为风险率；`0–1` 比率转换为百分数必须显式记录单位换算。

### 10.4 空间与多尺度行为契约

`spatial-behavior.yaml` 统一管理空间策略与尺度依赖行为：

```yaml
spatial:
  accepted_source_crs: [EPSG:4490, EPSG:4326]
  analysis_crs_policy: derive-for-operation
  display_crs_policy: delivery-dependent
  extent_policy: data-bounds-with-padding
  geometry_validity: repair-with-report
  topology:
    non_overlapping_roles: [risk_regions]
  antimeridian_policy: split-and-wrap
  polar_policy: require-explicit-projection
scale:
  denominator_range: [10000, 500000]
  generalization:
    preserve_topology: true
    displacement_limit: {value: 0.2, unit: mm-at-output-scale}
```

明确数据存储 CRS、分析/量测 CRS 和显示 CRS 的不同职责。面积统计优先选择适用的等面积或明确的椭球面积算法；距离和缓冲使用满足误差预算的投影或测地算法，不能一律使用显示 CRS。

概化策略还须明确适用角色、最小保留面积、聚合方式和符号/标签尺度规则。几何筛选、聚合和概化阈值由空间契约拥有；尺度变化时的符号尺寸和标签密度由表达契约拥有，以同一尺度键关联，不在两个文件重复定义。误差约束带单位，实施时换算为引擎参数并验证拓扑。修复无效几何须保留原始数据摘要、修复算法和变化报告；超过批准容差必须返回上游。

是否处理反经线、极区等边界由声明的空间适用性决定；不支持的输入要可预测地拒绝，不要求每个城市模板都实现全球投影。

### 10.5 图层与表达契约

`portrayal.yaml` 同时定义图层节点及其编码，减少跨文件同步：

```yaml
layers:
  - id: risk_fill
    source_role: risk_regions
    order: 10
    depends_on: []
    encoding: flood_risk_fill
  - id: shelter_points
    source_role: shelters
    order: 20
    depends_on: []
    encoding: shelter_capacity
bindings:
  flood_risk_fill:
    map_type: choropleth/sequential
    value_field_role: risk_rate
    normalization: none
    classification:
      allowed: [jenks, quantile]
      preferred: jenks
      classes: {min: 4, max: 7, preferred: 5}
    visual_variable: fill-color
    monotonic: true
    null_symbol: no-data-hatch
    legend_sync: required
  shelter_capacity:
    map_type: proportional-symbol/count
    value_field_role: capacity
    visual_variable: symbol-area
    negative_values: reject
labels:
  density_policy: scale-dependent
```

图层计算依赖应构成 DAG，但父子组织、绘制顺序、Join 和遮罩必须使用明确类型，不把所有关系混成一种边。检查未知角色、缺失必需层、环、裁剪引用和不确定绘制顺序。符号尺寸的面积映射不能被误写为半径线性映射。

数据驱动的分类算法、空值、异常值、并列值和不足类别数处理必须可验证。实际断点保存到项目锁；若采用行业固定阈值，则模板可引用版本化标准，而不是假称由项目数据计算。图例必须由实际编码结果生成。

多图比较须声明是否共享断点、范围和色阶。标签优先级、避让、最小字号与不确定性表达遵循当前表达规范，不能为“好看”隐去必需标签或无数据区域。

视觉检查按目标覆盖色阶可辨性、常见色觉缺陷、灰度可读性、对比度、标签碰撞与截断、地图框裁剪及必需信息完整性。自动检查无法充分判断的空间叙事或专业风险交由指定审查人确认，不将其伪装成可自动证明的结论。

### 10.6 交付契约

`delivery.yaml` 只保留已正式支持目标的配置：

- 印刷：纸张物理尺寸、方向、DPI、安全区、出血、最小字号、线宽、颜色与字体处理。
- 图册：图幅编号、奇偶页装订边、索引、接图关系、共享图例与系列一致性。
- Web：视口断点、缩放、交互、瓦片、首屏资源和性能预算。
- 移动端：安全区、触控区域、横竖屏、弱网、离线及定位权限策略。

媒介依赖策略引用固定版本的 Delivery Profile。布局契约拥有槽位结构，交付契约拥有输出约束；两者冲突应失败，不通过重复声明同一参数覆盖解决。超出适配器能力的 CMYK、字体嵌入或交互能力不能标为已支持。

### 10.7 六种规则标签，不是优先级阶梯

沿用 `hard_rule`、`forbidden`、`mandatory`、`binding`、`default`、`reference` 六种作者语义，取消 L1～L6 的解析先后含义。

| 标签 | 含义 | 执行方式 |
|---|---|---|
| `hard_rule` | 适用范围内必须成立的不变量 | Schema、注册检查器或流程门禁 |
| `forbidden` | 明确禁止的动作、值或状态 | 负向断言或安全门禁 |
| `mandatory` | 满足已定义条件时必须具备的内容 | 平台检查器依据类型化条件判断 |
| `binding` | 已确认字段必须保留 | 比较字段与确认值、来源和版本 |
| `default` | 信息不足时的回退值 | 存在明确决定时覆盖，记录来源 |
| `reference` | 可自由采用、调整或放弃的参考 | 不进入阻断检查 |

这些标签区分约束性质，不建立通用大小顺序。适用的硬约束须同时成立；不能用另一个标签“覆盖掉”条件必需项。法规与行业标准也必须先验证版本、辖区和适用范围，不是所有标准都对所有地图自动生效。

规则准入须有可判断的边界。审美偏好不能直接升级成硬规则；绑定需要精确字段和可信来源；默认与参考放在所属业务契约，不生成冗长的门禁对象。偏离默认时记录决策来源或理由，不要求用户逐项批准；未采用参考无需说明。

### 10.8 注册检查器与质量门禁

`quality-gates.yaml` 只引用受信平台已有检查器及允许参数：

```yaml
baseline: carto-print@1.0.0
checks:
  - id: data.join-coverage
    params:
      min_ratio: 0.98
  - id: portrayal.legend-sync
```

98% 是业务参数示例，不是地图行业统一标准。无 Join 时该检查记录 `not_applicable`，不能伪报 `passed`。

注册表按版本定义检查器的参数 Schema、适用条件、阶段、约束标签、失败严重度、修复所有者及受信代码入口。示意：

```yaml
id: data.join-coverage
version: 1.0.0
strength: mandatory
phase: validate
applicability: {requires: join}
parameter_schema: join-coverage-params@1
failure_severity: error
repair_owner: data-binding
implementation: registered:data_join_coverage
```

`requires: join` 属于平台枚举，不是模板作者可执行的表达式。程序实现条件判定，不使用 `eval`，不允许模板提供 Python、SQL 或任意触发脚本。

平台按 kind、目标和适用行业规范确定最低基线；模板可以引用兼容基线并收紧可配置阈值，不能删除必需检查、降低最低阈值或把错误改成警告。检查器和基线变更通过平台版本发布；新模板需求先扩展受审查的检查器，不新增通用解释器。

存在用户绑定时，MapPlan 保存 `path/value/provenance/approval_ref`，平台绑定检查器负责核对。质量契约不复制所有绑定值。

### 10.9 结果严重度与证据

| `result_severity` | 处理 |
|---|---|
| `blocker` | 审批、安全、合同无解或发布完整性失败，停止当前流程 |
| `error` | 契约或产物不满足要求，验证失败，修复后重跑 |
| `warning` | 非阻断风险，需要显式处置记录 |
| `info` | 推导、默认覆盖等审计事实，不影响通过 |

严重度由平台检查器或操作门禁决定，不从六种标签简单换算。所有硬约束的实际违反都必须阻止进入不满足前提的阶段。不可评估的必需检查属于失败，不能按“不适用”跳过。

```yaml
check_id: portrayal.legend-sync
checker_version: 1.0.0
strength: hard_rule
status: failed
result_severity: error
observed: 图例包含未在渲染分类中出现的断点
artifact: previews/<validation-id>/risk_overview.png
evidence_ref: reports/<validation-id>/legend-sync.json
repair_owner: portrayal
retry_from: author
```

`status` 使用 `passed/failed/not_applicable`。报告同时记录内容、环境与检查器版本，不只输出“违反规则”。执行检查统计不包含 `reference`；默认采用与覆盖另记决策日志。

## 十一、分段组合、编译与实例锁

### 11.1 分段所有权

| 分段 | 决策来源 |
|---|---|
| 场景合同、必需业务角色 | MapScenario |
| 组织身份 | 显式 MapBrand，否则场景内置身份 |
| 制图表达规范 | 显式 MapStyle，否则场景内置规范 |
| 版面结构 | 显式 MapLayout，否则场景内置结构 |
| 字段含义、单位、时间和空间前提 | 数据契约及预检证据 |
| 数据到视觉映射 | 场景表达契约、Map Encoding 和真实数据 |
| 交付约束 | 选定 Delivery Profile 与目标配置 |
| 法定符号及强制内容 | 经适用性验证的行业或法规配置 |
| 当前项目值 | 已确认 MapPlan，最终冻结为 MapSpecLock |

同类型外部模板整段替换内置分段，不逐字段拼接。替换的是决策来源，不豁免数据语义、平台安全和适用标准。

### 11.2 确定性编译

1. 校验所有选定包、固定依赖及平台基线。
2. 一次解析选中包的全部小型机器契约，执行 Schema 校验。
3. 按固定所有权表选择完整分段，保留未采用分段的来源记录。
4. 确定目标、地域、数据角色和标准适用性。
5. 合并独立维度的约束，检查它们能否同时满足；同字段冲突不得静默折中。
6. 对未决字段应用默认，把参考材料留给模型按需读取。
7. 输出规范化对象与冲突清单。

```yaml
compiled_template:
  package_refs: []
  dependency_refs: []
  ownership: {}
  scenario: {}
  identity: {}
  cartography: {}
  layout: {}
  data_roles: {}
  spatial_behavior: {}
  portrayal: {}
  targets: {}
  validation_plan: []
  provenance: {}
```

不适用于当前 kind 的分段可缺省，由 Schema 约束。这里是内部模型，不增加模板业务文件。首期使用类型化规则和确定性字段检查，不求解任意用户表达式。

### 11.3 MapSpecLock 边界

地图生成侧在真实数据绑定、预检和预览通过后冻结：

- 选定模板、依赖、基线和数据快照摘要。
- 所有权结果、字段单位、分类断点、色板、图层语义及标准引用。
- 实际范围、分析/量测 CRS、空间变换和概化参数。
- 每个目标的显示 CRS、纸张或视口、标签参数、适配器及环境指纹。
- 默认覆盖、显式降级、审批引用和验证证据。

锁分为共享语义与 `targets` 参数。印刷与 Web 不要求相同显示 CRS、标签密度或交互，但不得改变字段含义和标准符号；涉及分类口径的目标差异必须被场景明确允许并单独说明。

预览使用候选计划的确定性快照，批准后冻结同一摘要。冻结后任何影响结果的更改都产生新锁、新输出目录并重新验证，不编辑旧锁。模板创建的 Fixture 锁只留作验证证据，不随模板成为下一项目的执行参数。

## 十二、发现与简化惰性加载

### 12.1 索引与确认边界

四类发现视图仍为：

```text
templates/indexes/
├─ map-brands.index.json
├─ map-styles.index.json
├─ map-layouts.index.json
└─ map-scenarios.index.json
```

本地模式由各类型索引承担该类型的发布发现权威；共享模式以注册表为权威，上述文件由其生成。索引只保留精确版本路径、摘要、适用条件、依赖摘要、正式目标、许可和包摘要，不内嵌设计正文。

不扫描目录补全候选，不把裸名称自动当作路径。未注册模板需用户提供精确根目录，作为 `explicit` 候选；私有模板也不能绕过完整性与生产运行门禁。

### 12.2 四级边界，三种不同“加载”

| 层级 | 程序读取 | 模型上下文 | 延迟内容 |
|---|---|---|---|
| L0 发现 | 索引或注册表摘要 | 少量候选摘要 | 全部模板正文 |
| L1 候选 | 候选 Manifest | 适用条件、目标与冲突摘要 | 业务契约、原型、资产 |
| L2 确认后规划 | 安装并校验选中包，解析其全部小型机器契约及固定规则依赖 | 当前所有者的完整决策规则与必要解释 | 大型参考、原型图像、资产解码、渲染器模块 |
| L3 执行 | 按锁定目标和精确引用加载资产与适配器 | 当前操作所需的规则和诊断 | 其他引擎、未使用资源 |

程序解析 YAML、向模型注入文字、加载 GIS 引擎或解码资产是三件不同的事。安装校验可能为哈希读取全部包字节，但不等于把全部内容注入模型，也不等于启动所有引擎。

### 12.3 不使用动态加载图的算法

```text
索引发现 → Manifest 候选检查 → 确认制图合同与模板选择
→ 安装精确版本并验摘要 → 一次解析小契约与固定规则依赖
→ 解析所有权、标准与正式目标 → 输出类型化决策上下文
→ 按明确资源 ID 加载资产 → 仅启动选定适配器
```

目标由已确认请求和支持清单确定；资源来自已编译规则或选定原型的精确引用。更换目标时重新校验并编译，不依靠新事实不断激活任意触发器。固定依赖图仍需在构建和安装时检查缺失与循环，但它是版本依赖解析，不是每次决策都运行的动态加载调度器。

Manifest 不再定义 `load_units`、`owner_unit` 或脚本化 `trigger`。对文档说明按段读取时，必须读取完整的相关规则及限定条件；不得截断成只剩偏好、丢失禁用条件的片段。

### 12.4 不能被延迟的内容

- 所有适用硬约束、禁止项、条件义务和字段绑定，在相关决策前必须已解析并验证。
- 平台安全、发布权限与最低质量基线始终执行，不能由模板选择关闭。
- 标准的适用性和语义必须在符号选择前确定；大体积符号文件可以在之后加载。
- 文件越界、摘要不匹配、依赖缺失或必需能力不可用时停止，不使用相似模板或旧资源替代。
- 未选模板以及被替换的内置分段不能继续影响有效决策。
- 模型需要作出判断时，应收到该判断的完整有效约束；程序端也要独立验证模型产出。

### 12.5 缓存与回执

首期只保留两类缓存：

1. 由来源摘要及分析器版本确定的分析缓存。
2. 由包与依赖摘要、Schema/编译器/基线版本、选定目标及相关数据预检摘要确定的编译缓存。

小契约改变时完整重编译，不建设细粒度下游失效图。渲染复用还须匹配锁、数据、资源、适配器和环境摘要，不能只检查模板版本。

回执记录选定包、编译指纹、目标、实际引用资源、适配器和未加载原因即可，不维护逐单元触发证据。后续只有性能测量证明必要时才引入细粒度缓存。

### 12.6 发布覆盖

发布前按“正式目标 × 原型 × 必要边界 Fixture”矩阵验证。覆盖原则由质量基线确定，不要求无意义的全组合，但任何被声明支持的目标与必需分支都必须有证据。报告记录 `supported_targets`、`coverage_matrix`、`unverified_claims`，正式发布要求最后一项为空。

运行时惰性加载不能减少发布验证。未实现的目标只能进入实验意向，不能通过“未触发”逃避检查。

## 十三、渲染适配器与隔离运行

### 13.1 能力接口

```text
capabilities(environment) -> AdapterCapabilities
compile(resolved_snapshot, target_id) -> RenderPackage
render(render_package, resource_bindings, limits) -> RenderArtifacts + Diagnostics
```

`resolved_snapshot` 是验证用候选快照或已冻结 MapSpecLock，不能是尚有待决项的 MapPlan。能力记录区分适配器版本与实际引擎版本，并包含字体、CRS 数据库、GDAL/PROJ、插件及运行环境信息。

适配器只转换实现形式，不重新决定字段、分类、图层语义和标准符号。缺少必需能力直接失败；只有契约允许的可选回退才能生效，并写入计划、证据和锁。目标有实质变化时需重新确认。

### 13.2 首期 MapLibre Web + SVG overlay 最小能力

- 将已解析的矢量数据、样式和版面元素编译为版本化 `RenderScene`，不在前端重新决定业务语义。
- 支持矢量图层、顺序分级设色、容量比例符号、图层顺序、基础标注和图例。
- 使用 SVG overlay 表达图名、图例、比例尺、指北针、署名和复合专题符号。
- 由受控浏览器完成 WebGL 握手、资源加载和截图，合成可编辑 SVG，并按目标合同派生 A3 PDF/PNG。
- 固定字体、视口、DPR、资源摘要和渲染器版本；字体、最小线宽、裁剪与无数据表达均须检查。
- 不支持的 MapLibre 表达式、资源类型或 overlay 类型出具清单，不静默丢弃。

比例尺必须依据当前地图框、CRS 和量测方式生成，不能仅在槽位填入任意文本。指北针和经纬网是否必需由目标和空间契约决定，不能套用“每张地图都必须有”的规则。

### 13.3 工作进程保障

受控浏览器渲染器在独立进程中执行，按作业限制超时、内存、CPU、临时磁盘、输出体积和并发。进程隔离不等同于安全沙箱；多租户或不可信输入场景须使用容器或操作系统沙箱限制文件与网络访问。

工作进程只获得该作业的数据和资产引用，默认无任意网络、数据库凭据及其他租户目录权限。取消须终止子进程树，释放文件锁，记录部分输出为失败产物；不得标记成功。只对暂时性资源或网络错误有限重试，确定性的契约错误直接返回修复层。

固定环境、字体、随机种子及排序保证可重放。PDF 时间戳等非语义字节差异需规范化比较，不承诺跨平台逐字节相同；语义、布局和视觉容差必须有明确验收。

## 十四、命令行与应用接口

### 14.1 单一 CLI

以下均为拟实现接口，命令参数必须经过类型及路径校验：

```text
carto_template.py analyze <sources...> --workdir <path>
carto_template.py brief <workdir> --kind <kind> --scope <scope> --id <id> --version <version>
carto_template.py confirm <workdir> --action brief --approval-receipt <receipt>
carto_template.py author <workdir>
carto_template.py validate <workdir> --render [--target print-a3]
carto_template.py confirm <workdir> --action publish --approval-receipt <receipt>
carto_template.py publish <workdir> --repository <root> [--dry-run]
carto_template.py status <workdir>
carto_template.py resume <workdir>
carto_template.py cancel <workdir>
```

`confirm` 验证外部可信审批回执；本地交互确认模式由宿主获取登录身份并记录动作，不能靠模型生成回执。发布审批请求可从验证结果获取待批准的包、证据和目标库摘要。

`validate --render` 包含预览，无需单独的预览状态或 `preview` 命令。`--target` 只控制本次验证子集，发布仍要求覆盖全部正式目标。Brand/Style 自动执行适用检查，不启动虚构的地图渲染。

`publish` 内部完成安装与注册，不再暴露需要用户串联的 `install/register` 创建命令。地图生成所需的包安装是仓库模块的独立读包操作，不改变发布状态。

所有命令支持 `--json`；stdout 只输出结构化结果，stderr 输出进度和诊断。`--help` 和发布 `--dry-run` 不写入包或注册表，dry-run 不产生可替代提交的审批或成功记录。

### 14.2 服务化边界

共享部署可以为同一应用层提供作业提交、状态查询、审批、取消和发布 API，不再实现第二套业务流程。鉴权、命名空间、幂等键、追踪 ID 和资源配额由入口传递到各模块。

恢复接口核验当前身份及权限、输入指纹和证据有效性，不能仅根据 `run-state.json` 的状态跳过门禁。当前步骤不存在恢复条件时返回待决问题，不自动批准或扩大权限。

## 十五、错误、修复与重试

| 错误码 | 含义 | 修复位置 |
|---|---|---|
| `ROUTE_AMBIGUOUS` | 无法确定唯一复用范围 | 简报 / 用户 |
| `SOURCE_UNSUPPORTED` | 来源格式、模式或版本不支持 | 来源分析 |
| `BRIEF_NOT_CONFIRMED` | 缺少有效简报确认 | 审批 |
| `APPROVAL_INVALID` | 身份、权限、摘要或有效期不符 | 审批 |
| `KIND_BOUNDARY_VIOLATION` | 契约越过类型所有权 | 模板编写 |
| `CONTRACT_SCHEMA_INVALID` | 契约结构、类型或引用不合法 | 模板编写 |
| `CONSTRAINT_CONFLICT` | 适用约束不能同时成立 | 对应规则所有者 |
| `SPATIAL_CONTRACT_INVALID` | CRS、量测、拓扑或尺度矛盾 | 空间契约 / 数据准备 |
| `ENCODING_SEMANTICS_INVALID` | 单位、分类或视觉映射错误 | 数据绑定 / 表达契约 |
| `ADAPTER_CAPABILITY_MISSING` | 缺少必需能力 | 目标选择 / 适配器 |
| `RENDER_TIMEOUT` | 工作进程超过预算 | 资源配置 / 渲染 |
| `INTEGRITY_MISMATCH` | 文件或依赖摘要不一致 | 包来源 / 构建 |
| `LICENSE_BLOCKED` | 数据或资产许可不满足分发 | 来源或资产所有者 |
| `VALIDATION_STALE` | 内容或环境变化使证据失效 | 验证 |
| `VERSION_CONFLICT` | 相同版本键对应不同内容 | 发布者，新建版本 |
| `PUBLISH_COMMIT_UNKNOWN` | 超时导致提交结果未知 | 按幂等键查询后恢复 |

错误响应包含 `code/message/run_id/phase/artifact/evidence_ref/repair_owner/retry_from/retryable`；规则错误另带 `check_id/strength/result_severity`，不相关字段可为空。

严禁无限修复循环。自动修复只能在已批准范围内生成候选修改，重新验证；改变场景目标、必需能力或业务语义时回到简报确认。重试次数、退避和总作业预算由平台配置。

## 十六、安全、许可与企业生产基线

### 16.1 包与数据安全

- 路径规范化后验证允许根，拒绝路径穿越、越界符号链接或 junction、重复路径及大小写别名冲突。
- 解包限制文件数、压缩比、单文件和总大小；拒绝归档越界和 XML 外部实体。
- YAML 使用安全解析和大小/深度限制；SVG/HTML 禁止脚本、未批准外链及危险嵌入。
- 原生工程中的宏、插件、外部命令和不受支持表达式不自动执行。
- 远程访问使用允许来源、协议和目标地址策略，阻断 SSRF；不从模板接受任意下载地址或凭据。
- 密钥通过运行环境的受控引用提供，模板、锁和日志均不保存明文秘密或签名 URL。
- 默认不复制生产数据，Fixture 优先合成；业务数据访问、保留和脱敏遵循项目权限。

包校验不赋予任意代码执行权。即使包已签名，也不能跳过内容安全、许可和能力检查。

### 16.2 许可与专业合规

资产记录作者、来源、许可、分发范围和摘要；字体明确嵌入与再分发许可；底图只保存获准引用或缓存内容。包声明的总体许可不能替代逐资产许可核查。

标准记录发布机构、编号、版本、辖区、适用比例尺和有效期。涉及公开地图发布的地域法规、行政界线、敏感设施、地图审核或保密要求，按部署地区接入相应检查和人工审批；技术验证不能替代法定审查。本示例为研判模板，不默认具有法定预警发布或测绘成果资质。

### 16.3 首次生产发布必须具备

| 能力 | 最低验收 |
|---|---|
| 可信身份与权限 | 审批绑定内容、动作、目标和有效身份，越权被拒绝 |
| 隔离与限额 | 受控浏览器超时、取消、资源超限和租户越界可受控处理 |
| 完整性与幂等 | 摘要校验、不可变版本、并发冲突和重试语义可验证 |
| 发布与回滚 | 未提交包不可见，已发布版本可按记录恢复或回退选择 |
| 证据与审计 | 每次发布可追溯到来源、确认、验证环境和最终包 |
| 备份恢复 | 注册表、包、证据和授权信息有备份及恢复演练 |
| 运维预算 | 超时、并发、磁盘配额、告警阈值和故障处置已配置 |

上述是生产门槛，不因采用单体而省略。可先采用部署配置而非复杂治理平台；但在共享多租户使用前，RBAC、租户隔离和可信审计必须完成。

广泛的包签名分发体系、多区域复制和全引擎兼容可延后。若首期就跨信任域接收离线审批或分发包，则该边界需要的签名、信任根和撤销验证不能延后。

## 十七、可观测性与证据保留

每个作业、验证和发布分别使用 `run_id`、`validation_id`、`publication_id`，贯穿日志、审批和产物。

审计至少包括：路由依据、来源摘要、批准动作、输入变更、步骤回执、验证版本与结果、模板摘要、发布提交和撤回。共享部署的审计应追加写入受控存储，普通模板作者无权修改历史。

指标包括阶段耗时、失败率、工作进程超时、队列时长、资源峰值、验证缺口、发布冲突及缓存命中。日志不包含数据行、完整几何、凭据或未脱敏路径。

上线前必须明确服务目标、保留期、备份周期、RPO/RTO 和负责人，并完成故障恢复演练；这些由实际部署规模决定，不在模板中硬编码一个适用于所有环境的数值。发布证据的保留期不得短于仍受支持版本的追溯要求。

## 十八、测试与完成定义

### 18.1 必需测试

1. 四类路由及契约边界：合法、非法、缺字段、未知字段和版本差异。
2. 六份场景契约：字段引用、Schema 和依赖一致性。
3. 所有权：整段替换、适用标准冲突、绑定失配，不发生字段拼接。
4. 检查器：参数越界、最低基线不可降低、未知检查 ID、适用/不适用边界。
5. 加载：确认前不读正文；确认后小契约完整校验；无关适配器不启动；相关约束不遗漏。
6. 数据空间：单位换算、时效、Join、无效几何、量测误差和超出适用地域的拒绝。
7. 表达交付：分类并列值、无数据、比例符号面积、图例同步、字号线宽和印刷尺寸。
8. 安全：越界路径、恶意归档、脚本/表达式注入、审批伪造及摘要篡改。
9. 故障恢复：进程崩溃、取消、磁盘满、发布提交超时、并发同版本发布和索引更新失败。
10. 端到端：四类最小模板各一个；场景完成 MapLibre Web/SVG 预览验证、发布、项目安装和 Fixture 重放。

视觉回归比较语义稳定区域并给定容差，不能只做逐像素比较，也不能只检查文件是否存在。扩展其他引擎后增加共享语义一致性测试，不以视觉相同替代语义验证。

### 18.2 模板完成定义

- kind 唯一，MapScenario 恰好六份业务契约。
- 固定依赖、全部包文件及运行时清单完整且摘要匹配。
- 人读说明与机器规则无已知矛盾，所有可执行参数有唯一来源。
- 适用硬约束通过，`blocker/error` 为零，警告有处置记录。
- 每个正式目标及原型具备所需 Fixture 覆盖，没有未验证的正式能力声明。
- 许可、安全和所需专业审批通过。
- 证据绑定当前包与环境，发布审批绑定同一内容。
- 发布事务完成，精确版本可发现或以项目私有来源安装。
- 发布回执可查询，重试不会生成重复版本，失败遗留物有受控回收策略。

未引用暂存文件或失败产物的清理由保留期和授权任务处理，不在成功交接时无条件递归删除工作区。

## 十九、分阶段落地与旧稿迁移

| 阶段 | 范围 | 退出条件 |
|---|---|---|
| P0：规范收敛 | 对齐三份文档、四类命名、六契约、Schema、审批和仓库治理规则 | 无并行旧模型，测试位置和代码入口获准 |
| P1～P3：内核 | 五模块边界、状态与回执、编译器、注册检查器、简化加载、单一发布 | 无渲染器的完整生命周期和故障恢复通过 |
| P4～P6：首个生产闭环 | 四类作者策略、两种必要 Map Encoding、MapLibre Web/SVG overlay、洪涝场景、可信审批、隔离与运维基线 | 从来源到发布及项目 Fixture 重放通过 |
| P7：多终端 | Web/移动端、第二适配器、响应式与性能、跨引擎语义 | 每个新增正式目标均有完整验证 |
| P8：行业与规模治理 | 适用标准目录扩展、迁移、广泛签名分发、受支持 mirror 与 ArcGIS | 按具体行业及部署需求验收 |

首期只实现分级设色和比例符号等该场景需要的表达条目，不以完成 8～10 种表达作为上线前提。基础标准适用性、许可、审批和恢复能力不能整体推迟到 P8；P8 扩展的是覆盖范围与治理规模。

旧稿迁移不是同时支持两套运行协议：

- 编写阶段把旧空间/多尺度字段迁入 `spatial-behavior.yaml`，图层/编码字段迁入 `portrayal.yaml`。
- 删除模板侧动态加载单元及任意条件表达式，改为固定依赖、类型化目标和注册检查器。
- 将旧规则的适用性和元数据迁入检查器注册表，默认/参考留在对应业务分段。
- 合并旧 `install/register` 外部操作为 `publish`；目录增加版本层。
- 将旧长状态链映射为作业状态、当前步骤和回执，不继续增加兼容状态。
- 历史发布包若实际存在，迁移生成新版本并复验，不原地修改；只有草稿可直接改写。

当前 `implement-plan.md` 的 P2、P3 和 CLI 任务应据此调整后再进入编码。本文不会把尚未实现的接口当作已部署系统，也不在本次修改中批量改写其他文档。

## 二十、具体运行示例：城市洪涝风险研判场景

本例为未来实现的验收脚本说明，并非已经运行的结果。采用 MapLibre Web + SVG overlay、A3 印刷、两个数据角色和一个完整原型，演示从创建到发布再到业务项目交接。

### 20.1 输入与范围

```text
D:/carto-input/flood-risk/
├─ reference.qgz
├─ requirements.md
├─ agency-logo.svg
└─ sample-fields.csv
```

用户要复用“城市洪涝应急研判”场景，故选择 MapScenario，而不是因为输入包含完整 QGIS 工程。QGIS 工程在这里仅作为受支持子集的来源输入；正式目标为 A3 印刷，由 Web 渲染场景生成中间 SVG 并派生交付产物。

角色为行政区风险率 `risk_regions.risk_rate` 和避难场所容量 `shelters.capacity`。容量表达为符号面积；空风险值显示无数据纹理。Logo 须有分发许可；地图不冒充法定预警发布。

以下 PowerShell 命令使用绝对路径，不依赖当前目录。输入、工具及可信审批系统需在实现后实际存在。

### 20.2 分析与简报

```powershell
python 'D:/IdeaProjects/github/code-reviewer/ppt-master-main/skills/carto-agent/scripts/carto_template.py' analyze 'D:/carto-input/flood-risk/reference.qgz' 'D:/carto-input/flood-risk/requirements.md' 'D:/carto-input/flood-risk/agency-logo.svg' 'D:/carto-input/flood-risk/sample-fields.csv' --workdir 'D:/IdeaProjects/github/code-reviewer/ppt-master-main/projects/_carto_template_builds/urban-flood-risk-20260911' --json

python 'D:/IdeaProjects/github/code-reviewer/ppt-master-main/skills/carto-agent/scripts/carto_template.py' brief 'D:/IdeaProjects/github/code-reviewer/ppt-master-main/projects/_carto_template_builds/urban-flood-risk-20260911' --kind map-scenario --scope library --id urban-flood-risk --version 1.0.0 --json
```

简报关键字段：

```yaml
kind: map-scenario
id: urban-flood-risk
version: 1.0.0
scope: library
creation_mode: standard
audience: 城市应急指挥中心
decision_goal: 识别高风险区域并核对避难资源覆盖
supported_targets: [print-a3]
experimental_intents: [web-dashboard]
data_roles: [risk_regions, shelters]
encodings:
  - choropleth/sequential@1.2.0
  - proportional-symbol/count@1.0.0
```

此时作业为 `status=waiting_approval, step=brief`。系统展示简报及未决项，由用户或审批服务批准；此时尚未创建模板正文。

### 20.3 可信确认与模板编写

审批系统在核验用户身份、权限和简报摘要后签发 `approvals/brief.json`。该文件是审批服务产物，不能用文本编辑自行伪造。

```powershell
python 'D:/IdeaProjects/github/code-reviewer/ppt-master-main/skills/carto-agent/scripts/carto_template.py' confirm 'D:/IdeaProjects/github/code-reviewer/ppt-master-main/projects/_carto_template_builds/urban-flood-risk-20260911' --action brief --approval-receipt 'D:/IdeaProjects/github/code-reviewer/ppt-master-main/projects/_carto_template_builds/urban-flood-risk-20260911/approvals/brief.json' --json

python 'D:/IdeaProjects/github/code-reviewer/ppt-master-main/skills/carto-agent/scripts/carto_template.py' author 'D:/IdeaProjects/github/code-reviewer/ppt-master-main/projects/_carto_template_builds/urban-flood-risk-20260911' --json
```

生成：

```text
staging/package/
├─ manifest.yaml
├─ templates/design_spec.md
├─ contracts/
│  ├─ scenario.yaml
│  ├─ data.schema.yaml
│  ├─ spatial-behavior.yaml
│  ├─ portrayal.yaml
│  ├─ delivery.yaml
│  └─ quality-gates.yaml
├─ prototypes/01_risk_overview.svg
├─ fixtures/
│  ├─ risk-regions.geojson
│  ├─ shelters.geojson
│  └─ dataset-metadata.yaml
├─ assets/logos/agency-logo.svg
├─ dependencies.lock.yaml
└─ checksums.sha256
```

主 Fixture 使用足够形成有效分级的合成区域和避难点；额外边界用例覆盖空值、并列值、无效几何及越界风险率。Fixture 的时间由固定验证时钟核对，真实业务任务必须使用真实观测时间，不可沿用测试时间。

### 20.4 校验与预览

```powershell
python 'D:/IdeaProjects/github/code-reviewer/ppt-master-main/skills/carto-agent/scripts/carto_template.py' validate 'D:/IdeaProjects/github/code-reviewer/ppt-master-main/projects/_carto_template_builds/urban-flood-risk-20260911' --render --target print-a3 --json
```

预期报告形态：

```json
{
  "run_id": "urban-flood-risk-20260911",
  "validation_id": "val-001",
  "status": "passed",
  "package_digest": "sha256:<computed-package-digest>",
  "evidence_digest": "sha256:<computed-evidence-digest>",
  "blockers": 0,
  "errors": 0,
  "warnings": 0,
  "supported_targets": ["print-a3"],
  "coverage_matrix": [
    {
      "target": "print-a3",
      "prototype": "risk_overview",
      "adapter": "maplibre-web",
      "fixture_suite": "flood-risk-boundaries",
      "status": "passed"
    }
  ],
  "unverified_claims": [],
  "experimental_intents": ["web-dashboard"]
}
```

摘要占位符由工具计算，不是实际哈希。所有失败用例须触发预期拒绝才算对应测试通过。Web 仅为意向不产生正式能力声明；若改成正式目标但没有适配器验证，发布必须失败。

预览位于 `previews/val-001/`，报告和 Fixture 锁位于 `reports/val-001/`。例如风险率被错误绑定到容量字段时，系统返回 `ENCODING_SEMANTICS_INVALID`，停止渲染或发布，由作者修正后生成新的验证记录。

### 20.5 一次发布

验证通过后，请有权限的发布者批准同一包摘要、证据摘要和目标库。服务签发 `approvals/publish.json`，然后：

```powershell
python 'D:/IdeaProjects/github/code-reviewer/ppt-master-main/skills/carto-agent/scripts/carto_template.py' confirm 'D:/IdeaProjects/github/code-reviewer/ppt-master-main/projects/_carto_template_builds/urban-flood-risk-20260911' --action publish --approval-receipt 'D:/IdeaProjects/github/code-reviewer/ppt-master-main/projects/_carto_template_builds/urban-flood-risk-20260911/approvals/publish.json' --json

python 'D:/IdeaProjects/github/code-reviewer/ppt-master-main/skills/carto-agent/scripts/carto_template.py' publish 'D:/IdeaProjects/github/code-reviewer/ppt-master-main/projects/_carto_template_builds/urban-flood-risk-20260911' --repository 'D:/IdeaProjects/github/code-reviewer/ppt-master-main/skills/carto-agent/templates' --dry-run --json

python 'D:/IdeaProjects/github/code-reviewer/ppt-master-main/skills/carto-agent/scripts/carto_template.py' publish 'D:/IdeaProjects/github/code-reviewer/ppt-master-main/projects/_carto_template_builds/urban-flood-risk-20260911' --repository 'D:/IdeaProjects/github/code-reviewer/ppt-master-main/skills/carto-agent/templates' --json
```

最终版本位置：

```text
skills/carto-agent/templates/scenarios/urban-flood-risk/1.0.0/
```

发现记录示例：

```json
{
  "namespace": "local",
  "kind": "map-scenario",
  "id": "urban-flood-risk",
  "version": "1.0.0",
  "root": "scenarios/urban-flood-risk/1.0.0",
  "supported_targets": ["print-a3"],
  "package_digest": "sha256:<computed-package-digest>",
  "publication_id": "pub-001"
}
```

`root` 相对配置的模板库根解析。返回时作业为 `status=succeeded, step=publish`，包状态为 `published`。再次执行相同发布返回 `pub-001`；修改内容后继续占用 `1.0.0` 则返回 `VERSION_CONFLICT`。

### 20.6 地图生成侧的交接边界

本节仅定义消费协议，`generate-map` 的完整规划、执行与交付流程由其独立 TRD 负责。

1. 用户提出“制作某日城市洪涝风险 A3 研判图”，系统只用索引和 Manifest 展示候选。
2. 确认本次受众、指标、日期、范围、数据权限与精确模板版本。
3. 将 `urban-flood-risk/1.0.0` 安装到项目私有目录，验包与固定依赖摘要。
4. 一次解析六契约，结合显式 Brand/Style/Layout 解析所有权，不启动其他适配器。
5. 绑定真实风险率和容量字段，检查单位、时效、CRS、几何和可用性。
6. 计算实际范围与分类断点，形成候选计划；加载引用的 Logo、符号和渲染资源，编译 `RenderScene` 并生成预览。
7. 预览与门禁通过后冻结 MapSpecLock，再按固定参数生成正式产物。
8. 模板、数据、目标或参数变化时建立新计划和锁；不能修改既有发布包来“临时适配”。

该例中，模板规定“这种研判地图需要哪些数据、如何表达、怎样验证”，项目锁记录“这一次用了哪些数据、范围、断点和运行环境”。创建和生成共享契约内核，但各自拥有独立的作业、审批、状态和产物生命周期。
