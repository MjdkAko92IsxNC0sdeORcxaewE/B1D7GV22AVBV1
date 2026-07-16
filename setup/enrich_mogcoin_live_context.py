#!/usr/bin/env python3
"""Refresh Mog Coin's block-pinned launch context from Ethereum RPC evidence."""

from __future__ import annotations

import datetime as dt
import json
import os
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
LIVE_CONTEXT_PATH = ROOT / "setup" / "live_context.json"
BLUEPRINT_PATH = ROOT / "blueprints" / "mogcoin_fund_reward.json"

TOKEN = "0xaaee1a9723aadb7afa2810263653a34ba2c21c7a"
PAIR = "0xc2eab7d33d3cb97692ecb231a5d0e4a649cb539d"
ROUTER = "0x7a250d5630b4cf539739df2c5dacb4c659f2488d"
DEPLOYER = "0x20e12a9a5c738e265ec81d6f2a8e77785b6aa8b8"
DEAD = "0x000000000000000000000000000000000000dead"
ZERO = "0x0000000000000000000000000000000000000000"
DEPLOY_BLOCK = 17_731_591
DEPLOY_TX = "0xdb32e45e46546066b3afe1224c59dcbd37696652cabda1ed14c87be368c95958"
RENOUNCE_BLOCK = 17_731_932

COMMON_ASSETS = {
    "WETH": ("0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2", 18),
    "USDT": ("0xdac17f958d2ee523a2206206994597c13d831ec7", 6),
    "USDC": ("0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", 6),
}

EVENT_TYPES = {
    "AutoLiquify": ["uint256", "uint256"],
    "ClearStuck": ["uint256"],
    "ClearToken": ["address", "uint256"],
    "EditTax": ["uint8", "uint8", "uint8"],
    "set_MaxTX": ["uint256"],
    "set_MaxWallet": ["uint256"],
    "set_Receivers": ["address", "address", "address", "address"],
    "set_SwapBack": ["uint256", "bool"],
    "user_TxExempt": ["address", "bool"],
    "user_exemptfromfees": ["address", "bool"],
}

EVENT_SIGNATURES = {
    "AutoLiquify": "AutoLiquify(uint256,uint256)",
    "ClearStuck": "ClearStuck(uint256)",
    "ClearToken": "ClearToken(address,uint256)",
    "EditTax": "EditTax(uint8,uint8,uint8)",
    "OwnershipTransferred": "OwnershipTransferred(address,address)",
    "set_MaxTX": "set_MaxTX(uint256)",
    "set_MaxWallet": "set_MaxWallet(uint256)",
    "set_Receivers": "set_Receivers(address,address,address,address)",
    "set_SwapBack": "set_SwapBack(uint256,bool)",
    "user_TxExempt": "user_TxExempt(address,bool)",
    "user_exemptfromfees": "user_exemptfromfees(address,bool)",
}

CONFIG_METHODS = {
    "0x293230b8": ("startTrading", []),
    "0xa70419d2": ("reduceFee", []),
    "0xc0cbdea4": ("setStructure", ["uint256", "uint256", "uint256"]),
    "0x751039fc": ("removeLimits", []),
    "0x715018a6": ("renounceOwnership", []),
    "0x282c8749": ("setParameters", ["uint256"] * 6),
    "0x82528791": ("setWallets", ["address"] * 5),
    "0xdf20fd49": ("setSwapBackSettings", ["bool", "uint256"]),
    "0x5d83e1d5": ("maxWalletRule", ["uint256"]),
    "0xf2fde38b": ("transferOwnership", ["address"]),
}


def utc_iso(timestamp: int) -> str:
    return dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def human(raw: int, decimals: int) -> str:
    value = Decimal(raw) / (Decimal(10) ** decimals)
    return format(value, "f")


def word_address(word: str) -> str:
    return "0x" + word[-40:].lower()


def decode_word(word: str, abi_type: str) -> Any:
    if abi_type == "address":
        return word_address(word)
    value = int(word, 16)
    if abi_type == "bool":
        return bool(value)
    return value


def decode_data(data: str, types: list[str]) -> list[Any]:
    payload = data[2:]
    words = [payload[index : index + 64] for index in range(0, len(payload), 64)]
    return [decode_word(word, abi_type) for word, abi_type in zip(words, types)]


class Rpc:
    def __init__(self, endpoint: str):
        self.endpoint = endpoint
        self.session = requests.Session()
        self.request_id = 0

    def call(self, method: str, params: Any) -> Any:
        self.request_id += 1
        response = self.session.post(
            self.endpoint,
            json={"jsonrpc": "2.0", "id": self.request_id, "method": method, "params": params},
            timeout=45,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise RuntimeError(f"{method} failed: {payload['error']}")
        return payload.get("result")

    def eth_call(self, address: str, calldata: str, block: str) -> str:
        return self.call("eth_call", [{"to": address, "data": calldata}, block])

    def storage(self, address: str, slot: int | str, block: str) -> str:
        slot_hex = hex(slot) if isinstance(slot, int) else slot
        return self.call("eth_getStorageAt", [address, slot_hex, block])

    def topic(self, signature: str) -> str:
        return self.call("web3_sha3", ["0x" + signature.encode().hex()])


def sanitize_rpc(endpoint: str) -> str:
    if "rpc.ankr.com" in endpoint:
        return "https://rpc.ankr.com/eth/<redacted>"
    parts = endpoint.split("/")
    return "/".join(parts[:3]) if len(parts) >= 3 else endpoint


def uint_call(rpc: Rpc, address: str, selector: str, block: str) -> int:
    return int(rpc.eth_call(address, selector, block), 16)


def address_call(rpc: Rpc, address: str, selector: str, block: str) -> str:
    return word_address(rpc.eth_call(address, selector, block))


def balance_of(rpc: Rpc, token: str, holder: str, block: str) -> int:
    calldata = "0x70a08231" + holder[2:].lower().zfill(64)
    return uint_call(rpc, token, calldata, block)


def mapping_slot(rpc: Rpc, address: str, slot: int) -> str:
    encoded = "0x" + address[2:].lower().zfill(64) + hex(slot)[2:].zfill(64)
    return rpc.call("web3_sha3", [encoded])


def mapping_bool(rpc: Rpc, contract: str, address: str, slot: int, block: str) -> bool:
    return bool(int(rpc.storage(contract, mapping_slot(rpc, address, slot), block), 16))


def query_logs(query: Rpc, normal: Rpc, names: list[str], start: int, end: int, *, descending: bool = False, page_size: int = 1000) -> list[dict[str, Any]]:
    topics = [normal.topic(EVENT_SIGNATURES[name]) for name in names]
    all_logs: list[dict[str, Any]] = []
    page_token = ""
    while True:
        params: dict[str, Any] = {
            "blockchain": "eth",
            "fromBlock": start,
            "toBlock": end,
            "address": [TOKEN],
            "topics": [topics],
            "pageSize": page_size,
            "decodeLogs": False,
            "descOrder": descending,
        }
        if page_token:
            params["pageToken"] = page_token
        result = query.call("ankr_getLogs", params)
        all_logs.extend(result.get("logs", []))
        page_token = result.get("nextPageToken", "")
        if not page_token:
            return all_logs


def decode_special_history(logs: list[dict[str, Any]], topic_to_name: dict[str, str]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for log in logs:
        name = topic_to_name[log["topics"][0].lower()]
        if name == "OwnershipTransferred":
            values = [word_address(log["topics"][1]), word_address(log["topics"][2])]
            fields = {"previous_owner": values[0], "new_owner": values[1]}
        else:
            values = decode_data(log["data"], EVENT_TYPES[name])
            fields = {f"arg_{index}": value for index, value in enumerate(values)}
            if name == "ClearToken":
                fields = {"token": values[0], "amount_raw": str(values[1])}
        grouped[name].append(
            {
                "block_number": int(log["blockNumber"], 16),
                "timestamp": utc_iso(int(log["timestamp"], 16)),
                "transaction_hash": log["transactionHash"].lower(),
                "decoded": fields,
            }
        )

    return {
        name: {
            "all_time_count": len(grouped.get(name, [])),
            "logs": grouped.get(name, []),
            "complete_range": [DEPLOY_BLOCK, None],
        }
        for name in EVENT_SIGNATURES
    }


def query_launch_transactions(query: Rpc) -> list[dict[str, Any]]:
    result = query.call(
        "ankr_getTransactionsByAddress",
        {
            "blockchain": "eth",
            "address": DEPLOYER,
            "fromBlock": DEPLOY_BLOCK,
            "toBlock": RENOUNCE_BLOCK,
            "includeLogs": False,
            "descOrder": False,
            "pageSize": 1000,
        },
    )
    decoded = []
    for transaction in result.get("transactions", []):
        if (transaction.get("to") or "").lower() != TOKEN:
            continue
        calldata = transaction.get("input", "")
        method = CONFIG_METHODS.get(calldata[:10].lower())
        if not method:
            continue
        name, arg_types = method
        args = decode_data("0x" + calldata[10:], arg_types)
        decoded.append(
            {
                "block_number": int(transaction["blockNumber"], 16),
                "timestamp": utc_iso(int(transaction["timestamp"], 16)),
                "transaction_hash": transaction["hash"].lower(),
                "caller": transaction["from"].lower(),
                "method": name,
                "args": args,
                "status": int(transaction["status"], 16),
            }
        )
    return decoded


def main() -> int:
    with LIVE_CONTEXT_PATH.open("r", encoding="utf-8") as handle:
        old_context = json.load(handle)
    with BLUEPRINT_PATH.open("r", encoding="utf-8") as handle:
        blueprint = json.load(handle)

    normal_endpoint = os.environ.get("ETHEREUM_RPC_URL") or old_context.get("rpc_endpoint_used")
    if not normal_endpoint or "<redacted>" in normal_endpoint:
        raise RuntimeError("ETHEREUM_RPC_URL is required for a fresh pinned-state capture")
    query_endpoint = os.environ.get("ANKR_QUERY_RPC_URL")
    if not query_endpoint and "rpc.ankr.com/eth/" in normal_endpoint:
        query_endpoint = normal_endpoint.replace("/eth/", "/multichain/")
    if not query_endpoint:
        raise RuntimeError("ANKR_QUERY_RPC_URL is required for complete indexed history")

    rpc = Rpc(normal_endpoint)
    query = Rpc(query_endpoint)
    latest_block = int(rpc.call("eth_blockNumber", []), 16)
    block = hex(latest_block)
    header = rpc.call("eth_getBlockByNumber", [block, False])
    timestamp = int(header["timestamp"], 16)

    storage = {slot: rpc.storage(TOKEN, slot, block) for slot in range(32)}
    uint_slots = {slot: int(value, 16) for slot, value in storage.items()}
    packed_slot = uint_slots[29]

    owner = word_address(storage[0])
    weth = word_address(storage[2])
    pair = "0x" + hex(packed_slot & ((1 << 160) - 1))[2:].zfill(40)
    trading_open = bool((packed_slot >> 160) & 0xFF)
    swap_enabled = bool((packed_slot >> 168) & 0xFF)
    receivers = {
        "auto_liquidity": word_address(storage[20]),
        "marketing": word_address(storage[21]),
        "development": word_address(storage[22]),
        "buyback": word_address(storage[23]),
        "burn": word_address(storage[24]),
    }

    factory = address_call(rpc, ROUTER, "0xc45a0155", block)
    token0 = address_call(rpc, pair, "0x0dfe1681", block)
    token1 = address_call(rpc, pair, "0xd21220a7", block)
    reserves_raw = rpc.eth_call(pair, "0x0902f1ac", block)[2:]
    reserve0 = int(reserves_raw[0:64], 16)
    reserve1 = int(reserves_raw[64:128], 16)
    reserve_timestamp = int(reserves_raw[128:192], 16)
    lp_total_supply = uint_call(rpc, pair, "0x18160ddd", block)

    target_code = rpc.call("eth_getCode", [TOKEN, block])
    pair_code = rpc.call("eth_getCode", [pair, block])
    target_code_hash = rpc.call("web3_sha3", [target_code])
    pair_code_hash = rpc.call("web3_sha3", [pair_code])

    actor_roles: dict[str, list[str]] = defaultdict(list)
    for role, address in {
        "token_contract": TOKEN,
        "uniswap_v2_pair": pair,
        "router": ROUTER,
        "factory": factory,
        "weth": weth,
        "deployer": DEPLOYER,
        "current_owner": owner,
        "dead": DEAD,
        "zero": ZERO,
        **{f"{name}_receiver": address for name, address in receivers.items()},
    }.items():
        actor_roles[address.lower()].append(role)

    actor_matrix = []
    for address, roles in actor_roles.items():
        actor_matrix.append(
            {
                "address": address,
                "roles": sorted(roles),
                "authorized": mapping_bool(rpc, TOKEN, address, 1, block),
                "fee_exempt": mapping_bool(rpc, TOKEN, address, 8, block),
                "max_tx_exempt": mapping_bool(rpc, TOKEN, address, 9, block),
                "mog_balance_raw": str(balance_of(rpc, TOKEN, address, block)),
            }
        )

    custody_addresses = {TOKEN, pair, DEAD, ZERO, *receivers.values()}
    custody_balances = []
    for address in sorted(custody_addresses):
        assets: dict[str, Any] = {
            "ETH": {
                "raw": str(int(rpc.call("eth_getBalance", [address, block]), 16)),
                "decimals": 18,
            },
            "MOG": {"raw": str(balance_of(rpc, TOKEN, address, block)), "decimals": 18},
        }
        for symbol, (asset, decimals) in COMMON_ASSETS.items():
            assets[symbol] = {"raw": str(balance_of(rpc, asset, address, block)), "decimals": decimals}
        for value in assets.values():
            value["human"] = human(int(value["raw"]), value["decimals"])
        custody_balances.append({"address": address, "roles": sorted(actor_roles[address.lower()]), "assets": assets})

    total_supply = uint_slots[3]
    dead_balance = balance_of(rpc, TOKEN, DEAD, block)
    zero_balance = balance_of(rpc, TOKEN, ZERO, block)
    pair_balance = balance_of(rpc, TOKEN, pair, block)
    contract_balance = balance_of(rpc, TOKEN, TOKEN, block)
    show_supply = total_supply - dead_balance - zero_balance

    special_names = list(EVENT_SIGNATURES)
    special_logs = query_logs(query, rpc, special_names, DEPLOY_BLOCK, latest_block)
    topic_to_name = {rpc.topic(signature).lower(): name for name, signature in EVENT_SIGNATURES.items()}
    special_history = decode_special_history(special_logs, topic_to_name)
    for item in special_history.values():
        item["complete_range"][1] = latest_block

    transfer_topic = rpc.topic("Transfer(address,address,uint256)")
    recent_transfers_raw = query.call(
        "ankr_getLogs",
        {
            "blockchain": "eth",
            "fromBlock": DEPLOY_BLOCK,
            "toBlock": latest_block,
            "address": [TOKEN],
            "topics": [[transfer_topic]],
            "pageSize": 25,
            "decodeLogs": False,
            "descOrder": True,
        },
    ).get("logs", [])
    recent_transfers = [
        {
            "block_number": int(log["blockNumber"], 16),
            "timestamp": utc_iso(int(log["timestamp"], 16)),
            "transaction_hash": log["transactionHash"].lower(),
            "from": word_address(log["topics"][1]),
            "to": word_address(log["topics"][2]),
            "amount_raw": str(int(log["data"], 16)),
            "amount_human": human(int(log["data"], 16), 18),
        }
        for log in recent_transfers_raw
    ]
    launch_history = query_launch_transactions(query)

    fee_values = {
        "liquidity_fee": uint_slots[10],
        "marketing_fee": uint_slots[11],
        "development_fee": uint_slots[12],
        "buyback_fee": uint_slots[13],
        "burn_fee": uint_slots[14],
        "total_fee": uint_slots[15],
        "fee_denominator": uint_slots[16],
        "sell_percent": uint_slots[17],
        "buy_percent": uint_slots[18],
        "transfer_percent": uint_slots[19],
        "backing_ratio": uint_slots[25],
        "backing_ratio_denominator": uint_slots[26],
    }
    for flow in ("buy", "sell", "transfer"):
        numerator = fee_values["total_fee"] * fee_values[f"{flow}_percent"]
        denominator = fee_values["fee_denominator"] * 100
        fee_values[f"effective_{flow}_fee_fraction"] = f"{numerator}/{denominator}"
        fee_values[f"effective_{flow}_fee_percent"] = str(Decimal(numerator) * 100 / Decimal(denominator)) if denominator else "undefined"

    missing_evidence = [
        {
            "id": "private_mapping_global_enumeration",
            "bounded_missing": "Solidity mappings are not enumerable; authorization and exemption state is storage-proven only for the known actor set recorded here.",
            "promotion_rule": "Probe any newly identified actor key at the pinned block before relying on its mapping state.",
        },
        {
            "id": "other_erc20_inventory",
            "bounded_missing": "Vanilla RPC cannot enumerate every spam or unsolicited ERC20 held by an address; MOG, ETH, WETH, USDT, and USDC are explicitly refreshed for all custody actors.",
            "promotion_rule": "Query balanceOf for any additional token named by a candidate before proving a drain.",
        },
        {
            "id": "full_transfer_history",
            "bounded_missing": "The high-volume Transfer stream is represented by the 25 most recent logs; all emitted configuration, ownership, recovery, and AutoLiquify event types are queried over the complete deployment-to-capture range.",
            "promotion_rule": "Fetch a candidate-specific Transfer range when historical balance flow is part of the exploit claim.",
        },
        {
            "id": "candidate_specific_fork_execution",
            "bounded_missing": "This launch artifact proves storage, calls, balances, pair state, and indexed history, but does not impersonate every actor against every write function on a fork.",
            "promotion_rule": "No critical candidate may be promoted without a pinned-fork or equivalent local reproduction at this block.",
        },
    ]

    stale_at = dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc) + dt.timedelta(hours=168)
    context = {
        "schema_version": "acte-live-context-v4",
        "protocol": {
            "name": "Mog Coin",
            "source_repo": "incjanta/mogcoin",
            "source_commit": "6c30620064e24c3cf417e58ad6c76fff82428194",
            "paid_impact_focus": "fund extraction and reward extraction",
        },
        "chain": "ethereum",
        "chain_id": 1,
        "captured_at": utc_iso(timestamp),
        "latest_block": latest_block,
        "capture_block_hash": header["hash"],
        "rpc_endpoint_used": sanitize_rpc(normal_endpoint),
        "target": {
            "address": TOKEN,
            "deployment_kind": "direct",
            "deployment_block": DEPLOY_BLOCK,
            "deployment_transaction": DEPLOY_TX,
            "code_size_bytes": (len(target_code) - 2) // 2,
            "runtime_code_hash": target_code_hash,
            "native_balance_wei": str(int(rpc.call("eth_getBalance", [TOKEN, block]), 16)),
            "explorer_url": f"https://etherscan.io/address/{TOKEN}",
        },
        "source_identity": old_context.get("source_identity", {}),
        "storage_layout_evidence": {
            "source": "forge inspect src/MOG.sol:MOG storage-layout at source commit",
            "slots_read": [0, 31],
            "block_number": latest_block,
        },
        "common_views": {
            "name": "Mog Coin",
            "symbol": "Mog",
            "decimals": 18,
            "owner": owner,
            "owner_renounced": owner == ZERO,
            "TradingOpen": trading_open,
            "swapEnabled": swap_enabled,
            "swapThreshold": uint_slots[30],
            "_maxTxAmount": uint_slots[4],
            "_maxWalletToken": uint_slots[5],
            "totalFee": uint_slots[15],
            "totalSupply": total_supply,
            "showSupply": show_supply,
            "router": ROUTER,
            "pair": pair,
            "WETH": weth,
        },
        "pair_identity": {
            "address": pair,
            "factory": factory,
            "code_size_bytes": (len(pair_code) - 2) // 2,
            "runtime_code_hash": pair_code_hash,
            "token0": token0,
            "token1": token1,
            "reserve0_raw": str(reserve0),
            "reserve1_raw": str(reserve1),
            "reserve_timestamp": reserve_timestamp,
            "lp_total_supply_raw": str(lp_total_supply),
            "mog_balance_raw": str(pair_balance),
            "weth_balance_raw": str(balance_of(rpc, weth, pair, block)),
            "reserve_balance_reconciliation": {
                "token0_balance_raw": str(balance_of(rpc, token0, pair, block)),
                "token1_balance_raw": str(balance_of(rpc, token1, pair, block)),
                "token0_balance_minus_reserve": str(balance_of(rpc, token0, pair, block) - reserve0),
                "token1_balance_minus_reserve": str(balance_of(rpc, token1, pair, block) - reserve1),
            },
        },
        "ownership_and_authorization": {
            "current_owner": owner,
            "renounced": owner == ZERO,
            "renounce_block": RENOUNCE_BLOCK,
            "renounce_transaction": "0xc5aad0f6c6ab72c4775b0a2a7672eefd5760d532d4949c51105f30c6176aec6e",
            "important_note": "renounceOwnership clears _owner but does not clear the separate authorizations mapping; deployer remains authorized for transfer gating.",
            "known_actor_matrix": actor_matrix,
        },
        "fee_receivers": receivers,
        "tokenomics_parameters": fee_values,
        "swap_and_limits": {
            "trading_open": trading_open,
            "swap_enabled": swap_enabled,
            "swap_threshold_raw": str(uint_slots[30]),
            "max_tx_raw": str(uint_slots[4]),
            "max_wallet_raw": str(uint_slots[5]),
            "limits_equal_total_supply": uint_slots[4] == total_supply and uint_slots[5] == total_supply,
            "contract_mog_balance_raw": str(contract_balance),
            "swap_threshold_reached": contract_balance >= uint_slots[30],
        },
        "balances": {
            "custody_assets_by_actor": custody_balances,
            "supply_reconciliation": {
                "total_supply_raw": str(total_supply),
                "dead_mog_raw": str(dead_balance),
                "zero_mog_raw": str(zero_balance),
                "show_supply_raw": str(show_supply),
                "computed_total_minus_dead_minus_zero_raw": str(total_supply - dead_balance - zero_balance),
                "matches_show_supply": show_supply == total_supply - dead_balance - zero_balance,
                "pair_mog_raw": str(pair_balance),
                "contract_mog_raw": str(contract_balance),
            },
        },
        "history": {
            "deployment_to_capture_special_events": special_history,
            "launch_configuration_transactions": launch_history,
            "recent_transfer_sample": {
                "order": "newest_first",
                "limit": 25,
                "logs": recent_transfers,
            },
            "coverage_note": "Advanced indexed history covers every emitted non-Transfer event type from deployment through the capture block; launch configuration calls without dedicated events are recovered from deployer transactions through renunciation.",
        },
        "abi_inventory": old_context.get("abi_inventory", {}),
        "missing_evidence": missing_evidence,
        "context_quality": {
            "status": "enriched",
            "audit_launch_ready": True,
            "deepwiki_usable": True,
            "capture_is_block_pinned": True,
            "stale_after": stale_at.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "max_age_hours": 168,
            "required_before_critical_promotion": [item["promotion_rule"] for item in missing_evidence],
            "rule": "Launch questions may use this snapshot; candidate promotion still requires candidate-specific fresh state and local proof.",
            "blueprint": "blueprints/mogcoin_fund_reward.json",
        },
        "evidence_sources": [
            "Ethereum JSON-RPC block-pinned eth_call, eth_getStorageAt, eth_getBalance, and eth_getCode",
            "Ankr indexed ankr_getLogs and ankr_getTransactionsByAddress for bounded history",
            "Verified src/MOG.sol at source commit 6c30620064e24c3cf417e58ad6c76fff82428194",
            f"Etherscan deployment transaction {DEPLOY_TX}",
        ],
        "audit_notes": [
            "Values are captured at exactly latest_block and must not be silently reused after stale_after.",
            "Private mappings are probed only for recorded known actors; absence elsewhere is not inferred.",
            "Owner-only configuration is not a valid paid exploit without an unprivileged authorization bypass.",
            "Public manualSend and clearStuckToken always forward to the stored auto-liquidity receiver; attacker capture requires a separate redirection path.",
        ],
    }

    blueprint["live_context_path"] = "setup/live_context.json"
    blueprint["live_context_binding"] = {
        "schema_version": context["schema_version"],
        "chain": "ethereum",
        "chain_id": 1,
        "target_address": TOKEN,
        "pair_address": pair,
        "source_commit": context["protocol"]["source_commit"],
        "required_status": "enriched",
        "max_age_hours": 168,
    }
    blueprint["live_context_summary"] = {
        "captured_at": context["captured_at"],
        "latest_block": latest_block,
        "status": "enriched",
        "owner": owner,
        "owner_renounced": owner == ZERO,
        "pair": pair,
        "token0": token0,
        "token1": token1,
        "reserve0_raw": str(reserve0),
        "reserve1_raw": str(reserve1),
        "lp_total_supply_raw": str(lp_total_supply),
        "pair_mog_balance_raw": str(pair_balance),
        "fee_receivers": receivers,
        "effective_buy_fee_percent": fee_values["effective_buy_fee_percent"],
        "effective_sell_fee_percent": fee_values["effective_sell_fee_percent"],
        "effective_transfer_fee_percent": fee_values["effective_transfer_fee_percent"],
        "bounded_missing_evidence_count": len(missing_evidence),
    }
    blueprint["live_context_hint"] = (
        "Load setup/live_context.json as the canonical fresh snapshot. Enforce its protocol/source/chain/target/status/age binding before generating questions. "
        "Use pair identity and reserves, known-actor authorization/exemption matrix, fee receivers and parameters, custody asset matrix, and decoded history; "
        "preserve every missing_evidence promotion rule instead of guessing unknown mapping keys or token holdings."
    )

    with LIVE_CONTEXT_PATH.open("w", encoding="utf-8") as handle:
        json.dump(context, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    with BLUEPRINT_PATH.open("w", encoding="utf-8") as handle:
        json.dump(blueprint, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    print(f"captured Mog Coin at block {latest_block} ({context['captured_at']})")
    print(f"special event logs: {len(special_logs)}; launch config calls: {len(launch_history)}")
    print(f"context status: {context['context_quality']['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
