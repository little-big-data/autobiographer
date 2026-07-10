"""localizer CLI — click-based entry point for the localizer package.

Commands
--------
localizer sources                             List registered plugins
localizer status [source] [--json]            Show record counts
localizer export --format --table --output    Export data to file(s)
localizer fetch <source> [--since] [--full] [--dry-run]
localizer sync [--since] [--dry-run]
localizer db path | vacuum | migrate
localizer config show | set <key> <value>
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import click
from dotenv import load_dotenv

from localizer.settings import LocalizerSettings

_BATCH_SIZE = 1_000  # records per DuckDB write; keeps peak RAM at O(batch) not O(total)


def _upsert_for_table(store: Any, batch: list[dict[str, Any]], table: Any) -> None:
    """Write a batch of records to whichever store table ``table`` designates.

    Shared by ``fetch`` and ``sync`` so both single-output plugins (the
    common case — one ``OUTPUT_TABLES`` entry) and dual-output plugins (e.g.
    ``FlickrPlugin``, which declares ``[PLACES, EVENTS]`` and drains its
    primary ``fetch_records()`` stream into the first entry and its
    ``fetch_secondary_records()`` stream into the second) route through one
    place instead of duplicating the events/places/content if-chain.

    Args:
        store: Open ``LocalizerStore``.
        batch: List of record dicts already shaped for the target table.
        table: The ``OutputTable`` member this batch belongs to. Falls back
            to ``upsert_events`` when ``table`` is ``None``/unrecognized,
            matching the historical default for plugins with an empty
            ``OUTPUT_TABLES`` list.
    """
    from localizer.plugins.base import OutputTable  # noqa: PLC0415

    if table == OutputTable.PLACES:
        store.upsert_places(batch)
    elif table == OutputTable.CONTENT:
        store.upsert_content(batch)
    else:
        store.upsert_events(batch)


def _get_store_path() -> Path:
    """Resolve the DuckDB store path via settings / env var.

    Returns:
        Path to the DuckDB store file.
    """
    return LocalizerSettings().get_store_path()


def _get_settings() -> LocalizerSettings:
    """Return a LocalizerSettings instance, respecting LOCALIZER_CONFIG_PATH.

    Returns:
        Configured LocalizerSettings instance.
    """
    env_cfg = os.environ.get("LOCALIZER_CONFIG_PATH")
    if env_cfg:
        return LocalizerSettings(config_path=Path(env_cfg))
    return LocalizerSettings()


# ---------------------------------------------------------------------------
# Root group
# ---------------------------------------------------------------------------


@click.group()
def cli() -> None:
    """localizer — personal life-data fetch, normalize, and store."""
    load_dotenv()


# ---------------------------------------------------------------------------
# sources
# ---------------------------------------------------------------------------


@cli.command("sources")
def sources_cmd() -> None:
    """List all registered source plugins."""
    from localizer.plugins import REGISTRY, load_builtin_plugins  # noqa: PLC0415

    load_builtin_plugins()

    if not REGISTRY:
        click.echo("No plugins registered.")
        return

    for plugin_id, plugin_cls in sorted(REGISTRY.items()):
        fetch_mode = getattr(plugin_cls, "FETCH_MODE", None)
        mode_name = fetch_mode.name if fetch_mode is not None else "UNKNOWN"
        output_tables = getattr(plugin_cls, "OUTPUT_TABLES", [])
        table_names = ", ".join(t.value for t in output_tables) if output_tables else "-"
        click.echo(f"{plugin_id}  {mode_name}  {table_names}")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@cli.command("status")
@click.argument("source", required=False, default=None)
@click.option("--json", "as_json", is_flag=True, default=False, help="Output as JSON.")
def status_cmd(source: str | None, as_json: bool) -> None:
    """Show record counts from the store.

    If SOURCE is given, show counts for that plugin only.
    """
    from localizer.store.db import LocalizerStore  # noqa: PLC0415

    store_path = _get_store_path()
    with LocalizerStore(store_path) as store:
        # Collect counts per table.
        events_df = store.query_events(source_id=source)
        places_df = store.query_places(source_id=source)
        content_df = store.query_content(source_id=source)

        event_count = len(events_df)
        place_count = len(places_df)
        content_count = len(content_df)

        # Also build per-source breakdown when no filter is applied.
        if source is None:
            all_events = store.query_events()
            all_places = store.query_places()
        else:
            all_events = events_df
            all_places = places_df

    if as_json:
        output: dict[str, Any] = {
            "totals": {
                "events": event_count,
                "places": place_count,
                "content": content_count,
            }
        }

        # Per-source event counts.
        if not all_events.empty and "source_id" in all_events.columns:
            for src, group in all_events.groupby("source_id"):
                output.setdefault(str(src), {})["record_count"] = len(group)

        # Per-source place counts.
        if not all_places.empty and "source_id" in all_places.columns:
            for src, group in all_places.groupby("source_id"):
                output.setdefault(str(src), {})["record_count"] = output.get(str(src), {}).get(
                    "record_count", 0
                ) + len(group)

        click.echo(json.dumps(output))
    else:
        click.echo(f"events:  {event_count}")
        click.echo(f"places:  {place_count}")
        click.echo(f"content: {content_count}")


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


@cli.command("export")
@click.option(
    "--format",
    "fmt",
    required=True,
    type=click.Choice(["parquet", "csv", "json"], case_sensitive=False),
    help="Output format.",
)
@click.option(
    "--table",
    "table",
    default=None,
    type=click.Choice(["events", "places", "content"], case_sensitive=False),
    help="Table to export. Exports all tables if omitted.",
)
@click.option(
    "--since", "since", default=None, type=int, help="Export records since this Unix timestamp."
)
@click.option(
    "--output",
    "output",
    required=True,
    type=click.Path(),
    help="Output directory path.",
)
def export_cmd(fmt: str, table: str | None, since: int | None, output: str) -> None:
    """Export data from the store to files.

    Writes one file per table to OUTPUT directory.
    """
    from localizer.store.db import LocalizerStore  # noqa: PLC0415

    output_path = Path(output)
    output_path.mkdir(parents=True, exist_ok=True)

    store_path = _get_store_path()
    tables_to_export = [table] if table else ["events", "places", "content"]

    with LocalizerStore(store_path) as store:
        for tbl in tables_to_export:
            if tbl == "events":
                df = store.query_events(since=since)
            elif tbl == "places":
                df = store.query_places(since=since)
            else:
                df = store.query_content(since=since)

            if df.empty:
                continue

            file_path = output_path / f"{tbl}.{fmt}"
            if fmt == "parquet":
                df.to_parquet(file_path, index=False)
            elif fmt == "csv":
                df.to_csv(file_path, index=False)
            else:  # json
                df.to_json(file_path, orient="records", lines=True)

            click.echo(f"Exported {len(df)} rows from {tbl} to {file_path}")


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------


@cli.command("fetch")
@click.argument("source")
@click.option(
    "--since", "since", default=None, type=int, help="Fetch records since this Unix timestamp."
)
@click.option(
    "--full", "full", is_flag=True, default=False, help="Ignore last cursor and fetch all records."
)
@click.option(
    "--dry-run", "dry_run", is_flag=True, default=False, help="Fetch but do not write to store."
)
@click.option(
    "--set-dir",
    "set_dir",
    default=None,
    type=click.Path(),
    help="Save a directory path to config and use it for this fetch (e.g. swarm_dir).",
)
@click.option(
    "--set-file",
    "set_file",
    default=None,
    type=click.Path(),
    help="Save a file path to config and use it for this fetch (e.g. csv_path).",
)
def fetch_cmd(
    source: str,
    since: int | None,
    full: bool,
    dry_run: bool,
    set_dir: str | None,
    set_file: str | None,
) -> None:
    """Fetch records from SOURCE plugin and write to the store.

    SOURCE must be a registered plugin ID (e.g. 'lastfm', 'swarm').

    Use --set-dir or --set-file to save a path to config in the same step:

      localizer fetch swarm --set-dir "G:/My Drive/Swarm Export"
      localizer fetch letterboxd --set-file "/path/to/diary.csv"
    """
    from localizer.plugins import REGISTRY, load_builtin_plugins  # noqa: PLC0415
    from localizer.store.db import LocalizerStore  # noqa: PLC0415

    load_builtin_plugins()

    # Persist and apply any inline path config.
    settings = _get_settings()
    if set_dir:
        settings.set_setting(f"{source}_dir", set_dir)
    if set_file:
        # Derive the config key from the plugin's first file_path field, fallback to csv_path.
        plugin_proto_cls = REGISTRY.get(source)
        if plugin_proto_cls:
            fields = plugin_proto_cls().get_config_fields()
            file_key = next((f["key"] for f in fields if f.get("type") == "file_path"), "csv_path")
        else:
            file_key = "csv_path"
        settings.set_setting(file_key, set_file)

    if source not in REGISTRY:
        click.echo(
            f"Error: unknown source '{source}'. Available: {', '.join(sorted(REGISTRY.keys()))}",
            err=True,
        )
        sys.exit(1)

    plugin_cls = REGISTRY[source]
    plugin = plugin_cls()

    store_path = _get_store_path()

    # Determine since timestamp from sync state when not forced.
    effective_since = since
    if not full and effective_since is None:
        with LocalizerStore(store_path) as store:
            state = store.get_sync_state(source)
            effective_since = state.get("last_synced_at")

    import time  # noqa: PLC0415

    from rich.console import Console  # noqa: PLC0415

    console = Console(stderr=True)
    output_tables = getattr(plugin_cls, "OUTPUT_TABLES", [])
    primary_table = output_tables[0] if output_tables else None
    secondary_table = output_tables[1] if len(output_tables) > 1 else None
    count = 0
    batch: list[dict[str, Any]] = []

    if dry_run:
        with console.status(f"  {source}: counting…", spinner="dots") as status:
            for _ in plugin.fetch_records(since=effective_since):
                count += 1
                status.update(f"  {source}: {count} records (dry-run)…")
            if secondary_table is not None:
                for _ in plugin.fetch_secondary_records(since=effective_since):
                    count += 1
                    status.update(f"  {source}: {count} records (dry-run)…")
        click.echo(f"[dry-run] Would write {count} record(s) from '{source}' to store.")
        return

    with (
        LocalizerStore(store_path) as store,
        console.status(f"  {source}: fetching…", spinner="dots") as status,
    ):
        for record in plugin.fetch_records(since=effective_since):
            batch.append(record)
            count += 1
            if len(batch) >= _BATCH_SIZE:
                status.update(f"  {source}: writing batch… ({count} records so far)")
                _upsert_for_table(store, batch, primary_table)
                batch.clear()
            status.update(f"  {source}: fetching {count} records…")
        if batch:
            status.update(f"  {source}: writing final batch… ({count} records)")
            _upsert_for_table(store, batch, primary_table)
            batch.clear()

        if secondary_table is not None:
            for record in plugin.fetch_secondary_records(since=effective_since):
                batch.append(record)
                count += 1
                if len(batch) >= _BATCH_SIZE:
                    status.update(f"  {source}: writing batch… ({count} records so far)")
                    _upsert_for_table(store, batch, secondary_table)
                    batch.clear()
                status.update(f"  {source}: fetching {count} records…")
            if batch:
                status.update(f"  {source}: writing final batch… ({count} records)")
                _upsert_for_table(store, batch, secondary_table)
                batch.clear()

        # Only advance the cursor when records were actually written — a zero-record
        # run (misconfiguration, transient error) must not set last_synced_at to now,
        # or the next run would filter out all historical data.
        if count > 0:
            store.set_sync_state(
                source,
                last_synced_at=int(time.time()),
                record_count=count,
                status="ok",
            )

    click.echo(f"Fetched and stored {count} record(s) from '{source}'.")


# ---------------------------------------------------------------------------
# sync
# ---------------------------------------------------------------------------


@cli.command("sync")
@click.option(
    "--since", "since", default=None, type=int, help="Sync records since this Unix timestamp."
)
@click.option(
    "--dry-run", "dry_run", is_flag=True, default=False, help="Fetch but do not write to store."
)
def sync_cmd(since: int | None, dry_run: bool) -> None:
    """Sync all registered plugins."""
    from rich.console import Console  # noqa: PLC0415

    from localizer.plugins import REGISTRY, load_builtin_plugins  # noqa: PLC0415
    from localizer.store.db import LocalizerStore  # noqa: PLC0415

    load_builtin_plugins()

    console = Console(stderr=True)
    store_path = _get_store_path()
    total_written = 0

    for plugin_id, plugin_cls in sorted(REGISTRY.items()):
        try:
            plugin = plugin_cls()
        except TypeError as exc:
            click.echo(f"  {plugin_id}: skipped (requires configuration — {exc})", err=True)
            continue
        output_tables = getattr(plugin_cls, "OUTPUT_TABLES", [])
        primary_table = output_tables[0] if output_tables else None
        secondary_table = output_tables[1] if len(output_tables) > 1 else None

        # Determine effective since from sync state.
        effective_since = since
        if effective_since is None and not dry_run:
            with LocalizerStore(store_path) as store:
                state = store.get_sync_state(plugin_id)
                effective_since = state.get("last_synced_at")
        page_label: list[str] = [""]

        def _progress_cb(current: int, total: int, _pl: list[str] = page_label) -> None:
            _pl[0] = f" page {current}/{total}"

        count = 0
        batch: list[dict[str, Any]] = []

        if dry_run:
            try:
                with console.status(f"  {plugin_id}: counting…", spinner="dots") as status:
                    for _ in plugin.fetch_records(since=effective_since, progress_cb=_progress_cb):
                        count += 1
                        status.update(f"  {plugin_id}: {count} records{page_label[0]} (dry-run)…")
                    if secondary_table is not None:
                        for _ in plugin.fetch_secondary_records(
                            since=effective_since, progress_cb=_progress_cb
                        ):
                            count += 1
                            status.update(
                                f"  {plugin_id}: {count} records{page_label[0]} (dry-run)…"
                            )
            except OSError as exc:
                click.echo(f"  {plugin_id}: skipped ({exc})", err=True)
                continue
            click.echo(f"[dry-run] {plugin_id}: would write {count} record(s).")
            continue

        try:
            import time  # noqa: PLC0415

            with (
                LocalizerStore(store_path) as store,
                console.status(f"  {plugin_id}: fetching…", spinner="dots") as status,
            ):
                for record in plugin.fetch_records(since=effective_since, progress_cb=_progress_cb):
                    batch.append(record)
                    count += 1
                    if len(batch) >= _BATCH_SIZE:
                        status.update(
                            f"  {plugin_id}: writing batch… ({count} records{page_label[0]})"
                        )
                        _upsert_for_table(store, batch, primary_table)
                        batch.clear()
                    status.update(f"  {plugin_id}: fetching {count} records{page_label[0]}…")
                if batch:
                    status.update(f"  {plugin_id}: writing final batch… ({count} records)")
                    _upsert_for_table(store, batch, primary_table)
                    batch.clear()

                if secondary_table is not None:
                    for record in plugin.fetch_secondary_records(
                        since=effective_since, progress_cb=_progress_cb
                    ):
                        batch.append(record)
                        count += 1
                        if len(batch) >= _BATCH_SIZE:
                            status.update(
                                f"  {plugin_id}: writing batch… ({count} records{page_label[0]})"
                            )
                            _upsert_for_table(store, batch, secondary_table)
                            batch.clear()
                        status.update(f"  {plugin_id}: fetching {count} records{page_label[0]}…")
                    if batch:
                        status.update(f"  {plugin_id}: writing final batch… ({count} records)")
                        _upsert_for_table(store, batch, secondary_table)
                        batch.clear()

                if count > 0:
                    store.set_sync_state(
                        plugin_id,
                        last_synced_at=int(time.time()),
                        record_count=count,
                        status="ok",
                    )
        except OSError as exc:
            click.echo(f"  {plugin_id}: skipped ({exc})", err=True)
            continue

        total_written += count
        click.echo(f"  {plugin_id}: wrote {count} record(s).")

    if not dry_run:
        click.echo(f"Sync complete. Total records written: {total_written}.")


# ---------------------------------------------------------------------------
# db group
# ---------------------------------------------------------------------------


@cli.group("db")
def db_group() -> None:
    """Database management commands."""


@db_group.command("path")
def db_path_cmd() -> None:
    """Print the resolved DuckDB store path."""
    click.echo(str(_get_store_path()))


@db_group.command("vacuum")
def db_vacuum_cmd() -> None:
    """Run VACUUM on the DuckDB store to reclaim space."""
    from localizer.store.db import LocalizerStore  # noqa: PLC0415

    store_path = _get_store_path()
    with LocalizerStore(store_path) as store:
        assert store.conn is not None
        store.conn.execute("VACUUM")
    click.echo("Vacuum complete.")


@db_group.command("migrate")
def db_migrate_cmd() -> None:
    """Apply any pending schema migrations."""
    from localizer.store.db import LocalizerStore  # noqa: PLC0415

    store_path = _get_store_path()
    with LocalizerStore(store_path) as _store:
        pass  # Migrations are applied on open.
    click.echo("Migrations applied.")


@db_group.command("shell")
def db_shell_cmd() -> None:
    """Launch an interactive DuckDB shell (not available in this environment)."""
    click.echo(f"Store path: {_get_store_path()}")
    click.echo("Interactive shell not available. Use the DuckDB CLI directly.")


# ---------------------------------------------------------------------------
# config group
# ---------------------------------------------------------------------------


@cli.group("config")
def config_group() -> None:
    """Configuration management commands."""


@config_group.command("show")
def config_show_cmd() -> None:
    """Show all settings from the config file."""
    settings = _get_settings()
    config_path = settings._config_path  # noqa: SLF001

    if not config_path.exists():
        click.echo("No config file found.")
        return

    click.echo(f"Config file: {config_path}")
    text = config_path.read_text(encoding="utf-8")
    if text.strip():
        click.echo(text)
    else:
        click.echo("(empty)")


@config_group.command("set")
@click.argument("key")
@click.argument("value")
def config_set_cmd(key: str, value: str) -> None:
    """Set a configuration value.

    KEY and VALUE are stored as strings in the config file.
    """
    settings = _get_settings()
    settings.set_setting(key, value)
    click.echo(f"Set {key} = {value}")
