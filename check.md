# Mog Coin machine readiness check

## Bound target

- Source repository: `incjanta/mogcoin`
- Source commit: `6c30620064e24c3cf417e58ad6c76fff82428194`
- Chain: `ethereum` (`1`)
- Live address: `0xaaee1a9723aadb7afa2810263653a34ba2c21c7a`
- Capture block: `25541742`
- Blueprint: `blueprints/mogcoin_fund_reward.json`
- Paid impacts: fund extraction and reward extraction only

## Hard gates

- [x] Verified source and successful ACTE build are present.
- [x] Blueprint identity, scope files, ABI surfaces, and live target match.
- [x] `setup/live_context.json` is block-pinned and protocol-bound.
- [x] `repositories.json` is exactly `[]` before DeepWiki setup.
- [x] Old project queues are excluded from the prepared machine.
- [x] Destination repository is public under `MjdkAko92IsxNC0sdeORcxaewE`: `https://github.com/MjdkAko92IsxNC0sdeORcxaewE/B1D7GV22AVBV1`.
- [x] All 11 tracked workflows appear as active in the GitHub Actions workflows API.
- [ ] Operator has configured required repository secrets before workflow launch.

## Live-context enrichment required

- [ ] Uniswap V2 pair code identity, token0, token1, reserves, LP total supply, and current pair MOG balance at the pinned block
- [ ] current owner or renounced-owner confirmation plus live authorization, fee-exemption, and max-transaction-exemption state for known actors
- [ ] current auto-liquidity, marketing, development, buyback, and burn receiver addresses
- [ ] current liquidity, marketing, development, buyback, burn, denominator, buy, sell, transfer, and backing-ratio parameters
- [ ] decoded Transfer, AutoLiquify, EditTax, set_Receivers, ClearStuck, ClearToken, and limit-change history beyond the bounded sampled window
- [ ] MOG balances for the pair, contract, DEAD, ZERO, and fee receivers reconciled to total supply and showSupply
- [ ] contract ETH, WETH, USDT, USDC, and other ERC20 balances refreshed and reconciled before any drain proof
- [ ] fork-confirmed actor matrix for every public and owner-only value-moving or configuration function

DeepWiki may use the current ACTE v3 snapshot for candidate generation. Missing values must remain unknown, and any candidate depending on them stays `NEEDS_LOCAL_PROOF` until refreshed live evidence and a local or pinned-fork test bind the impact.
