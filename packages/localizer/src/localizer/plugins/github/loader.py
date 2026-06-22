"""GitHub source plugin for the localizer package."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

import requests

from localizer.plugins import register
from localizer.plugins.base import FetchMode, OutputTable, SourcePlugin

GITHUB_API_BASE = "https://api.github.com"


@register
class GitHubPlugin(SourcePlugin):
    """Fetch GitHub commit history via the GitHub REST API.

    Credentials are read from environment variables:
    - ``LOCALIZER_GITHUB_TOKEN``
    - ``LOCALIZER_GITHUB_USERNAME``

    Args:
        repos: Optional list of ``owner/repo`` strings to fetch commits from.
               When None, the plugin discovers repos from the authenticated user.
    """

    PLUGIN_ID = "github"
    DISPLAY_NAME = "GitHub"
    FETCH_MODE = FetchMode.API
    OUTPUT_TABLES = [OutputTable.EVENTS]

    def __init__(self, repos: list[str] | None = None) -> None:
        """Initialise the plugin with an optional repo list.

        Args:
            repos: List of ``owner/repo`` full names. When None, the plugin
                   will derive repos from the authenticated user.
        """
        self._repos = repos or []

    def get_config_fields(self) -> list[dict[str, Any]]:
        """Return empty list — this plugin is env-var-driven.

        Returns:
            Empty list.
        """
        return []

    def get_fetch_env_vars(self) -> list[dict[str, str]]:
        """Return env vars required to fetch GitHub data.

        Returns:
            List of env var descriptor dicts.
        """
        return [
            {
                "var": "LOCALIZER_GITHUB_TOKEN",
                "description": "GitHub personal access token",
            },
            {
                "var": "LOCALIZER_GITHUB_USERNAME",
                "description": "GitHub username to fetch activity for",
            },
        ]

    def fetch_records(
        self,
        since: int | None = None,
        progress_cb: Any | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield normalized event dicts fetched from the GitHub REST API.

        Args:
            since: Optional Unix timestamp; yield only records newer than this.
            progress_cb: Optional callback invoked with ``(current, total)``
                for progress reporting.

        Yields:
            Dicts with keys: ``source_id``, ``timestamp``, ``label``,
            ``sublabel``, ``category``, ``raw_json``, ``fetched_at``.

        Raises:
            EnvironmentError: If required env vars are not set.
            requests.exceptions.HTTPError: On non-2xx responses.
        """
        token = os.environ.get("LOCALIZER_GITHUB_TOKEN")
        if not token:
            raise OSError("LOCALIZER_GITHUB_TOKEN environment variable is not set.")

        username = os.environ.get("LOCALIZER_GITHUB_USERNAME")
        if not username:
            raise OSError("LOCALIZER_GITHUB_USERNAME environment variable is not set.")

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        repos = self._repos if self._repos else [f"{username}/{username}"]

        fetched_at = int(time.time())

        for repo_full_name in repos:
            url = f"{GITHUB_API_BASE}/repos/{repo_full_name}/commits"
            params: dict[str, Any] = {"per_page": 100}
            if since is not None:
                # GitHub API accepts ISO 8601 for the `since` parameter
                since_dt = datetime.fromtimestamp(since, tz=timezone.utc)
                params["since"] = since_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

            response = requests.get(
                url,
                headers=headers,
                params=params,
                timeout=(10, 30),
            )
            response.raise_for_status()

            commits = response.json()
            for commit in commits:
                sha = commit.get("sha", "")
                commit_data = commit.get("commit", {})
                message = commit_data.get("message", "")
                author_info = commit_data.get("author", {})
                date_str = author_info.get("date", "")

                # Parse ISO 8601 date string to Unix timestamp
                timestamp = 0
                if date_str:
                    try:
                        dt = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ").replace(
                            tzinfo=timezone.utc
                        )
                        timestamp = int(dt.timestamp())
                    except ValueError:
                        timestamp = 0

                yield {
                    "source_id": "github",
                    "timestamp": timestamp,
                    "label": repo_full_name,
                    "sublabel": message[:100],
                    "category": sha[:8],
                    "raw_json": json.dumps(commit),
                    "fetched_at": fetched_at,
                }
