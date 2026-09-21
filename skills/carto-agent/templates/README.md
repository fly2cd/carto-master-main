# 内置模板示例库

本目录保存由当前 Carto Agent 作者实现确定性生成的**合成模板示例包**，用于开发、测试、文档说明和模板创建流程回归验证。

## 重要边界

- 本目录不是 `TemplateRepository` 管理的权威发布仓库，不参与运行时 `discover()` 或 `generate-map` 的已发布模板发现。
- 这里的模板均保持 `draft` 状态；示例包不等于已验证、已审批或已发布模板，也不构成生产制图能力。
- 不得将示例包手工复制到发布仓库的 `packages/`，不得据此伪造 `template-index.yaml`、RenderReceipt、审批回执、发布事务或其他发布证据。
- 模板进入运行时前，必须通过正式的 `validate → TP → publish` 流程，由模板仓库原子写入不可变包和权威索引。
- 包内 Fixture 仅为非敏感合成数据，只用于工程验证；不得用于真实洪涝风险研判、导航、正式交付或应急决策。
- 示例包是闭合且带校验和的生成物，不应直接手工编辑。需要变更时，应修改作者实现或输入，并重新确定性生成整个包及 `checksums.sha256`。

## 当前实例

| 模板身份 | 状态 | 用途 | 数据边界 | 输出目标 |
| --- | --- | --- | --- | --- |
| `local/map-scenario/urban-flood-risk/1.0.0` | `draft` | 城市洪涝风险工程预览示例 | 合成、非生产、无敏感坐标 | SVG、PDF、PNG |

实例目录：

```text
map-scenario/urban-flood-risk/1.0.0/
├─ manifest.yaml
├─ checksums.sha256
├─ dependencies.lock.yaml
├─ templates/design_spec.md
├─ contracts/
├─ fixtures/flood-risk.synthetic.geojson
└─ prototypes/risk-overview.yaml
```

该实例对应当前唯一开放的 `map-scenario/flood-risk-overview` 作者能力，声明 EPSG:4326 输入、EPSG:3857 展示、A3 横版工程预览以及 `production_ready: false`。原型中的 `renderer_execution: not-run` 表明仓库内实例没有替代正式验证渲染。

## 验证

开发阶段可运行：

```powershell
python -m unittest skills/carto-agent/scripts/tests/test_template_library_examples.py -v
```

测试会验证包闭合性、Schema、依赖锁、业务语义、合成数据边界、未知字段拒绝、篡改检测，以及示例与当前作者实现的一致性；它不会执行浏览器渲染或发布操作。
