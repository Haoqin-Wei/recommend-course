"""Catalog loaders."""

from app.catalog.loaders.base import CatalogLoader
from app.catalog.loaders.uci_relational import UCIRelationalLoader

__all__ = ["CatalogLoader", "UCIRelationalLoader"]
