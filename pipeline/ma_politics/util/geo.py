"""Shared geospatial helpers for the fetch/build scripts."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import geopandas as gpd

from ma_politics.util.http import get

TARGET_CRS = "EPSG:4269"  # NAD83 geographic — TIGER's native CRS; everything is reprojected to this


def download_shapefile(url: str, shp_path_in_zip: str | None, extract_dir: Path, session) -> gpd.GeoDataFrame:
    """Download a zipped shapefile and read it with geopandas.

    shp_path_in_zip=None auto-detects the single .shp in the archive (TIGER
    zips have it at the root; the exact name varies by layer/year)."""
    resp = get(session, url)
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        if shp_path_in_zip is None:
            shp_names = [n for n in zf.namelist() if n.endswith(".shp")]
            if len(shp_names) != 1:
                raise ValueError(f"Expected exactly one .shp in {url}, found {shp_names}")
            shp_path_in_zip = shp_names[0]
        extract_dir.mkdir(parents=True, exist_ok=True)
        zf.extractall(extract_dir)
    return gpd.read_file(extract_dir / shp_path_in_zip)
