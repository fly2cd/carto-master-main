# 制图领域模型与模板体系一致性收敛记录

日期：2026-11-09（Asia/Shanghai）

状态：本轮设计决定已整理并写入相关文档；运行实现未变。

本记录说明讨论结论、替代的旧表述、修订位置、实现边界和待决项。它不是机器协议、能力注册、审批回执或测试通过证明。运行时只消费 `skills/carto-agent/` 下的 Schema、策略、权威模板及项目产物。

## 1. 收敛目标与依据

依据本轮关于通用专题制图、多图、海报、MapLayout 和模板职责的讨论，修正将“布局 × 专题表达 × 渲染后端”视为完整领域模型的简化。目标设计为：

- **语义表达 Encoding**：数据到视觉变量的映射、单位、分类/缩放和比较约束。
- **视觉样式 Appearance**：在语义约束内选择兼容的颜色、符号、字体与图例外观。
- **页面构成 Composition**：页面/面板/内容区域的空间组织及适配。
- **独立执行层 Renderer**：能力声明、测量、绘制、合成、导出。
- **共同基础与输出**：内容、数据、地理视图、身份资产、许可和业务/标准约束；Delivery 为输出合同。

“正交”指职责与决定可分别表达，不代表互不影响或所有组合都能执行。模板是可复用规范的组合载体，不与三个维度一一映射；不能通过重命名组件掩盖双重来源或未实现能力。

统一领域定义放在[模板体系设计的 2026-11-09 收敛章节](carto-template-dsg.md)。本记录负责追溯，不作为另一份可执行协议或独立设计权威。总体架构解释层次，各专题文档细化组件边界，两份 TRD 约束实现与交接。

## 2. 决策清单

| 编号 | 旧表述或风险 | 收敛决定 | 主要落点 |
|---|---|---|---|
| C01 | 布局、表达、后端被视为完整同层三维 | 原三项保留为工程覆盖矩阵；领域采用 Encoding/Appearance/Composition，后端独立 | 总体架构、模板体系 |
| C02 | 一个模板包含布局和样式被误认为不正交 | 模板 = 部分规范 + 约束 + 参数接口 + 依赖；允许组合多个维度 | 模板体系、Scenario |
| C03 | MapStyle、portrayal 与表达目录可能重复持有分类/缩放 | 目录定义机制，Scenario/任务选择与约束，项目绑定实际值，Style 主要提供兼容外观，编译固定唯一结果 | Style、表达与符号、生成 TRD |
| C04 | 单图、网格、跨格、插图被当成互斥模式 | 基础模型 single/grid/mosaic/freeform；inset 为可附加的父视图关联结构 | Layout、生成 TRD |
| C05 | 海报等于自由布局；自由等于任意绘图 | 海报为媒介/用途；先固定自由编排，再受控锚定/求解，显式层级、重叠和裁剪 | Layout、图片转模板计划 |
| C06 | 显式组合/按年份分面由布局直接决定 | 组织方式归 Scenario/项目规划，产生视图后绑定 Layout 接口 | Layout、Scenario、生成 TRD |
| C07 | 一个 shared 开关控制所有多图关系 | 地理视图、专题映射、图例分别按组共享；图例共享需语义兼容，比例尺/方向绑定视图 | 模板体系、表达与符号、生成 TRD |
| C08 | 固定坐标是缺陷，或用户可任意覆盖纸张/网格 | 固定模板、有限变体、受控参数都合法；只在声明范围内实例化，不改已发布包 | Layout、创建 TRD |
| C09 | 必须内嵌三段和只能整段替换被当成永久架构 | v1 当前规则保留；目标允许精确引用/内嵌、声明参数、限定作用域调整，禁止任意深层合并 | Scenario、所有相关组合章节 |
| C10 | 后端自行决定表达或失败后换工具 | 候选阶段按整页能力匹配并测量，首期一页一后端；冻结后无静默回退 | 总体架构、生成 TRD |
| C11 | 模板、布局或表达分别产生相互竞争的实例权威 | 演进现有 MapPlan/ResolvedMap/executionSnapshot/MapSpecLock；所有来源归一，无第二套锁 | 模板体系、两份 TRD |
| C12 | 目录/Schema/宿主安装等于业务能力；旧洪涝被称为当前实现 | 区分定义、代码、宿主可用、组合准入、真实验收；更新到 general 分类栅格单图基线 | 各专题当前状态章节 |

## 3. 模板到领域的映射

| 模板或组件 | 目标角色 |
|---|---|
| MapStyle | 主要贡献 Appearance，以 Profile 引用兼容编码，不复制算法或最终断点 |
| MapLayout | 贡献 Composition 的结构、内容接口、参数范围、容量与适配 |
| MapBrand | 提供身份资产、视觉默认与使用约束，不具有覆盖业务语义的最高优先级 |
| MapScenario | 组合用途、数据角色、编码要求和各组件；不是第四个视觉维度 |
| 表达目录/受信方法 | 机制、适用条件、参数与实际计算，登记不等于已准入 |
| 项目实例 | 本次真实数据、面板、视图、编码、外观、共享组、资源及来源 |
| Renderer / Delivery | 实现与输出合同，不作为新的模板种类或业务用途 |

组合调整分为结构性组件替换、已声明参数赋值、限定作用域的允许调整。六种规则语义保持不变，多个硬约束共同满足，不通过简单优先级或后加载覆盖消除冲突。固定业务色不能被当作任意皮肤，字号和空间必须共同验证。

## 4. 本轮修订文件与内容

| 文件 | 实质修订 |
|---|---|
| [carto-template-dsg.md](carto-template-dsg.md) | 新增统一领域章节；修正固定坐标、组合机制、表达状态、FAQ 和旧演示基线 |
| [carto-agent-architecture.md](carto-agent-architecture.md) | 区分设计维度、模板分类与执行层；v1 六契约不再作为永久对象模型；补充组合和多图边界 |
| [template/map-style.md](template/map-style.md) | 收紧 Appearance 职责，保留编码约束；修正旧 quantile/半径现状，明确参数与作用域调整 |
| [template/map-layout.md](template/map-layout.md) | 纳入四种基础模型及 inset，区分分面/共享语义；更新 ResolvedLayout、单图与测量现状 |
| [template/map-scenario.md](template/map-scenario.md) | 从固定内嵌载体演进为组合方案；明确 v1/目标边界，更新 general 作者、样张和发布状态 |
| [template/map-brand.md](template/map-brand.md) | 身份资产不作为设计维度或最高覆盖级；更新当前字体/组合边界 |
| [template/map-expression-and-symbol-design.md](template/map-expression-and-symbol-design.md) | 与三维模型对齐；替换过时洪涝半径诊断，明确目录与实际准入差别 |
| [carto-create-template-TRD.md](carto-create-template-TRD.md) | 目标组件合同、声明调整及样张覆盖范围；一张样张不能证明任意参数组合 |
| [carto-generate-map-TRD.md](carto-generate-map-TRD.md) | 面板/共享组的目标合同、后端选择与冻结边界；修复指向已替换旧诊断的链接 |
| [global-implement-plan.md](global-implement-plan.md) | 增加合同→固定多图→矢量混合→后端与更多构成的目标增量，不改写历史完成记录 |
| [image-to-style-layout-implementation-plan.md](image-to-style-layout-implementation-plan.md) | 区分图片中的空间、外观和待核对语义证据；修正作者/渲染基线和组合规则 |
| [template/thematic-image-to-template-workflow.svg](template/thematic-image-to-template-workflow.svg) | 仅修正旧洪涝状态和组合规则的短文案，不改变图形结构 |
| [本收敛记录](design-convergence-20261109.md) | 决策追溯、基线、实施门槛、未决项和检查范围 |

本轮不重写 doc/dev-log、doc/impl-log、doc/reference 中的历史记录，也不把其他按日期记录的专项计划整体替换为当前状态。保留的洪涝等业务例子是示意/历史目标，不是当前已注册能力。

## 5. 当前实现基线：未随文档改变

静态核对依据为 [SKILL](../skills/carto-agent/SKILL.md)、[能力策略](../skills/carto-agent/policies/scenario-capabilities.yaml) 与其实现引用：

- 当前仅注册 general_thematic_mapping / general-thematic-raster / general-thematic-map@1.0.0。
- 输入为用户已分类栅格；单图 A4 横向 300 dpi PDF+PNG；禁生产数据和敏感坐标，强制声明及许可。
- 分类栅格模板样张分支已实现，验证与发布链存在；这不是本轮新增，也不证明真实身份或用户数据已验收。
- Layout 运行实现仍限制单地图、mm、DPR=1、非重叠框；已有 ResolvedLayout 和静态栅格页面的字体测量。
- 后端已有 maplibre-web 与 rasterio-matplotlib-page；当前 general 固定使用后者，不代表静态后端已是通用矢量绘图器。
- v1 Scenario 必须内嵌三个段，当前 general 的 replaceable_segments 为空；独立 Brand/Style/Layout 业务创建、通用组合与目标参数模型未开放。
- 现有安全、审批、摘要、资源闭包、回执、非生产政策与唯一 CLI 均未改变。

## 6. 采纳但尚未实现的工作

1. 严格定义面板/view/Frame、表达实例、共享组、组件来源、参数与作用域的协议；字段名、Schema 版本和迁移拒绝方式另行定案。
2. 先复用分类栅格完成固定双图/四图完整链路，使用通用合同而不是新建栅格 subplot 协议；单图仍需回归。
3. 补齐单一符号、矢量类别、面分级、点比例符号与参考图层的真实准备、编译、渲染和检查。
4. 接入后端能力匹配与分后端探测，按整页组合验收。固定 freeform、mosaic/inset、锚定求解、独立组件作者分别准入。
5. 更新所有消费者与代码摘要绑定；任一面板、映射、字体或后端漂移使旧候选/证据失效。不为旧格式增加兼容旁路。

## 7. 尚待确定的细节

- 组件引用与内嵌的具体 Schema、参数命名和允许的作用域地址；不将本文措辞直接作为请求字段。
- 网格最大容量、最小面板与字体阈值、freeform 初始约束算子和允许重叠规则。
- 表达参数、视觉默认与业务硬约束发生冲突时的具体诊断结构和来源记录形式。
- 后端能力矩阵的存储/版本形式、偏好选择的确定性规则、PDF 中矢量/栅格质量合同。
- 独立组件创建与分发的实施时点、模板版本升级和验证样张覆盖集。

这些细节未定不影响本轮领域职责结论；也不能被当作已授权的默认行为。

## 8. 核查与非目标

本轮只修改上述 doc 文档；不改 Python、Schema、策略、Fixture、运行工作流、已发布包或业务数据，不安装依赖，不签发审批。

检查范围为差异/空白检查、新增和替换的相对文档链接、Markdown 围栏结构、SVG XML 与短文案长度，以及新旧职责和当前状态表述的定向检索。未运行开发测试、CLI 制图或真实数据验收；文档收敛不表示任何目标能力已经可用。SVG 仅做结构与文本检查，未进行像素渲染验收。
