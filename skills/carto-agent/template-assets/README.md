# template-assets：迁移段资产源目录（2026Oct → 主仓）

用户于 2026-11-17 授权将外部项目 `2026Oct/carto-master` 的段模板资产搬入主仓。
本目录是 **git 可跟踪的资产源**（`projects/` 为运行时产物目录，不跟踪），共 13 项：

- `map-style` ×6：guangdong-admin-area-style、kernel-density-sequential-style、pastel-admin-area-style、putuo-cultural-tourism-style、yongchun-tea-tourism-style、yunnan-dem-3d-style（均 0.1.0）
- `map-layout` ×7：a2-portrait-comparison、a3-landscape-two-column、a4-landscape-comparison、a4-landscape-three-column-comparison、main-map-with-right-info-panel、portrait-admin-with-legend、yongchun-tea-tourism-layout（均 0.1.0）

2026-11-18：品牌段（map-brand/identity）经用户授权整体移除——它在渲染链中无消费者；
原迁入的 dingtalk-brand-identity 资产已一并删除。

## 目录形状

每个资产 `<kind>/<id>/<version>/` 含两个文件：

- `original.yaml`：2026Oct 原契约，逐字节保留，仅作溯源，运行时不消费；
- `<identity|cartography|layout>.yaml`：适配主仓 Schema 后的契约，是唯一可入库版本。

`MIGRATION.yaml` 记录每项资产的源相对路径、源摘要与适配说明。
守卫测试 `scripts/tests/test_template_assets.py` 强制：适配契约全部通过主仓 Schema、
原件摘要与迁移记录一致、目录与记录一一对应。

## 适配规则（最小改动，不发明设计值）

| kind | 规则 |
|---|---|
| map-style | `schema_version` 1→2；移除 `symbol_definitions`（主仓 cartography v2 无此字段，原件中保留）；补充主仓通用模板 typography 基线（源契约无字号声明） |
| map-layout | 每个 frame 补 `content_id = frame id`（主仓显式绑定协议；源早于该协议）。几何与设计数值零改动 |

## 入库方式

资产通过真实 `TemplateRepository.publish` 路径发布（闭合包 + 摘要 + 索引），
开发种子脚本：`projects/.carto-dev/_s3_asset_seed.py`（幂等，合成迁移凭据，
**不代表业务审批，也未过场景验证渲染门禁**）。已发布的开发库位于
`projects/asset-library/repo`（本机运行时产物，不跟踪）。

## 边界

- 这些是**库参考资产**：供 `template match` 只读评分与 `scenario.segment_refs` 引用消费；
- 未过 T1/TP 业务审批与验证渲染，不得宣称为生产可用模板；
- 两类段模板（style/layout）的正式创建路由（S3）尚未开放；
- 资产不含密钥、坐标或业务数据行。