"""ADR-001 阶段2.1：encoding-ir schema 的无损承载与组合矩阵验证。

本测试只验证协议层（schema 能表达什么、拒绝什么），不接入执行链——那是 2.2。
三条核心保证：
1. 无损承载：single/categorical/choropleth/proportional 四种 legacy encoding 均可表达为 IR。
2. 解绑证明：raster-cell + interval 在协议层合法（当前 thematic-design L727-738 拒绝），
   这是"表达脱离几何"的协议层证据；执行层支持见 ADR §4.2 阶段 2.3。
3. 组合矩阵：仅拒绝物理不可行组合（scaling 需点载体、raster-cell 禁 scaling/size、
   nominal→discrete、null field→single），而非按几何硬绑表达。
"""
from pathlib import Path
import sys
SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))
import unittest

from carto_core.schema_registry import SchemaRegistry
from carto_core.errors import ProtocolError


def sym(color):
    return {"color": color, "stroke": "#222222", "stroke_width_pt": 0.4, "radius_mm": 2.0}


def single_ir():
    return {"schema_version": 1, "key_mode": "discrete", "geometry_role": "polygon",
            "domain": {"field": None, "measurement": "nominal", "unit": None, "normalization": None},
            "scale": {"categories": []},
            "channels": {"symbols": [sym("#2288CC")], "shape": "auto"},
            "missing": {"policy": "reject", "label": "No data", "symbol": None},
            "legend": {"policy": "all", "uniform_label": "Single symbol"}}


def categorical_ir():
    return {"schema_version": 1, "key_mode": "discrete", "geometry_role": "polygon",
            "domain": {"field": "code", "measurement": "nominal", "unit": None, "normalization": None},
            "scale": {"categories": [{"value": "A", "label": "Category A"},
                                     {"value": "B", "label": "Category B"},
                                     {"value": 3, "label": "Category C"}]},
            "channels": {"symbols": [sym("#2288CC"), sym("#CC3322"), sym("#228833")], "shape": "auto"},
            "missing": {"policy": "reject", "label": "No data", "symbol": None},
            "legend": {"policy": "observed"}}


def choropleth_ir():
    return {"schema_version": 1, "key_mode": "interval", "geometry_role": "polygon",
            "domain": {"field": "population", "measurement": "density", "unit": "people/km2",
                       "normalization": {"denominator_field": "area", "scale": 1}},
            "scale": {"edges": [5, 7.5, 10], "labels": ["Class 1", "Class 2"],
                      "interval_policy": "left-closed-last-both", "out_of_range": "reject"},
            "channels": {"symbols": [sym("#6BAED6"), sym("#08519C")], "shape": "auto"},
            "missing": {"policy": "reject", "label": "No data", "symbol": None},
            "legend": {"policy": "all"}}


def proportional_ir():
    return {"schema_version": 1, "key_mode": "scaling", "geometry_role": "point",
            "domain": {"field": "population", "measurement": "count", "unit": "people", "normalization": None},
            "scale": {"domain_max": 100, "range_mm": [0, 5], "size_scale": "sqrt",
                      "zero_policy": "omit", "negative_policy": "reject", "out_of_range": "reject",
                      "legend_values": [25, 100]},
            "channels": {"symbols": [sym("#2288CC")], "shape": "auto"},
            "missing": {"policy": "reject", "label": "No data", "symbol": None},
            "legend": {"policy": "all"}}


def raster_interval_ir():
    # 解绑证据：栅格像元 + 分级着色，协议层合法（执行层见 ADR 2.3）。
    return {"schema_version": 1, "key_mode": "interval", "geometry_role": "raster-cell",
            "domain": {"field": "value", "measurement": "density", "unit": "x", "normalization": None},
            "scale": {"edges": [0, 50, 100], "labels": ["Low", "High"],
                      "interval_policy": "left-closed-last-both", "out_of_range": "reject"},
            "channels": {"symbols": [sym("#6BAED6"), sym("#08519C")], "shape": "auto"},
            "missing": {"policy": "reject", "label": "No data", "symbol": None},
            "legend": {"policy": "all"}}


class EncodingIrSchemaTests(unittest.TestCase):
    def setUp(self):
        self.registry = SchemaRegistry()

    def test_four_legacy_kinds_expressed_losslessly(self):
        cases = {"single": single_ir(), "categorical": categorical_ir(),
                 "choropleth": choropleth_ir(), "proportional": proportional_ir()}
        for name, ir in cases.items():
            with self.subTest(kind=name):
                self.registry.validate("encoding-ir", ir)

    def test_raster_cell_interval_is_admitted_at_protocol_layer(self):
        # 当前 thematic-design.schema.json L727-738 只允许 raster+nominal；IR 打破此耦合。
        self.registry.validate("encoding-ir", raster_interval_ir())

    def test_scaling_requires_point_carrier(self):
        for role in ("raster-cell", "polygon", "line"):
            ir = proportional_ir()
            ir["geometry_role"] = role
            with self.subTest(role=role), self.assertRaises(ProtocolError):
                self.registry.validate("encoding-ir", ir)

    def test_raster_cell_forbids_scaling(self):
        ir = proportional_ir()
        ir["geometry_role"] = "raster-cell"
        ir["key_mode"] = "scaling"
        with self.assertRaises(ProtocolError):
            self.registry.validate("encoding-ir", ir)

    def test_raster_cell_shape_must_be_auto(self):
        ir = raster_interval_ir()
        ir["channels"]["shape"] = "circle"
        with self.assertRaises(ProtocolError):
            self.registry.validate("encoding-ir", ir)

    def test_nominal_cannot_use_interval(self):
        ir = choropleth_ir()
        ir["domain"]["measurement"] = "nominal"
        with self.assertRaises(ProtocolError):
            self.registry.validate("encoding-ir", ir)

    def test_null_field_forces_discrete_single(self):
        ir = choropleth_ir()
        ir["domain"]["field"] = None
        with self.assertRaises(ProtocolError):
            self.registry.validate("encoding-ir", ir)

    def test_single_requires_uniform_label(self):
        ir = single_ir()
        del ir["legend"]["uniform_label"]
        with self.assertRaises(ProtocolError):
            self.registry.validate("encoding-ir", ir)

    def test_key_mode_scale_mismatch_rejected(self):
        ir = choropleth_ir()
        ir["scale"] = {"categories": []}   # interval key_mode 配 discrete scale
        with self.assertRaises(ProtocolError):
            self.registry.validate("encoding-ir", ir)

    def test_unknown_field_rejected(self):
        ir = categorical_ir()
        ir["renderer_id"] = "matplotlib-vector-page"   # IR 必须后端无关，不得含渲染指令
        with self.assertRaises(ProtocolError):
            self.registry.validate("encoding-ir", ir)


if __name__ == "__main__":
    unittest.main()
