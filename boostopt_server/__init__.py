"""boostopt_server — BOOSTOPT's PRIVATE hosted backend (the premium tier).

  ⚠ NEVER published. NEVER shipped inside the free `boostopt` client. NEVER imported by `boostopt`.

The one architectural rule that makes open-core work (BOOSTOPT_Tiers P4):

        boostopt_server  ── imports ──▶  boostopt        (the shared, free-tier core)
        boostopt         ── imports ──▶  (nothing here)

The dependency arrow points ONE WAY. This package REUSES the free engine (gate, orchestrator,
adapters) on OUR compute; it never duplicates it. Because premium logic lives in a *separate
package* that isn't in the client's build, the open client literally cannot contain a paywall —
there is no `if premium:` to sneak in. The token gate is enforced HERE, server-side.

When the core is open-sourced, publish `boostopt/` and keep `boostopt_server/` private — a clean cut
at this package line.
"""
