# Shop Project Architecture

## Components

- `shop.orders` — order lifecycle (placement, cancellation).
- `shop.payments` — payment capture against the gateway.
- `shop.checkout_legacy` — legacy checkout path kept for an old mobile
  client; slated for removal once that client is retired.
- `shop.dashboard` — seller-facing order dashboard rendering.

## Boundaries

Orders and payments are separate modules with no shared state; the
legacy checkout module bypasses both and computes totals itself, which
is the main architectural wart in this system.
