import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    mhz19b_device: str
    sps30_device: str
    i2c_bus: int

    sample_interval_s: float
    mhz19b_warmup_s: float

    buffer_db_path: str
    server_url: str
    post_batch_size: int
    post_timeout_s: float
    backoff_initial_s: float
    backoff_max_s: float


def load() -> Config:
    return Config(
        mhz19b_device     = os.environ.get("AIRMON_MHZ19B_DEVICE", "/dev/ttyAMA0"),
        sps30_device      = os.environ.get("AIRMON_SPS30_DEVICE",  "/dev/ttyAMA3"),
        i2c_bus           = int(os.environ.get("AIRMON_I2C_BUS", "1")),
        sample_interval_s = float(os.environ.get("AIRMON_SAMPLE_INTERVAL_S", "5")),
        mhz19b_warmup_s   = float(os.environ.get("AIRMON_MHZ19B_WARMUP_S", "180")),
        buffer_db_path    = os.environ.get("AIRMON_BUFFER_DB", os.path.expanduser("~/.local/state/airmon/buffer.db")),
        server_url        = os.environ.get("AIRMON_SERVER_URL", "http://127.0.0.1:8000/api"),
        post_batch_size   = int(os.environ.get("AIRMON_POST_BATCH_SIZE", "50")),
        post_timeout_s    = float(os.environ.get("AIRMON_POST_TIMEOUT_S", "10")),
        backoff_initial_s = float(os.environ.get("AIRMON_BACKOFF_INITIAL_S", "2")),
        backoff_max_s     = float(os.environ.get("AIRMON_BACKOFF_MAX_S", "120")),
    )
