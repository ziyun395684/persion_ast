from urllib.parse import quote_plus

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    debug: bool = False
    host: str = "127.0.0.1"
    port: int = 8111
    auth_secret: str = Field(
        "change-me-in-production",
        validation_alias=AliasChoices("AUTH_SECRET", "APP_AUTH_SECRET"),
    )
    auth_token_ttl_sec: int = Field(
        86400,
        validation_alias=AliasChoices("AUTH_TOKEN_TTL_SEC", "APP_AUTH_TOKEN_TTL_SEC"),
    )
    auth_login_max_attempts: int = Field(
        5,
        validation_alias=AliasChoices("AUTH_LOGIN_MAX_ATTEMPTS", "APP_AUTH_LOGIN_MAX_ATTEMPTS"),
    )
    auth_login_window_sec: int = Field(
        300,
        validation_alias=AliasChoices("AUTH_LOGIN_WINDOW_SEC", "APP_AUTH_LOGIN_WINDOW_SEC"),
    )
    database_url: str | None = Field(
        None,
        validation_alias=AliasChoices("APP_DATABASE_URL", "DATABASE_URL"),
    )
    db_host: str | None = Field(None, validation_alias=AliasChoices("DB_HOST", "APP_DB_HOST"))
    db_port: int = Field(3306, validation_alias=AliasChoices("DB_PORT", "APP_DB_PORT"))
    db_user: str | None = Field(None, validation_alias=AliasChoices("DB_USER", "APP_DB_USER"))
    db_password: str | None = Field(None, validation_alias=AliasChoices("DB_PASSWORD", "APP_DB_PASSWORD"))
    db_name: str | None = Field(None, validation_alias=AliasChoices("DB_NAME", "APP_DB_NAME"))
    hindsight_url: str = Field(
        "http://127.0.0.1:8888",
        validation_alias=AliasChoices("HINDSIGHT_URL", "APP_HINDSIGHT_URL"),
    )
    hindsight_api_key: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "HINDSIGHT_API_KEY", "APP_HINDSIGHT_API_KEY"
        ),
    )
    hindsight_bank_id: str = Field(
        "main",
        validation_alias=AliasChoices("HINDSIGHT_BANK_ID", "APP_HINDSIGHT_BANK_ID"),
    )
    hindsight_enabled: bool = Field(
        False,
        validation_alias=AliasChoices("HINDSIGHT_ENABLED", "APP_HINDSIGHT_ENABLED"),
    )
    hindsight_recall_enabled: bool = Field(
        False,
        validation_alias=AliasChoices(
            "HINDSIGHT_RECALL_ENABLED", "APP_HINDSIGHT_RECALL_ENABLED"
        ),
    )
    hindsight_timeout_sec: int = Field(
        5,
        validation_alias=AliasChoices(
            "HINDSIGHT_TIMEOUT_SEC", "APP_HINDSIGHT_TIMEOUT_SEC"
        ),
    )
    llm_mode: str = Field("ollama", validation_alias=AliasChoices("LLM_MODE", "APP_LLM_MODE"))
    ollama_base_url: str = Field(
        "http://127.0.0.1:11434",
        validation_alias=AliasChoices("LLM_OLLAMA_BASE", "APP_OLLAMA_BASE_URL"),
    )
    main_model: str = Field(
        "qwen2.5:14b",
        validation_alias=AliasChoices("QWEN_DEFAULT_MODEL", "LLM_OLLAMA_CHAT_MODEL", "APP_MAIN_MODEL"),
    )
    qwen_base_url: str = Field(
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        validation_alias=AliasChoices("QWEN_BASE_URL", "APP_QWEN_BASE_URL"),
    )
    qwen_api_key: str | None = Field(
        None,
        validation_alias=AliasChoices("MY_DASHSCOPE_API_KEY", "APP_QWEN_API_KEY"),
    )
    web_query_api_key: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "WEB_QUERY_API_KEY", "DOUBAO_SEARCH_API_KEY", "APP_WEB_QUERY_API_KEY"
        ),
    )
    web_query_endpoint: str = Field(
        "",
        validation_alias=AliasChoices(
            "DOUBAO_SEARCH_ENDPOINT", "WEB_QUERY_ENDPOINT", "APP_WEB_QUERY_ENDPOINT"
        ),
    )
    web_query_api_version: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "DOUBAO_SEARCH_API_VERSION",
            "WEB_QUERY_API_VERSION",
            "APP_WEB_QUERY_API_VERSION",
        ),
    )
    web_query_timeout: int = Field(
        15,
        validation_alias=AliasChoices("WEB_QUERY_TIMEOUT", "APP_WEB_QUERY_TIMEOUT"),
    )
    small_model: str = Field(
        "qwen2.5:7b",
        validation_alias=AliasChoices("QWEN_DEFAULT_MODEL", "LLM_FALLBACK_CHAT_MODEL", "APP_SMALL_MODEL"),
    )
    milvus_uri: str = Field("http://127.0.0.1:19530", validation_alias=AliasChoices("MILVUS_URI", "APP_MILVUS_URI"))
    milvus_token: str | None = Field(None, validation_alias=AliasChoices("MILVUS_TOKEN", "APP_MILVUS_TOKEN"))
    milvus_user: str | None = Field(None, validation_alias=AliasChoices("MILVUS_USER", "APP_MILVUS_USER"))
    milvus_password: str | None = Field(None, validation_alias=AliasChoices("MILVUS_PASSWORD", "APP_MILVUS_PASSWORD"))
    milvus_db: str = Field("default", validation_alias=AliasChoices("MILVUS_DB", "APP_MILVUS_DB"))
    milvus_timeout: int = Field(30, validation_alias=AliasChoices("MILVUS_TIMEOUT", "APP_MILVUS_TIMEOUT"))

    short_window_turns: int = 8
    short_window_messages: int = 16

    summary_trigger_queue: int = 20
    summary_max_tokens: int = 400
    summary_target_chars: int = 300
    summary_min_interval_min: int = 30
    summary_max_output_tokens: int = 600

    reflection_interval_turns: int = 20
    snapshot_hard_limit_tokens: int = 300
    snapshot_decay_days: int = 14
    snapshot_decay_factor: float = 0.5
    snapshot_hit_boost: float = 0.1
    snapshot_weight_max: float = 1.0
    snapshot_drop_weight: float = 0.2
    reflection_max_output_tokens: int = 512

    recall_top_k: int = 3
    recall_min_score: float = 0.65
    importance_weight: dict[str, float] = Field(
        default_factory=lambda: {"high": 1.0, "mid": 0.7, "low": 0.4}
    )
    embedding_model: str = Field(
        "bge-small-zh",
        validation_alias=AliasChoices("LLM_OLLAMA_EMBED_MODEL", "LLM_API_EMBED_MODEL", "APP_EMBEDDING_MODEL"),
    )
    embedding_dim: int = Field(512, validation_alias=AliasChoices("LLM_EMBED_DIMENSIONS", "APP_EMBEDDING_DIM"))
    extract_flush_timeout_sec: int = 8
    extract_polling_interval_sec: int = 2
    extract_max_output_tokens: int = 256
    intent_max_output_tokens: int = 256
    laya_enabled: bool = Field(False, validation_alias=AliasChoices("LAYA_ENABLED", "APP_LAYA_ENABLED"))
    laya_model: str = Field(
        "convaiinnovations/laya",
        validation_alias=AliasChoices("LAYA_MODEL", "APP_LAYA_MODEL"),
    )
    laya_min_confidence: float = Field(
        0.80,
        validation_alias=AliasChoices("LAYA_MIN_CONFIDENCE", "APP_LAYA_MIN_CONFIDENCE"),
    )
    laya_device: str = Field(
        "cpu",
        validation_alias=AliasChoices("LAYA_DEVICE", "APP_LAYA_DEVICE"),
    )
    event_text_max_chars: int = 200
    vector_retry_interval_sec: int = 30
    vector_retry_queue_max: int = 20
    forget_min_score: float = 0.70

    asr_model: str = Field("sensevoice-small", validation_alias=AliasChoices("ASR_MODEL", "APP_ASR_MODEL"))
    tts_voice: str = Field("zh-CN-XiaoxiaoNeural", validation_alias=AliasChoices("TTS_VOICE", "APP_TTS_VOICE"))
    tts_rate: str = Field("+0%", validation_alias=AliasChoices("TTS_RATE", "APP_TTS_RATE"))
    tts_max_chars: int = Field(500, validation_alias=AliasChoices("TTS_MAX_CHARS", "APP_TTS_MAX_CHARS"))
    volc_api_key: str | None = Field(None, validation_alias=AliasChoices("VOLC_API_KEY", "APP_VOLC_API_KEY"))
    volc_cluster: str | None = Field(None, validation_alias=AliasChoices("VOLC_CLUSTER", "APP_VOLC_CLUSTER"))
    volc_voice: str | None = Field(None, validation_alias=AliasChoices("VOLC_VOICE", "APP_VOLC_VOICE"))
    asr_ws_url: str = Field(
        "wss://openspeech.bytedance.com/api/v2/asr",
        validation_alias=AliasChoices("ASR_WS_URL", "APP_ASR_WS_URL"),
    )
    tts_ws_url: str = Field(
        "wss://openspeech.bytedance.com/api/v1/tts/ws_binary",
        validation_alias=AliasChoices("TTS_WS_URL", "APP_TTS_WS_URL"),
    )
    voice_sample_rate: int = Field(16000, validation_alias=AliasChoices("VOICE_SAMPLE_RATE", "APP_VOICE_SAMPLE_RATE"))
    voice_channels: int = Field(1, validation_alias=AliasChoices("VOICE_CHANNELS", "APP_VOICE_CHANNELS"))
    voice_bits: int = Field(16, validation_alias=AliasChoices("VOICE_BITS", "APP_VOICE_BITS"))
    voice_timeout_sec: int = Field(30, validation_alias=AliasChoices("VOICE_TIMEOUT_SEC", "APP_VOICE_TIMEOUT_SEC"))

    main_model_max_tokens: int = 512
    polish_model_max_tokens: int = 256
    stream_chunk_chars: int = 4
    stream_chunk_delay_ms: int = 35
    model_timeout_sec: int = Field(30, validation_alias=AliasChoices("LLM_TIMEOUT", "APP_MODEL_TIMEOUT_SEC"))
    small_task_semaphore: int = 1
    temperature: dict[str, float] = Field(
        default_factory=lambda: {
            "main_chat": 0.8,
            "polish": 0.7,
            "classify": 0.0,
            "summary": 0.0,
            "reflection": 0.0,
            "extract": 0.0,
            "style_switch_confirm": 0.8,
        }
    )

    consecutive_task_nudge: int = 3
    system_token_limit: int = 2000
    system_summary_truncate_chars: int = 300

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="APP_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    @model_validator(mode="after")
    def resolve_database_url(self):
        if self.database_url:
            return self
        if all((self.db_host, self.db_user, self.db_name)):
            user = quote_plus(self.db_user or "")
            password = quote_plus(self.db_password or "")
            host = self.db_host or ""
            self.database_url = (
                f"mysql+pymysql://{user}:{password}@{host}:{self.db_port}/{self.db_name}"
            )
        else:
            self.database_url = "sqlite:///./data.db"
        return self


CFG = Settings()
