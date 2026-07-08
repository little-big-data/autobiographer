import os
import shutil
import time
import unittest

import pandas as pd

from analysis_utils import get_cache_key, get_cached_data, save_to_cache


class TestCaching(unittest.TestCase):
    def setUp(self):
        self.test_dir = "data/test_cache_dir"
        self.cache_dir = "data/test_cache"
        os.makedirs(self.test_dir, exist_ok=True)
        os.makedirs(self.cache_dir, exist_ok=True)

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


if __name__ == "__main__":
    unittest.main()
