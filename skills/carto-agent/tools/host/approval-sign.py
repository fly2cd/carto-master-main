"""审批回执签发脚本（D1 决策：仓库外审批方辅助工具）。

用途：把"用户在对话中给出的批准"落成内核可验签的 ApprovalReceipt YAML。
不属于 carto CLI 的一部分，不绕过任何门禁——内核仍然全量校验签名、
身份、作用域、时效与防重放；本脚本只是让持有密钥的审批方能正确造出回执。

使用前提（纪律，见 doc/leadership-visit-e2e-plan.md "D1 两层关系说明"）：
  签发前必须已发生：agent 向用户展示对象要点 + approval_object_digest 并提问，
  用户真实回复同意。agent 不得未经用户明确批准就运行本脚本。
  真实数据期：密钥文件由用户持有，agent 只提供本命令行，不代跑。

用法：
  python approval-sign.py <gate> <object_digest> [选项]

  gate ∈ {g1, g2, g3, review, t1, tp}
  object_digest 形如 sha256:<64 hex>（来自 CLI 各步骤输出 JSON 的
  approval_object_digest 字段）

选项：
  --request PATH     项目 generate-request.yaml（自动提取 approver_subject_id /
                     tenant_id / scope / environment；推荐）
  --subject ID       手动指定 subject_id（无 --request 时必填）
  --tenant ID        手动指定 tenant_id（无 --request 时必填）
  --scope SCOPE      手动指定 scope（无 --request 时必填）
  --environment ENV  默认 local
  --out PATH         输出回执路径，默认 <gate>.yaml（当前目录）
  --ttl-minutes N    回执有效期（分钟），默认 60
  --key-file PATH    HMAC 密钥文件路径，默认 ./.approval-key（首次运行自动生成
                     32 字节随机密钥；真实数据期请换用户私有位置并删除自动文件）
  --key-env NAME     优先从该环境变量读密钥（默认 CARTO_APPROVAL_HMAC_KEY）

门与动作绑定（内核 workflow/approvals.py 的 GATES 定义）：
  g1     → approve-map-brief       / map-brief
  g2     → approve-freeze          / resolved-map
  g3     → approve-delivery        / delivery-manifest
  review → approve-product-review  / validation-report
  t1     → approve-template-brief  / template-brief
  tp     → approve-template-publish / template-publication

复用仓库实现（不自建平行加密）：ApprovalReceipt / sign_receipt / canonical JSON /
atomic_yaml 全部 import 自 carto_core，保证与内核验签逐字节一致。
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(r"D:\workspace\project_1\IGSA_1118\Intelligent_Geo-Spatiotemporal_Agent")
SCRIPTS = REPO / "skills" / "carto-agent" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from carto_core.artifacts import atomic_yaml  # noqa: E402
from carto_core.schema_registry import load_document  # noqa: E402
from carto_core.security.approval import ApprovalReceipt, sign_receipt  # noqa: E402

# 与内核 workflow/approvals.py GATES 一致；review 走 require_attestation 通道
GATES = {
    "g1": ("approve-map-brief", "map-brief"),
    "g2": ("approve-freeze", "resolved-map"),
    "g3": ("approve-delivery", "delivery-manifest"),
    "review": ("approve-product-review", "validation-report"),
    "t1": ("approve-template-brief", "template-brief"),
    "tp": ("approve-template-publish", "template-publication"),
}
MIN_KEY_BYTES = 32


def load_key(args) -> bytes:
    """密钥解析：环境变量优先，其次密钥文件（首次自动生成）。"""
    env_key = os.environ.get(args.key_env, "")
    if env_key:
        key = env_key.encode("utf-8")
        if len(key) < MIN_KEY_BYTES:
            sys.exit(f"ERROR: 环境变量 {args.key_env} 的密钥不足 {MIN_KEY_BYTES} 字节")
        return key
    key_file = Path(args.key_file)
    if not key_file.exists():
        generated = secrets.token_hex(MIN_KEY_BYTES)
        key_file.write_text(generated, encoding="utf-8")
        print(f"[approval-sign] 已生成新密钥 → {key_file}（真实数据期请移至用户私有位置）")
        return generated.encode("utf-8")
    key = key_file.read_text(encoding="utf-8").strip().encode("utf-8")
    if len(key) < MIN_KEY_BYTES:
        sys.exit(f"ERROR: 密钥文件 {key_file} 内容不足 {MIN_KEY_BYTES} 字节")
    return key


def resolve_identity(args) -> tuple[str, str, str]:
    """从 generate-request 提取签发身份；无请求文件时用手动参数。"""
    if args.request:
        request = load_document(Path(args.request))
        subject = request.get("subject", {})
        approver = (subject.get("approver_subject_id")
                    or subject.get("subject_id") or "")
        tenant = subject.get("tenant_id", "")
        scope = request.get("scope", "")
        environment = (request.get("environment")
                       or request.get("subject", {}).get("environment") or "local")
        missing = [n for n, v in (("approver_subject_id", approver),
                                  ("tenant_id", tenant), ("scope", scope)) if not v]
        if missing:
            sys.exit(f"ERROR: 请求 {args.request} 缺少 {missing}，请用 --subject/--tenant/--scope 手动指定")
    else:
        approver, tenant, scope = args.subject, args.tenant, args.scope
        environment = "local"
        missing = [n for n, v in (("subject", approver), ("tenant", tenant), ("scope", scope)) if not v]
        if missing:
            sys.exit(f"ERROR: 未提供 --request，必须手动指定 {missing}")
    if args.environment:
        environment = args.environment
    return approver, tenant, scope, environment


def main() -> None:
    parser = argparse.ArgumentParser(description="签发审批回执（D1：仓库外审批方辅助工具）")
    parser.add_argument("gate", choices=sorted(GATES))
    parser.add_argument("object_digest", help="sha256:<64 hex>，来自 CLI 输出的 approval_object_digest")
    parser.add_argument("--request", help="generate-request.yaml（自动提取签发身份）")
    parser.add_argument("--subject")
    parser.add_argument("--tenant")
    parser.add_argument("--scope")
    parser.add_argument("--environment", default="")
    parser.add_argument("--out", default="")
    parser.add_argument("--ttl-minutes", type=int, default=60)
    parser.add_argument("--key-file", default=".approval-key")
    parser.add_argument("--key-env", default="CARTO_APPROVAL_HMAC_KEY")
    args = parser.parse_args()

    action, object_type = GATES[args.gate]
    approver, tenant, scope, environment = resolve_identity(args)
    key = load_key(args)
    now = datetime.now(timezone.utc)
    # receipt_id 须匹配 ^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$（小写、无冒号）
    receipt_id = f"{args.gate}-{now.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    nonce = f"approval-{uuid.uuid4().hex}"  # 满足 16-128 可打印 ASCII，全局唯一防重放

    receipt = sign_receipt(ApprovalReceipt(
        schema_version=1,
        receipt_id=receipt_id,
        issuer="approval-sign.py",
        subject_id=approver,
        tenant_id=tenant,
        action=action,
        object_type=object_type,
        object_digest=args.object_digest,
        scope=scope,
        policy_id="carto-security",
        environment=environment,
        nonce=nonce,
        issued_at=(now - timedelta(minutes=1)).isoformat(),
        expires_at=(now + timedelta(minutes=args.ttl_minutes)).isoformat(),
    ), key)

    out = Path(args.out) if args.out else Path(f"{args.gate}.yaml")
    if out.exists():
        confirm = input(f"回执 {out} 已存在，覆盖重签？[y/N] ")
        if confirm.strip().lower() != "y":
            sys.exit("已取消（旧回执保留；nonce 防重放会拒绝旧回执重复消费）")
    atomic_yaml(out, asdict(receipt), create_once=False)
    print(f"[approval-sign] 已签发 {out}")
    print(f"  gate={args.gate}  action={action}  object_type={object_type}")
    print(f"  object_digest={args.object_digest}")
    print(f"  subject={approver}  tenant={tenant}  scope={scope}  environment={environment}")
    print(f"  有效期至 {receipt.expires_at}（{args.ttl_minutes} 分钟）")
    print("  纪律提醒：本回执应对应一次用户在对话中已明确给出的批准。")


if __name__ == "__main__":
    # Pin stdout/stderr to UTF-8: hosts capture this script's output through
    # pipes whose codepage (cp936 on Chinese Windows) would otherwise re-encode
    # the Chinese receipt summary into invalid bytes.
    for _stream in (sys.stdout, sys.stderr):
        if _stream is not None:
            try:
                _stream.reconfigure(encoding="utf-8")
            except (AttributeError, ValueError):
                pass
    main()
