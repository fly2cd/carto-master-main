# A2 开发日志：统一数据与素材处理（第一阶段）

更新日期：2026-11-12（Asia/Shanghai）
状态：**A2.1 框架完成；P0-0/P0-1/P0-2/P0-3/P0-4 全部完成——A2 素材链端到端打通（material_sources→提取→data_facts→execution_digest→失效传播）；A1 端到端链路跑通；A2.3 OCR 推迟（P2）**

## 前置

- A1.3 审图闭环已完成
- A0 的数据采用责任已确认

## A2 总体范围（来自实施计划）

| 子任务 | 内容 | 状态 |
|--------|------|------|
| A2.1 | 拆数据事实、语义和表达，保持现有栅格结果与检查不退化 | ✅ 框架完成（纵向失效链见 P0-1/P0-2） |
| A2.2 | 接入普通文档、表格和图片提取，保留来源定位 | ✅ 初次完成（text/plain, text/csv） |
| A2.3 | 接一种获准 OCR 方案（Tesseract） | ⏸️ 推迟（外部依赖，见 P2-1） |
| A2.4 | 准备服务产生实际结果和工具证据 | ✅ 基础证据框架完成（素材事实入候选见 P0-1） |

## 改动文件清单

| # | 文件 | 类型 | 改动概要 |
|---|------|------|----------|
| 1 | `schemas/material-source.schema.json` | 新增 | 素材来源 Schema：格式、来源定位、提取工具、版本摘要 |
| 2 | `schemas/extraction-result.schema.json` | 新增 | 提取结果 Schema：字段定义、行级溯源定位、问题记录 |
| 3 | `schemas/data-facts.schema.json` | 新增 | 数据事实 Schema：不可变捕获摘要、素材引用、观测维度 |
| 4 | `schemas/prepared-data-bundle.schema.json` | 修改 | 新增 `material_sources`、`adoption_evidence`、`data_facts`；raster/vector role_binding 新增 `semantic_fields`、`facts_digest` |
| 5 | `schemas/extraction-result.schema.json` | 修改 | 新增 `source_format` 可选字段 |
| 6 | `workflow/material_extraction.py` | 新增 | 素材提取框架 + PlainTextExtractor + CsvExtractor（含行/单元格级溯源定位） |
| 7 | `workflow/data_adoption.py` | 新增 | 数据采用服务：安全扫描、格式白名单、尺寸校验、数据事实构建 |
| 8 | `workflow/map_data_preparation.py` | 修改 | 集成素材提取管道：在 GIS 准备后提取 request.material_sources |
| 9 | `workflow/preparation_bundle.py` | 修改 | raster role_binding 新增 `facts_digest` 和 `semantic_fields`；vector 同理 |
| 10 | `workflow/__init__.py` | 修改 | 导出 `MaterialExtractionService`、`DataAdoptionService` |
| 11 | `tests/test_a2_material.py` | 新增 | 34 个测试（文本提取 7、CSV 提取 9、数据采用 10、安全 4、类型检测 4） |

## 实施详情

### A2.1：数据/语义/表达三层分离

**核心设计**：
```
数据事实（Data Facts）  → 不可变，改变即失效
    ├─ 像素/坐标/文本/表格（已验证摘要）
    └─ facts_digest: sha256(pixel_source + dimensions + CRS)

语义层（Semantic）      → 可更新（同一事实可有不同解释）
    ├─ 类别→标签映射（值 1="耕地"、值 2="林地"）
    └─ semantic_fields: {value_X: "category_label"}

表达层（Expression）    → 独立于语义
    ├─ 颜色、符号、线宽（已在 raster_portrayal.py / vector_portrayal.py）
    └─ 换配色不重算统计 ← 关键验收项
```

**prepared-data-bundle 变更**：
- Raster role_binding 新增 `semantic_fields`（与 vector 对齐）：`{"value_1": "耕地", "value_2": "林地"}`
- Raster/Vector role_binding 新增 `facts_digest`：数据事实的不可变摘要，修改源数据改变此摘要
- Bundle 顶层新增：
  - `material_sources`：非 GIS 素材的提取引用
  - `adoption_evidence`：每条素材的采用/排除决策记录
  - `data_facts`：聚合数据事实摘要

**不变性保证**：
- 修改配色 → 不变 `facts_digest`（表达层变更）
- 修改图例映射 → 不变 `facts_digest`（语义层变更）
- 修改源数据文件 → `facts_digest` 改变（事实层变更，语义和表达失效）
- 通过 `load_verified` 的 drift 检测防止静默替换

### A2.2：素材提取框架

**PlainTextExtractor**：
- 提取纯文本/markdown 为行级溯源定位的结构化结果
- 每行记录：`{index, cells: {line: "..."}, source_location: {line_start, line_end, byte_offset, byte_length}}`
- 限制：UTF-8 only, ≤1 MiB, 禁止控制字符

**CsvExtractor**：
- 提取 CSV 为单元格级溯源定位的表格数据
- 每行记录：`{index, cells: {col1: val1, ...}, source_location: {line_start, line_end}}`
- 自动类型检测：integer → number → string → boolean 优先级
- 限制：≤50000 行, ≤256 列, 列名必须 `[a-zA-Z_][a-zA-Z0-9_]*`

**安全防护**：
- 阻塞模式扫描（`import os`、`subprocess.`、`eval(` 等执行指令）
- 格式白名单（仅允许 `.txt`, `.csv`, `.md`, `.json`, `.png`, `.jpg`, `.tiff`, `.pdf`）
- 文件大小限制（64 MiB）
- PathGuard 范围校验（禁止越权读取）

**确定性保证**：
- 同一文件 → 同一 digest（内容导出确定性）
- 不同 source_id → 不同 digest（避免碰撞）
- Excel 方言（不用 csv.Sniffer，避免不稳定的方言检测）

### A2.3：OCR（推迟）

推迟原因：
- 需要 Tesseract 作为外部依赖（不在当前 conda 环境）
- OCR 不确定性模型和纠错协议需要独立设计
- Schema 接口已预留：`extraction-result` 的 `text_content`、`image_metadata`、`issues` 字段可直接承载 OCR 结果

接入点设计：
- 新增 `OcrExtractor(BaseExtractor)` → 实现 `extract()` 返回 `ExtractionResult`
- `source_ref.content_ref` 指向图片文件
- `issues[]` 记录识别不确定性
- `DataAdoptionService` 的 `_scan_blocked_patterns` 自动适用于 OCR 文本

### A2.4：证据硬化

**提取证据链**：
```
source_file → _snapshot_bytes() → content_ref (sha256 of bytes)
  → BaseExtractor.extract() → ExtractionResult (validated, digest)
    → DataAdoptionService.adopt() → adoption_evidence {decision, reason, adopted_at}
      → build_data_facts() → data-facts {material_refs, observed_dimensions}
```

**拒绝机制**（返回 evidence with `decision: "excluded"`，不静默跳过）：
- 格式不匹配 → `"Format X is not in the allowed set"`
- 空提取 → `"Extraction has zero bytes"`
- 超限 → `"Tabular data exceeds N row limit"`
- 阻塞模式 → `SecurityError("MATERIAL_BLOCKED_PATTERN")`（直接拒绝，不是 excluded）

## 测试基线

| 测试套件 | 结果 |
|----------|------|
| test_a2_material.py | ✅ 34/34 |
| Schema 检查 | ✅ 80/80 |
| test_security.py | ✅ 16/17 (1 skipped) |
| test_up1.py | ✅ 31/31 |
| test_up27_integration.py | ✅ 10/10 |
| test_a12_revision.py | ✅ 16/16 |
| test_raster_formal.py | ✅ 16/16 |

**123 passed, 1 skipped, 0 failed**（核心回归 + A2）

## 关键设计决策

1. **用 Excel 方言而非 csv.Sniffer**：Sniffer 对单列或极小 CSV 不可靠（产生空列名或错误分隔符），Excel 方言对所有合法 CSV 是确定性的
2. **source_format 作为提取结果的可选字段**：提取器明确知道格式时填入，DataAdoptionService 回退到 URI 扩展名检测
3. **facts_digest 基于源数据和观测维度**：不包含语义标签（语义可变），但包含几何/维度（物理属性不可变）
4. **adoption_evidence 包含 excluded 决策**：不静默跳过材料，每个材料都有明确的采用/排除记录

## 实施进展更新（2026-11-12 清障会话）

### P0-1 已实施：素材事实纳入 execution_digest

采用方案 A（execution base 引用素材事实），3 处改动打通"素材事实 → 候选 → 锁失效"：

| # | 文件 | 改动 |
|---|------|------|
| 1 | `schemas/common.schema.json` | `executionSnapshot` 新增可选字段 `material_facts_refs`（array of artifactRef）|
| 2 | `scenarios/general_thematic.py` | `_execution_base()` 增加 `material_facts_refs`（引用 `bundle["data_facts"]`）|
| 3 | `scenarios/general_vector.py` | 内联 base 同步增加 `material_facts_refs` |

透传机制已验证：`bind_execution` 用 `result = deepcopy(execution)` + `update(...)`，raster 分支的 `pop` 只删 camera/overlay_coordinate_policy/interaction_policy 三键，`material_facts_refs` 会透传进最终 execution → `execution_digest`。失效链：改素材源文本 → `facts_digest` 变 → `material_facts_refs[].digest` 变 → `execution_digest`/`candidate_digest` 变 → 旧锁 render 触发 `MAP_SPEC_LOCK_CANDIDATE_DRIFT`（map_generation.py:1058，先于 :1060 EXECUTION_DRIFT），再被 `_locked_render_inputs` 的 except 归一化为对外 `LOCK_INPUT_DRIFT`（原始码留 message，:1106-1109）。

### 清障：修复 7 项预存 bug，A1 端到端链路首次跑通

为验证 P0-1，需先让唯一准入场景（general-thematic raster）的 compile 链跑通，过程中修复 7 项 A1.1/A1.3 遗留的预存 bug：

| # | Bug | 类型 | 修复 |
|---|-----|------|------|
| Bug1 | dependency_refs oneOf 冲突（categorical 同时匹配 artifactRef/mapExpressionRef）| 生产·schema | `resourceRef` oneOf→anyOf |
| Bug2 | APPROVAL_SUBJECT_MISMATCH（票据 test-reviewer vs 请求 test-subject）| 测试·fixture | `sign()` 参数化 subject/scope，generate 线对齐 request |
| Bug3 | PAGE_CONTRACT_VERSION（validation_scene 产 v3 page）| 生产·场景 | validation_scene page v3→v4 + 注释同步 |
| Bug4 | APPROVAL_ACTION_MISMATCH（review 签 approve-review/validation-report）| 测试·fixture | review 签法对齐 G2（approve-freeze/resolved-map）|
| Bug5 | test_schemas fixture 缺失（5 个 A1.2/A2 新 schema）| 测试·fixture | 补 5 个 VALID_CASES（INVALID 自动派生）|
| Bug6 | APPROVAL_NONCE_CONFLICT（freeze/review 同 G2 nonce）| 测试·fixture | `sign()` nonce 按 digest 唯一化 |
| Bug7 | KeyError 'g3'（check/review 拆分后断言过时）| 测试·fixture | `checked["g3"]`→`reviewed["g3"]` |

**复测结果（geo313，2026-11-12）**：

| 测试套件 | 结果 |
|----------|------|
| test_schemas | ✅ 20/20 |
| test_general_thematic | ✅ 23/23（含完整 G1→…→G3→幂等重放）|
| test_raster_formal | ✅ 16/16 |

**附带确认（修正早期静态评估）**：清障实证工作区已修复 R1（nonce 防重放真实生效——Bug6 的 nonce 冲突即证据）与 R3（`_gate_coordinator` 用 `trusted_subject_id` 取自 request 而非票据——Bug2 即证据）。A1 整体验收链路首次真正端到端跑通。

### 新发现：断点 P0-0（比 P0-1 更靠前）

核查 P0-3/P0-4 前置时发现：`generate-request.schema.json` 顶层 `additionalProperties: false` 且**无 `material_sources` 字段**，而 `map_data_preparation.py:40` 读 `request.get("material_sources", [])`。因此带素材的请求会被 schema 拒绝，素材提取/采用/data_facts 管道**从不被触发**。即 A2 素材链有两个断点：断点0（request 入口未开）+ 断点1（data_facts 未进 execution，已由 P0-1 修复）。P0-2/P0-3/P0-4 端到端失效验证必须先补断点0。

### P0-0 已修复 + P0-3/P0-4 端到端验证通过（2026-11-12）

补断点0 时又发现两个更深的子断点，一并按方案 X 修复：

| 子断点 | 根因 | 修复 |
|--------|------|------|
| 断点0（schema）| generate-request 无 material_sources 字段 | 加可选 `material_sources`（item = {source_id, path, format?}，format enum 对齐 ALLOWED_FORMATS）|
| 断点0.5（bundle 比对）| 场景 candidate_compiler 用 BundlePreparer 重建 bundle（不含 material），与 MapDataPreparer 产出的含 material bundle 严格比对必失败 | 新增共享 `bundle_core()`（排除 material 三字段），general_thematic.py + map_candidate.py（raster/vector）三处比对改用；material 完整性由 execution_digest 保证 |
| 断点0.6（相对路径）| extract_many 的 guard.resolve 未传 base_root，素材相对路径报 RELATIVE_PATH_WITHOUT_ROOT | extract_many 加 base_root 参数，MapDataPreparer 传 project_root（与 GIS 源解析一致）|

**P0-3/P0-4 端到端验证（test_general_thematic 新增 2 测试）**：
- P0-3 `test_material_sources_reach_execution`：material_sources 经 workflow.compile → bundle（material_sources/adoption_evidence/data_facts）→ execution.material_facts_refs，且 refs[0].digest == bundle.data_facts.digest ✅
- P0-4 `test_material_change_invalidates_execution_digest`：改素材内容 → data_facts.digest 变 → execution_digest 变（失效传播成立）✅
- P0-2 闭环 `test_material_change_invalidates_frozen_lock`：素材 A 跑到 freeze 锁候选 A → 改素材 B 重编译候选 B → 旧锁 render 触发 `LOCK_INPUT_DRIFT`（内部根因 `MAP_SPEC_LOCK_CANDIDATE_DRIFT`）→ 旧锁失效端到端实证 ✅

**全量回归（geo313，2026-11-12）**：test_schemas 20 + test_a2_material 34 + test_general_thematic 25 + test_raster_formal 16 = **95 tests OK**（仅 raster/categorical@1.0.0 弃用 FutureWarning，非本次引入）。

**A2 素材链首次端到端打通**：素材文件 → 提取(溯源) → 采用(证据) → data_facts → execution.material_facts_refs → execution_digest → 锁失效。P0-1~P0-4 全部闭环。

## 后续工作（A2 第二阶段）— 按链路完整性优先级分级

分级原则：**先纵向打通**（素材事实 → 候选 → 失效传播），**再横向扩展提取器**（OCR / 图片 / JSON / Markdown）。

依据：素材链原有两个断点——断点0（`generate-request` schema 无 `material_sources` 字段，素材进不了请求，提取/采用/data_facts 管道从不触发）+ 断点1（`data_facts` 未进候选 `execution_digest` 与锁失效链）。断点1 已由 P0-1 修复（`material_facts_refs` 经 `bind_execution` 透传）；断点0（P0-0）仍在，是 P0-2/P0-3/P0-4 的前置。分级原则：先纵向打通，再横向扩展提取器。

### P0：链路完整性核心（纵向打通）— ✅ 全部完成

- [x] **P0-0（已完成）** 素材入口接入：generate-request 加 `material_sources` + 修复断点0.5（`bundle_core` 排除 material 比对）+ 断点0.6（extract_many 加 base_root 解析相对路径）
- [x] **P0-1（已完成）** 素材事实入候选：`executionSnapshot` 新增 `material_facts_refs`，两个场景 base 引用 `bundle["data_facts"]`，经 `bind_execution` 透传进 `execution_digest`
- [x] **P0-2（已完成）** 失效传播：改素材 → `facts_digest` 变 → `execution_digest`/`candidate_digest` 变 → 旧锁 render 触发 `MAP_SPEC_LOCK_CANDIDATE_DRIFT`（对外归一化 `LOCK_INPUT_DRIFT`）；由 `test_material_change_invalidates_frozen_lock` 端到端实证
- [x] **P0-3（已完成）** 集成测试：`test_material_sources_reach_execution`（material_sources 经 MapDataPreparer→compile→execution.material_facts_refs）
- [x] **P0-4（已完成）** 端到端验收：`test_material_change_invalidates_execution_digest`（改素材→execution_digest 变）

### P1：接口已预留，按触发条件实现（横向格式扩展）

扩展点已就绪：继承 `BaseExtractor` + 注册 `_FORMAT_EXTRACTORS` / `_extractors` 即可，不改架构；未映射格式已优雅降级为 `MATERIAL_EXTRACTOR_MISSING`。

- [ ] P1-1 ImageExtractor（image/png、image/jpeg、image/tiff 基础元数据：尺寸/颜色模式）— 触发：A3.2 海报（图片素材刚需，A3.2 前必须）
- [ ] P1-2 JsonExtractor（application/json 字段级提取）— 触发：需结构化 JSON 输入；当前可先映射到 plain-text 兜底
- [ ] P1-3 Markdown 结构化提取（标题/表格/列表层级）— 触发：海报/调研需解析 md 结构；当前 `.md` 已由 plain-text 行级兜底

### P2：可推迟（外部依赖 / 增强）

- [ ] P2-1 Tesseract OCR 接入（`OcrExtractor` + 不确定性模型 + 纠错协议）— 外部依赖不在当前 conda 环境；`extraction-result` 的 `text_content` / `image_metadata` / `issues` 接口已预留；触发：真实业务出现扫描件素材
- [ ] P2-2 图片完整 EXIF 解析（拍摄地/时间等）— 基础尺寸/颜色模式够用时可简化；触发：需元数据核验时

### 待实现能力的标注方式（与既有准入机制一致）

- 代码层：未映射格式接入 `policies/capability-roadmap.yaml` 的 `not_implemented` 准入类（带 `admission_class` / `feature` / `status`），让“未实现”成为可查询的显式路线图状态，而非裸错误。
- 占位提取器：为 OCR / Image / Json 各建 `raise not_implemented` 占位子类并登记注册表，接口显式存在、状态可查，实现时只替换 `extract()` 体。