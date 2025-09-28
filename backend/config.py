"""Configuration management for brākTrād"""

from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, validator
import json


class Settings(BaseSettings):
    """Application settings with validation"""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        protected_namespaces=('settings_',)
    )
    
    # Database
    database_url: str = Field(
        default="sqlite+aiosqlite:///./braktrad.db",
        description="Database connection string"
    )
    redis_url: str = Field(
        default="redis://localhost:6379",
        description="Redis connection string"
    )
    
    # API Keys
    finviz_api_key: Optional[str] = Field(default=None, description="Finviz Elite API key")
    groq_api_key: Optional[str] = Field(default=None, description="Groq API key")
    openrouter_api_key: Optional[str] = Field(default=None, description="OpenRouter API key")
    
    # Finviz Configuration
    finviz_portfolio_numbers: List[int] = Field(
        default_factory=list,
        description="List of Finviz portfolio IDs"
    )
    
    # Security
    secret_key: str = Field(
        default="development-secret-key-change-in-production",
        description="Secret key for JWT"
    )
    algorithm: str = Field(default="HS256", description="JWT algorithm")
    access_token_expire_minutes: int = Field(default=30, description="Token expiry")
    
    # App Config
    environment: str = Field(default="development", description="Environment")
    debug: bool = Field(default=False, description="Debug mode")
    cors_origins: List[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:3000"],
        description="Allowed CORS origins"
    )
    
    # Rate Limiting
    finviz_rate_limit: int = Field(default=10, description="Requests per window")
    finviz_rate_window: int = Field(default=60, description="Window in seconds")
    model_rate_limit: int = Field(default=100, description="Model calls per window")
    model_rate_window: int = Field(default=60, description="Window in seconds")
    
    # Cache Configuration
    headline_cache_ttl: int = Field(default=300, description="Headlines cache TTL")
    sentiment_cache_ttl: int = Field(default=3600, description="Sentiment cache TTL")
    analytics_cache_ttl: int = Field(default=600, description="Analytics cache TTL")
    
    # Model Configuration
    available_groq_models: List[str] = Field(
        default_factory=lambda: [
            "llama-3.3-70b-versatile",
            "llama-3.2-90b-text-preview",
            "llama-3.2-11b-text-preview",
            "llama-3.2-3b-preview",
            "llama-3.2-1b-preview",
            "llama-3.1-70b-instant",
            "llama-3.1-8b-instant",
            "mixtral-8x7b-32768",
            "gemma2-9b-it",
            "gemma-7b-it",
            "llama3-70b-8192",
            "llama3-8b-8192",
            "llama3-groq-70b-8192-tool-use-preview",
            "llama3-groq-8b-8192-tool-use-preview",
            "whisper-large-v3"
        ],
        description="Available Groq models"
    )
    
    available_openrouter_models: List[str] = Field(
        default_factory=lambda: [
            # Free models (verified from OpenRouter - $0 input/output)
            "x-ai/grok-4-fast:free",
            "nvidia/nemotron-nano-9b-v2:free",
            "deepseek/deepseek-chat-v3.1:free",
            "openai/gpt-oss-120b:free",
            "openai/gpt-oss-20b:free",
            "z-ai/glm-4.5-air:free",
            "qwen/qwen3-coder:free",
            "moonshotai/kimi-k2:free",
            "cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
            "google/gemma-3n-e2b-it:free",
            "tencent/hunyuan-a13b-instruct:free",
            "tngtech/deepseek-r1t2-chimera:free",
            "mistralai/mistral-small-3.2-24b-instruct:free",
            "moonshotai/kimi-dev-72b:free",
            "deepseek/deepseek-r1-0528-qwen3-8b:free",
            "deepseek/deepseek-r1-0528:free",
            "mistralai/devstral-small-2505:free",
            "google/gemma-3n-e4b-it:free",
            "meta-llama/llama-3.3-8b-instruct:free",
            "qwen/qwen3-4b:free",
            "qwen/qwen3-30b-a3b:free",
            "qwen/qwen3-8b:free",
            "qwen/qwen3-14b:free",
            "qwen/qwen3-235b-a22b:free",
            "tngtech/deepseek-r1t-chimera:free",
            "microsoft/mai-ds-r1:free",
            "shisa-ai/shisa-v2-llama3.3-70b:free",
            "arliai/qwq-32b-arliai-rpr-v1:free",
            "agentica-org/deepcoder-14b-preview:free",
            "moonshotai/kimi-vl-a3b-thinking:free",
            "meta-llama/llama-4-maverick:free",
            "meta-llama/llama-4-scout:free",
            "qwen/qwen2.5-vl-32b-instruct:free",
            "deepseek/deepseek-chat-v3-0324:free",
            "mistralai/mistral-small-3.1-24b-instruct:free",
            "google/gemma-3-4b-it:free",
            "google/gemma-3-12b-it:free",
            "google/gemma-3-27b-it:free",
            "qwen/qwq-32b:free",
            "nousresearch/deephermes-3-llama-3-8b-preview:free",
            "cognitivecomputations/dolphin3.0-r1-mistral-24b:free",
            "cognitivecomputations/dolphin3.0-mistral-24b:free",
            "qwen/qwen2.5-vl-72b-instruct:free",
            "mistralai/mistral-small-24b-instruct-2501:free",
            "deepseek/deepseek-r1-distill-llama-70b:free",
            "deepseek/deepseek-r1:free",
            "google/gemini-2.0-flash-exp:free",
            "meta-llama/llama-3.3-70b-instruct:free",
            "qwen/qwen-2.5-coder-32b-instruct:free",
            "meta-llama/llama-3.2-3b-instruct:free",
            "qwen/qwen-2.5-72b-instruct:free",
            "meta-llama/llama-3.1-405b-instruct:free",
            "mistralai/mistral-nemo:free",
            "google/gemma-2-9b-it:free",
            "mistralai/mistral-7b-instruct:free",
            
            # Paid models (verified from OpenRouter)
            "meta-llama/llama-3.2-1b-instruct",
            "liquid/lfm-7b",
            "google/gemma-2-9b-it",
            "cognitivecomputations/dolphin3.0-r1-mistral-24b",
            "deepseek/deepseek-r1-0528-qwen3-8b",
            "meta-llama/llama-3.3-70b-instruct",
            "agentica-org/deepcoder-14b-preview",
            "liquid/lfm-3b",
            "meta-llama/llama-3.2-3b-instruct",
            "meta-llama/llama-3.1-8b-instruct",
            "google/gemma-3n-e4b-it",
            "mistralai/mistral-nemo",
            "meta-llama/llama-guard-3-8b",
            "arliai/qwq-32b-arliai-rpr-v1",
            "moonshotai/kimi-vl-a3b-thinking",
            "nousresearch/hermes-2-pro-llama-3-8b",
            "tencent/hunyuan-a13b-instruct",
            "mistralai/mistral-7b-instruct",
            "mistralai/mistral-7b-instruct-v0.3",
            "meta-llama/llama-3-8b-instruct",
            "cognitivecomputations/dolphin3.0-mistral-24b",
            "opengvlab/internvl3-78b",
            "qwen/qwen3-32b",
            "deepseek/deepseek-r1-distill-llama-70b",
            "deepseek/deepseek-r1-distill-llama-8b",
            "mistralai/ministral-3b",
            "openai/gpt-oss-20b",
            "sao10k/l3-lunaris-8b",
            "google/gemma-3-4b-it",
            "thudm/glm-4.1v-9b-thinking",
            "qwen/qwen3-8b",
            "amazon/nova-micro-v1",
            "qwen/qwen-2.5-7b-instruct",
            "cohere/command-r7b-12-2024",
            "google/gemini-flash-1.5-8b",
            "meta-llama/llama-3.2-11b-vision-instruct",
            "mistralai/devstral-small-2505",
            "thudm/glm-z1-32b",
            "shisa-ai/shisa-v2-llama3.3-70b",
            "qwen/qwen2.5-vl-32b-instruct",
            "google/gemma-3-12b-it",
            "mistralai/mistral-small-3.1-24b-instruct",
            "mistralai/mistral-small-24b-instruct-2501",
            "nvidia/nemotron-nano-9b-v2",
            "thedrummer/skyfall-36b-v2",
            "microsoft/phi-4-multimodal-instruct",
            "gryphe/mythomax-l2-13b",
            "qwen/qwen-turbo",
            "microsoft/phi-4",
            "openai/gpt-oss-120b",
            "qwen/qwen-2.5-coder-32b-instruct",
            "qwen/qwen3-30b-a3b",
            "qwen/qwen3-14b",
            "amazon/nova-lite-v1",
            "openai/gpt-5-nano",
            "mistralai/mistral-small-3.2-24b-instruct",
            "google/gemma-3-27b-it",
            "qwen/qwen-2.5-72b-instruct",
            "baidu/ernie-4.5-21b-a3b",
            "qwen/qwen3-coder-30b-a3b-instruct",
            "qwen/qwen3-30b-a3b-instruct-2507",
            "mistralai/devstral-small",
            "qwen/qwen2.5-vl-72b-instruct",
            "microsoft/phi-4-reasoning-plus",
            "google/gemini-2.0-flash-lite-001",
            "google/gemini-flash-1.5",
            "qwen/qwen3-30b-a3b-thinking-2507",
            "z-ai/glm-4-32b",
            "qwen/qwen3-235b-a22b-2507",
            "meta-llama/llama-4-scout",
            "mistralai/ministral-8b",
            "mistralai/pixtral-12b",
            "microsoft/phi-3.5-mini-128k-instruct",
            "microsoft/phi-3-mini-128k-instruct",
            "bytedance/ui-tars-1.5-7b",
            "allenai/molmo-7b-d",
            "meta-llama/llama-3.1-70b-instruct",
            "mistralai/mistral-7b-instruct-v0.1",
            "alibaba/tongyi-deepresearch-30b-a3b",
            "qwen/qwen3-235b-a22b-thinking-2507",
            "arcee-ai/afm-4.5b",
            "google/gemini-2.5-flash-lite",
            "google/gemini-2.5-flash-lite-preview-06-17",
            "openai/gpt-4.1-nano",
            "google/gemini-2.0-flash-001",
            "nousresearch/hermes-4-70b",
            "neversleep/llama-3.1-lumimaid-8b",
            "nousresearch/hermes-3-llama-3.1-70b",
            "deepseek/deepseek-r1-distill-qwen-14b",
            "qwen/qwen3-next-80b-a3b-thinking",
            "qwen/qwen3-next-80b-a3b-instruct",
            "meituan/longcat-flash-chat",
            "nousresearch/deephermes-3-mistral-24b-preview",
            "qwen/qwq-32b",
            "baidu/ernie-4.5-vl-28b-a3b",
            "arcee-ai/spotlight",
            "meta-llama/llama-guard-4-12b",
            "meta-llama/llama-4-maverick",
            "cohere/command-r-08-2024",
            "openai/gpt-4o-mini-2024-07-18",
            "openai/gpt-4o-mini",
            "thedrummer/rocinante-12b",
            "aion-labs/aion-rp-llama-3.1-8b",
            "qwen/qwq-32b-preview",
            "qwen/qwen-2.5-vl-7b-instruct",
            "meta-llama/llama-guard-2-8b",
            "bytedance/seed-oss-36b-instruct",
            "z-ai/glm-4.5-air",
            "qwen/qwen3-235b-a22b",
            "deepcogito/cogito-v2-preview-llama-109b-moe",
            "ai21/jamba-mini-1.7",
            "mistralai/mistral-saba",
            "mistralai/mistral-small",
            "qwen/qwen-vl-plus",
            "mistralai/mistral-tiny",
            "deepseek/deepseek-r1-distill-qwen-32b",
            "minimax/minimax-01",
            "qwen/qwen3-coder",
            "meta-llama/llama-3-70b-instruct",
            "nousresearch/hermes-4-405b",
            "deepseek/deepseek-chat-v3.1",
            "deepseek/deepseek-v3.1-base",
            "tngtech/deepseek-r1t-chimera",
            "microsoft/mai-ds-r1",
            "deepseek/deepseek-chat-v3-0324",
            "deepseek/deepseek-chat",
            "x-ai/grok-code-fast-1",
            "inception/mercury",
            "x-ai/grok-3-mini",
            "inception/mercury-coder",
            "x-ai/grok-3-mini-beta",
            "anthropic/claude-3-haiku",
            "moonshotai/kimi-k2",
            "mistralai/codestral-2508",
            "baidu/ernie-4.5-300b-a47b",
            "mistralai/codestral-2501",
            "meta-llama/llama-3.2-90b-vision-instruct",
            "moonshotai/kimi-dev-72b",
            "thedrummer/unslopnemo-12b",
            "mistralai/mixtral-8x7b-instruct",
            "qwen/qwen3-coder-flash",
            "openai/gpt-5-mini",
            "minimax/minimax-m1",
            "thedrummer/anubis-70b-v1.1",
            "undi95/remm-slerp-l2-13b",
            "qwen/qwen-plus-2025-07-28",
            "qwen/qwen-plus",
            "microsoft/wizardlm-2-8x22b",
            "moonshotai/kimi-k2-0905",
            "baidu/ernie-4.5-vl-424b-a47b",
            "google/gemini-2.5-flash-image-preview",
            "google/gemini-2.5-flash",
            "openai/gpt-4.1-mini",
            "z-ai/glm-4.5",
            "deepseek/deepseek-r1-0528",
            "arcee-ai/coder-large",
            "mistralai/mistral-medium-3.1",
            "mistralai/devstral-medium",
            "mistralai/mistral-medium-3",
            "thedrummer/anubis-pro-105b-v1",
            "deepseek/deepseek-r1",
            "mistralai/magistral-small-2506",
            "cohere/command-r",
            "cohere/command-r-03-2024",
            "openai/gpt-3.5-turbo",
            "z-ai/glm-4.5v",
            "deepseek/deepseek-prover-v2",
            "qwen/qwen-plus-2025-07-28:thinking",
            "openai/gpt-4o-mini-search-preview"
        ],
        description="Available OpenRouter models (verified from OpenRouter catalog)"
    )
    
    selected_models: List[str] = Field(
        default_factory=list,
        description="User-selected models for current run"
    )
    
    # Processing Configuration
    dedupe_threshold: float = Field(
        default=0.85,
        description="Similarity threshold for deduplication"
    )
    max_headline_age_hours: int = Field(
        default=24,
        description="Maximum age of headlines to process"
    )
    
    @validator("finviz_portfolio_numbers", pre=True)
    def parse_portfolio_numbers(cls, v):
        """Parse portfolio numbers from string if needed"""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except:
                return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v
    
    @validator("cors_origins", pre=True)
    def parse_cors_origins(cls, v):
        """Parse CORS origins from string if needed"""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except:
                return [x.strip() for x in v.split(",") if x.strip()]
        return v
    
    @validator("selected_models", pre=True)
    def parse_selected_models(cls, v):
        """Parse selected models from string if needed"""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except:
                return [x.strip() for x in v.split(",") if x.strip()]
        return v
    
    @property
    def is_production(self) -> bool:
        """Check if running in production"""
        return self.environment.lower() == "production"
    
    @property
    def is_development(self) -> bool:
        """Check if running in development"""
        return self.environment.lower() == "development"


# Global settings instance
settings = Settings()
