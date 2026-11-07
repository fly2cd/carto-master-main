# 2026-11-04 布局契约实际消费：第一阶段

> 后续状态：业务示例已在同日清理；本文的示例集成记录仅供历史追溯，通用布局契约实现保留。当前场景注册为空，见 `20261104-remove-business-examples.md`。

## 目标与基线

本阶段让模板已经声明的模块位置真正驱动输出，不以旧代码的硬编码位置为视觉基线。
主图 `[15, 28, 310, 250]`、标题 `[15, 10, 390, 14]`、图例 `[330, 55, 75, 170]` 均沿用现有契约，单位为毫米；指北针、比例尺、来源说明和合成数据声明补齐明确的 frame。
原来未实际执行的标题 `shrink` 改为明确支持的 `reject`。这些调整仅更新仓库内未发布的 draft 示例和作者实现，不覆盖已发布模板。

本阶段不做真实内容测量、自动换行、字体缩放、候选搜索、受控回调或复合专题页求解。

## 数据链

```text
scenario.embedded.layout（frame.content_id 显式绑定内容）
  -> compiler/layout.py：结构、绑定、边界及溢出策略检查，mm -> px
  -> resolved_layout：契约引用及摘要、契约快照、解析器版本、page、frames
  -> RenderScene.resolved_layout + execution.resolved_layout
  -> 预览前校验 scene/execution 一致性
  -> 既有 G2 / MapSpecLock
  -> 正式渲染与 final.layout-elements 消费同一快照
```

不引入第二种锁；机器协议仍在 Skill 的 `schemas/` 中。布局不是塞入 `shared_semantics` 的无类型配置，运行时不读取本文档。

## 几何与渲染

- `layout.frames[].bounds` 为 `[x, y, width, height]`，原点为页面左上角；`content_id` 对应唯一 view 或 overlay ID。
- 页面像素 = 毫米 × DPI / 25.4。frame 保留小数像素，页面及地图截图尺寸四舍五入到整数像素；DPR 固定为 1。
- 地理范围在 map frame 对应的独立浏览器视口中拟合，不再用整页相机 padding 模拟地图框；截图按契约的 x/y/width/height 合成到页面。
- PDF 使用快照中的物理纸张尺寸；SVG 打印样式同步指定毫米尺寸，避免把 144 DPI 输出像素当作 96 DPI 的 CSS 物理尺寸。
- 标题、图例、指北针、比例尺及说明的页面锚点统一由 frame 和现有 SVG 图元的局部 inset 计算，场景构建器不再声明整页绝对位置。

## 支持边界

- 仅单 map frame、互不重叠的页面 frame、毫米画布、DPR=1；不支持 inset、多地图和复合布局。
- 地图仅支持 `clip`，叠加内容仅支持 `reject`；`shrink`、`paginate` 等返回 `LAYOUT_OVERFLOW_UNSUPPORTED`，不静默降级。
- SVG 固定字号为 16px。当前用共享的保守图元包络检查内容是否超出 frame，超出返回 `LAYOUT_CONTENT_OVERFLOW`。**这不是真实字体测量，也不证明可读性或无视觉碰撞。**
- capacity 仍是既有场景预检的粗粒度约束；本阶段不会把字符数估算宣称为实际排版测量，也不会执行任意声明式关系求解。
- 输出继续受现有场景策略约束，当前为 A3 横向、144 DPI；支持坐标换算不等于开放新的输出规格。

## 摘要、审批与升级

- `executionSnapshot.resolved_layout` 为必填，旧候选或旧锁缺少该字段时拒绝继续；不自动填充或迁移。
- 预览、正式渲染和终检重新核对契约解析结果、scene/execution 布局快照、场景摘要、camera、view 绑定与目标纸张尺寸。
- frame 变化会影响契约、scene 与 execution 摘要，必须重新编译、预览和取得精确 G2；不能复用旧场景证据。渲染器及叠加引擎版本更新为 1.1.0，frontend build 同步更新。
- 内置 `templates/map-scenario/urban-flood-risk/1.0.0/` 仅是 draft，不作为运行时发布仓库；本次仅更新其契约和校验和。
- 若已有已发布的 1.0.0，必须另行进行版本、注册与发布授权，再走验证/TP 和地图编译/预览/G2 流程。本次不覆盖已发布包、不改能力策略、不签发审批。
- 底层 renderer 保留独立场景/环境探测用途；业务 execution 仍强制要求布局快照，这不是旧锁兼容通道。

## 改动位置

- 协议：`layout.schema.json`、新增 `resolved-layout.schema.json`、`common.schema.json`、`render-scene.schema.json`。
- 公共解析：新增 `scripts/carto_core/compiler/layout.py`。
- 场景作者/候选/验证：`scenarios/synthetic_flood/{author,candidate,validation}.py`。
- 渲染适配器：`adapters/{webmap_renderer,controlled_renderer,svg_compositor}.py`。
- 工作流：`workflow/{template_validation,map_preview,map_render,map_final_check}.py`。
- 示例与测试：内置 draft、合法/非法 resolved-layout JSON、公共 Schema Fixture、新增布局回归测试源码。

## 验证状态

新增 `scripts/tests/test_layout_contract.py`，覆盖结构与显式绑定、frame 位移/重叠/越界、未支持策略拒绝、快照篡改、旧证据拒绝、SVG 地图框、PDF 物理尺寸、模拟视口切换及两类场景构建入口的一致性。

**遵照用户要求，没有运行任何测试代码；也未运行业务 CLI、浏览器、渲染或审批流程。**
仅进行源码/差异审阅、Python AST 与 JSON 静态解析、模板文件校验和静态核对及差异空白检查。静态检查不能代替运行与视觉验收；后续需经用户授权后运行回归，并检查真实 PNG/PDF、字体、页面布局和证据闭环。
