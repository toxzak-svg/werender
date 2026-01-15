"""Synchronization manager for WeRender."""

import hashlib
import json
import shutil
import zipfile
from pathlib import Path
from typing import Dict, List, Optional
import tempfile

class SyncManager:
    """Manages synchronization of settings and add-ons."""

    def __init__(self, config_path: Optional[Path] = None, addons_dir: Optional[Path] = None):
        """
        Initialize the SyncManager.

        Args:
            config_path: Path to the global settings file (werender.json).
            addons_dir: Path to the directory containing add-ons to distribute.
        """
        self.config_path = config_path
        self.addons_dir = addons_dir
        self.cached_manifest: Optional[Dict] = None

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

        return {
            "settings_hash": settings_hash,
            "addons_hash": addons_hash,
            "timestamp": 0, # TODO: add timestamp
        }

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
