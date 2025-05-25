"""
Configuration management for Google Maps Reviews Scraper.
"""

import logging
from pathlib import Path
from typing import Dict, Any

import yaml

# Configure logging
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s")
log = logging.getLogger("scraper")

# Default configuration path
DEFAULT_CONFIG_PATH = Path("config.yaml")

# Default configuration - will be overridden by config file
DEFAULT_CONFIG = {
    "url": "https://www.google.com/maps/place//data=!4m4!3m3!1s0x89c25888bac5a51f:0xc6f812b99e2d60e1!9m1!1b1",
    "headless": True,
    "sort_by": "relevance",
    "stop_on_match": False,
    "overwrite_existing": False,
    "use_mongodb": False,
    "mongodb": {
        "uri": "mongodb://localhost:27017",
        "database": "reviews",
        "collection": "google_reviews"
    },
    "backup_to_json": True,
    "json_path": "google_reviews_2.json",
    "seen_ids_path": "google_reviews.ids",
    "convert_dates": True,
    "download_images": True,
    "image_dir": "review_images",
    "download_threads": 4,
    "store_local_paths": True,  # Option to control storing local image paths
    "replace_urls": False,  # Option to control URL replacement
    "custom_url_base": "https://mycustomurl.com",  # Base URL for replacement
    "custom_url_profiles": "/profiles2/",  # Path for profile images
    "custom_url_reviews": "/reviews2/",  # Path for review images
    "preserve_original_urls": True,  # Option to preserve original URLs
    "custom_params": {  # Custom parameters to add to each document
        "company": "Thaitours",  # Default example
        "source": "Google Maps"  # Default example
    }
}


def load_config(config_path: Path = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    """Load configuration from YAML file or use defaults"""
    config = DEFAULT_CONFIG.copy()

    if config_path.exists():
        try:
            with open(config_path, 'r') as f:
                user_config = yaml.safe_load(f)
                if user_config:
                    # Merge configs, with nested dictionary support
                    def deep_update(d, u):
                        for k, v in u.items():
                            if isinstance(v, dict) and k in d and isinstance(d[k], dict):
                                deep_update(d[k], v)
                            else:
                                d[k] = v

                    deep_update(config, user_config)
                    log.info(f"Loaded configuration from {config_path}")
        except Exception as e:
            log.error(f"Error loading config from {config_path}: {e}")
            log.info("Using default configuration")
    else:
        log.info(f"Config file {config_path} not found, using default configuration")
        # Create a default config file for future use
        with open(config_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False)
            log.info(f"Created default configuration file at {config_path}")

    return config
