# ADR-001 附录：geospatial-mcp continuous 统计改造补丁（新会话交接包）

> 本文件是 ADR-001 阶段 2.3 的 **MCP 侧改造交接包**。carto 侧 ①-⑦ + ⑧schema + 测试桩已完成并零回归
> （见 [ADR-001 §8.4](ADR-001-encoding-ir-geometry-decoupling.md)）。本补丁改造 `geospatial-mcp`，使
> `geo_raster_statistics` 对 float 栅格输出 continuous 统计，精确匹配 carto 的 `geospatial-wire.schema.json`。

## 0. 前置：新会话 workspace 要求

**必须在包含 geospatial-mcp 的 workspace 中执行**（当前 carto-master-main 单项目会话无法编辑 MCP，工具报
`can not edit the file outside the projects`）：
- 方式 A：`File → Add Folder to Workspace` 加 `D:\IdeaProjects\github\code-reviewer\geospatial-mcp`，**然后新开对话**；
- 方式 B：直接打开父目录 `D:\IdeaProjects\github\code-reviewer`（同含 carto-master-main 与 geospatial-mcp），新开对话。

新会话启动后，先读本文件 + ADR-001 §8.4，再按下述清单实施。

## 1. 改造清单（4 文件，categorical 路径零改动）

### 文件 1：`src/geospatial_mcp/schemas.py`

**(a) import 行加 `model_serializer`：**
```python
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_serializer, model_validator
```

**(b) 替换 `ClassCount` + `RasterStatistics`（原 L159-173）为：**
```python
class ClassCount(Contract):
    value: int
    count: int = Field(gt=0)


class Histogram(Contract):
    min: float
    max: float
    bucket_count: int = Field(ge=1, le=4096)
    counts: list[int]

    @model_validator(mode="after")
    def consistent(self):
        if self.min > self.max or len(self.counts) != self.bucket_count or any(c < 0 for c in self.counts):
            raise ValueError("Histogram requires min<=max, len(counts)==bucket_count and non-negative counts.")
        return self


class ContinuousStatistics(Contract):
    min: float
    max: float
    mean: float
    stddev: float = Field(ge=0)
    histogram: Histogram

    @model_validator(mode="after")
    def consistent(self):
        if self.min > self.max:
            raise ValueError("Continuous min must not exceed max.")
        return self


class RasterStatistics(Contract):
    source: RasterSourceRef
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(gt=0)
    raster_info: RasterInfo
    total_pixels: int = Field(gt=0)
    valid_pixels: int = Field(ge=0)
    masked_pixels: int = Field(ge=0)
    classes: list[ClassCount] | None = None
    continuous: ContinuousStatistics | None = None
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def exactly_one_statistic(self):
        # Integer bands carry classes; float bands carry continuous. Never both, never neither.
        if (self.classes is None) == (self.continuous is None):
            raise ValueError("Provide exactly one of classes (integer band) or continuous (float band).")
        return self

    @model_serializer(mode="wrap")
    def _drop_absent_statistic(self, handler):
        # Emit classes XOR continuous (never a null key) so carto's oneOf wire contract matches exactly.
        return {key: value for key, value in handler(self).items() if value is not None}
```

### 文件 2：`src/geospatial_mcp/services/raster.py`

**(a) `INTEGER_DTYPES`（L19）后加：**
```python
FLOAT_DTYPES = {"float32", "float64"}
```

**(b) `class_counts` 函数之后（L65 后）新增：**
```python
@contextmanager
def continuous_raster(path: Path, max_pixels: int):
    if path.suffix.lower() not in {".tif", ".tiff"}:
        raise GeoError("UNSUPPORTED_FORMAT", "Continuous operations require a self-contained GeoTIFF.")
    if any(Path(str(path) + suffix).exists() for suffix in (".msk", ".aux.xml", ".ovr")):
        raise GeoError("RASTER_SIDECAR_UNSUPPORTED", "Embed masks and georeferencing in the GeoTIFF before registering it.")
    try:
        with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_TIFF_INTERNAL_MASK=True,
                          GDAL_PAM_ENABLED=False, GDAL_CACHEMAX=64 * 1024 * 1024):
            with rasterio.open(path, driver="GTiff") as src:
                check_pixels(src.width, src.height, max_pixels)
                if src.count != 1 or src.dtypes[0] not in FLOAT_DTYPES:
                    raise GeoError("CONTINUOUS_RASTER_REQUIRED", "Require one float band (32/64-bit) for continuous statistics.")
                yield src
    except GeoError:
        raise
    except Exception as exc:
        raise GeoError("INVALID_RASTER_DATA", "Unable to process the continuous GeoTIFF.") from exc


def continuous_statistics(src, bucket_count: int = 256):
    """Two-pass exact statistics over valid finite pixels: min/max/mean/stddev + histogram.

    Pass 1 accumulates count/min/max/sum/sum-of-squares; pass 2 bins into a fixed [min,max]
    histogram (last bucket closed). sum(counts) == valid_pixels by construction.
    """
    n, vmin, vmax, total, total_sq = 0, math.inf, -math.inf, 0.0, 0.0
    for window in windows(src.width, src.height):
        values = src.read(1, window=window, masked=True).compressed().astype("float64")
        values = values[np.isfinite(values)]
        if values.size == 0:
            continue
        n += int(values.size)
        vmin = min(vmin, float(values.min())); vmax = max(vmax, float(values.max()))
        total += float(values.sum()); total_sq += float((values ** 2).sum())
    if n == 0:
        raise GeoError("RASTER_NO_VALID_PIXELS", "Continuous statistics require at least one valid finite pixel.")
    mean = total / n
    stddev = math.sqrt(max(0.0, total_sq / n - mean * mean))
    counts = [0] * bucket_count
    span = vmax - vmin
    for window in windows(src.width, src.height):
        values = src.read(1, window=window, masked=True).compressed().astype("float64")
        values = values[np.isfinite(values)]
        if values.size == 0:
            continue
        idx = (np.zeros(values.shape, dtype=int) if span <= 0
               else np.clip(np.floor((values - vmin) / span * bucket_count).astype(int), 0, bucket_count - 1))
        for i in idx:
            counts[int(i)] += 1
    continuous = {"min": vmin, "max": vmax, "mean": mean, "stddev": stddev,
                  "histogram": {"min": vmin, "max": vmax, "bucket_count": bucket_count, "counts": counts}}
    return continuous, n
```

### 文件 3：`src/geospatial_mcp/raster_operations.py`

**(a) import（L6）改为：**
```python
from .services.raster import (FLOAT_DTYPES, categorical_raster, class_counts, continuous_raster,
                              continuous_statistics, reproject_categorical, validate_resolution)
```

**(b) 替换 `statistics` 方法（L30-39）为：**
```python
    def statistics(self, source: RasterSourceRef) -> RasterStatistics:
        path, identity = self._resolve(source)
        metadata = inspect_raster(path)
        if metadata.bands[0].dtype in FLOAT_DTYPES:
            with continuous_raster(path, self.settings.max_raster_pixels) as src:
                continuous, valid = continuous_statistics(src)
                total = src.width * src.height
            self._verify_input(path, identity)
            return RasterStatistics(source=source, sha256=identity.sha256, size_bytes=identity.size_bytes,
                                    raster_info=metadata, total_pixels=total, valid_pixels=valid,
                                    masked_pixels=total - valid, continuous=continuous, warnings=metadata.warnings)
        with categorical_raster(path, self.settings.max_raster_pixels) as src:
            classes, valid = class_counts(src, self.settings.max_raster_classes)
            total = src.width * src.height
        self._verify_input(path, identity)
        return RasterStatistics(source=source, sha256=identity.sha256, size_bytes=identity.size_bytes,
                                raster_info=metadata, total_pixels=total, valid_pixels=valid,
                                masked_pixels=total - valid, classes=classes, warnings=metadata.warnings)
```
> 注意：原实现先 `categorical_raster` 再 `inspect_raster`；新版先 `inspect_raster` 拿 dtype 再分支。
> `inspect_raster` 只读元数据、无副作用、且不限制 dtype（`services/data.py` L140 直接取 `src.dtypes[i]`），categorical 行为等价。

### 文件 4：`src/geospatial_mcp/tools/analysis.py`

**替换 `geo_raster_statistics` docstring（L103-109）：**
```python
        """Exact bounded statistics for one single-band GeoTIFF.

        Accept exactly one registered dataset_id or TIFF artifact_id, never a path or layer.
        Integer bands (8/16/32-bit) return exact sorted class code counts; float bands (32/64-bit)
        return continuous statistics (min/max/mean/stddev + fixed-bucket histogram). Respect embedded
        NoData/internal masks; zero is a valid integer value unless explicitly masked. No inferred
        category names, sampling, or area calculation.
        """
```

## 2. 验证（MCP 侧）

**(a) categorical 不回退：**
```powershell
cd D:\IdeaProjects\github\code-reviewer\geospatial-mcp
python -m unittest tests.test_raster tests.test_raster_mcp -v
```
现有 categorical 测试应全绿（`RasterStatistics` classes 路径不变；`model_serializer` 对 categorical
输出 `classes`、不含 `continuous` key）。注意 `test_raster.py` L63 的 round-trip
`RasterStatistics.model_validate_json(result.model_dump_json())` 会验证 serializer + validator 自洽。

**(b) 新增 continuous 测试：**
- `tests/raster_fixtures.py`：仿 `make_categorical` 加 `make_continuous`（写 float32 单波段 GeoTIFF，含 NoData/mask）；
- `test_raster.py`：加用例断言 float 栅格 statistics 返回 `continuous`（无 `classes`），且
  `min<=max`、`stddev>=0`、`len(histogram.counts)==bucket_count`、`sum(counts)==valid_pixels`；
- 断言整数栅格仍只返回 `classes`（无 `continuous` key）——验证 XOR。

## 3. 契约对齐检查表（MCP 输出 ↔ carto geospatial-wire）

| carto wire 要求 | MCP 改造保证 |
|---|---|
| `statistics.continuous{min,max,mean,stddev,histogram}` | ContinuousStatistics/Histogram 字段名一一对应 |
| `histogram{min,max,bucket_count,counts}` | 同名同构 |
| oneOf(classes \| continuous)，`additionalProperties:false` | model_serializer 排除 None → classes XOR continuous，绝无 null key |
| carto `_statistics` 校验 `sum(hist.counts)==valid_pixels` | 两遍扫描保证 counts 之和==n==valid_pixels |
| carto `_metadata` 要求 dtype∈SUPPORTED（含 float32/64） | FLOAT_DTYPES = {float32,float64} 对齐 |

## 4. carto 端到端联调（回 carto-master-main workspace，见 ADR §8.4 待续 (a)）

MCP 改造完成后，carto 侧还需（均在 carto workspace 内，本会话已具备执行链 ①-⑦）：
1. **continuous fixture**：`PreparationFixture` 假设 categorical+legend（test_raster_classification L37-42），
   需新建 continuous fixture：float32 TIFF（`set_raster` 已支持 float，helpers L85 已产 continuous evidence）
   + continuous request（`raster-classification-request` continuous 变体：source+measurement+unit+classification+color_ramp，无 legend）
   + 手工 `rasterContinuousLayer` portrayal contract。
2. **continuous 端到端测试**：`analyze`(continuous) → `raster-continuous-preparation`(interval IR) →
   `RasterPortrayalCompiler._build_continuous` → resolved-portrayal(key_mode=interval) →
   `RasterMapBodyRenderer._continuous_indices` → PNG；断言出图 + 分级像素。
3. **（可选）完整 generate 准入**：若要跑完整 workflow，需 scenario-capabilities 加 raster-continuous profile
   + general_thematic author 产 rasterContinuousLayer + validation_scene continuous 样张。
4. **真实 MCP 联调**：carto 的 `GeospatialMcpAdapter` 指向改造后的 geospatial-mcp，跑真实 float 栅格 statistics。

## 5. 阶段 3（合并）——依赖 2.3 端到端跑通后启动

见 ADR-001 §9.5/§9.6：portrayal/scene 去几何分叉合并为 `portrayal_resolver`（含 vector_portrayal 重命名）、
契约层合并为「专题基座 + 几何数据适配参数」。**顺序不可反**：先 2.3 端到端落地，再阶段 3 合并。
