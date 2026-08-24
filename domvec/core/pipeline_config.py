import os
from dataclasses import dataclass

@dataclass
class PipelineConfig:
    # Scanner (scanner.py)
    scanner_max_scrolls: int = 300   # was 60; allow longer infinite-scroll pages
    scanner_no_change_limit: int = 3          # was 1 – allow a few quiet scrolls before stopping
    scanner_settle_timeout: float = 1.0
    scanner_settle_stable_for: float = 0.25
    scanner_poll_interval: float = 0.05
    scanner_scroll_step_fraction: float = 0.6
    scanner_bottom_sentinel_retries: int = 2  # number of extra bottom-jump retries after first

    # Verification gate (mapper.py / chunk_absorber.py)
    stream_min_new_nodes: int = 50
    absorb_new_node_delta: int = 80
    absorb_min_interval_s: float = 1.5
    stability_threshold: int = 2

    @property
    def absorber_stability_threshold(self) -> int:
        return self.stability_threshold

    # Pipeline queues (pipeline_runner.py)
    queue_maxsize: int = 128          # increased from 32; live delta batches need headroom
    queue_put_timeout_s: float = 0.5  # blocking-put timeout before dropping
    stats_emit_interval_s: float = 0.4
    log_coalesce_interval_s: float = 0.05
    pipeline_tfidf_join_timeout_s: float = 120.0
    pipeline_stream_join_timeout_s: float = 300.0  # increased for large kuzu persist batches

    # TF-IDF (global_tfidf_store.py)
    tfidf_min_query_df: int = 3
    tfidf_svd_components: int = 256
    tfidf_svd_recompute_every: int = 1000

    # Bottom-up chunker (bottom_up_chunker.py)
    hard_char_limit: int = 2048          # max prose chars per chunk (≈512 tokens)
    min_char_limit: int = 40             # drop trivial ×1 chunks below this budget (e.g. short nav links)
    strict_hash_match: bool = True      # require identical content_hash across pattern members

    # Live chunking toggle – when False, the bottom‑up chunker runs once
    # after the full DOM is captured, not on every scroll delta.
    live_chunking: str = "js"

    def __post_init__(self):
        if "WFH_STRICT_HASH_MATCH" in os.environ:
            self.strict_hash_match = os.environ["WFH_STRICT_HASH_MATCH"].lower() in ("1", "true", "yes")

    @classmethod
    def default(cls) -> "PipelineConfig":
        return cls()

    @classmethod
    def from_env(cls) -> "PipelineConfig":
        return cls()

_config_instance = PipelineConfig.default()

def get_config() -> PipelineConfig:
    return _config_instance