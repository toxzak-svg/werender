"""Synchronization manager for WeRender with incremental sync support."""

import hashlib
import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set
import tempfile
import sqlite3
from contextlib import contextmanager


class SyncManager:
    """Manages synchronization of settings and add-ons with incremental sync."""

    def __init__(
        self,
        config_path: Optional[Path] = None,
        addons_dir: Optional[Path] = None,
        cache_db_path: Optional[Path] = None,
    ):
        """
        Initialize the SyncManager.

        Args:
            config_path: Path to the global settings file (werender.json).
            addons_dir: Path to the directory containing add-ons to distribute.
            cache_db_path: Optional path to cache database for asset tracking.
        """
        self.config_path = config_path
        self.addons_dir = addons_dir
        self.cached_manifest: Optional[Dict] = None
        
        # Asset cache database for deduplication
        if cache_db_path:
            self.cache_db_path = cache_db_path
            self.cache_db_path.parent.mkdir(parents=True, exist_ok=True)
            self._init_cache_db()
        else:
            self.cache_db_path = None

    @contextmanager
    def _get_cache_connection(self):
        """Get cache database connection."""
        if not self.cache_db_path:
            yield None
            return
        
        conn = sqlite3.connect(str(self.cache_db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_cache_db(self) -> None:
        """Initialize cache database for asset tracking."""
        if not self.cache_db_path:
            return

        with self._get_cache_connection() as conn:
            if conn is None:
                return
            cursor = conn.cursor()

            # Asset cache table - tracks files by hash for deduplication
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS asset_cache (
                    file_hash TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    last_used TIMESTAMP NOT NULL,
                    use_count INTEGER DEFAULT 1,
                    job_ids TEXT
                )
            """)

            # Create index for faster lookups
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_asset_cache_hash ON asset_cache(file_hash)")

    def get_manifest(self) -> Dict:
        """
        Get the current synchronization manifest.

        Returns:
            Dict containing hashes of settings and add-ons.
        """
        if self.cached_manifest:
            # In a real scenario, we might want to invalidate this cache periodically
            # or watch for file changes. For now, let's recalculate if we want to be safe,
            # or rely on a property that we clear when things change.
            # For simplicity in this MVP, let's recalculate.
            pass

        settings_hash = self._calculate_settings_hash()
        addons_hash = self._calculate_addons_hash()

        manifest = {
            "settings_hash": settings_hash,
            "addons_hash": addons_hash,
            "timestamp": datetime.now().isoformat(),
        }

        self.cached_manifest = manifest
        return manifest

    def get_addons_list(self) -> List[Dict]:
        """
        Get list of available add-ons.

        Returns:
            List of dicts with add-on info.
        """
        if not self.addons_dir or not self.addons_dir.exists():
            return []

        addons = []
        for item in self.addons_dir.iterdir():
            if item.is_file() and item.suffix == ".zip":
                addons.append({
                    "name": item.stem,
                    "filename": item.name,
                    "hash": self._calculate_file_hash(item),
                    "size": item.stat().st_size
                })
        return addons
    
    def get_settings(self) -> Dict:
        """Get the current global settings."""
        if not self.config_path or not self.config_path.exists():
            return {}
        
        try:
            with open(self.config_path, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"❌ Error loading settings: {e}")
            return {}

    def _calculate_settings_hash(self) -> str:
        """Calculate hash of the settings file."""
        if not self.config_path or not self.config_path.exists():
            return ""
        return self._calculate_file_hash(self.config_path)

    def _calculate_addons_hash(self) -> str:
        """Calculate combined hash of all add-ons."""
        if not self.addons_dir or not self.addons_dir.exists():
            return ""
        
        # Hash based on sorted list of add-on hashes to be deterministic
        addons = self.get_addons_list()
        if not addons:
            return ""
            
        hasher = hashlib.md5()
        # Sort by name to ensure consistent order
        for addon in sorted(addons, key=lambda x: x["name"]):
            hasher.update((addon["name"] + addon["hash"]).encode("utf-8"))
        
        return hasher.hexdigest()

    def _calculate_file_hash(self, file_path: Path) -> str:
        """Calculate MD5 hash of a file."""
        hasher = hashlib.md5()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception:
            return ""

    def register_asset(self, file_hash: str, file_path: Path, job_id: str) -> None:
        """
        Register an asset in the cache for deduplication.

        Args:
            file_hash: Hash of the file
            file_path: Path to the file
            job_id: Job ID using this asset
        """
        if not self.cache_db_path:
            return

        with self._get_cache_connection() as conn:
            if conn is None:
                return
            cursor = conn.cursor()

            # Check if asset already exists
            cursor.execute("SELECT job_ids, use_count FROM asset_cache WHERE file_hash = ?", (file_hash,))
            row = cursor.fetchone()

            if row:
                # Update existing asset
                job_ids_str = row["job_ids"] or ""
                job_ids = set(job_ids_str.split(",")) if job_ids_str else set()
                job_ids.add(job_id)
                
                cursor.execute("""
                    UPDATE asset_cache
                    SET last_used = ?, use_count = use_count + 1, job_ids = ?
                    WHERE file_hash = ?
                """, (datetime.now(), ",".join(job_ids), file_hash))
            else:
                # Insert new asset
                file_size = file_path.stat().st_size if file_path.exists() else 0
                cursor.execute("""
                    INSERT INTO asset_cache (file_hash, file_path, file_size, last_used, use_count, job_ids)
                    VALUES (?, ?, ?, ?, 1, ?)
                """, (file_hash, str(file_path), file_size, datetime.now(), job_id))

    def get_cached_asset_path(self, file_hash: str) -> Optional[Path]:
        """
        Get path to a cached asset by hash.

        Args:
            file_hash: Hash of the file

        Returns:
            Path to cached file or None if not found
        """
        if not self.cache_db_path:
            return None

        with self._get_cache_connection() as conn:
            if conn is None:
                return None
            cursor = conn.cursor()

            cursor.execute("SELECT file_path FROM asset_cache WHERE file_hash = ?", (file_hash,))
            row = cursor.fetchone()

            if row:
                path = Path(row["file_path"])
                if path.exists():
                    return path

        return None

    def get_asset_stats(self) -> Dict[str, any]:
        """
        Get statistics about cached assets.

        Returns:
            Dictionary with cache statistics
        """
        if not self.cache_db_path:
            return {}

        with self._get_cache_connection() as conn:
            if conn is None:
                return {}
            cursor = conn.cursor()

            cursor.execute("""
                SELECT 
                    COUNT(*) as total_assets,
                    SUM(file_size) as total_size,
                    SUM(use_count) as total_uses
                FROM asset_cache
            """)
            row = cursor.fetchone()

            if row:
                return {
                    "total_assets": row["total_assets"] or 0,
                    "total_size_bytes": row["total_size"] or 0,
                    "total_uses": row["total_uses"] or 0,
                }

        return {}

    def cleanup_old_assets(self, max_age_days: int = 30, min_uses: int = 1) -> int:
        """
        Clean up old unused assets from cache.

        Args:
            max_age_days: Maximum age in days for unused assets
            min_uses: Minimum number of uses to keep asset

        Returns:
            Number of assets cleaned up
        """
        if not self.cache_db_path:
            return 0

        from datetime import timedelta
        cutoff_date = datetime.now() - timedelta(days=max_age_days)

        with self._get_cache_connection() as conn:
            if conn is None:
                return 0
            cursor = conn.cursor()

            cursor.execute("""
                DELETE FROM asset_cache
                WHERE last_used < ? AND use_count < ?
            """, (cutoff_date, min_uses))

            return cursor.rowcount

    def package_addon(self, addon_path: Path, output_dir: Path) -> Optional[Path]:
        """
        Package an unstructured add-on folder into a distributable zip.
        
        Args:
            addon_path: Path to the installed add-on directory (source)
            output_dir: Directory to save the zip file to
            
        Returns:
            Path to the created zip file, or None if failed.
        """
        if not addon_path.exists():
            return None
            
        output_dir.mkdir(parents=True, exist_ok=True)
        zip_path = output_dir / f"{addon_path.name}.zip"
        
        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                if addon_path.is_dir():
                    for file in addon_path.rglob("*"):
                        if file.name == "__pycache__" or ".git" in file.parts:
                            continue
                        zf.write(file, file.relative_to(addon_path.parent))
                else:
                    zf.write(addon_path, addon_path.name)
            return zip_path
        except Exception as e:
            print(f"❌ Error packaging add-on: {e}")
            return None
