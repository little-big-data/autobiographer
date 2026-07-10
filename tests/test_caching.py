import os
import shutil
import tempfile
import time
import unittest

import pandas as pd

from analysis_utils import get_cache_key, get_cached_data, save_to_cache


class TestCaching(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_cache_dir_")
        self.cache_dir = tempfile.mkdtemp(prefix="test_cache_")

        self.lastfm_file = os.path.join(self.test_dir, "test_tracks.csv")
        self.df = pd.DataFrame(
            {
                "artist": ["Artist 1", "Artist 2"],
                "track": ["Track 1", "Track 2"],
                "timestamp": [1610000000, 1610000100],
                "date_text": ["2021-01-01 10:00", "2021-01-01 10:01"],
            }
        )
        self.df.to_csv(self.lastfm_file, index=False)

        self.swarm_dir = os.path.join(self.test_dir, "swarm")
        os.makedirs(self.swarm_dir, exist_ok=True)
        with open(os.path.join(self.swarm_dir, "checkins_1.json"), "w") as f:
            f.write('{"items": []}')

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        if os.path.exists(self.cache_dir):
            shutil.rmtree(self.cache_dir)

    def test_cache_key_consistency(self):
        key1 = get_cache_key(self.lastfm_file, self.swarm_dir)
        key2 = get_cache_key(self.lastfm_file, self.swarm_dir)
        self.assertEqual(key1, key2)

    def test_cache_key_changes_on_lastfm_update(self):
        key1 = get_cache_key(self.lastfm_file, self.swarm_dir)

        # Wait more than 1s to ensure mtime changes even on 1s resolution filesystems
        time.sleep(1.1)
        with open(self.lastfm_file, "a") as f:
            f.write("\n")

        key2 = get_cache_key(self.lastfm_file, self.swarm_dir)
        self.assertNotEqual(key1, key2)

    def test_cache_key_changes_on_swarm_update(self):
        key1 = get_cache_key(self.lastfm_file, self.swarm_dir)

        time.sleep(1.1)
        with open(os.path.join(self.swarm_dir, "checkins_2.json"), "w") as f:
            f.write('{"items": []}')

        key2 = get_cache_key(self.lastfm_file, self.swarm_dir)
        self.assertNotEqual(key1, key2)

    def test_cache_key_changes_with_timeline_path(self):
        timeline_file = os.path.join(self.test_dir, "Timeline.json")
        with open(timeline_file, "w") as f:
            f.write('{"semanticSegments": []}')

        key_without = get_cache_key(self.lastfm_file, self.swarm_dir)
        key_with = get_cache_key(self.lastfm_file, self.swarm_dir, timeline_path=timeline_file)
        self.assertNotEqual(key_without, key_with)

    def test_cache_key_changes_on_timeline_update(self):
        timeline_file = os.path.join(self.test_dir, "Timeline.json")
        with open(timeline_file, "w") as f:
            f.write('{"semanticSegments": []}')
        key1 = get_cache_key(self.lastfm_file, self.swarm_dir, timeline_path=timeline_file)

        time.sleep(1.1)
        with open(timeline_file, "a") as f:
            f.write(" ")

        key2 = get_cache_key(self.lastfm_file, self.swarm_dir, timeline_path=timeline_file)
        self.assertNotEqual(key1, key2)

    def test_save_and_load_cache(self):
        key = get_cache_key(self.lastfm_file, self.swarm_dir)
        save_to_cache(self.df, key, cache_dir=self.cache_dir)

        loaded_df = get_cached_data(key, cache_dir=self.cache_dir)
        self.assertIsNotNone(loaded_df)
        self.assertEqual(len(loaded_df), 2)
        self.assertEqual(loaded_df.iloc[0]["artist"], "Artist 1")

    def test_invalid_cache_key(self):
        df = get_cached_data("nonexistent_key", cache_dir=self.cache_dir)
        self.assertIsNone(df)

    def test_setup_uses_unique_per_invocation_paths(self):
        """Fixture paths must be unique per invocation, not a hardcoded shared
        path, so parallel pytest-xdist workers running different test methods
        of this TestCase never race on the same directory (handoff.md
        Subtask 1)."""
        other = TestCaching("test_cache_key_consistency")
        other.setUp()
        try:
            self.assertNotEqual(
                self.test_dir,
                other.test_dir,
                "self.test_dir must be a unique per-invocation path, not a "
                "shared hardcoded path reused across invocations",
            )
            self.assertNotEqual(
                self.cache_dir,
                other.cache_dir,
                "self.cache_dir must be a unique per-invocation path, not a "
                "shared hardcoded path reused across invocations",
            )
            # tearing down one invocation's fixtures must never remove the
            # other invocation's still-in-use fixtures.
            other.tearDown()
            self.assertTrue(
                os.path.exists(self.test_dir),
                "tearing down a different TestCaching invocation must not "
                "delete this invocation's still-in-use test_dir",
            )
            self.assertTrue(
                os.path.exists(self.cache_dir),
                "tearing down a different TestCaching invocation must not "
                "delete this invocation's still-in-use cache_dir",
            )
        finally:
            if os.path.exists(other.test_dir):
                shutil.rmtree(other.test_dir)
            if os.path.exists(other.cache_dir):
                shutil.rmtree(other.cache_dir)


if __name__ == "__main__":
    unittest.main()
