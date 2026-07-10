"""Autobiographer dashboard entrypoint.

Configures the page, renders the shared sidebar, and runs the multi-page
navigation. All chart logic lives in the ``pages/`` modules; shared data
loading lives in ``components/sidebar``.

Run with::

    streamlit run visualize.py
"""

from __future__ import annotations

from functools import partial

import streamlit as st
from dotenv import load_dotenv

import components.theme  # registers autobio_dark Plotly template as default  # noqa: F401
from components.sidebar import render_sidebar
from pages.beer import render_beer
from pages.city_soundtracks import render_city_soundtracks
from pages.culture import render_culture
from pages.data_sources import render_data_sources, render_plugin_page
from pages.deep_music import render_deep_music
from pages.discovery_zones import render_discovery_zones
from pages.fitness import render_fitness
from pages.geo_explorer import render_geo_explorer
from pages.insights import render_insights, render_insights_and_narrative  # noqa: F401
from pages.life_events import render_life_events
from pages.life_in_chapters import render_life_in_chapters
from pages.listening_lifestyle import render_listening_lifestyle
from pages.music import render_music, render_top_charts  # noqa: F401
from pages.overview import render_overview  # noqa: F401
from pages.places import render_checkin_insights  # noqa: F401
from pages.taste_drift import render_taste_drift
from pages.venue_patterns import render_venue_patterns
from plugins.sources import REGISTRY, load_builtin_plugins

load_dotenv()

_GLOBAL_CSS = """
<style>
/* ── Chrome — hide unwanted UI without touching the sidebar toggle ─────────
   Do NOT hide stHeader or stToolbar: they contain the collapsed-sidebar
   expand button, and hiding them traps users with no way to reopen it.      */
#MainMenu                          {visibility: hidden;}
footer                             {visibility: hidden;}
[data-testid="stDecoration"]       {display: none;}
[data-testid="stStatusWidget"]     {visibility: hidden;}

/* ── Layout ───────────────────────────────────────────────────────────────*/
.block-container {
    padding-top: 1.5rem;
    padding-bottom: 1rem;
}

/* ── Card containers ──────────────────────────────────────────────────────
   Targets bordered st.container() blocks and the overview hero card.        */
[data-testid="stVerticalBlockBorderWrapper"] {
    background-color: #141c2f !important;
    border-radius: 12px !important;
    border: 1px solid #2d3a52 !important;
    box-shadow: 0 4px 24px rgba(0,0,0,0.4);
}

.autobio-hero-card {
    background: linear-gradient(135deg, #1e1b4b, #0c1120);
    border: 1px solid #6366f1;
    border-radius: 12px;
    padding: 2rem 2.5rem;
    margin-bottom: 1.5rem;
}

/* ── Section headers (sidebar nav group labels) ───────────────────────────*/
.autobio-section-header {
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    opacity: 0.55;
    margin: 0.5rem 0 0.15rem 0;
    padding-left: 0.5rem;
    line-height: 1.5;
}
</style>
"""


@st.cache_resource
def _load_plugins_once() -> None:
    """Load built-in plugins into REGISTRY exactly once per server process."""
    load_builtin_plugins()


@st.cache_resource
def _build_plugin_nav_pages() -> list[st.Page]:
    """Build the Sources nav pages once; reused on every subsequent rerun."""
    pages: list[st.Page] = [
        st.Page(render_data_sources, title="Data Sources", icon=":material/database:"),
    ]
    for plugin_id, plugin_cls in REGISTRY.items():
        plugin = plugin_cls()
        pages.append(
            st.Page(
                partial(render_plugin_page, plugin_id),
                title=plugin.DISPLAY_NAME,
                icon=plugin.ICON,
                url_path=plugin_id,
            )
        )
    return pages


def main() -> None:
    """Configure and launch the Autobiographer multi-page dashboard."""
    st.set_page_config(page_title="Autobiographer", layout="wide")
    st.markdown(_GLOBAL_CSS, unsafe_allow_html=True)

    # Populate REGISTRY before building nav so plugin pages can be listed.
    _load_plugins_once()

    sources_pages = _build_plugin_nav_pages()

    pg = st.navigation(
        {
            "Overview": [
                st.Page(render_overview, title="Overview", icon=":material/dashboard:"),
                st.Page(render_geo_explorer, title="Geo Explorer", icon=":material/explore:"),
            ],
            "Music": [
                st.Page(render_music, title="Listening", icon=":material/headphones:"),
                st.Page(render_insights, title="Insights", icon=":material/auto_stories:"),
                st.Page(render_discovery_zones, title="Discovery Zones", icon=":material/explore:"),
                st.Page(
                    render_life_in_chapters,
                    title="Life in Chapters",
                    icon=":material/auto_stories:",
                ),
                st.Page(
                    render_listening_lifestyle,
                    title="Listening Lifestyle",
                    icon=":material/self_improvement:",
                ),
                st.Page(
                    render_deep_music,
                    title="Deep Music Analysis",
                    icon=":material/insights:",
                ),
                st.Page(
                    render_taste_drift,
                    title="Geographic Taste Drift",
                    icon=":material/travel_explore:",
                ),
                st.Page(
                    render_life_events,
                    title="Life Event Detection",
                    icon=":material/timeline:",
                ),
            ],
            "Places": [
                st.Page(
                    render_checkin_insights, title="Check-in Insights", icon=":material/insights:"
                ),
                st.Page(
                    render_city_soundtracks,
                    title="City Soundtracks",
                    icon=":material/music_note:",
                ),
                st.Page(
                    render_venue_patterns,
                    title="Venue Patterns",
                    icon=":material/place:",
                ),
            ],
            "Health": [
                st.Page(render_fitness, title="Fitness", icon=":material/fitness_center:"),
            ],
            "Culture": [
                st.Page(render_culture, title="Films & Books", icon=":material/local_library:"),
                st.Page(render_beer, title="Drinking History", icon=":material/sports_bar:"),
            ],
            "Sources": sources_pages,
        }
    )

    # render_sidebar after st.navigation so it appears below the nav list.
    render_sidebar()

    pg.run()


if __name__ == "__main__":
    main()
