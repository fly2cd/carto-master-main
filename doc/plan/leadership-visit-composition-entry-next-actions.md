# 领导调研自由组合与需求入口：后续具体事项与目标

| 项目 | 内容 |
|---|---|
| 日期 | 2026-11-25（Asia/Shanghai） |
| 状态 | 后续实施建议与验收目标，待执行；不表示工作已完成，也不构成代码执行或业务审批授权 |
| 现状依据 | 本次讨论中对工作区源码、实施状态和验收记录的读取；实施前须重新核验快照和未提交变更，不能用本文替代最新代码核验 |
| 建议首批 | 事项 1、2，以及事项 3 的协议与资产方案准备 |
| 相关材料 | [所有权与合同边界裁决](leadership-visit-ownership-contract-boundaries.md)、[46 字段映射](leadership-visit-style-contract-field-mapping.md)、[实施状态](composable-template-implementation-status.md)、[验收包](leadership-visit-acceptance-package.md) |

> 本文保存本次讨论中的“下一步具体事项与目标”。它是工作清单，不新增所有权权威、运行协议或平行工作流。文中的代码现状与日志状态对应清单形成时的读取结果；若后续实现已经改变，应先核验并更新状态，不重复修改已经完成的工作。

## 总体推进方向

建议把下一步明确成 **“消费者收口 → 独立组件组合 → 业务入口调整 → 检索闭环”**，而不是再次重做 46 字段拆分。

需要先说明一个事实：**映射结构已经建立，但本次核对时仍有少量消费者没有完整执行新合同语义。**这些应作为第一批收尾事项，否则后面开放自由组合时会把问题放大。

## 一、建议分成三个交付目标

| 交付目标 | 用户可感知的结果 |
|---|---|
| **M1：显式组件组合** | 给定已发布的 Style/Layout 引用，领导调研能够正确生成、修订、冻结和交付 |
| **M2：需求入口** | 用户不填写模板 ID，也能提交业务任务、获得并采用设计方案 |
| **M3：检索闭环** | 系统根据需求检索兼容组件、解释候选，由明确选择进入生成链 |

**先完成 M1，再完成 M2/M3。完整 P3b、GD、多页自由编排不作为前置条件。**

---

## 二、事项 1：收口新合同的实际消费

这是当前最应该先处理的事项，不属于重新拆字段。

### 当前代码依据

`skills/carto-agent/scripts/carto_core/scenarios/leadership_visit/contract_migration.py` 中仍有：

```python
def _value(measurement):
    return measurement["value"]
```

角色选择仍有：

```python
roles[f"group-{gid}"]
roles[f"route-{gid}"]
```

`design-instances.schema.json` 的组件参数仍是普通 object；当前编译入口没有完整接上组件定义中的参数 Schema。

### 具体工作

1. **完成度量解析**
   - 使用声明的 `kind`；
   - 解析和校验 `rule_ref`；
   - 不支持的单位组合明确拒绝；
   - 不把 mm/pt 的数值直接当参考像素使用。

2. **完成显式角色绑定**
   - 从 `group_bindings` 找视觉角色；
   - 不根据业务组名拼接 Style 角色名；
   - 拒绝重复、缺失和悬挂绑定。

3. **接通组件定义校验**
   - 解析受信组件定义；
   - 按定义校验参数、结构模式、角色和后端要求；
   - 未知参数不能被接受后丢弃。

4. **核对内容和放置选择**
   - 内容列表中的可选项必须实际生效；
   - fixed/preferred 必须进入真正的布局约束；
   - 不以 Schema 合法代替消费者验证。

### 涉及位置

以下路径相对 `skills/carto-agent/scripts/carto_core/`，Schema 除外：

- `scenarios/leadership_visit/contract_migration.py`
- `scenarios/leadership_visit/candidate_compiler.py`
- `compiler/image_symbols.py`
- `skills/carto-agent/schemas/design-instances.schema.json`
- 组件定义及参数 Schema

### 完成目标

> 修改一个合法的新合同选择，输出或拒绝结果必须符合其语义；不存在“字段接受了，但运行仍按固定名称或默认规则执行”。

---

## 三、事项 2：让修订直接作用于新合同，避免旧形状往返

### 当前代码依据

领导调研的 `apply_overrides()` 仍采用：

```text
design_instances
→ 解析为旧有效样式形状
→ 合并 style_overrides
→ migrate_image_itinerary
→ 重建 design_instances
```

这条路径可能无法保留旧形状不能表达的选择。

### 具体工作

- 将修订按归属分别作用于：
  - 外观；
  - 组件参数；
  - 注记放置；
  - 内容选择；
  - 分组绑定；
  - 底图显示。
- 旧形状仅保留为必要的**单向后端派生副本**。
- 实现明确的修改、替换和恢复基线语义。
- 继续使用现有修订状态机和依赖失效机制。

### 涉及位置

- `scenarios/leadership_visit/request_contract.py`
- `scenarios/leadership_visit/revision.py`
- `skills/carto-agent/schemas/design-revision-proposal.schema.json`
- 修订与依赖分析测试

### 完成目标

至少通过：

> 只修改颜色，组件结构、内容选择、fixed 注记、分组绑定、底图参数和度量规则引用保持不变。

原始行程数据是否复用，仍由真实输入摘要检查决定。

---

## 四、事项 3：形成真正独立的 Style/Layout 资产

现在“存在 `style_roles` 数据”与“能够选择一个独立已发布 Style”还不是同一件事。

### 具体工作

1. **确定 Style 包如何承载新的角色化外观**
   - 对接现有 `map-style` 创建、验证和发布流程；
   - 不重新嵌入一整个 `image_itinerary`；
   - 不新增无约束的扩展参数袋。

2. **形成独立 Layout 包**
   - 使用已支持的页面和内容接口；
   - 明确适用范围、必需容器及容量条件。

3. **Scenario 改为业务合同与默认组合来源**
   - 保留业务语义；
   - 引用默认 Style/Layout；
   - 明确允许替换的段及兼容条件。

4. **完成合法版本发布**
   - 当前作者仍固定 `leadership-visit-map@1.0.0`，不能用改变后的合同覆盖旧版本；
   - 确定新模板版本、作者协议和准入登记；
   - 在存在旧版本的仓库中验证发布与切换。

### 涉及位置

- `skills/carto-agent/schemas/style.schema.json` 及相关外观合同
- `scenarios/leadership_visit/route_author.py`
- `workflow/segment_workflow.py`
- `workflow/segment_validation.py`
- 领导调研创建请求 Schema
- `skills/carto-agent/policies/scenario-capabilities.yaml`，如登记语义需要变化

### 完成目标

> 至少两份独立 Style、两份兼容 Layout 可以真实创建、验证、发布和精确引用，不依赖修改场景 Python 常量来换设计。

这一步涉及策略语义时，必须走现有 steward 评审。

---

## 五、事项 4：接通领导调研请求级组件组合，完成 M1

### 当前代码依据

领导调研仍明确拒绝：

```python
if request.get("segment_refs"):
    raise ProtocolError("SEGMENT_SELECTION_UNSUPPORTED", ...)
```

作者也仍只声明：

```yaml
replaceable_segments:
  - layout
```

编译器主要从 Scenario 的 `portrayal.design_instances` 获取设计，尚未将独立选中的 Style 作为完整来源接入。

### 具体工作

1. 从受信仓库解析选中的 Style/Layout。
2. 使用共享所有权规则形成唯一有效设计。
3. 将 Scenario 默认、组件替换和实例参数的来源分清。
4. 由实际规划生产者填写内容、组件、放置及绑定信息，不能只有 MapPlan Schema 增加字段。
5. 扩展现有选择一致性门，绑定实际采用的组件和实例。
6. 接通 `segment_refs` 修订及重新预览、冻结。
7. **完成后才解除领导调研的拒绝条件。**

### 涉及位置

- `scenarios/leadership_visit/request_contract.py`
- `scenarios/leadership_visit/planner.py`
- `scenarios/leadership_visit/candidate_compiler.py`
- `scenarios/leadership_visit/revision.py`
- `compiler/map_candidate.py`
- `compiler/ownership.py`

### 完成目标

```text
显式提供 Style/Layout 引用
→ compile
→ preview
→ G2 freeze
→ render
→ check / review
→ G3 deliver
```

并证明：

- 换 Style 不改变业务事实；
- 换 Layout 不丢必需内容；
- 不兼容组合明确拒绝；
- 新增兼容模板无须修改场景编译器。

---

## 六、事项 5：拆分业务入口和内部执行输入，完成 M2

### 当前代码依据

- 领导调研 `_REQUIRED_FIELDS` 仍要求 `template`；
- `request_scaffold.py` 固定查询 `leadership-visit-map`；
- `resolve_generate()` 仍通过模板身份取得能力档案。

### 具体工作

建立两个清晰层次：

```text
业务输入：
目标、材料、输出要求、硬约束、偏好
不要求模板 ID

内部执行输入：
已采用的业务基线、Style/Layout 精确引用、
实例参数、数据绑定和设计选择证据
```

然后：

1. `request_scaffold` 不再以查询到固定模板作为创建业务任务的前提。
2. 允许用户指定模板约束，但不强制指定。
3. 设计选择形成不可变产物或版本，与业务请求关联。
4. 编译前必须完整解析选择，不能临时猜测。
5. 不在已 intake 的请求中原地补写模板引用。

### 涉及位置

- `services/itinerary-tools/request_scaffold.py`
- 生成请求和领导调研请求协议
- `workflow/map_generation.py`
- `workflow/map_planning.py`
- `scenario_registry.py`

### 完成目标

> 用户只提供业务需求与合法材料，就能建立任务、获得设计提案；模板尚未选定时进入明确的规划／澄清状态，而不是因为缺 `template` 直接失败。

**这一阶段仍可保留已登记 Scenario 作为内部业务基线，不必同时完成任意 Scenario 身份准入。**

---

## 七、事项 6：接通类型化检索，完成 M3

### 当前代码依据

`cli/match_cmd.py::_resolve` 仍存在：

```text
固定寻找 general-thematic 档案
使用 LayoutResolver 解析候选
固定采用 300 DPI
```

它还不是领导调研的完整设计检索入口。

### 具体工作

- 传入实际场景能力和输出上下文；
- Style、Layout、组件分别提取类型化事实；
- 核验角色、表达、容量、字体和后端要求；
- 区分不兼容、未知条件、搜索不完整和确实没有匹配；
- 由 LLM／用户明确采用方案，分数只作建议；
- 将结果交给已经验证的 M1 组合生成链。

### 涉及位置

- `cli/match_cmd.py`
- `repository/template_matching.py`
- `compiler/design_requirements.py`
- `compiler/creation_orchestration.py`
- 规划入口及设计选择协议

### 完成目标

> 用户无需手写模板 ID，系统能够给出有依据的兼容方案，并将明确采用的方案准确执行。

---

## 八、必须贯穿上述事项的验收与发布工作

本清单形成时，`leadership-visit-acceptance-package.md` 的最终全量结果仍是待填状态；读取的最新日志也尚未给出最终汇总。因此应先把证据收口，而不是仅以状态标题认定发布就绪。开始实施前应重新核验最新结果。

具体包括：

1. **固定实际代码快照**  
   本次读取时仍是 HEAD 加大量未提交工作区，需要明确验收对应的文件版本。

2. **真实跨场景验证**  
   同一份兼容 Style/Layout 分别进入两个场景的生成链，不只是重复调用 `LayoutResolver`。

3. **修订与安全反例**  
   未选择组件、摘要漂移、错误作用域、未知参数、规则引用漂移和恢复路径均有验证。

4. **版本切换演练**  
   在已有旧模板的仓库上测试；不覆盖旧包、不自动修改旧锁。

5. **更新支持矩阵**  
   明确当前支持的组件、参数、单位、版式和后端；未验证项不能写成已支持。

---

## 九、推荐执行顺序

```text
事项 1：合同实际消费收口
    ↓
事项 2：新合同无损修订
    ↓
事项 3：独立资产与合法版本发布
    ↓
事项 4：领导调研显式组合全链——M1
    ↓
事项 5：业务输入与执行输入分层——M2
    ↓
事项 6：类型化检索与规划连接——M3
```

验收、摘要治理和版本处理贯穿每一项，不留到最后补。

**如果现在只启动下一批，建议范围限定为事项 1、2，再准备事项 3 的协议与资产方案。**这批的目标非常明确：

> **任何合法的新合同选择都能被实际执行或明确拒绝；一次局部修订不会丢失其他已采用设计。**

达到这个条件后，再开放独立模板组合和需求驱动入口，风险会明显更可控。

本次仅保存工作清单，未修改运行代码、Schema、策略或既有验收记录，也未执行测试。
