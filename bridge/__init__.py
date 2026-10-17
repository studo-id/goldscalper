"""MT5 HTTP bridge — thin execution/quote proxy for the Windows MT5 host.

The Linux bot container cannot talk to MetaTrader5 directly, so this package
runs on the Windows machine that hosts the MT5 terminal and exposes a minimal
HTTP surface consumed by :class:`core.mt5_connector.BridgeMT5Client`.

Contract (must match the client):

    GET  /health                    -> {"status", "connected", "server"}
    GET  /tick?symbol=              -> {"time", "bid", "ask"}
    GET  /rates?symbol&timeframe&start&end      -> {"candles": [...]}
    POST /order   (OrderPayload)    -> OrderResult dict
    GET  /positions?symbol=         -> {"positions": [...]}
    POST /close   {ticket, price, volume}       -> OrderResult dict
    POST /modify  {ticket, sl, tp}              -> OrderResult dict

Auth: ``Authorization: Bearer <BRIDGE_TOKEN>`` on every endpoint except
``/health``.
"""

from bridge.app import create_bridge_app

__all__ = ["create_bridge_app"]
