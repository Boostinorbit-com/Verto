"""verto_server admin CLI (PREMIUM — PRIVATE). Manage tokens + see usage.

This is the operator's tool that STANDS IN for the sign-up + payment flow (roadmap Phase 2.1–2.3):
today you mint a token by hand after someone pays; at release a Stripe webhook calls the same
`store.issue()` and this CLI stays as the ops/support tool. It writes the same JSON store the
server reads ($VERTO_SERVER_DATA, default ~/.verto_server).

  python -m verto_server.admin plans                       # what plans exist + what they grant
  python -m verto_server.admin list                        # every token, its plan + usage
  python -m verto_server.admin issue --plan pro --note x    # mint a token (prints the secret)
  python -m verto_server.admin usage <token>               # runs used this period
  python -m verto_server.admin revoke <token>              # deactivate a token
"""
from __future__ import annotations

import argparse
import sys

from . import entitlement, store


def _cmd_plans(_a) -> int:
    print("plans (from entitlement.PLANS):")
    for name, ent in entitlement.PLANS.items():
        quota = "unlimited" if not ent.monthly_quota else f"{ent.monthly_quota}/mo"
        feats = ", ".join(sorted(ent.features)) or "—"
        print(f"  {name:<14} engine={entitlement.engine_label(ent):<32} quota={quota:<12} "
              f"features=[{feats}]")
    return 0


def _cmd_list(_a) -> int:
    s = store.default_store()
    accts = s.all_accounts()
    if not accts:
        print("(no accounts — issue one:  python -m verto_server.admin issue --plan pro)")
        return 0
    period = store._period()
    print(f"accounts (usage for {period}):")
    for a in accts:
        ent = entitlement.PLANS.get(a.plan)
        quota = "∞" if not (ent and ent.monthly_quota) else ent.monthly_quota
        state = "active" if a.active else "REVOKED"
        print(f"  {a.token:<32} {a.plan:<13} {a.used_this_period()}/{quota:<6} {state:<8} "
              f"{a.note}")
    return 0


def _cmd_issue(a) -> int:
    if a.plan not in entitlement.PLANS:
        print(f"unknown plan {a.plan!r}. Known: {', '.join(entitlement.PLANS)}", file=sys.stderr)
        return 2
    acct = store.default_store().issue(a.plan, note=a.note or "")
    print(f"issued token for plan {a.plan!r}:")
    print(f"  {acct.token}")
    print("give this to the customer as their --verto-token (VERTO_TOKEN).")
    return 0


def _cmd_usage(a) -> int:
    used, period = store.default_store().usage(a.token)
    acct = store.default_store().resolve(a.token)
    if acct is None:
        print(f"token not found or revoked: {a.token}", file=sys.stderr)
        return 1
    ent = entitlement.PLANS.get(acct.plan)
    quota = "∞" if not (ent and ent.monthly_quota) else ent.monthly_quota
    print(f"{a.token}  plan={acct.plan}  used={used}/{quota}  period={period}")
    return 0


def _cmd_revoke(a) -> int:
    ok = store.default_store().revoke(a.token)
    print("revoked." if ok else f"token not found: {a.token}", file=sys.stderr if not ok else None)
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="verto_server.admin", description="Manage hosted tokens.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plans", help="list plans and what they grant").set_defaults(fn=_cmd_plans)
    sub.add_parser("list", help="list all tokens + usage").set_defaults(fn=_cmd_list)
    pi = sub.add_parser("issue", help="mint a token for a plan")
    pi.add_argument("--plan", required=True)
    pi.add_argument("--note", default="", help="who it's for (free text)")
    pi.set_defaults(fn=_cmd_issue)
    pu = sub.add_parser("usage", help="show a token's usage")
    pu.add_argument("token")
    pu.set_defaults(fn=_cmd_usage)
    pr = sub.add_parser("revoke", help="deactivate a token")
    pr.add_argument("token")
    pr.set_defaults(fn=_cmd_revoke)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
