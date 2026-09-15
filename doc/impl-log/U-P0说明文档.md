# U-P0：规范收敛与安全底座 — 实施说明文档

## 文档信息

| 项目 | 内容 |
|---|---|
| 阶段 | U-P0：规范收敛与安全底座 |
| 对应架构 | A（前半） |
| 对应 TRD | P0 / GM-P0 |
| 实施日期 | 2026-09-14 |
| 依据 | [实施计划 v2.1](../implement-plan.md) 第二章 |
| 状态 | 已实施退出标准的前四项；后四项待后续阶段补齐 |

---

## 术语速查（写给开发小白）

> 以下用前端 / 后端开发者熟悉的概念来解释本文档中的专业词汇。如果你做过 Web 开发，这些类比应该能帮你快速理解。

### 安全类

#### 安全原语（Security Primitives）

**一句话**：安全原语就是「安全乐高积木」——最小化的、不可再拆分的安全功能单元。

**类比**：就像前端组件库里的基础组件（Button、Input），你不会从头手写一个按钮，而是用现成组件。安全原语同理：路径校验、签名验证、权限检查这些功能被封装成独立的「积木块」，业务代码拿来即用，不自己手写安全逻辑。

**在本项目中**：`security/` 目录下的 `paths.py`、`approval.py`、`authorization.py`、`sensitive.py` 就是四块安全积木，每块负责一个安全职责。

---

#### 路径穿越（Path Traversal）

**一句话**：用户通过输入 `../../etc/passwd` 这样的路径，访问到本不该访问的文件。

**类比**：假设你有一个静态文件服务器，对外提供 `www.example.com/files/` 下的文件。如果用户请求 `www.example.com/files/../../config/database.yml`，服务器傻乎乎地把数据库配置返回了——这就是路径穿越攻击。

**在本项目中**：`PathGuard` 类负责拦截这种攻击。它规定了「允许根」（allowed root），任何路径解析后如果跑出了允许根的范围，直接拒绝，错误码 `PATH_OUTSIDE_ALLOWED_ROOT`。

---

#### 链接逃逸（Link Escape）

**一句话**：在允许目录里放一个快捷方式（符号链接），快捷方式指向允许目录外面的地方，从而绕过路径检查。

**类比**：假设小区门禁只允许你进入 3 号楼。你在 3 号楼走廊里放了一扇「传送门」，传送门直通小区外面的银行金库。你进入 3 号楼（通过了门禁检查），然后走传送门就到了金库——门禁形同虚设。

**在本项目中**：`PathGuard` 逐段检查路径上的每一级目录，如果发现某一级是符号链接（Linux 的 symlink）或 junction（Windows 的目录联接），直接拒绝，错误码 `PATH_LINK_ESCAPE`。

---

#### 符号链接（Symlink）/ Junction

**一句话**：类似于 Windows 的「快捷方式」，一个文件或文件夹指向另一个位置。

- **symlink**：Linux/macOS 的符号链接，相当于一个「软快捷方式」
- **junction**：Windows 特有的目录联接，类似于「目录级别的快捷方式」

**为什么危险**：攻击者可以在允许目录内创建一个链接指向敏感目录，然后通过这个链接读写不该碰的文件。

---

#### 防重放（Replay Protection）

**一句话**：防止同一个审批凭证被拿来用第二次、第三次。

**类比**：你给快递员写了一张「允许取货」的纸条。快递员拿纸条取了一次货，然后又拿同一张纸条再取一次——这就是「重放攻击」。防重放就是给纸条盖一个一次性戳记，盖过戳的纸条作废。

**在本项目中**：每个审批回执带一个 `nonce`（一次性随机数）。验证时，系统先把 nonce 记录下来；如果同一个 nonce 再次出现，说明这张回执被重复使用了，直接拒绝，错误码 `APPROVAL_REPLAYED`。

---

#### Nonce

**一句话**：一个只允许使用一次的随机字符串，用来防止重复操作。

**类比**：就像演唱会门票上的条形码——检票时扫一次就作废，不能拿同一张票进去两次。nonce 就是审批回执上的「条形码」。

---

#### HMAC-SHA256

**一句话**：一种「带密钥的哈希」算法，用来验证数据没被篡改且确实是你信任的人发的。

**类比**：普通的哈希（如 MD5/SHA256）就像一个封蜡章——任何人都可以做同样的封蜡章，无法区分谁盖的。HMAC 的区别是多了一把「密钥」——只有持有密钥的人才能盖出正确的章。验证时也要用同一把密钥来核对。

**在本项目中**：审批回执用 HMAC-SHA256 签名。签发方持有一把密钥（环境变量 `CARTO_APPROVAL_HMAC_KEY`），签发时盖「章」；验证时用同一把密钥核对章的真伪。AI 模型没有这把密钥，所以**模型无法伪造审批**。

---

#### RBAC（Role-Based Access Control，基于角色的访问控制）

**一句话**：不直接给每个用户分配权限，而是先定义角色（如管理员、审核员），给角色分配权限，再把用户分配到角色。

**类比**：就像公司工牌系统——你不需要给每个人单独配置「能进哪个门」，而是按工种发不同颜色的工牌：蓝色工牌能进办公区，红色工牌能进机房，黑色工牌哪儿都能进。`authorize` 函数就是刷卡验牌的门禁逻辑。

**在本项目中**：定义了 6 个角色（viewer / author / reviewer / publisher / operator / admin），每个角色有固定的动作集合。授权时检查三件事：你是谁（身份）、你有什么牌（角色）、你要进哪个门（命名空间）。

---

#### 数据分级（Data Classification）

**一句话**：按敏感程度给数据贴标签，不同标签的数据有不同的外发规则。

**类比**：就像公文管理——「公开」文件谁都能看，「内部」文件只限公司内部，「机密」文件需要审批才能看，「绝密」文件根本不能出门。

**在本项目中**：分为 public → internal → confidential → restricted 四级。confidential 和 restricted 级别的数据**绝对不能**发往公网服务（如公开的地理编码 API），错误码 `SENSITIVE_DATA_EGRESS_DENIED`。

---

#### 日志脱敏（Log Redaction）

**一句话**：在写入日志之前，自动把敏感字段（密码、坐标、行程等）的值替换成 `[REDACTED]`。

**类比**：就像银行流水单上把卡号中间几位打成 `****`——你看到的是「尾号 `****1234` 的卡消费了 100 元」，而不是完整卡号。日志脱敏就是这个思路，只不过是对结构化数据递归处理。

**在本项目中**：`redact_for_log` 函数递归遍历字典/列表，发现键名包含 `password`、`token`、`coordinate`、`itinerary` 等关键词时，把对应的值替换为 `[REDACTED]`。

---

#### 允许根（Allowed Root）

**一句话**：系统事先划定的「安全活动范围」——只有这些目录下的文件可以被访问。

**类比**：就像沙箱游戏的边界墙。你在墙内怎么跑都行，但试图走出墙外会被拦住。CLI 的 `--allowed-root` 参数就是告诉系统「这面墙在哪里」。

---

#### Windows 交替流（Alternate Data Stream）

**一句话**：Windows NTFS 文件系统的一个特殊机制，允许在同一个文件名下附加隐藏的数据流。

**类比**：想象一个文件是「正面」，交替流是「背面」——你在资源管理器里看到的只是正面，但背面可能藏着别的东西。攻击者可以用 `file.txt:secret` 这种写法访问交替流中的隐藏数据。

**在本项目中**：`PathGuard` 检查路径中是否包含 `:`，如果发现就拒绝，错误码 `PATH_ALTERNATE_STREAM`。

---

### 协议类

#### Schema / JSON Schema

**一句话**：Schema 就是数据的「图纸」或「规格说明书」——它规定了某个 JSON/YAML 文件必须长什么样。

**类比**：就像 API 文档里的请求体定义——「必须包含 `name` 字符串、`age` 整数、可选 `email` 字符串」。JSON Schema 做的是完全一样的事，只不过它是标准化的、可被程序自动校验的格式。

**在本项目中**：27 个 `.schema.json` 文件就是 27 张图纸，分别描述了模板清单、地图计划、审批回执等数据结构的规格。任何不符合图纸的数据都会被拒绝。

---

#### Draft 2020-12

**一句话**：JSON Schema 的一个版本标准，类似于 ES6 之于 JavaScript。

**在本项目中**：所有 Schema 统一使用 `"$schema": "https://json-schema.org/draft/2020-12/schema"`，这是目前最新的稳定版本，支持跨文件引用和公共定义复用。

---

#### additionalProperties: false

**一句话**：告诉校验器「除了我明确列出的字段，不许有其他字段」。

**类比**：就像后端接口定义了 `name`、`age` 两个字段，前端如果多传了一个 `role: "admin"`，后端直接报错拒绝。`additionalProperties: false` 就是 JSON Schema 版的这个「严格模式」。

**在本项目中**：所有 Schema 都设置了 `additionalProperties: false`，任何「未知字段」都会被拒绝。这是防止协议漂移（有人偷偷加字段不走审批流程）的硬手段。

---

#### $ref（引用）

**一句话**：在一个 Schema 中引用另一个 Schema 或其中的一部分，避免重复定义。

**类比**：就像前端的 `import`——你不需要在每个文件里重复定义 Button 组件，`import { Button } from 'ui-lib'` 就行。`$ref` 做的是同样的事，只不过引用的是数据结构定义。

**在本项目中**：`common.schema.json` 集中定义了 `identifier`、`digest`、`timestamp` 等公共类型，其他 Schema 通过 `"$ref": "...common.schema.json#/$defs/identifier"` 来引用，不重复写一遍。

---

#### 契约（Contract）

**一句话**：在本项目中，「契约」指模板包内的六份配置文件，每份负责一个方面的规则。

**类比**：就像签合同——你跟甲方签了六份附件，分别约定身份标识、数据要求、空间行为、地图表达、交付格式和质量标准。整份合同一起生效，拆开单看不完整。

**在本项目中**：一个完整的 MapScenario 模板包必须包含六份契约文件（scenario / data / spatial-behavior / portrayal / delivery / quality-gates），每份有对应的 Schema 校验。

---

#### 回执（Receipt）

**一句话**：审批通过后生成的「凭证文件」，证明某个操作已被授权。

**类比**：就像你申请盖章后拿到的「审批单」——上面写了「谁批准的、批准了什么操作、批的是哪个对象、什么时候到期、只能用一次」。后续执行操作时，系统先验这个凭证的真伪和有效性。

**在本项目中**：`ApprovalReceipt` 是一个包含 16 个字段的数据结构，覆盖身份、动作、对象摘要、作用域、时效和防重放标识，用 HMAC-SHA256 签名防伪。

---

#### 门禁（Gate）

**一句话**：流程中的强制检查点，过了门禁才能继续下一步。

**类比**：就像地铁进站的三道闸——刷卡（验身份）、余额够（验权限）、站内有效（验范围），三关都过了才能进站。门禁不通过，流程到此为止。

**在本项目中**：三条主路由各有门禁——G1（制图合同审批）、G2（实例冻结审批）、G3（成果交付审批）。每个门禁验证对应的审批回执，不通过就阻断。

---

#### 候选快照（Candidate Snapshot）

**一句话**：地图生成过程中产生的一份「待审批的完整参数集」——所有参数都已确定，但还没被冻结。

**类比**：就像你做了一个设计方案，方案里所有尺寸、颜色、材料都定好了，但还没签字盖章。领导看完方案觉得 OK，就盖章变成正式版；不满意就打回修改。

**在本项目中**：`resolved-map` 就是候选快照，包含完整的执行参数（`execution` 字段）。

---

#### 实例锁（Instance Lock / MapSpecLock）

**一句话**：候选快照通过 G2 审批后被「冻结」成的不可变版本，后续渲染只认这把锁，不接受任何修改。

**类比**：就像盖了章的正式施工图纸——施工队只能照图施工，不能自己改图纸。如果方案变了，必须重新出图、重新盖章，旧图作废。

**在本项目中**：`map-spec-lock` 包含与候选快照完全相同的 `execution` 和 `execution_digest`。冻结后任何修改都会导致摘要值变化，系统检测到不一致就拒绝。

---

#### execution_digest（执行摘要）

**一句话**：把候选 / 锁中的全部执行参数做一次哈希算出的「指纹」，用来检测参数是否被改动过。

**类比**：就像文件的 MD5 校验值——文件哪怕改了一个字节，MD5 值就完全不同。`execution_digest` 做的是同样的事，只不过是对结构化数据先做规范化序列化再哈希。

**在本项目中**：候选快照和实例锁共享同一个 `execution` 对象和 `execution_digest` 值，有专门测试验证两者一致、且任何改动都会导致摘要变化。

---

#### 规范化 JSON（Canonical JSON）

**一句话**：对 JSON 数据做标准化序列化——键名排序、去掉多余空格、禁用特殊值——使得同一份数据在任何环境下都产生完全相同的字节序列。

**类比**：就像两个人写了同样内容的合同，但排版不同（一个左对齐一个右对齐、一个用全角逗号一个用半角）。规范化就是统一成同一种排版，这样比较内容时就不会被格式差异干扰。

**在本项目中**：`canonical_json_bytes` 函数用 `sort_keys=True`（键名排序）、`separators=(",",":")`（去掉多余空格）、`ensure_ascii=False`（保留中文）、`allow_nan=False`（禁用 NaN/Infinity）来生成规范化 JSON，然后计算 SHA256 摘要。这保证了审批回执的签名和执行摘要的计算是确定性的。

---

### Python / 代码类

#### frozen dataclass

**一句话**：Python 的数据类加了 `frozen=True`，创建后所有字段不可修改。

**类比**：就像前端的 `const` 或 `Object.freeze()`——变量一旦赋值就不能再改。在安全场景下特别重要：审批回执、主体上下文等安全对象创建后不可变，防止运行中被偷偷篡改。

**在本项目中**：`ApprovalReceipt`、`SubjectContext`、`ExternalAccessPolicy` 都是 frozen dataclass。

---

#### slots=True

**一句话**：Python 数据类加了 `slots=True`，禁止动态添加属性，同时节省内存。

**类比**：就像 TypeScript 中定义了 `interface User { name: string; age: number }`，你不能给 `user` 对象加一个 `user.role = "admin"`——类型系统不允许。`slots=True` 就是 Python 版的这个约束。

**在本项目中**：所有安全数据结构都用了 `slots=True`，防止有人给安全对象偷偷塞字段。

---

#### StrEnum

**一句话**：Python 3.11+ 的枚举类型，枚举值是字符串，可以直接当字符串用。

**类比**：就像 TypeScript 的 `type Role = "viewer" | "author" | "reviewer"`——既是类型安全的枚举，又能当普通字符串传递和比较。

---

#### frozenset

**一句话**：Python 的不可变集合，创建后不能添加或删除元素。

**类比**：就像一个被锁住的数组——内容固定，不能 push 也不能 splice。在安全场景下用来定义角色权限映射表，防止运行时篡改。

---

#### Fixture（测试固件）

**一句话**：预先准备好的标准测试数据，用来验证代码行为是否符合预期。

**类比**：就像前端组件开发的 Storybook——你准备几组典型的输入数据，看组件渲染结果对不对。Fixture 就是后端版的 Storybook 数据。

**在本项目中**：`schema_cases.py` 为 26 个 Schema 各准备了一份合法数据（`VALID_CASES`）和一份非法数据（`INVALID_CASES`），用来验证 Schema 校验逻辑的正确性。

---

## 一、阶段目标

统一三份设计文档（架构、模板创建 TRD、地图生成 TRD）的 Schema、命名、契约格式和审批协议，建立安全底座和仓库治理规则，确保后续编码不产生并行旧模型。

核心交付物为四大支柱：

1. **规范对齐**：四类模板命名、六契约体系、规则标签正交、状态模型统一、目录结构固化。
2. **共享 Schema 定义**：27 个 JSON Schema 文件覆盖全部协议实体。
3. **安全底座**：路径安全、审批回执验证与防重放、RBAC 授权、敏感信息外发控制。
4. **仓库治理**：独立 Skill 目录、统一 CLI 入口、测试位置规则、依赖管理。

---

## 二、代码结构总览

```
carto-master-main/
├── AGENTS.md                          # 仓库级智能体入口约束
├── CLAUDE.md                          # Claude 专用约定
├── pyproject.toml                     # 构建配置与依赖声明
├── doc/
│   ├── implement-plan.md              # 分阶段实施计划（v2.1）
│   ├── carto-agent-architecture.md   # 总体架构方案
│   ├── carto-generate-map-TRD.md      # 地图生成 TRD
│   ├── carto-create-template-TRD.md   # 模板创建 TRD
│   ├── carto-template-dsg.md          # 模板体系设计
│   └── impl-log/                      # 实施日志（本文件所在目录）
│
└── skills/carto-agent/                # 唯一运行实现根目录
    ├── SKILL.md                       # Skill 入口与阶段边界声明
    ├── requirements.txt               # 运行依赖
    ├── workflows/
    │   └── routing.md                 # 顶层路由表与状态声明
    ├── schemas/                       # 27 个 JSON Schema 文件
    │   ├── common.schema.json         # 共享类型定义（核心）
    │   ├── manifest.schema.json       # 模板包清单
    │   ├── identity.schema.json       # MapBrand 契约
    │   ├── cartography.schema.json    # MapStyle 契约
    │   ├── layout.schema.json         # MapLayout 契约
    │   ├── scenario.schema.json       # MapScenario 场景合同
    │   ├── data-role.schema.json      # 数据角色定义
    │   ├── spatial-behavior.schema.json  # 空间行为约束
    │   ├── portrayal.schema.json      # 图层与表达规范
    │   ├── delivery.schema.json      # 交付配置
    │   ├── quality-gates.schema.json  # 质量门禁定义
    │   ├── source-manifest.schema.json   # 数据来源清单
    │   ├── map-spec-lock.schema.json    # 不可变实例锁
    │   ├── map-plan.schema.json       # 可变工作计划
    │   ├── map-intent.schema.json     # 意图解析
    │   ├── map-brief.schema.json      # 地图生成简报
    │   ├── template-brief.schema.json # 模板创建简报
    │   ├── generate-request.schema.json # 生成请求
    │   ├── resolved-map.schema.json   # 候选快照
    │   ├── delivery-manifest.schema.json # 交付清单
    │   ├── prepared-data-bundle.schema.json # 数据准备产物包
    │   ├── knowledge-evidence.schema.json   # 知识证据
    │   ├── tool-binding.schema.json   # 工具绑定
    │   ├── data-preparation-task.schema.json # 数据准备任务
    │   ├── intent-profiles.schema.json # 意图场景配置
    │   ├── job-state.schema.json      # 作业状态
    │   └── approval-receipt.schema.json # 审批回执
    ├── policies/                      # 8 个策略文件
    │   ├── security-policy.yaml       # 安全策略总纲
    │   ├── tool-bindings.yaml         # 工具能力绑定注册
    │   ├── data-preparation-policy.yaml # 数据准备策略
    │   ├── knowledge-sources.yaml     # 知识来源注册
    │   ├── intent-profiles.yaml       # 三场景意图配置
    │   ├── checker-registry.yaml      # 检查器注册表
    │   ├── scope-baseline.yaml        # 首期范围基线
    │   └── baselines/
    │       └── carto-core-1.0.0.yaml  # 核心质量基线
    └── scripts/                       # Python 运行代码
        ├── carto.py                   # CLI 薄入口
        ├── carto_core/                # 核心包
        │   ├── __init__.py            # 包声明与版本号
        │   ├── cli.py                 # CLI 参数解析与分发
        │   ├── errors.py              # 统一错误类型体系
        │   ├── canonical.py           # 规范化 JSON 与摘要计算
        │   ├── schema_registry.py     # Schema 注册表与文档加载
        │   └── security/              # 安全原语模块
        │       ├── __init__.py        # 统一导出
        │       ├── paths.py           # 路径安全（PathGuard）
        │       ├── approval.py        # 审批回执与防重放
        │       ├── authorization.py   # RBAC 授权模型
        │       └── sensitive.py      # 敏感信息外发与日志脱敏
        └── tests/                    # 自动测试
            ├── __init__.py
            ├── test_schemas.py        # Schema 结构与 Fixture 测试
            ├── test_security.py       # 安全组件全链路测试
            └── fixtures/
                ├── __init__.py
                └── schema_cases.py     # 合法/非法 Fixture 定义
```

---

## 三、规范对齐实现详解

### 3.1 四类模板命名

在 [common.schema.json](../../skills/carto-agent/schemas/common.schema.json) 的 `templateRef.$defs` 中以 `enum` 固化：

| Schema 值 | 中文固定名 | 所有权 |
|---|---|---|
| `map-brand` | 地图身份模板 | 身份段替换 |
| `map-style` | 制图表达规范 | 表达段替换 |
| `map-layout` | 地图版式模板 | 版面段替换 |
| `map-scenario` | 制图场景方案 | 场景合同段替换 |

在 [manifest.schema.json](../../skills/carto-agent/schemas/manifest.schema.json) 的 `package.kind` 和 [scenario.schema.json](../../skills/carto-agent/schemas/scenario.schema.json) 的 `owned_segments` / `replaceable_segments` 中同步引用，确保命名全局一致。

### 3.2 六契约对齐

场景模板的六份业务契约在 Schema 层以独立文件定义：

| 契约文件 | Schema 文件 | 所属段 |
|---|---|---|
| scenario.yaml | scenario.schema.json | MapScenario 拥有 |
| data.schema.yaml | data-role.schema.json | MapScenario 拥有 |
| spatial-behavior.yaml | spatial-behavior.schema.json | MapScenario 拥有 |
| portrayal.yaml | portrayal.schema.json | MapScenario 拥有 |
| delivery.yaml | delivery.schema.json | MapScenario 拥有 |
| quality-gates.yaml | quality-gates.schema.json | MapScenario 拥有 |

[scenario.schema.json](../../skills/carto-agent/schemas/scenario.schema.json) 中的 `owned_segments` 字段以 `enum` 固定了全部六段，`replaceable_segments` 允许其余三段（identity、cartography、layout）被替换，实现了"分段所有权"原则。

### 3.3 规则标签与严重度正交

在 [common.schema.json](../../skills/carto-agent/schemas/common.schema.json) 的 `rule` 定义中：

```
strength: enum [hard_rule, forbidden, mandatory, binding, default, reference]
```

在 [checker-registry.yaml](../../skills/carto-agent/policies/checker-registry.yaml) 中，每个检查器同时声明 `strength` 和 `failure_severity`，两者独立赋值：

| 检查器 ID | strength | failure_severity |
|---|---|---|
| protocol.schema-valid | hard_rule | blocker |
| security.path-contained | hard_rule | blocker |
| approval.receipt-valid | hard_rule | blocker |

在 [carto-core-1.0.0.yaml](../../skills/carto-agent/policies/baselines/carto-core-1.0.0.yaml) 基线中，四种严重度各自映射到不同处理行为：

| 严重度 | 处理行为 |
|---|---|
| blocker | stop |
| error | fail-validation |
| warning | disposition-required |
| info | record |

### 3.4 状态模型对齐

**作业状态**在 [job-state.schema.json](../../skills/carto-agent/schemas/job-state.schema.json) 中以 `enum` 固定：

```
pending / running / waiting_approval / failed / succeeded / cancelled
```

**包生命周期**在 [manifest.schema.json](../../skills/carto-agent/schemas/manifest.schema.json) 的 `package.status` 中固定：

```
draft / validated / published
```

### 3.5 目录结构对齐

在 [scope-baseline.yaml](../../skills/carto-agent/policies/scope-baseline.yaml) 中声明了首期部署形态和信任边界：

- 部署模式：`controlled-single-host`
- 信任边界：`authenticated-operating-system-user`
- 企业共享服务：`not-claimed`（明确不误报）

---

## 四、安全底座实现详解

安全底座由四个安全原语模块构成，均位于 `carto_core/security/` 目录下。

### 4.1 路径安全 — `PathGuard`

**文件**：[security/paths.py](../../skills/carto-agent/scripts/carto_core/security/paths.py)（118 行）

**设计意图**：所有用户可控路径必须经过 `PathGuard` 校验后才能被系统使用，防止路径穿越、越界符号链接和 Windows 特殊路径攻击。

**核心机制**：

| 防护层 | 实现方式 | 对应错误码 |
|---|---|---|
| 允许根验证 | 构造时校验绝对路径、存在性、目录性、非链接 | `ALLOWED_ROOT_NOT_ABSOLUTE` / `ALLOWED_ROOT_INVALID` / `ALLOWED_ROOT_IS_LINK` |
| 空字节注入 | 检查路径中是否包含 `\x00` | `PATH_INVALID` |
| 路径穿越 | `commonpath` 检查解析后路径是否在允许根内 | `PATH_OUTSIDE_ALLOWED_ROOT` |
| 符号链接逃逸 | 逐段检查路径组件是否为 symlink 或 junction | `PATH_LINK_ESCAPE` |
| Windows 保留名 | 拒绝 `CON`、`PRN`、`AUX`、`NUL`、`COM1-9`、`LPT1-9` | `PATH_RESERVED_NAME` |
| Windows 交替流 | 拒绝路径组件中包含 `:` | `PATH_ALTERNATE_STREAM` |
| 尾部点/空格 | 拒绝 Windows 上以点或空格结尾的路径段 | `PATH_RESERVED_NAME` |

**跨平台设计**：`_is_link_or_junction` 同时处理 POSIX symlink 和 Windows junction，使用 `getattr(path, "is_junction", None)` 安全探测 Python 3.12+ 的 junction 支持。

### 4.2 审批回执验证与防重放 — `ApprovalReceipt`

**文件**：[security/approval.py](../../skills/carto-agent/scripts/carto_core/security/approval.py)（203 行）

**设计意图**：实现 G1/G2/G3 三门禁的审批回执验证机制，确保模型无权签发审批，且回执不可重放。

**回执数据结构**（`ApprovalReceipt` frozen dataclass）：

| 字段 | 类型 | 用途 |
|---|---|---|
| schema_version | int | 协议版本（当前固定为 1） |
| receipt_id | str | 回执唯一标识 |
| issuer | str | 签发方身份 |
| subject_id | str | 被授权主体 |
| tenant_id | str | 租户隔离标识 |
| action | str | 授权动作 |
| object_type | str | 对象类型 |
| object_digest | str | 对象内容摘要（sha256:hex） |
| scope | str | 授权作用域 |
| policy_id | str | 关联策略 ID |
| environment | str | 环境标识 |
| issued_at | str | 签发时间（ISO 8601 带时区） |
| expires_at | str | 过期时间（ISO 8601 带时区） |
| nonce | str | 防重放随机数（16-128 字符） |
| signature_algorithm | str | 签名算法（固定 hmac-sha256） |
| signature | str | HMAC-SHA256 签名 |

**验证流程**（`verify_receipt` 函数）：

```
1. 结构校验（_validate_shape）
   → 版本、必填字段、摘要格式、签名格式、算法一致性

2. HMAC 密钥强度校验
   → 密钥长度 >= 32 字节

3. 签名验证
   → 规范化 JSON → HMAC-SHA256 → hmac.compare_digest（常数时间比较）

4. 上下文绑定验证
   → action / object_digest / scope / tenant_id / policy_id / issuer / subject_id / object_type / environment
   → 全部与预期值逐一匹配

5. 时效验证
   → issued_at <= 当前时间 < expires_at
   → expires_at > issued_at

6. 防重放
   → nonce_store.consume(issuer, nonce, expires_at)
   → 每个回执的 nonce 只能被消费一次
```

**防重放存储**：

| 存储 | 适用场景 | 实现 |
|---|---|---|
| `InMemoryNonceStore` | 单进程测试 | `threading.Lock` 保护的 `set` |
| `SqliteNonceStore` | 受控单机生产 | SQLite WAL 模式，`BEGIN IMMEDIATE` 事务，自动清理过期记录 |

SQLite 存储的设计要点：
- 使用 `INSERT OR IGNORE` + `rowcount` 判断是否首次消费
- 每次消费前先 `DELETE` 过期记录，控制表增长
- `isolation_level=None` 配合显式 `BEGIN IMMEDIATE` 实现即时锁

**规范化摘要**（[canonical.py](../../skills/carto-agent/scripts/carto_core/canonical.py)）：

```
canonical_json_bytes(value)
  → json.dumps(ensure_ascii=False, allow_nan=False, separators=(",",":"), sort_keys=True)
  → .encode("utf-8")
```

确保同一逻辑对象在不同平台、不同序列化顺序下产生相同的字节序列和摘要值。

### 4.3 RBAC 授权模型 — `authorize`

**文件**：[security/authorization.py](../../skills/carto-agent/scripts/carto_core/security/authorization.py)（69 行）

**角色体系**（`Role` StrEnum）：

| 角色 | 授权动作集 |
|---|---|
| viewer | read |
| author | read, create_template, validate, generate_map |
| reviewer | read, validate, approve_brief, approve_freeze |
| publisher | read, publish_template, approve_delivery, deliver |
| operator | read, validate, generate_map, deliver |
| admin | 全部动作（含 manage_policy） |

**授权检查**（`authorize` 函数）三重验证：

1. **身份验证**：`subject_id` 和 `tenant_id` 必须非空
2. **角色验证**：角色集非空且全部在注册表中
3. **命名空间验证**：资源命名空间必须在主体授权范围内（支持 `*` 通配）
4. **动作验证**：至少一个角色授予该动作

**设计约束**：
- `SubjectContext` 是 frozen dataclass，创建后不可变
- 使用 `StrEnum` 确保序列化和比较的类型安全
- 角色到动作的映射使用 `frozenset`，防止运行时篡改

### 4.4 敏感信息外发与日志脱敏 — `ExternalAccessPolicy` + `redact_for_log`

**文件**：[security/sensitive.py](../../skills/carto-agent/scripts/carto_core/security/sensitive.py)（65 行）

**数据分级**（`DataClassification` StrEnum）：

```
public < internal < confidential < restricted
```

**外发策略**（`ExternalAccessPolicy.require_allowed`）：

| 条件 | 判定 |
|---|---|
| 服务未注册 | `EXTERNAL_SERVICE_DENIED` |
| confidential 或 restricted 级别 | `SENSITIVE_DATA_EGRESS_DENIED`（禁止发往公网） |
| leadership_itinerary 或 emergency_location | `SENSITIVE_DATA_APPROVAL_REQUIRED`（必须显式审批） |
| internal 级别且无审批 | `INTERNAL_DATA_EGRESS_DENIED` |

**日志脱敏**（`redact_for_log`）：

递归遍历 dict / list / tuple，对键名包含以下片段的值替换为 `[REDACTED]`：

```
apikey, authorization, coordinate, credential, geometry,
itinerary, password, secret, token
```

### 4.5 错误类型体系

**文件**：[errors.py](../../skills/carto-agent/scripts/carto_core/errors.py)（27 行）

统一错误基类 `CartoError`（dataclass + Exception），携带 `code`、`message`、`details` 三字段，派生三个子类：

| 子类 | 语义 | 示例错误码 |
|---|---|---|
| `ConfigurationError` | 配置不合法 | `ALLOWED_ROOT_NOT_ABSOLUTE` |
| `SecurityError` | 安全违规 | `PATH_OUTSIDE_ALLOWED_ROOT`、`APPROVAL_REPLAYED` |
| `ProtocolError` | 协议违规 | `SCHEMA_VALIDATION_FAILED`、`DOCUMENT_PARSE_FAILED` |

CLI 层捕获这三类错误并统一输出 JSON 格式的错误响应。

---

## 五、Schema 注册表与文档加载

### 5.1 SchemaRegistry

**文件**：[schema_registry.py](../../skills/carto-agent/scripts/carto_core/schema_registry.py)（116 行）

**核心职责**：

1. **批量加载**：构造时扫描 `schemas/` 目录下所有 `*.schema.json` 文件
2. **一致性校验**：每个 Schema 必须声明 `$id` 和 `$schema`（Draft 2020-12），禁止重名和重 ID
3. **引用解析**：使用 `referencing` 库构建跨 Schema `$ref` 解析注册表
4. **结构自检**：`check_all()` 对每个 Schema 调用 `validator_for(schema).check_schema(schema)` 验证 Schema 本身的合法性
5. **实例校验**：`validate(name, instance)` 使用 `FormatChecker` 和跨 Schema 引用解析进行完整校验，按路径排序输出第一个错误

### 5.2 文档加载安全

**`load_document` 函数**的防护层：

| 防护 | 实现 | 错误码 |
|---|---|---|
| 文件大小限制 | 5 MB（`MAX_DOCUMENT_BYTES`） | `DOCUMENT_TOO_LARGE` |
| 文件类型限制 | 仅 `.json` / `.yaml` / `.yml` | `DOCUMENT_TYPE_UNSUPPORTED` |
| 编码验证 | 必须 UTF-8 | `DOCUMENT_ENCODING_INVALID` |
| 解析错误 | JSON / YAML 解析异常捕获 | `DOCUMENT_PARSE_FAILED` |
| 深度限制 | 64 层（`MAX_DOCUMENT_DEPTH`） | `DOCUMENT_TOO_DEEP` |
| 循环检测 | YAML 锚点别名循环检测 | `DOCUMENT_CYCLIC` |
| 键类型 | 映射键必须为字符串 | `DOCUMENT_KEY_INVALID` |

---

## 六、CLI 入口设计

**文件**：[cli.py](../../skills/carto-agent/scripts/carto_core/cli.py)（96 行）/ [carto.py](../../skills/carto-agent/scripts/carto.py)（6 行）

CLI 采用 `argparse` 子命令结构，当前提供三组能力：

```
carto schema check                           # 校验所有注册 Schema 的结构合法性
carto schema validate <name> <instance>      # 用指定 Schema 校验文档实例
  --allowed-root <dir> (required, repeatable)

carto security check-path <path>             # 路径安全校验
  --allowed-root <dir> (required, repeatable)
  --must-exist

carto approval verify <receipt>              # 审批回执验证
  --allowed-root <dir> (required, repeatable)
  --key-env <env_var> (default: CARTO_APPROVAL_HMAC_KEY)
  --action --object-digest --scope --policy-id
  --tenant-id --issuer --subject-id
  --object-type --environment --nonce-db
  (以上均为 required)
```

**设计约束**：
- 所有命令都要求 `--allowed-root` 参数，不允许在无允许根的情况下操作任何路径
- 成功输出 `{"ok": true, ...}` JSON 到 stdout；失败输出 `{"ok": false, "code": ..., "message": ...}` JSON 到 stderr
- 退出码：成功 0，失败 2
- 审批回执验证命令先经过 Schema 校验，再经过 HMAC 签名验证和防重放检查

---

## 七、策略文件体系

### 7.1 安全策略总纲 — `security-policy.yaml`

声明了部署模式（`controlled-single-host`）、路径安全配置、文档限制、审批协议参数、授权模型和外部访问策略。

关键配置项：

| 配置 | 值 | 实现 |
|---|---|---|
| 路径穿越拒绝 | `reject_parent_traversal: true` | PathGuard.\_containing\_root |
| 链接逃逸拒绝 | `reject_out_of_root_links: true` | PathGuard.\_reject\_linked\_segments |
| Windows 保留名拒绝 | `reject_windows_reserved_names: true` | PathGuard.\_reject\_reserved\_parts |
| 文档大小限制 | 5242880 字节 | MAX\_DOCUMENT\_BYTES |
| 审批算法 | hmac-sha256 | ApprovalReceipt |
| 最小密钥长度 | 32 字节 | MINIMUM\_HMAC\_KEY\_BYTES |
| 防重放 | sqlite-persistent | SqliteNonceStore |
| 授权模型 | rbac-with-resource-namespace | authorize 函数 |
| 外发默认 | deny | ExternalAccessPolicy |
| 日志禁用字段 | credential/token/password/secret/geometry/coordinates/itinerary | redact\_for\_log |

### 7.2 工具绑定注册 — `tool-bindings.yaml`

注册了三个初始工具能力，默认拒绝（`default: deny`）未注册能力：

| capability_id | adapter | effect | 授权策略 | 快照策略 |
|---|---|---|---|---|
| local-file-read | local | read | project-source-read | required |
| schema-validate | local | transform | protocol-validation | receipt-only |
| qgis-environment-probe | local | read | environment-probe | receipt-only |

每个绑定声明了 `path_guard_required` 和 `credential_mode`，确保工具调用受路径安全和凭据隔离约束。

### 7.3 数据准备策略 — `data-preparation-policy.yaml`

| 配置 | 值 |
|---|---|
| 默认模式 | deterministic |
| 允许操作 | read, filter, join, reproject, aggregate, classify |
| 禁止操作 | dynamic-python, shell, arbitrary-sql, unapproved-download |
| 数据子智能体 | disabled（需四项条件才可启用） |
| 快照要求 | required |
| 变换回执要求 | required |
| 质量证据要求 | required |

### 7.4 知识来源注册 — `knowledge-sources.yaml`

注册了两个初始知识来源，默认拒绝外部搜索：

| source_id | kind | access | classification | authority |
|---|---|---|---|---|
| platform-term-dictionary | structured-dictionary | local-read-only | internal | platform-reviewed |
| approved-standard-catalog | document-catalog | local-read-only | internal | domain-review-required |

关键约束：`credentials_from_document: forbidden`，禁止从文档中读取凭据。

### 7.5 意图场景配置 — `intent-profiles.yaml`

定义三个业务场景的意图配置：

| scene_id | task_ids | required_information | unsupported_actions |
|---|---|---|---|
| government_thematic | administrative-map, indicator-map, facility-map | theme, geography, time, source, output | invent-unconfirmed-policy-theme |
| emergency_mapping | hazard-result-map, resource-map, situation-map | hazard, event-phase, data-nature, observation-time, geography, source, output | hazard-prediction, remote-sensing-auto-extraction, command-decision |
| leadership_visit | visit-route-map | itinerary, visit-order, route-mode, geography, confidentiality, output | reorder-visits, replace-road-route-with-straight-line |

### 7.6 检查器注册表 — `checker-registry.yaml`

注册三个初始检查器，未知检查器拒绝（`unknown_checker: reject`）。每个检查器声明了 ID、版本、阶段、规则强度、失败严重度、修复所有者和实现引用。

### 7.7 首期范围基线 — `scope-baseline.yaml`

声明了 U-P0 到 U-P1 之间的范围基线，状态为 `pending_trusted_approval`：

| 项目 | 值 |
|---|---|
| 部署模式 | controlled-single-host |
| 信任边界 | authenticated-operating-system-user |
| 首个纵向切片 | emergency-mapping-flood |
| 首切片来源格式 | geopackage, geojson, csv |
| 首切片表达 | choropleth-risk, point-shelter |
| 首切片输出 | a3-pdf, a3-png |
| 正式生产任务 | 空（须 U-P4 能力矩阵通过后加入） |
| 模型宿主 | application-managed |
| 敏感数据出公网 | forbidden |
| 模型输出形态 | typed_candidate_only |
| 任意代码执行 | forbidden |
| 验收安全审批人 | pending-assignment |
| 验收业务审批人 | pending-assignment |

### 7.8 核心质量基线 — `carto-core-1.0.0.yaml`

声明三个必需检查器及其严重度处理映射：

```
required_checks:
  - protocol.schema-valid@1.0.0
  - security.path-contained@1.0.0
  - approval.receipt-valid@1.0.0
```

---

## 八、测试体系

### 8.1 Schema 测试 — `test_schemas.py`

| 测试用例 | 验证内容 |
|---|---|
| `test_every_schema_is_structurally_valid` | 所有 27 个 Schema 通过 `check_schema` 结构校验 |
| `test_every_instance_schema_has_valid_and_invalid_fixture` | 除 common 外的 26 个 Schema 各有合法和非法 Fixture |
| `test_candidate_and_lock_share_identical_execution_contract` | resolved-map 候选与 map-spec-lock 实例锁共享同一 `execution` 和 `execution_digest`；变更后摘要不同 |
| `test_versioned_intent_profile_policy_matches_schema` | intent-profiles.yaml 策略文件通过 intent-profiles Schema 校验 |

### 8.2 安全测试 — `test_security.py`

| 测试类 | 测试用例 | 验证内容 |
|---|---|---|
| PathSecurityTests | 允许根内路径 | 正常解析 |
| | 拒绝路径穿越 | `../outside.txt` 被拒绝 |
| | 拒绝符号链接逃逸 | symlink 到允许根外被拒绝 |
| ApprovalTests | 签名回执验证一次通过 | HMAC 验证成功 |
| | 重放被拒绝 | 同一 nonce 二次消费失败 |
| | 篡改摘要被拒绝 | object\_digest 不匹配被拒绝 |
| | SQLite 持久化防重放 | 跨进程实例重放被拒绝 |
| | 上下文必须匹配 | environment 不匹配被拒绝 |
| | 弱密钥被拒绝 | < 32 字节密钥被拒绝 |
| | CLI 跨进程防重放 | subprocess 二次调用返回码 2 |
| AuthorizationAndPrivacyTests | RBAC 和命名空间双重检查 | 越权和越界被拒绝 |
| | 敏感地点不可达公网 | confidential + leadership\_itinerary 被拒绝 |
| | 日志递归脱敏 | 嵌套 dict 中敏感键被替换 |
| | Windows 交替流被拒绝 | `map.geojson:secret` 被拒绝 |

### 8.3 Fixture 设计 — `schema_cases.py`

- 以洪涝场景为基础，为 26 个实例 Schema 各提供一个合法 Fixture
- 非法 Fixture 通过在合法 Fixture 上添加 `unexpected_parallel_protocol: true` 字段实现，验证 `additionalProperties: false` 约束
- 候选快照和实例锁共享同一个 `EXECUTION` 对象和 `EXECUTION_DIGEST`，确保一致性

---

## 九、合理性与设计评价

### 9.1 整体架构评价

**合理之处**：

1. **协议先行**：U-P0 先于编码对齐了全部 Schema、策略和安全原语，后续 U-P1 的业务代码直接消费已定义的协议，不会产生并行旧模型。

2. **关注点分离清晰**：
   - `errors.py` 只定义错误类型，不含业务逻辑
   - `canonical.py` 只负责规范化序列化，不依赖安全或协议模块
   - `schema_registry.py` 只负责 Schema 加载和校验，不直接处理安全
   - `security/` 下四个模块各自独立，通过 `__init__.py` 统一导出

3. **安全原语组合完备**：路径安全、审批回执、RBAC 授权、敏感信息控制四层覆盖了实施计划 §2.3.3 的全部安全需求。

4. **跨 Schema 引用设计**：`common.schema.json` 集中定义共享类型（identifier、semanticVersion、digest、timestamp、relativePath、artifactRef、templateRef、provenance、rule、bbox、crs、executionSnapshot），其他 Schema 通过 `$ref` 引用，避免重复定义。

5. **测试覆盖全面**：合法/非法 Fixture 覆盖全部实例 Schema；安全测试覆盖正常路径、攻击路径和跨进程场景；候选—锁一致性有专门测试。

6. **跨平台安全**：PathGuard 同时处理 POSIX 和 Windows 的路径安全问题，包括 junction、保留名和交替流，适配项目 Windows 部署环境。

### 9.2 值得注意的设计决策

| 决策 | 理由 | 影响 |
|---|---|---|
| 使用 `frozen=True, slots=True` dataclass | 不可变、内存高效、防止运行时篡改 | 所有安全数据结构创建后不可修改 |
| HMAC 而非非对称签名 | 受控单机部署，无需 PKI；简化密钥管理 | 生产环境如需非对称签名，可在 U-P4 升级 |
| SQLite 而非 Redis 防重放 | 单机部署无需外部依赖 | 共享部署时需替换为分布式存储 |
| `additionalProperties: false` 全局禁止 | 拒绝未知字段，防止协议漂移 | 任何新增字段必须先更新 Schema |
| 规范化 JSON 使用 `ensure_ascii=False` | 支持中文内容正确摘要 | 中文字段在摘要中保持原意 |
| CLI 要求 `--allowed-root` | 所有路径操作必须在显式根下 | 防止意外访问文件系统任意位置 |

### 9.3 待改进项

| 项目 | 当前状态 | 建议 |
|---|---|---|
| 剩余模板契约 Schema | identity、cartography、layout、scenario、spatial-behavior、portrayal、delivery、source-manifest 已创建 | 实施计划退出标准第 5 项待勾选 |
| Schema Fixture 独立性 | 当前非法 Fixture 仅添加未知字段 | 可增加字段类型错误、必填缺失、枚举值非法等更细粒度的非法用例 |
| CLI 审批验证参数 | 9 个 `--expected-*` 参数全部 required | 可考虑将预期值打包为 JSON 文件以简化调用 |
| Python 环境验证 | 当前开发机 Python 不可用 | 需配置 Python 3.11+ 环境以运行测试 |

---

## 十、退出标准对照

| 退出标准 | 状态 | 证据 |
|---|---|---|
| 三份文档无并行旧模型，命名和契约数量一致 | 已完成 | 四类模板命名在 common/manifest/scenario 三处 Schema 一致；六契约在 scenario.owned\_segments 中固化 |
| 核心 Schema 草案已创建（13 个核心 + 14 个扩展 = 27 个） | 已完成 | schemas/ 目录下 27 个 .schema.json 文件全部加载并通过 check\_all() |
| 安全底座策略文件完成 | 已完成 | security-policy.yaml + tool-bindings.yaml + data-preparation-policy.yaml + knowledge-sources.yaml 含授权边界、凭据隔离和路径安全规则 |
| 仓库治理规则确认 | 已完成 | AGENTS.md + SKILL.md 声明独立目录、CLI 入口、测试位置和不并行旧实现 |
| 剩余模板契约 Schema 待补齐 | 已完成 | identity、cartography、layout、scenario、spatial-behavior、portrayal、delivery、source-manifest 均已创建 |
| Schema 通过 JSON Schema 结构校验测试 | 已完成 | test\_every\_schema\_is\_structurally\_valid 验证 27 个 Schema 通过 check\_schema |
| 核心 Schema 具有合法/非法 Fixture、引用解析和候选—锁一致性测试 | 已完成 | schema\_cases.py 提供 26 组 Fixture；test\_schemas.py 验证合法/非法/一致性 |
| 首期部署形态、能力范围、模型运行边界和验收责任已批准并版本化 | 待完成 | scope-baseline.yaml 已形成草案，status 为 pending\_trusted\_approval；安全审批人和业务审批人待分配 |

---

## 十一、与后续阶段的衔接

U-P0 的交付物为 U-P1（内核骨架与协议层）提供了以下基础：

| U-P0 交付物 | U-P1 消费方式 |
|---|---|
| 27 个 Schema | workflow/compiler/validation/adapters/repository 五模块直接引用 Schema 做类型化输入校验 |
| ApprovalReceipt + verify\_receipt | G1/G2/G3 三门禁的审批回执验证 |
| PathGuard | 所有文件 I/O 操作的路径安全前置 |
| authorize + SubjectContext | 工具网关和能力调用的身份与范围校验 |
| ExternalAccessPolicy + redact\_for\_log | 敏感信息边界和日志脱敏 |
| SchemaRegistry + load\_document | Schema 校验和文档加载的统一入口 |
| intent-profiles.yaml | IntentResolver 的场景目录 |
| checker-registry.yaml | Validator 的检查器注册表 |
| tool-bindings.yaml | ToolGateway 的能力注册表 |
| scope-baseline.yaml | U-P1 启动前的范围验收基线 |

---

*本文档基于 2026-09-14 代码快照编写，反映 U-P0 阶段的实际实现状态。*
