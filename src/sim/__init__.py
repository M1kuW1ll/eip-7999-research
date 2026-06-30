"""Synthetic EIP-7999 bandwidth simulator components."""

from .config import (
    BandwidthConfig,
    ExecutionStateConfig,
    SimulatorConfig,
    SyntheticConfig,
    load_config,
)
from .replay import replay
from .rpc_bal import BAL_SEMANTICS, build_rpc_bal_for_block, build_rpc_bal_from_traces
from .rpc_authorizations import (
    fetch_authorization_data_for_blocks,
    query_xatu_type4_transactions,
)
from .rpc_access_lists import fetch_access_list_data_for_blocks
from .rpc_state_growth import (
    summarize_rpc_state_growth_for_block,
    summarize_rpc_state_growth_for_blocks,
    summarize_rpc_state_growth_from_traces,
)
from .synthetic import BlockDemand, generate_synthetic_blocks
from .xatu_calldata import query_xatu_calldata_by_block
from .xatu_state_growth import query_xatu_state_growth_by_block

__all__ = [
    "BandwidthConfig",
    "BAL_SEMANTICS",
    "BlockDemand",
    "ExecutionStateConfig",
    "SimulatorConfig",
    "SyntheticConfig",
    "build_rpc_bal_for_block",
    "build_rpc_bal_from_traces",
    "fetch_access_list_data_for_blocks",
    "fetch_authorization_data_for_blocks",
    "generate_synthetic_blocks",
    "load_config",
    "query_xatu_calldata_by_block",
    "query_xatu_type4_transactions",
    "query_xatu_state_growth_by_block",
    "replay",
    "summarize_rpc_state_growth_for_block",
    "summarize_rpc_state_growth_for_blocks",
    "summarize_rpc_state_growth_from_traces",
]
