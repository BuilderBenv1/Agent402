from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    # Supabase (Agent402's own database)
    supabase_url: str = ""
    supabase_key: str = ""

    # x402 Payment Protocol
    x402_pay_to: str = ""  # Wallet address to receive USDC payments
    x402_network: str = "eip155:8453"  # Base Mainnet
    x402_facilitator_url: str = "https://api.cdp.coinbase.com/platform/v2/x402"
    x402_price_eval: str = "$0.01"  # Trust evaluation
    x402_price_search: str = "$0.01"  # Agent search
    x402_price_stats: str = "$0.005"  # Network stats

    # CDP API credentials (required for mainnet facilitator)
    cdp_api_key_id: str = ""
    cdp_api_key_secret: str = ""

    # Wallet for on-chain operations (signing, self-registration)
    private_key: str = Field(
        default="",
        validation_alias=AliasChoices("PRIVATE_KEY", "ORACLE_PRIVATE_KEY"),
    )

    # Oracle identity
    oracle_name: str = "Agent402 Trust Oracle"
    oracle_description: str = (
        "Pay-per-use reputation oracle for AI agents. "
        "Trust evaluations, risk assessments, and network analytics "
        "via x402 USDC micropayments."
    )
    oracle_version: str = "1.0.0"

    # Server
    host: str = "0.0.0.0"
    port: int = 8402
    base_url: str = "https://agent402.io"
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        origins = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        for prod in [
            "https://agent402.io",
            "https://www.agent402.io",
            "https://api.agent402.io",
            "https://agent402.sh",
            "https://www.agent402.sh",
            "https://api.agent402.sh",
        ]:
            if prod not in origins:
                origins.append(prod)
        return origins

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


@lru_cache()
def get_settings() -> Settings:
    return Settings()
