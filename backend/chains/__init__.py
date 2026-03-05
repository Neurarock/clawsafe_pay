"""
chains — Multi-chain abstraction layer for ClawSafe Pay.

Supported chain families:
    evm      Ethereum & L2s  (Sepolia, Base, …)
    solana   Solana           (placeholder)
    bitcoin  Bitcoin          (placeholder)
    zcash    Zcash            (placeholder)
    cardano  Cardano          (placeholder)

Quick start::

    from chains import get_chain, list_chains

    # List all registered chains
    print(list_chains())               # ["base", "sepolia"]

    # Resolve the Sepolia implementation
    reg = get_chain("sepolia")
    cfg      = reg.config              # ChainConfig
    provider = reg.provider_cls(...)   # ChainProvider subclass
    builder  = reg.builder_cls()       # TxBuilder subclass
    signer   = reg.signer_cls()        # TxSigner subclass

Importing this package auto-registers all implemented chains.
"""

from chains.base import (                   # noqa: F401 – re-exported
    ChainConfig,
    ChainProvider,
    SignedTx,
    TxBuilder,
    TxSigner,
    UnsignedTx,
)
from chains.registry import (               # noqa: F401 – re-exported
    get_chain,
    get_config,
    is_registered,
    list_chains,
    register_chain,
)

# ── Auto-register implemented chains on package import ───────────────────────
import chains.evm.sepolia    # noqa: F401 – triggers registration
import chains.evm.base_l2    # noqa: F401 – triggers registration (placeholder)
