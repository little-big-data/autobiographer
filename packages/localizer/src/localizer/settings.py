"""LocalizerSettings: configuration reader/writer for the localizer package.

Reads settings from ``~/.localizer/config.toml`` (TOML format) with support
for environment-variable overrides via the ``LOCALIZER_`` prefix.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


class LocalizerSettings:
    """Read and write localizer configuration from a TOML file.

    The config file is created on first write if it does not exist.
    Environment variable ``LOCALIZER_DB_PATH`` overrides the store path.
    Environment variable ``LOCALIZER_CONFIG_PATH`` overrides the config file path.

    Args:
        config_path: Path to the TOML config file. Defaults to
            ``~/.localizer/config.toml``, unless ``LOCALIZER_CONFIG_PATH``
            is set.
    """

    DEFAULT_CONFIG_DIR = Path.home() / ".localizer"
    DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.toml"
    DEFAULT_STORE_FILE = DEFAULT_CONFIG_DIR / "store.duckdb"

    def __init__(self, config_path: Path | None = None) -> None:
        # Allow env var override of config path (used by tests via LOCALIZER_CONFIG_PATH).
        env_config = os.environ.get("LOCALIZER_CONFIG_PATH")
        if config_path is not None:
            self._config_path = Path(config_path)
        elif env_config:
            self._config_path = Path(env_config)
        else:
            self._config_path = self.DEFAULT_CONFIG_FILE

    # ------------------------------------------------------------------
    # Store path
    # ------------------------------------------------------------------

    def get_store_path(self) -> Path:
        """Return the resolved DuckDB store path.

        Checks ``LOCALIZER_DB_PATH`` env var first; falls back to the default.

        Returns:
            Path to the DuckDB store file.
        """
        env_path = os.environ.get("LOCALIZER_DB_PATH")
        if env_path:
            return Path(env_path)
        return self.DEFAULT_STORE_FILE

    # ------------------------------------------------------------------
    # Config file read/write
    # ------------------------------------------------------------------

    def _load_config(self) -> dict[str, Any]:
        """Load the TOML config file, returning an empty dict if missing.

        Returns:
            Parsed TOML dict, or empty dict if the file does not exist.
        """
        if not self._config_path.exists():
            return {}
        try:
            import tomllib  # noqa: PLC0415 — stdlib in 3.11+; available in 3.9+ via tomli

            with self._config_path.open("rb") as fh:
                result: dict[str, Any] = tomllib.load(fh)
                return result
        except ImportError:
            # Python 3.9/3.10 — fall back to tomli if available, else parse manually.
            try:
                import tomli  # noqa: PLC0415

                with self._config_path.open("rb") as fh:
                    result2: dict[str, Any] = tomli.load(fh)
                    return result2
            except ImportError:
                return self._load_config_manual()

    def _load_config_manual(self) -> dict[str, Any]:
        """Minimal TOML parser for simple key = 'value' lines.

        Only handles top-level string assignments. Sufficient for the
        settings round-trip test.

        Returns:
            Dict of parsed key-value pairs.
        """
        result: dict[str, Any] = {}
        try:
            text = self._config_path.read_text(encoding="utf-8")
        except OSError:
            return result

        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                # Strip surrounding quotes if present.
                if (value.startswith('"') and value.endswith('"')) or (
                    value.startswith("'") and value.endswith("'")
                ):
                    value = value[1:-1]
                result[key] = value
        return result

    def _save_config(self, data: dict[str, Any]) -> None:
        """Write the config dict back to the TOML file.

        Args:
            data: Dict of key-value pairs to persist.
        """
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        for key, value in data.items():
            # Serialize all values as TOML strings.
            escaped = str(value).replace('"', '\\"')
            lines.append(f'{key} = "{escaped}"')
        self._config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Read a setting from the config file.

        Args:
            key: Setting key to look up.
            default: Value to return when the key is absent. Defaults to None.

        Returns:
            The stored value, or ``default`` if the key is not found.
        """
        data = self._load_config()
        return data.get(key, default)

    def set_setting(self, key: str, value: str) -> None:
        """Write a setting to the config file.

        Creates the config file if it does not exist.

        Args:
            key: Setting key.
            value: String value to store.
        """
        data = self._load_config()
        data[key] = value
        self._save_config(data)
