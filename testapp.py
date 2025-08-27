import streamlit as st
import folium
from streamlit_folium import st_folium
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from folium.features import GeoJsonTooltip
import matplotlib.pyplot as plt
import sqlite3
from datetime import datetime

st.set_page_config(layout="wide")
st.title("Welcome to the Park Puls App!")

# =====================
# Load Layers (Cached)
# =====================
@st.cache_data(show_spinner="Loading spatial data...")
def load_layer(path: str, layer_name: str) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path, layer=layer_name)
    return gdf.to_crs(epsg=4326)

layer_variables = load_layer(
    path=r"data/VARIABLES_for_streamlit.gpkg",
    layer_name="VARIABLES_for_streamlit"
)

# Optional: simplify geometries for faster rendering
layer_variables["geometry"] = layer_variables["geometry"].simplify(0.00005)

# =====================
# Dropdown for Themes
# =====================
themes = {
    "Amenities": ["NAMN_top5", "TYP_combined", "typology", "amenities"],
    "Environment": ["NAMN_top5", "BIOTOP_combined"],
    "Accessibility": ["NAMN_top5"],
    "Socioeconomic factors": ["NAMN_top5"]
}

column_aliases = {
    "NAMN_top5": "Name(s)",
    "TYP_combined": "Typology1",
    "typology": "Typology2",
    "BIOTOP_combined": "Biotope",
    "amenities": "Amenities",
}

layer_options = list(themes.keys())
selected_layer = st.selectbox("Select a theme to view in the dropdown list", layer_options)
st.markdown("Click a park to view more information")

# =====================
# Filtered Data (Cached)
# =====================
@st.cache_data
def get_filtered_layer(_layer_variables, selected_layer, themes):
    cols = themes[selected_layer] + ["geometry"]
    return _layer_variables[cols].copy()

layer_variables_filtered = get_filtered_layer(layer_variables, selected_layer, themes)
popup_cols = [col for col in themes[selected_layer] if col in layer_variables_filtered.columns]

# =====================
# Session state for last clicked polygon
# =====================
if "clicked_park_index" not in st.session_state:
    st.session_state.clicked_park_index = None

print(st.session_state)
# =====================
# Initialize SQLite database
# =====================
conn = sqlite3.connect("feedback.db", check_same_thread=False)
c = conn.cursor()
c.execute("""
CREATE TABLE IF NOT EXISTS park_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    park_name TEXT,
    rating INTEGER,
    comment TEXT,
    timestamp TEXT
)
""")
conn.commit()

def log_feedback(park_name, rating, comment):
    timestamp = datetime.utcnow().isoformat()
    c.execute(
        "INSERT INTO park_feedback (park_name, rating, comment, timestamp) VALUES (?, ?, ?, ?)",
        (park_name, rating, comment, timestamp)
    )
    conn.commit()

# =====================
# Initialize Folium Map
# =====================
m = folium.Map(location=(59.33, 17.99), zoom_start=10.5, tiles=None)

# Add base GeoJSON layer (all parks)
folium.GeoJson(
    layer_variables_filtered,
    name=selected_layer,
    style_function=lambda x: {
        "fillColor": "yellow",
        "color": "black",
        "weight": 0.5,
        "fillOpacity": 0.4
    },
    tooltip=GeoJsonTooltip(fields=themes[selected_layer]),
).add_to(m)

# =====================
# Highlight layer (only if a polygon is clicked)
# =====================
highlight_idx = st.session_state.get("clicked_park_index", None)

if highlight_idx is not None:
    # Get the clicked polygon
    highlight_polygon = layer_variables_filtered.iloc[[highlight_idx]]

    # Add it as a separate layer to avoid crashes
    folium.GeoJson(
        highlight_polygon,
        name="Highlighted Park",
        style_function=lambda x: {
            "fillColor": "red",
            "color": "red",
            "weight": 3,
            "fillOpacity": 0.2
        },
    ).add_to(m)

# =====================
# Basemaps
# =====================
folium.map.CustomPane("labels").add_to(m)

folium.TileLayer(
    tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    attr='Esri',
    name='Esri Satellite',
    overlay=False,
    control=True
).add_to(m)

folium.LayerControl('topright', collapsed=False).add_to(m)

# =====================
# Render map
# =====================
out = st_folium(m, key="map", use_container_width=True, height=750)

# =====================
# Handle clicks and sidebar
# =====================
st.sidebar.title("Park Details")

if out and out.get("last_object_clicked"):
    clicked_lat = out["last_object_clicked"]["lat"]
    clicked_lon = out["last_object_clicked"]["lng"]

    clicked_point = gpd.GeoDataFrame(geometry=[Point(clicked_lon, clicked_lat)], crs="EPSG:4326")
    clicked_polygon = gpd.sjoin(clicked_point, layer_variables_filtered, predicate="within")

    if not clicked_polygon.empty:
        idx = clicked_polygon.index[0]
        st.session_state.clicked_park_index = idx  # Save clicked polygon

        park_info = clicked_polygon.iloc[0].to_dict()

        st.sidebar.subheader("Selected Park Info")
        for key, val in park_info.items():
            if key != "geometry":
                st.sidebar.markdown(f"**{column_aliases.get(key, key)}:** {val}")

        area = clicked_polygon.iloc[0].geometry.area * (111_000**2)
        st.sidebar.markdown(f"**Area:** {area:,.0f} m²")

        numeric_cols = [col for col in clicked_polygon.columns
                        if col not in ["geometry", "index_right"] and pd.api.types.is_numeric_dtype(clicked_polygon[col])]
        if numeric_cols:
            st.sidebar.subheader("Park Attributes (Numeric)")
            fig, ax = plt.subplots()
            clicked_polygon[numeric_cols].iloc[0].plot(kind='bar', ax=ax)
            plt.xticks(rotation=45)
            plt.tight_layout()
            st.sidebar.pyplot(fig)

        # 5-star rating using slider
        feedback = st.sidebar.slider("Rating ⭐", min_value=1, max_value=5, value=3, step=1)
        st.sidebar.markdown("Your rating: " + "⭐" * feedback + "☆" * (5 - feedback))

        # Comment form
        st.sidebar.header("Leave a comment")
        with st.sidebar.form("comment_form"):
            comment = st.text_area("Park comment", placeholder="Add comment here", label_visibility="collapsed")
            submitted = st.form_submit_button("Submit")
            if submitted:
                park_name = park_info.get("NAMN_top5", "Unknown")
                log_feedback(park_name, feedback, comment)
                st.sidebar.success("Thank you for your comment!")

# =====================
# Example Download Button
# =====================
import numpy as np

@st.cache_data
def get_data():
    df = pd.DataFrame(np.random.randn(50, 20), columns=("col %d" % i for i in range(20)))
    return df

@st.cache_data
def convert_for_download(df):
    return df.to_csv().encode("utf-8")

df = get_data()
csv = convert_for_download(df)

st.download_button(
    label="Example file (file type)",
    data=csv,
    file_name="data.csv",
    mime="text/csv",
    icon=":material/download:",
)