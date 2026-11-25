# P6 §13.5 单位 / 几何技术验证报告

| 项目 | 内容 |
|---|---|
| 日期 | 2026-11-25 |
| 性质 | 完整迁移的**进入条件**验证（计划 §13.5），非迁移本身 |
| 环境 | geo313 / Python 3.13.18 / pyproj 3.8.0 / PROJ 9.7.1 |
| 数据 | 全合成；无业务数据、审批或渲染准入 |
| 验证测试 | `tests/test_p6_unit_geometry_validation.py`（14 passed, 13 subtests） |
| 容差 | 先固定后测量：几何 1e-6 px；宽高比 1e-9；字体 pt 1e-9；物理 pt 1e-9。**不因结果放宽** |

## 1. 单位流向图

```
WGS84 lon/lat
   │  pyproj Transformer (EPSG:4326 → 投影米制 CRS, always_xy, offline, allow_ballpark=False)
   ▼
投影米 (x, y)
   │  (xy - origin_m) / [1000, -1000]   ← local km, y-down
   ▼
局部 km (y-down)
   │  @ affine[:, :2].T + affine[:, 2]   ← local_km_y_down_to_pixel (2x3)
   ▼
原图像素 (零基, 像素中心)                ← inside: [-0.5, size-0.5) 半开
   │  clip_line (Liang-Barsky, 不夹断顶点)
   │  display_window {x,y,width,height}  ← 裁边窗口，独立测量事实，不进 affine
   ▼
显示窗口像素
   │  contain_layout: scale=min(frame.w/src.w, frame.h/src.h), 居中
   ▼
页面像素 (地图框内)                     ← px_per_mm = dpi/25.4
   │
   ├─ 图形符号: reference-design px × scale, scale=max(1.0, min(win/REF))  ← REFERENCE_WIDTH_PX=2381@144DPI
   │            (route.width_px / pin.radius_px / callout.*_px / offset_px)
   │
   └─ 页面家具: 物理 pt/mm，**不参与 scale**
                title_font_pt 34 / body_font_pt 12.76 / frame_border mm
                furniture_font_pt / legend_font_pt (PDF 与 frontend 共享推导)
                linewidth_pt = width_mm × 72/25.4   ← 唯一 mm→pt 转换点
```

## 2. 转换点清单（实测定位）

| 域转换 | 位置 | 合同 | 验证 |
|---|---|---|---|
| 地理→投影米 | `geo_to_image_pixels.py:64` PixelConverter | 投影米制 CRS、always_xy、offline、cond≤1e12 | 拒绝地理 CRS / 奇异矩阵 ✓ |
| 投影米→局部 km | `geo_to_image_pixels.py:81` | `/[1000,-1000]` y-down |  identity affine 像素中心 ✓ |
| 局部 km→原图像素 | `geo_to_image_pixels.py:82` | 2x3 affine，零基像素中心 | 旋转 30° 非轴对齐 round-trip 1e-6 ✓ |
| 原图像素 inside | `geo_to_image_pixels.py:85` | `[-0.5, size-0.5)` 半开 | 边界 ✓ |
| 路线裁剪 | `geo_to_image_pixels.py:105` clip_line | Liang-Barsky，不夹断顶点 | 交点非夹断 ✓ |
| 显示窗口→页面框 | `image_layout.py:87` contain_layout | 宽高比保持、居中、不超框 | 4 种宽高比 1e-9 ✓ |
| mm→页面 px | `image_page_renderer.py:419` | `px_per_mm = dpi/25.4` | 144/200/300 DPI ✓ |
| mm→pt（线宽） | `image_page_renderer.py:429` | `width_mm × 72/25.4` | 物理 pt 跨 DPI 不变 1e-9 ✓ |
| 图框边线几何 | `image_layout.py:65` frame_border_rects | gap_mm 视觉边距， strokes 居中 | gap_mm 跨 DPI 物理不变 ✓ |
| 家具字体 pt | `image_layout.py:30` furniture_font_pt | nominal font_pt 优先，框容量 fit 权威，floor 4pt | PDF==frontend 1e-9；nominal 非溢出旁路 ✓ |
| 图例字体 pt | `image_layout.py:47` legend_font_pt | cap 3mm(8.504pt)，floor 3pt | floor/cap ✓ |
| pt→页面 px | `image_page_renderer.py:440` / `frontend_canvas.py:218` | `pt / pt_per_px`，pt_per_px=72/dpi | 单逆转换，两端一致 ✓ |
| 图形符号缩放 | `style.py:110` | `scale=max(1.0, min(win/REF))`，仅 _px 符号 | floor=1.0，2× 窗口符号 2× ✓ |

## 3. 误差累积测量结论

- **地理→原图像素**：identity 与旋转 affine round-trip 误差 ≤1e-6 px；投影由 pyproj 离线保证，无网络 ballpark。
- **contain_layout**：宽高比保持误差 ≤1e-9；居中误差 ≤1e-9；不超框。
- **物理单位**：0.25mm 边线 = 0.7087pt，在 144/200/300 DPI 下物理 pt 恒定（误差 ≤1e-9）；px 宽度随 DPI 线性，round-trip px→mm→pt 无双重缩放。
- **字体两域**：PDF 与 frontend 共享 `furniture_font_pt`/`legend_font_pt`，同 bounds+pt_per_px 下 pt 完全相等（≤1e-9）；frontend 经 `pt/pt_per_px` 单逆恢复 px，无二次设计。
- **参考设计缩放**：scale floor=1.0（小窗口不缩低于参考）；符号 _px 随 scale，页面家具 pt **不**随 scale。

**结论：几何与物理单位基础健全，不变量在预设容差内成立。** 迁移的阻断不在几何正确性，而在 Style 合同表达力（见 §4）。

## 4. 当前共享合同不能无损表达的项目

| 项目 | 现状 | 缺口 | 迁移决策 |
|---|---|---|---|
| 参考设计像素符号域 | leadership 图形用 reference-design px（width_px/radius_px/callout 500px/offset_px）+ scale floor | 共享 `style.schema.json` v2 的 typography 是 pt，**无参考像素符号域 + scale-floor 字段** | 须决定：(a) 扩展 Style 增加参考像素符号域与缩放规则；或 (b) 经 4px/mm 重锚定换算为物理 mm/pt（**有损**，需固定换算并验证）。不能静默换算 |
| scale floor 规则 | `max(1.0, min(win/REF))` 为 leadership 专有 | 共享 `appearance.resolve_appearance` 不建模该规则 | 若保留参考像素域，须把 scale 规则纳入共享外观解析或场景表达组件 |
| 业务分组语义 | morning/afternoon 配色 + per-date-group 编号 + right_offset_px | 分组/编号是**业务语义**，非通用 Style | 保留在场景；Style 只提供角色外观，分组绑定显式（route-line itinerary-group） |
| 页面家具 pt/mm | title_font_pt/body_font_pt/frame_border mm | 共享 Style typography(pt) + Layout(mm) **可表达** | 可直接迁移（无损） |
| 配准/裁边/contain 几何 | PixelConverter + display_window + contain_layout | 属受信空间适配，非 Style/Layout | 保留为共享几何服务，迁移不改原始路线事实 |
| main-map 隐式框 | 编译器经 `LayoutResolver.map_frame` 找 map 框 | 计划 §13.3 要求取消隐式字符串，改已验证视图/内容绑定 | 须建立显式 content_id→view 绑定 |

## 5. 完整迁移工作量估算（基于实测，非静态猜测）

| 工作包 | 范围 | 量级 | 风险 |
|---|---|---|---|
| W1 Layout 接入 | leadership 已消费 embedded.layout（共享 LayoutResolver）；replaceable 已声明。取消 main-map 隐式要求→显式内容绑定；共享 Layout 段承载 fixed-page 框 | 中 | 低（几何已验证） |
| W2 Style 合同决策 | 参考像素符号域：扩展 Style vs 物理换算（有损）。**先决决策**，影响 W3 | 中（决策）+ 大（若扩展 Schema） | 中（协议版本治理） |
| W3 表达拆解 | image_itinerary → 共享表达组件（分类路线/方向箭头/编号点/信息卡片/引线/辅助标签）+ Style；场景保留分组/编号业务语义 | 大 | 中（多组件 + 正反例） |
| W4 后端消费 | image-itinerary-page 消费共享 resolved appearance/graphics 实例；PDF+frontend 已共享 image_layout 推导 | 中-大 | 中（两端一致性） |
| W5 跨场景验收 | A17（同行程换 Style/Layout 事实不变）/A18（同组件跨两业务）+ P5 联验 | 中 | 中（依赖 P5） |
| W6 删除私有权威 | 移除 image_itinerary 第二权威；旧产物不自动迁移 | 小 | 低（前置 W3/W4 完成） |

**进入完整迁移的条件**：W2 Style 合同决策经评审（参考像素域无损表达或有损换算固定并验证）；§13.5 不变量已验证成立（本报告）。

**建议**：先做 W1（Layout，低风险）+ W2 决策；W3/W4 据 W2 决策展开；不在 W2 未决时把 image_itinerary 值静默换算进共享 Style。

## 6. 验证边界

- 本报告以合成数据固定不变量并测量误差，**不**证明真实敏感行程准入，**不**替代真实渲染视觉审查。
- 旋转/非轴对齐配准、非零裁边、多宽高比、144/200/300 DPI 已覆盖；真实业务配准精度须用户授权数据另行验收。
- 字体测量用共享推导函数等价性，非字形边界实测；可读性审查（A28）仍独立。