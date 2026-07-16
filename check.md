# Mog Coin machine readiness check

## Bound target

- Source repository: `incjanta/mogcoin`
- Source commit: `6c30620064e24c3cf417e58ad6c76fff82428194`
- Chain: `ethereum` (`1`)
- Live address: `0xaaee1a9723aadb7afa2810263653a34ba2c21c7a`
- Capture block: `25541974` (`2026-07-16T01:35:23Z`)
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

## Live-context quality gate

Status: `enriched`; audit-launch context gate passed. The snapshot expires at `2026-07-23T01:35:23Z` and must be refreshed after that time.

- [x] Uniswap V2 pair runtime identity/code hash, factory, token0, token1, reserves, LP total supply, pair MOG/WETH balances, and reserve-vs-balance reconciliation are pinned.
- [x] Owner is confirmed renounced at block `17731932`; authorization, fee-exemption, and max-transaction-exemption storage is decoded for the token, pair, router, factory, WETH, deployer/fee receiver, DEAD, and ZERO.
- [x] Auto-liquidity, marketing, development, and buyback receivers resolve to `0x20e12a9a5c738e265ec81d6f2a8e77785b6aa8b8`; burn resolves to `0x000000000000000000000000000000000000dead`.
- [x] Liquidity/marketing/development/buyback/burn fees, denominator, buy/sell/transfer multipliers, effective fees, backing ratio, swap settings, maxTx, and maxWallet are storage-decoded.
- [x] Every emitted non-Transfer event type is queried from deployment through the capture block; the 25 newest Transfers are decoded, and launch calls without dedicated events are reconstructed through renunciation.
- [x] MOG balances for the pair, contract, DEAD, ZERO, and all fee receivers reconcile `showSupply = totalSupply - DEAD - ZERO`.
- [x] ETH, MOG, WETH, USDT, and USDC balances are refreshed for the pair, contract, DEAD, ZERO, and fee receivers.
- [x] `blueprints/mogcoin_fund_reward.json` binds the canonical path, source/chain/target identity, required quality status, maximum age, and a compact live-state summary.
- [x] `questions.py` defaults to `setup/live_context.json` and hard-rejects missing, malformed, mismatched, unpinned, wrong-status, expired, or over-age context before prompt generation.

## Bounded missing evidence (not launch blockers)

- [ ] Solidity mappings cannot be globally enumerated. Probe any newly identified actor before relying on its authorization or exemption state.
- [ ] Vanilla RPC cannot enumerate every unsolicited/spam ERC20. Query any asset outside MOG/ETH/WETH/USDT/USDC if a candidate depends on it.
- [ ] Full high-volume Transfer history is not embedded. Fetch the candidate-specific range when historical flow is part of a claim.
- [ ] No candidate is submission-ready without a pinned-fork or equivalent local reproduction at the recorded block.

DeepWiki may generate candidates from the enriched v4 snapshot. Every bounded unknown remains unknown, and any dependent candidate stays `NEEDS_LOCAL_PROOF` until refreshed evidence and a local or pinned-fork test bind the impact.
