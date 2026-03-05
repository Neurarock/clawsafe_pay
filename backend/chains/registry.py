"""
chains.registry — Central registry for chain implementations.

Usage::

    from chains import get_chain, list_chains

    cfg, provider_cls, builder_cls, signer_cls = get_chain("sepolia")

Chain packages register themselves by calling ``register_chain()`` at
import time (in their ``__init__.py``).
"""

from __future__ import annotations

import logging
from typing import Type

from chains.base import ChainConfig, ChainProvider, TxBuilder, TxSigner

logger = logging.getLogger("chains.registry")


class ChainRegistration:
    """Bundle of classes that define a chain implementation."""

    __slots__ = ("config", "provider_cls", "builder_cls", "signer_cls")

    def __init__(
        self,
        config: ChainConfig,
        provider_cls: Type[ChainProvider],
        builder_cls: Type[TxBuilder],
        signer_cls: Type[TxSigner],
    ):
        self.config = config
        self.provider_cls = provider_cls
        self.builder_cls = builder_cls
        self.signer_cls = signer_cls


# ── Private registry store ───────────────────────────────────────────────────

_registry: dict[str, ChainRegistration] = {}


# ── Public API ───────────────────────────────────────────────────────────────


def register_chain(
    config: ChainConfig,
    provider_cls: Type[ChainProvider],
    builder_cls: Type[TxBuilder],
    signer_cls: Type[TxSigner],
) -> None:
    """
    Register a chain implementation.  Call this from a chain package's
    ``__init__.py`` so it self-registers on import.
    """
    cid = config.chain_id
    if cid in _registry:
        logger.warning("Chain %r is already registered — overwriting", cid)
    _registry[cid] = ChainRegistration(config, provider_cls, builder_cls, signer_cls)
    logger.debug("Registered chain: %s (%s)", cid, config.display_name)

    # Also add to SUPPORTED_CHAINS in transaction_builder models (backward compat)
    try:
        from transaction_builder.models import SUPPORTED_CHAINS
        SUPPORTED_CHAINS.add(cid)
    except ImportError:
        pass


def get_chain(chain_id: str) -> ChainRegistration:
    """
    Look up a registered chain by its slug.

    Raises ``KeyError`` if the chain has not been registered.
    """
    if chain_id not in _registry:
        available = ", ".join(sorted(_registry)) or "(none)"
        raise KeyError(
            f"Chain {chain_id!r} is not registered. Available: {available}"
        )
    return _registry[chain_id]


def list_chains() -> list[str]:
    """Return sorted list of registered chain IDs."""
    return sorted(_registry)


def get_config(chain_id: str) -> ChainConfig:
    """Convenience: get just the ChainConfig for a chain."""
    return get_chain(chain_id).config


def is_registered(chain_id: str) -> bool:
    """Return True if *chain_id* is registered."""
    return chain_id in _registry
