# 领导调研私有样式合同：46 字段最终映射设计

| 项目 | 内容 |
|---|---|
| 日期 | 2026-11-25（Asia/Shanghai） |
| 状态 | 字段级映射设计稿：46 项逐项给出明确去向；所有权裁决 D1–D7 已确认，本稿的具体字段级设计尚未实施或验收 |
| 规范依据 | [领导调研迁移的所有权与合同边界裁决](leadership-visit-ownership-contract-boundaries.md) |
| 事实基线 | 当前 `image-itinerary-style.schema.json` 的 46 个叶子字段，以及当前作者、编译器、静态/前端消费者 |
| 关联材料 | [前置盘点清单](leadership-field-owner-consumer-digest-inventory.md)、[实施计划](composable-template-architecture-implementation-plan.md)、[单位与几何技术验证](p6-unit-geometry-technical-validation.md) |
| 本轮范围 | 完成语义去向、配置来源、实例选择、单位转换、消费者和摘要/失效映射；仅新增本文档 |
| 不包含 | 修改 Python、Schema、策略、旧模板、运行产物；自动迁移；执行测试或宣称目标能力已开放 |

> 本文是已确认边界之下的字段映射设计，不新增一套所有权权威。旧盘点中的“迁移后归属”属于前置建议；本稿在 D1–D7 下细化并修正它。运行时不读取本文。目标逻辑地址用于定义接口语义，不是声称现行 Schema 已接受这些字段；正式 wire 字段、版本和生产者—消费者变更须按第 9 节成套落地。

## 1. 映射决定摘要

1. 保留五类来源主体，不新增 map-card、map-content、map-annotation、map-basemap 等并列模板种类。
2. `image_itinerary` 的业务组、标签、缺失分组处理、编号和内容开关不进入通用 Style。
3. 外观按视觉角色进入选定 Style；不把 `morning/afternoon` 变成所有 Style 必须认识的业务词汇。
4. 卡片宽度、内边距、分区间隔、换行和拟合由组件定义的参数接口约束，本次具体值进入项目组件实例；页面 Layout 不接管这些内部细节。
5. 卡片和辅助标签的偏移进入项目注记放置选择，不作为独立 Style 覆盖链。
6. 裁边阈值进入视图的底图显示合同；不再由换肤动作附带改变。
7. 原 `*_px` 值先保留“参考设计像素”度量，不凭固定 DPI 换算成永久 mm/pt；既有页面字号和边框保留 pt/mm。
8. 标题字重、分区间隔、辅助标签文字、页面来源字号和边框几何按真实消费者映射，不能只看旧字段名称。
9. 删除的是旧合同独立决定设计的权威；后端可以保留画图函数和机械生成的内部参数对象，但不得继续读取旧合同或补独立默认值。

### 1.1 字段去向统计

以下按主要逻辑去向统计，不代表新增 owner 或模板种类：

| 去向 | 字段数 |
|---|---:|
| Style 角色化外观 | 29 |
| 场景/项目内容、分组与编号绑定 | 5 |
| 组件内部排版参数 | 6 |
| 项目注记放置选择 | 4 |
| 底图显示处理 | 1 |
| 协议版本治理 | 1 |
| **合计** | **46** |

## 2. 合同位置、来源与消费者约定

### 2.1 最终逻辑地址

以下地址明确“值属于什么合同和作用域”，不预设每个地址都成为独立文件或顶层产物。方括号表示按稳定 ID 查找的条目，不是可执行表达式。

| 缩写 | 规范职责与逻辑位置 | 配置来源／实例选择 | 承载与限制 |
|---|---|---|---|
| `S` | Scenario 的业务定义、必需/允许内容、默认方案 | 已发布 Scenario；Project 不能改写事实或放宽硬约束 | 复用场景合同；新增业务语义按场景协议演进 |
| `I` | 当前 MapPlan 的内容、角色绑定、组件实例和明确选择 | 用户/LLM 提案经过采用、授权后形成项目选择 | 不是新的平行计划或状态机；必须绑定原请求及选择证据 |
| `A[role]` | 选定 Style 的角色化外观接口 | Style 是默认来源；Project 仅在其公开参数接口内实例化 | 基于现有 Style 体系扩展类型化外观；不是将旧 image_itinerary 原样嵌入 Style |
| `C[type]` | 已登记表达／内容组件定义：输入语义、结构模式、参数 Schema、单位、测量和后端要求 | 受信注册定义及其精确版本；不得由请求提供任意代码 | 路线、编号点、信息卡片、辅助标签、双线边框等需实际消费者和准入 |
| `J[id]` | `I.components[id].parameters`，按对应 `C[type]` 严格校验的组件内部参数 | Scenario 可引用组件预设；Project 明确采用及合法实例化 | 配置来源、所选值、规则定义分别记录；Renderer 不另补默认 |
| `N[id]` | `I.annotations[id].placement`，地图内注记的放置选择 | 组件预设可提供建议；Project 决定 preferred/fixed 等语义 | 地理锚点来自数据；Layout 提供外部容器；求解结果是派生值 |
| `V[id]` | 当前视图的 `basemap_display` 合同 | 获准底图来源＋Project 显示选择；处理方法由受信组件定义 | 保留来源图像和配准事实，不改数据文件或路线事实 |
| `U` | 精确引用的符号度量规则 | 表达定义声明允许模式，项目/所选预设明确采用 | 声明参考尺寸、缩放函数和下限；不把历史参考画布当普遍数学规则 |

`A[role]` 是外观接口的逻辑投影，不额外建立全局 token 层。比如一个类别颜色可以由同一 Style 离散外观条目提供，再由显式绑定供应路线、编号点和卡片背景；解析图形中的同色副本是派生值，不是三份独立颜色权威。

`C[type]` 可以规定可用参数和结构模式，但不能在执行时替项目选择未声明的设计。默认组件结构必须来自精确引用的预设，并在编译前展开为完整实例。

### 2.2 度量表示

- `Q(v)`：本次映射采用的参考设计长度，含数值 `v`、单位 `reference-design-px` 及精确度量规则 `U`。
- `PT(v)` / `MM(v)`：明确的物理长度。不得参加图形参考像素的缩放。
- 新协议必须使用可判别的度量表示，或由被引用定义严格限定单位；不能只改字段后缀而保留歧义。
- 初始基线的 `U` 明确采用当前参考画布 `2381×1684` 和 scale-floor=1.0，以维持既有参考像素行为。这是显式基线预设，不是所有 Style 的隐式默认。
- 将来采用物理符号尺寸是新的显式设计选择，不能从某次渲染结果反推后冒充等价迁移。

### 2.3 消费者代号

| 代号 | 目标消费者职责 | 当前实现中的主要对应位置 |
|---|---|---|
| CB | 场景内容构建、分组/编号/图例语义生成 | `leadership_visit/style.py` 中业务值读取、文字拼接和编号部分 |
| AR | 类型化角色绑定、外观参数解析、唯一来源核验 | 私有分组/外观读取，迁入共享解析机制；不由后端再次解释 |
| CL | 组件局部测量、宽度适配、换行和分区排列 | `image_layout.callout_text` 及卡片宽度推导 |
| AL | 注记放置、障碍输入、求解与结果验证 | `_place`、`_solve_annotations` 和现有授权工具 |
| GC | 受信表达组件生成冻结图形 | `apply_grouped_style` 的图形构造部分；场景只提供业务绑定 |
| BV | 底图窗口测量与视图/图片坐标适配 | `candidate_compiler` 的 display/projection 网关调用 |
| BE | 静态输出、前端文档及在线地理段适配 | `image_page_renderer`、`frontend_canvas`、`frontend_document` |

这些是职责代号，不要求新增同名模块，也不要求所有后端使用完全相同的绘图算法。

### 2.4 摘要与冻结代号

| 代号 | 含义 |
|---|---|
| T/R | 当前源绑定：模板文件/包，或含补丁的请求/Brief；所有合法变化先影响其实际来源 |
| S/I | 目标 Scenario 定义或已采用的项目计划选择及绑定 |
| A | 目标 Style 精确引用、合法实例参数与有效外观 |
| K | 目标表达/组件/单位规则的精确定义引用与采用的预设 |
| V/E | 视图/底图显示合同、工具输入/结果和回执证据 |
| G | 冻结图形及 `overlay.graphics_digest` |
| P/L | 页面合同／已解析页面布局 |
| X | 后续 RenderScene、execution、candidate、G2/MapSpecLock 绑定链 |

表中的箭头表示依赖，不保证每次参数变化都导致不同像素。G 会经 overlay 摘要进入 P。前端文档由同一有效实例重建并计算自己的摘要。T/R 改变但对应内容未使用时，G/P 可以不变，旧输入指纹和审批也不能因此自动复用。

## 3. 46 个叶子字段逐项映射

本节每行对应一个现行 Schema 叶子字段；数组顺序和整个对象的存在性另列第 6 节，不混入 46 项计数。

表内数值是本次读取的 RouteAuthor 基线，不是对所有既有已发布模板/项目补丁的统一覆盖。实际作者迁移必须以明确版本的合同和已采用参数为源；源值不同则保留该来源值及其含义，不擅自改成本文示例基线。

### 3.1 协议与分组（M01–M06）

| 编号 | 原字段 | 最终规范权威与逻辑去向 | 处理、来源和基线规则 | 消费者／摘要影响 |
|---|---|---|---|---|
| M01 | `schema_version` | 平台协议治理；分别使用 Scenario、Style、组件、计划及视图合同自身的版本 | **拆分并退出私有版本权威**。旧值 1 仅作为迁移来源记录，不复制成每份新合同的版本，也不把私有 v1 自动解释为共享 Style v2 | Schema/注册与引用校验；各合同精确引用进入 S/A/K/V→X；本项不是可调外观 |
| M02 | `groups[].id` | `S.group_definitions[].id`；实际绑定在 `I.group_bindings[].semantic_group` | **拆分定义与实例绑定**。morning/afternoon/default 留业务语义，Style 只认识对应视觉角色。旧补丁 ID 是查找键，不是重命名许可 | CB→AR；S/I→G/P→X；改业务分类不能冒充换色 |
| M03 | `groups[].label` | `S.group_definitions[].display_label` 为默认；`I.legend_labels[group]` 保存采用值 | **迁入内容合同**。基线为上午行程/下午行程/其他行程；项目别名须有来源与明确采用，不改变分组键。图例从实际映射生成 | CB；S/I→P→X；未显示分组的文字可能不影响图面 |
| M04 | `groups[].color` | `A[visual_group].color`；由 `I.group_bindings` 绑定类别视觉通道 | **保留为共享 Style 外观**。基线蓝/粉/紫分别绑定相应业务组，但 Style 不内置业务组名。路线、编号点、卡片背景若共用该通道，只保留一个颜色来源 | AR→GC/BE，图例读同一有效通道；A/I→G及P→X |
| M05 | `groups[].right_offset_px` | `A[route_visual_role(group)].display_offset.distance`，方向语义由路线表达定义 | **转为组路线角色的显示位移**。基线 morning=Q(2)、afternoon=Q(8)；只作用于路线显示，不修改数据。与 M09 在采用阶段归一为每组唯一有效值 | AR→路线 GC/BE；A/I/K→G→X；不进入原始路线几何 |
| M06 | `default_group` | `S.group_resolution` 的合法规则＋`I.group_resolution` 的采用值；另显式绑定通用停靠点图例角色 | **拆分两个旧作用**：缺失分组的允许回退，以及旧“行程点”图例取色。基线回退组为 default；图例角色显式采用基线紫色，不能在新系统继续从一个回退字段暗取颜色 | CB→AR；S/I→G/P→X。未知非空分组仍拒绝，不通过 Style 猜测 |

### 3.2 路线与编号点（M07–M13）

| 编号 | 原字段 | 最终规范权威与逻辑去向 | 处理、来源和基线规则 | 消费者／摘要影响 |
|---|---|---|---|---|
| M07 | `route.width_px` | `A[route_role].stroke.width` | **保留，单位显式化**。基线 Q(6)；取所选路线外观的有效值，不把数字 6 当 pt/mm | AR→路线 GC、AL 障碍、BE；A/K→G，障碍改变时 E→X |
| M08 | `route.halo_width_px` | `A[route_role].halo.width` | **保留为外观**。基线 Q(1)；光晕与主线是不同通道。碰撞是否计入 halo 必须由表达/注记规则声明，不能趁迁移悄悄扩大或忽略 | AR→GC/BE；A/K→G→X；当前 AL 并不自动使用相同 halo 范围 |
| M09 | `route.right_offset_px` | `A[default_route_role].display_offset.distance` | **作为通用路线角色默认并归一**。原作者未填该项；基线对未被 M05 指定的组明确采用 Q(0)。不得保留后端 get(...,0) 作为新设计权威 | AR 在角色采用阶段处理 M05/M09→GC；A/I/K→G→X |
| M10 | `route.arrows.size_px` | `A[route_arrow_role].head.size` | **保留**。基线 Q(8)；箭头形状及参数适用性由注册表达定义，尺寸由 Style 提供 | AR→箭头 GC/BE；A/K→G→X |
| M11 | `route.arrows.spacing_px` | `A[route_arrow_role].repeat.spacing` | **保留为符号重复参数**。基线 Q(200)；沿线方向和落点由算法按已选参数推导，不在后端自定间隔 | AR→箭头 GC/BE；A/K→G→X |
| M12 | `pin.radius_px` | `A[numbered_stop_marker].radius` | **保留**。基线 Q(12)；实际停靠点角色由场景决定。最终符号包络参与布局，不能由其他角色的半径冒代 | AR→点 GC、CL/AL、BE；A/K→G及可能E→X |
| M13 | `pin.font_size_px` | `A[visit_order_text].font.size` | **保留为编号文字外观**。基线 Q(12)；编号文字绑定的是访问顺序还是显示序号由 I 决定，不能由字体配置决定 | AR→GC/BE；A/I/K→G→X |

### 3.3 信息卡片（M14–M28）

| 编号 | 原字段 | 最终规范权威与逻辑去向 | 处理、来源和基线规则 | 消费者／摘要影响 |
|---|---|---|---|---|
| M14 | `callout.width_px` | `C[information-card]` 定义参数；实例为 `J[card].sizing.width.limit` | **迁入组件内部参数，不放页面 Layout**。基线 Q(500)。它在固定宽模式表示宽度，在限宽适配模式表示上限；必须和 M26 一起解释 | CL→AL/GC；I/K→派生G及可能E→X |
| M15 | `callout.title_font_px` | `A[card_title].font.size` | **保留为角色化文字外观**。基线 Q(22)；不同于页面大标题字号 M41 | AR→CL→GC/BE；A/K→G，尺寸变时E→X |
| M16 | `callout.body_font_px` | `A[card_body].font.size` | **保留为角色化文字外观**。基线 Q(14)；不从页面来源说明字号 M42 继承 | AR→CL→GC/BE；A/K→G，尺寸变时E→X |
| M17 | `callout.padding_px` | `J[card].inset`，参数定义与内盒模型由 `C[information-card]` 提供 | **迁入组件局部排版**。基线四边 Q(4)。与 Layout 容器内边距分作用域，不可归并成同一个 padding | CL→AL/GC；I/K→G及可能E→X |
| M18 | `callout.line_gap_px` | `J[card].sections.gap`；分隔线位于该间隔中点由组件结构明确 | **改名并转换含义**。当前是正文与标题之间的半间隔，而非逐行行距。基线旧 Q(3)→总间隔 Q(6)；只有正文存在时出现该分隔。不得简单改名后仍取 3 | CL→GC/BE；I/K→高度/分隔位置G及可能E→X |
| M19 | `callout.opacity` | `A[card_background].opacity` | **保留为背景外观**。基线 0.88，不解释成标题/正文整体透明度 | AR→GC/BE；A→G→X |
| M20 | `callout.leader_width_px` | `A[card_leader].stroke.width` | **保留**。基线 Q(3)。引线的连接关系/位置由组件与注记实例提供，线宽不拥有地理锚点 | AR→GC/BE；A/K→G→X |
| M21 | `callout.offset_x_px` | `N[card].preferred_offset.x` | **迁入实例注记放置选择**。基线 Q(45)，表示建议偏移而非必然最终坐标；点级明确位置选择单独处理，见 X09 | AL→GC；I/K→最终G→X；求解后值可能与初值不同 |
| M22 | `callout.offset_y_px` | `N[card].preferred_offset.y` | **迁入实例注记放置选择**。基线 Q(-135)，明确图片局部 y 向下，不以屏幕/page 坐标直接复用 | AL→GC；I/K→最终G→X |
| M23 | `callout.font_weight` | `A[card_title].font.weight` | **保留并收窄作用域**。基线 700；现实现主要作用于标题，不扩张到正文。后端不能无声明地把任意权重阈值化成 bold | AR→GC/BE；A→G→X；字体/后端能力不足应拒绝或走已批准映射 |
| M24 | `callout.title_wrap` | `J[card].title.wrap_mode`，取值由组件定义限定 | **转为明确排版模式**。false→single-line-reject-overflow，true→组件声明的换行模式；基线 false。正文并不因此获得自动换行能力 | CL→GC/BE；I/K→G及可能E→X |
| M25 | `callout.show_arrival_time` | `I.content[card].fields` 是否选择 arrival-time，受 S 必需/允许内容约束 | **移出 Style**。作者基线 False，迁移基线不包含该字段；若选择显示，数据来自受信绑定，缺值按显式策略处理。旧函数“字段缺省 True”不是新系统默认权威 | CB→CL/GC；S/I→G及可能E→X；原始到达时间事实不因显示开关改变 |
| M26 | `callout.fit_content` | `J[card].sizing.width.mode` | **转为局部排版策略**。true→fit-content-up-to-limit，false→fixed；与 M14 共用一个宽度合同。基线 true；不允许等价成自动缩字号或省略内容 | CL→AL/GC；I/K→派生G及可能E→X；该策略须显式冻结 |
| M27 | `callout.title_color` | `A[card_title].color` | **保留**。基线 #FFFFFF；不与卡片背景/分组色合并 | AR→GC/BE；A→G→X |
| M28 | `callout.body_color` | `A[card_body].color` | **保留**。基线 #17352D；正文缺失时可能没有可见像素变化，但来源声明仍绑定 | AR→GC/BE；A→G→X |

### 3.4 辅助地点标记与引线标签（M29–M38）

| 编号 | 原字段 | 最终规范权威与逻辑去向 | 处理、来源和基线规则 | 消费者／摘要影响 |
|---|---|---|---|---|
| M29 | `support_label.color` | `A[support_accent].color`，由辅助点/标签背景/引线的显式共同视觉通道引用 | **保留并明确多处消费关系**。基线 #E65C6C；辅助图例读同一有效符号。派生图形可以复制色值，不产生四份独立默认 | AR→GC及图例/BE；A/I→G/P→X |
| M30 | `support_label.text_color` | `A[support_label_text].color` | **归并为单一文字角色颜色**。基线 #FFFFFF。旧图形将其镜像到 title_color/body_color，但辅助标签正文为空；不得因此新增两个可独立设计的文字色 | AR→GC/BE；A→G→X |
| M31 | `support_label.point_radius_px` | `A[support_marker].radius` | **保留**。基线 Q(12)；辅助地点角色由数据/场景决定，不能因样式缺失被当成普通调研点 | AR→GC/AL/BE；A/I/K→G及可能E→X |
| M32 | `support_label.font_size_px` | `A[support_label_text].font.size` | **归并为单一文字角色字号**。基线 Q(24)；旧 title/body 字号镜像属于机械适配，不形成两个独立值 | AR→CL/GC/BE；A/K→G及可能E→X |
| M33 | `support_label.padding_px` | `J[support-label].inset`，由 `C[linked-label]` 定义 | **迁入标签局部排版**。基线 Q(4)，参与内容适配尺寸；不是页面 Frame 的 padding | CL→AL/GC；I/K→G及可能E→X |
| M34 | `support_label.opacity` | `A[support_label_background].opacity` | **保留为背景外观**。基线 0.95；不隐式设置文字透明度 | AR→GC/BE；A→G→X |
| M35 | `support_label.leader_width_px` | `A[support_label_leader].stroke.width` | **保留**。基线 Q(2)；不与卡片引线 M20 强制共用一个参数 | AR→GC/BE；A/K→G→X |
| M36 | `support_label.offset_x_px` | `N[support-label].preferred_offset.x` | **迁入注记放置选择**。基线 Q(20)；辅助标签属于单独实例，与普通卡片位置互不隐式继承 | AL→GC；I/K→最终G→X |
| M37 | `support_label.offset_y_px` | `N[support-label].preferred_offset.y` | **迁入注记放置选择**。基线 Q(-40)；坐标作用域与 M36 成对明确 | AL→GC；I/K→最终G→X |
| M38 | `support_label.font_weight` | `A[support_label_text].font.weight` | **保留**。基线 700；不由后端默认为普通标题/正文权重 | AR→GC/BE；A→G→X |

### 3.5 编号、底图和页面附属元素（M39–M46）

| 编号 | 原字段 | 最终规范权威与逻辑去向 | 处理、来源和基线规则 | 消费者／摘要影响 |
|---|---|---|---|---|
| M39 | `numbering` | `I.content.numbering[display-order]`，规则受 S 与组件内容接口约束 | **移出 Style**。per-date-group→按日期及语义分组计数；global→采用全局访问顺序。基线卡片显示局部编号，而编号点仍绑定 visit_order；两个编号角色明确区分 | CB→GC/图例；S/I/K→G/P→X；不得改写原访问顺序 |
| M40 | `white_threshold` | `V[main-view].crop.parameters.white_threshold`，处理方法由受信显示组件定义 | **迁入底图显示合同**。基线 245，使用明确的白边检测/裁边方法。修改配色不触发改变此值；原图和配准仍是独立来源事实 | BV→显示窗口→GC/BE；V/K/E/P→X，窗口变化可能再影响G |
| M41 | `page_furniture.title_font_pt` | `A[page_title].font.size` | **保留物理单位和名义字号**。基线 PT(34)。不得误用未实际驱动旧图的通用 CARTOGRAPHY.title_pt=18 覆盖它。实际容量适配另由明确排版策略决定 | AR→页面文字测量/BE；A/I→P→X，即使最终被容量限制，名义值仍可追溯 |
| M42 | `page_furniture.body_font_pt` | `A[source_notice].font.size` | **收窄为来源说明角色**。基线 PT(12.76)，不是所有卡片/正文的全局默认字号；不与 M16 归并 | AR→页面文字测量/BE；A/I→P→X |
| M43 | `page_furniture.frame_border.color` | `A[map_border].color`，双线结构由 `C[double-outline]` 说明 | **保留**。基线 #000000；边框围绕何处由视图/组件绑定决定，不由颜色字段决定 | AR→边框 GC/BE；A/K→P→X |
| M44 | `page_furniture.frame_border.inner_width_mm` | `A[map_border].inner_stroke.width` | **保留物理单位**。基线 MM(0.25)，不乘参考像素 scale；描边中心线约定由边框表达定义 | AR→边框 GC/BE；A/K→P→X |
| M45 | `page_furniture.frame_border.gap_mm` | `A[map_border].stroke_gap` | **保留为两条边框线之间的外观间隔**。基线 MM(1.0)；不是 Layout 容器外边距。外框位移按间隔及两线半宽机械计算 | AR→边框 GC/BE；A/K→P→X |
| M46 | `page_furniture.frame_border.outer_width_mm` | `A[map_border].outer_stroke.width` | **保留物理单位**。基线 MM(0.5)；与内线宽为两项不同设计通道，不做无依据归并 | AR→边框 GC/BE；A/K→P→X |

## 4. 唯一来源与成组解释规则

### 4.1 分组、类别外观与图例

- 业务 group ID 和显示名称由 S/I 绑定；视觉角色 ID 由 Style 提供。两者通过显式绑定连接，不依赖名称相似。
- M04 表示一个共同类别颜色通道。若路线、编号点、卡片背景约定同色，它们引用同一有效通道；不能把迁移变成三个可独立修改却都号称“分组色”的字段。
- M29 同理，辅助点、标签背景、引线及图例可以共享一个明确的辅助强调通道。若后来希望它们独立配色，应作为新的显式设计，不属于等价迁移。
- M05/M09 的既有含义为“分组路线偏移优先，否则通用路线偏移”。新设计在采用/归一阶段确定每个组的唯一有效路线外观和来源，不让多个消费者各自 merge；不由此引入任意深层覆盖或通用 CSS 级联。
- M06 的缺失分组规则不再暗中决定图例颜色。旧通用“行程点”图例是一个显式内容项，绑定通用点外观；是否改成逐组点图例属于另一项设计决定。

M39 的局部计数仅针对经场景判定为调研点、需要普通行程卡片的实例；辅助地点不加入该局部计数。计数顺序仍来自原 visit_order。将辅助地点混入、重新排序或让卡片序号覆盖点的访问顺序都不是等价迁移。

### 4.2 卡片宽度、分区间隔与内容

卡片实例必须同时确定 M14 与 M26 的语义：

```text
fixed：使用显式 width.limit 作为固定宽度，放不下按声明拒绝/修订
fit-content-up-to-limit：按已登记测量规则求内容宽度，但不超过 limit
```

两者都不能隐式缩字、删字段或改变访问顺序。Layout 只提供外部可用容器；组件的宽度选择还必须满足该容器约束。

M18 的基线变换是 `section_gap = 2 × old line_gap`。分隔线位于间隔中部，基线实际顺序为“正文 → 分隔 → 标题”；不能按字段名或通常卡片习惯悄悄改成标题在上。正文为空时无正文分隔，单行辅助标签的居中行为由选定组件预设明确。

M25 只决定内容列表是否采用 arrival-time。作者基线 False，与旧函数缺省时使用 True 是两个不同来源：迁移使用已知实际基线，并在新方案里显式选定；缺失来源应澄清，不能在后端继续补 True。

### 4.3 局部排版与注记放置

- `J` 仅控制组件内部；`N` 控制地图内放置选择；页面 Layout 控制外部容器。三者不能各保存一份相同的最终几何。
- M21/M22/M36/M37 是模板提供的建议偏移，归入 preferred placement，不代表最终坐标承诺。
- 对明确固定的实例注记，必须提供 fixed 语义，求解器无权移动；对 preferred 注记，求解结果可以不同，但须记录已采用规则和结果。
- 实际行程点/路线地理锚点不能作为避让变量修改。
- 组件内部文本、尺寸和输出框统一测量，静态/前端不能另算一套不同的卡片高度。

### 4.4 原子组件与显式子内容

本映射先采用原子信息卡片/引线标签组件：标题、正文等内部组织由 C/J 决定。

若项目确需独立摆放标题/正文，可选择显式子内容布局模式；该模式不得再让原子卡片组件生成相同内容和内部坐标。切换须明确进入另一份结构选择，不是两个渲染通道同时生效。

## 5. 源值、适配与渲染的边界

### 5.1 消费链

```text
S：业务定义/要求            数据证据：实际事实
            └──────────┬──────────┘
                       ↓
I：已采用内容、分组、编号、角色和视图/注记绑定
                       ↓
选定 Style A + 组件定义/预设 C/K + 外部 Layout + 字体/底图资源
                       ↓
严格校验与归一：唯一来源、单位、参数范围、角色与能力相容
                       ↓
组件测量 CL / 底图适配 BV / 注记求解 AL
                       ↓
冻结的有效外观、内容、布局、图形 G 和页面 P
                       ↓
静态 PDF/PNG、前端 canvas/geo 文档
```

### 5.2 后端适配器可以做什么

- 可以将相同有效文字角色镜像为旧绘图函数需要的 title/body 参数，前提是这些是不可独立改写的派生副本。
- 可以保留画路线、编号点、卡片、边框的专用函数。
- 可以转换显式单位，生成后端执行指令。
- 不得读取旧 `image_itinerary`，不得重新解释业务组名，不得根据缺省值决定显示内容、编号或字号。
- 当前前端 `_resolve_facts` 直接读取私有 groups/route 的路径必须改为消费同一有效分组/外观实例；不能只改 PDF。

### 5.3 字体、字重及测量

- 字体资源仍由获准请求绑定和字节摘要管理，不放进可复用 Style 作为本机绝对路径。
- M23/M38 保留数值权重语义。若某前端合同只能表示 bold 布尔，须扩展支持或按明确准入拒绝无法表达的权重，不能静默按 >=700 截断；基线 700 的已有表现仍应核验。
- 文本测量算法及版本是机械实现条件，不是设计来源。基线一致性和新测量算法的改进必须分开验收，不能一边迁移一边更换测量方式后仍宣称全等。

## 6. 不计入 46 项、但迁移必须显式处理的决定

以下不是新增私有样式叶子字段；它们是代码隐式规则、结构信息或外围输入。列出它们是为了避免“46 项搬完但旧权威仍在”。

| 编号 | 决定 | 最终处理 |
|---|---|---|
| X01 | `groups[]` 顺序 | 进入 I 的显式图例顺序，按实际使用组筛选；不是 Style 查找顺序。旧补丁数组顺序不当作重排指令 |
| X02 | `support_label` 对象是否存在影响 stop-type 读取 | 角色分类与样式存在性脱钩。场景依据 stop-type/map-role 确定角色；缺少所需外观即拒绝，不改成普通调研点 |
| X03 | 参考尺寸 2381×1684 与 floor=1.0 | 进入精确度量规则 U 的基线预设；不是所有符号/所有后端的隐式常量 |
| X04 | 标题/正文行高乘数 1.25/1.3、正文默认字重 | 文字行高/字重由对应 Style 文字角色显式给出。组件按同一度量规则使用；不能继续由两端各自补默认 |
| X05 | 正文先于标题、分隔线位置、空正文标签居中、辅助标签无换行 | 由选定 C 结构模式/J 参数明确；单行辅助标签默认模式写入预设，不靠通用卡片的遗漏字段触发 |
| X06 | 边框围绕实际 contain 后图片还是整个 Frame | 基线明确绑定 placed-map-content，即当前实际放置的图片矩形，不默改为整个地图框。改为 view-frame 是新设计选择 |
| X07 | 编号点的白色文字、页面标题/来源颜色、图例名义字号等代码外观默认 | 纳入实际使用的 Style 角色与明确适配规则；不会因为旧 image_itinerary 没字段就继续允许后端自定 |
| X08 | “行程点”“起始/折返点”、日期/时段/里程/时长文本格式 | 纳入 S/I 内容定义，图例符号由实际表达派生；不能把业务文本写进通用组件代码 |
| X09 | 数据字段中的 callout-offset-x/y | 视为具有来源证据的实例放置输入。新合同必须明确 preferred/fixed 语义；不能自动把旧值解释为 fixed，也不能在求解时忽略真实 fixed 约束。无法确认时澄清 |
| X10 | 字体适配：名义字号与容器容量 | 本次明确采用适配模式和合法下限。旧 furniture_font_pt 的限幅只能作为显式基线规则记录，不成为所有页面默认缩字权威 |
| X11 | 原始访问顺序与局部显示序号 | 保留两个独立语义角色：visit_order 为事实，display-order 为按规则推导；卡片/点各自绑定，不互相覆盖 |
| X12 | 绘制顺序、frame_id 和坐标空间 | 继续冻结声明的绘制顺序及实际框绑定；已经完成的真实 frame_id 接入保留，不恢复 main-map 隐式。图形锚点/本地偏移/页面位置区分作用域 |

这些决定需要对应合同、消费者和反例；若某项尚不能明确表达，不得通过“用旧默认兜底”宣布私有权威已退出。

## 7. 摘要、修订与数据复用

### 7.1 当前绑定与目标绑定

当前：模板原文通过 T 绑定，请求补丁通过 R/Brief 绑定，实际结果通过 G/P/L/E 进入 X；没有单独持久化完整有效 image_itinerary 引用。

目标：

- 所选 Scenario、Style、Layout、组件/单位定义及资源都有精确引用和来源。
- I 保存已采用的内容、分组绑定、组件参数、注记选择及视图显示选择；不能只在内存中保留关键来源。
- effective appearance/portrayal/layout/page/graphics 继续使用既有解析产物与冻结链，不新建同职责的第四套解析权威或第二套锁。
- 请求/设计选择 → MapPlan → execution.template_refs、dependency_refs/资源引用 → 候选和锁之间必须严格一致；未选、多余、缺失、漂移或错误所有权都拒绝。
- G1 后不能原地回填这些选择。变更按现行修订对象、请求指纹和审批规则形成新版本；新 G2 只批准对应实际候选。

### 7.2 修订范围

| 字段族 | 首要失效对象 | 数据证据是否当然失效 |
|---|---|---|
| 组身份/分组绑定 M02、M06 | 内容/表达计划、图例、图形和相关检查 | 若改 source_bindings 或源事实则按数据输入门失效；仅明确显示映射变化不能自动重写数据 |
| 组标签、到达时间显示、编号 M03/M25/M39 | 内容计划、组件测量、图形/图例、预览与冻结选择 | 通常不改变原始数据；仍由实际依赖摘要证明可复用 |
| Style 外观各项 | 有效外观、图形；有尺寸影响时连带组件测量和注记证据 | 不因“换色”当然重做行程准备 |
| J 局部排版 M14/M17/M18/M24/M26/M33 | 组件测量、注记求解、图形、页面 | 可复用条件不变的数据证据，不能复用失效的布局结果 |
| N 建议偏移 M21/M22/M36/M37 | 注记输入/结果和图形 | 若源自旧数据字段输入则遵守原数据证据绑定；新结构下按 I 失效规则处理 |
| 底图阈值 M40 | 显示窗口证据 E、视图显示、放置和受影响图形 | 不修改原图/配准/行程文件；其引用仍需重验 |
| 页面字号、边框 M41–M46 | 页面外观与测量、边框派生、页面及预览 | 不当然影响行程数据 |
| 组件/单位定义、字体或后端实现变化 | 所有受定义/资源/环境摘要影响的实例和证据 | 按声明依赖和运行时门决定，不只靠静态表 |

“移入另一合同”本身也会改变序列化和绑定结构。旧执行不能因为图像相似而就地升级；必须按正式协议重新准备/编译/授权/冻结。

## 8. 映射必须通过的检查

### 8.1 静态覆盖

1. 原 Schema 46 个叶子字段在 M01–M46 各出现一次，无漏项、无重复主映射。
2. 每行具有规范权威、配置来源/实例语义、实际消费者和摘要去向。
3. 未把业务词汇写成通用 Style 必识别项；未新增 owner 枚举或模板种类。
4. J/N/V 的逻辑路径不是开放扩展袋，后续须有闭合、类型化 Schema 和受信定义。

### 8.2 未来实现的反例与视觉验收（本轮未运行）

| 用例 | 必须观察到的结果 |
|---|---|
| 换 Style，不改 I 的内容选择 | 地点、组成员、访问顺序和是否显示时间不变 |
| 缺组信息或未知分组 | 按已声明 S/I 策略澄清/拒绝，不靠 Style 自动归下午 |
| M05/M09 同时存在 | 每组只得到一个有效位移及明确来源；后端不再各自覆盖 |
| M14/M26 两种模式 | 固定宽与限宽适配按各自定义执行；不能自动缩字/删信息 |
| M18=旧 3 的基线 | 新总间隔为参考单位 6，分隔居中，既有高度和排序可验证 |
| M25 false 与 true，分别有值/缺值 | 严格遵守内容选择和缺失策略，无渲染器默认显示或虚构时间 |
| M23/M38 字重在两端能力不等价 | 明确支持、拒绝或受批准映射，不能静默阈值化 |
| 标题/正文卡片切侧栏 | 同一内容实例不重复绘制，内部和外部布局无双权威 |
| preferred 与 fixed 注记 | preferred 可求解；fixed 不被移动；均不改地理锚点 |
| M40 改变且窗口相同/不同 | 均保存新输入证据；只有实际窗口影响的下游按依赖变化 |
| 不同底图长宽比、裁边、旋转配准与合法 DPI | 单位规则、锚点与双端坐标符合已声明模式，不重复缩放 |
| 边框与 contain 留白 | 基线围绕 placed-map-content，不悄悄围绕整个 Frame |
| 伪造、遗漏或漂移的组件引用 | 请求/设计选择/候选/锁一致性门拒绝 |

## 9. 协议落地与切换边界

### 9.1 当前 Schema 不能被误当成已经足够

当前 `style.symbol_roles[].symbol` 复用的 encoding-ir symbol 主要是固定的颜色、描边、pt 线宽和 mm 半径结构；`labeling.hierarchy` 也不等于完整的角色化字号/复合卡片外观接口。

因此，本表的箭头、参考像素度量、角色化文字、双线边框等逻辑接口需要：

- 有判别和参数 Schema 的受信表达/外观类型；
- 明确的单位与引用协议；
- 显式角色化文字接口，不能将页面 source 字号塞进全局 body 后影响卡片；
- 卡片/标签的组件内部参数和放置实例接口；
- 视图显示阈值及处理定义的来源绑定。

可复用现有合同和注册体系，但不能只往其中加入一个无约束 parameters 对象，也不能把整个私有合同搬进 `style.image_itinerary` 后宣布完成。

### 9.2 本轮已经确定与尚需落地的分界

**已在本稿确定：**每个旧字段的语义去向、作用域、单位策略、变换关系、唯一来源规则，以及消费者/摘要/验收要求。

**后续协议工作：**将这些逻辑接口落实为实际 Schema 字段、引用包装、严格参数变体和正式版本；同步请求、计划、有效实例、回放验证及消费者。此项不是允许重新随意分配所有权，而是将已确定逻辑接口落到机器协议。

实际公共协议版本遵循现行演进治理，说明采用加性还是新版本、兼容和失败条件；不假称“只是可选字段”就可以改变旧字段含义，也不机械地把所有合同一起升版。

### 9.3 旧基线的退出

1. 现有已发布模板、锁和回执不原地改写；需要新设计的运行重新准备和冻结。
2. 创建新 Style/组件预设时明确采用上述有效基线，不让未消费的 CARTOGRAPHY 默认值覆盖实际旧图参数。
3. 原请求补丁按目标合同拆到内容、外观、局部参数、注记和视图选择；不保留一套通用 merge 同时修改这些权威。
4. 可以做离线、显式、可审核的作者迁移与合成对比，不能在正式运行中静默接受旧输入再猜测转换。
5. 切换后旧 image_itinerary 不再拥有独立默认/覆盖权威；内部绘制适配参数可以保留，但必须完全由新有效实例机械产生。
6. 领导调研模板的可替换声明、数据/表达接口和能力登记如需改变，单独版本化与治理评审；本稿不授予生产、敏感数据或新后端准入。

## 10. 基线证据与本轮交付说明

### 10.1 源文件

- `skills/carto-agent/schemas/image-itinerary-style.schema.json`
- `skills/carto-agent/schemas/image-itinerary-style-override.schema.json`
- `skills/carto-agent/scripts/carto_core/scenarios/leadership_visit/route_author.py`
- `skills/carto-agent/scripts/carto_core/scenarios/leadership_visit/style.py`
- `skills/carto-agent/scripts/carto_core/scenarios/leadership_visit/request_contract.py`
- `skills/carto-agent/scripts/carto_core/scenarios/leadership_visit/candidate_compiler.py`
- `skills/carto-agent/scripts/carto_core/compiler/image_symbols.py`
- `skills/carto-agent/scripts/carto_core/adapters/image_layout.py`
- `skills/carto-agent/scripts/carto_core/adapters/image_page_renderer.py`
- `skills/carto-agent/scripts/carto_core/adapters/frontend_canvas.py`

### 10.2 读取快照

HEAD 为 `dbae41a49aeff837b98a18cd4c2865e361427190`，另有未提交工作区。下列 SHA-256 是本轮读取时的字节摘要，不替代完整实施快照，也不是运行审批：

| 文件 | SHA-256 |
|---|---|
| `image-itinerary-style.schema.json` | `30be890432bb8dbb5a7852d5172cbd1f30c5f756ae4674c5932d6dfc8b33c083` |
| `leadership_visit/route_author.py` | `43ee145e67010dbb693e0e069b5b8dec04b8516d42aea1391788b521dd2a53f6` |
| `leadership_visit/style.py` | `fe04e5f5771cfea26fe50bd02ec1bc6d7b5ded60cc5cccb3e9c0f96e6c92dbfd` |

本次只交付字段映射设计和静态覆盖检查。没有修改原盘点、已确认裁决或任何运行实现，没有执行开发测试或地图验收。
