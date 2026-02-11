"""
x402 payment middleware for Agent402.

Gates premium endpoints behind USDC micropayments via Coinbase's x402 protocol.
"""

import logging
import re

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
from x402.http.facilitator_client_base import AuthHeaders, AuthProvider
from x402.http.middleware.fastapi import PaymentMiddlewareASGI
from x402.http.types import RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.server import x402ResourceServer

from config import Settings

logger = logging.getLogger(__name__)


class PaymentLoggingMiddleware(BaseHTTPMiddleware):
    """Logs successful x402 payments to Supabase after verification."""

    PREMIUM_PATH_PATTERNS = [
        re.compile(r"^/api/v1/trust/\d+(/risk)?$"),
        re.compile(r"^/api/v1/agents/trusted$"),
    ]

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)

        payment_header = (
            request.headers.get("payment-signature")
            or request.headers.get("x-payment")
        )

        if payment_header and 200 <= response.status_code < 300:
            path = request.url.path
            if any(p.match(path) for p in self.PREMIUM_PATH_PATTERNS):
                agent_id = None
                match = re.search(r"/trust/(\d+)", path)
                if match:
                    agent_id = int(match.group(1))

                try:
                    from services.payments import log_payment
                    from config import get_settings

                    settings = get_settings()
                    log_payment(
                        payer_address="x402-payer",
                        amount_usd=float(settings.x402_price_eval.replace("$", "")),
                        network=settings.x402_network,
                        http_method=request.method,
                        http_path=path,
                        agent_id_queried=agent_id,
                    )
                except Exception as e:
                    logger.error(f"Payment logging failed: {e}")

        return response


class CdpAuthProvider:
    """AuthProvider that generates CDP JWT headers for the mainnet facilitator."""

    def __init__(self, api_key_id: str, api_key_secret: str) -> None:
        self._api_key_id = api_key_id
        self._api_key_secret = api_key_secret

    def _headers_for(self, method: str, path: str) -> dict[str, str]:
        from cdp.auth import get_auth_headers, GetAuthHeadersOptions

        return get_auth_headers(
            GetAuthHeadersOptions(
                api_key_id=self._api_key_id,
                api_key_secret=self._api_key_secret,
                request_method=method,
                request_host="api.cdp.coinbase.com",
                request_path=path,
            )
        )

    def get_auth_headers(self) -> AuthHeaders:
        return AuthHeaders(
            verify=self._headers_for("POST", "/platform/v2/x402/verify"),
            settle=self._headers_for("POST", "/platform/v2/x402/settle"),
            supported=self._headers_for("GET", "/platform/v2/x402/supported"),
        )


def setup_x402_middleware(app: FastAPI, settings: Settings) -> None:
    """Register x402 payment middleware on premium endpoints."""

    if not settings.x402_pay_to:
        logger.warning("X402_PAY_TO not set — cannot enable x402 payments")
        return

    # Build auth provider for CDP mainnet facilitator
    auth_provider = None
    if settings.cdp_api_key_id and settings.cdp_api_key_secret:
        auth_provider = CdpAuthProvider(
            settings.cdp_api_key_id, settings.cdp_api_key_secret
        )
        logger.info("CDP API key configured for mainnet facilitator")
    else:
        logger.warning(
            "CDP_API_KEY_ID / CDP_API_KEY_SECRET not set — "
            "facilitator auth disabled (required for mainnet)"
        )

    facilitator = HTTPFacilitatorClient(
        FacilitatorConfig(
            url=settings.x402_facilitator_url,
            auth_provider=auth_provider,
        )
    )
    server = x402ResourceServer(facilitator)
    server.register(settings.x402_network, ExactEvmServerScheme())

    def _option(price: str) -> PaymentOption:
        return PaymentOption(
            scheme="exact",
            pay_to=settings.x402_pay_to,
            price=price,
            network=settings.x402_network,
        )

    routes: dict[str, RouteConfig] = {
        "GET /api/v1/trust/*": RouteConfig(
            accepts=[_option(settings.x402_price_eval)],
            description="Trust evaluation and risk assessment for an AI agent",
            mime_type="application/json",
            extensions={
                "bazaar": {
                    "info": {
                        "output": {
                            "type": "json",
                            "example": {
                                "agent_id": 42,
                                "composite_score": 87.3,
                                "tier": "platinum",
                                "recommendation": "TRUSTED",
                                "risk_flags": [],
                                "feedback_count": 156,
                            },
                        },
                    },
                },
            },
        ),
        "GET /api/v1/agents/trusted": RouteConfig(
            accepts=[_option(settings.x402_price_search)],
            description="Search for trusted agents by category, score, tier",
            mime_type="application/json",
            extensions={
                "bazaar": {
                    "info": {
                        "output": {
                            "type": "json",
                            "example": [
                                {
                                    "agent_id": 42,
                                    "name": "DeFi Agent",
                                    "composite_score": 87.3,
                                    "tier": "platinum",
                                    "category": "defi",
                                    "feedback_count": 156,
                                },
                            ],
                        },
                    },
                },
            },
        ),
    }

    # Inner middleware (logging) added first, outer (payment gate) added second
    app.add_middleware(PaymentLoggingMiddleware)
    app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)

    logger.info(
        f"x402 payments enabled — network={settings.x402_network} "
        f"pay_to={settings.x402_pay_to[:10]}... "
        f"facilitator={settings.x402_facilitator_url}"
    )
