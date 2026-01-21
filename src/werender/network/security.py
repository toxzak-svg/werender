"""Security utilities for WeRender."""

import struct
import hashlib
from pathlib import Path
from typing import Optional, Tuple


class BlendFileValidator:
    """Validates .blend files for security."""

    # Magic bytes for .blend files
    BLEND_MAGIC = b'BLENDER'
    BLEND_MAGIC_64BIT = b'BLENDER'  # Same for 32 and 64 bit
    
    # Maximum file size (500 MB)
    MAX_FILE_SIZE = 500 * 1024 * 1024
    
    # File header structure
    HEADER_SIZE = 12  # Magic (7) + Pointer size (1) + Endianness (1) + Version (3)
    
    @staticmethod
    def validate_blend_file(file_path: Path) -> Tuple[bool, Optional[str]]:
        """
        Validate a .blend file for security risks.
        
        Args:
            file_path: Path to the .blend file
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not file_path.exists():
            return False, "File does not exist"
        
        # Check file size
        file_size = file_path.stat().st_size
        if file_size > BlendFileValidator.MAX_FILE_SIZE:
            return False, f"File too large ({file_size / 1024 / 1024:.1f} MB exceeds {BlendFileValidator.MAX_FILE_SIZE / 1024 / 1024} MB limit)"
        
        if file_size < BlendFileValidator.HEADER_SIZE:
            return False, "File too small to be a valid .blend file"
        
        # Check file extension
        if file_path.suffix.lower() != '.blend':
            return False, "File must have .blend extension"
        
        # Validate magic bytes
        try:
            with open(file_path, 'rb') as f:
                header = f.read(BlendFileValidator.HEADER_SIZE)
                
                # Check BLENDER magic bytes
                if not header.startswith(BlendFileValidator.BLEND_MAGIC):
                    return False, "Invalid .blend file: missing magic bytes"
                
                # Extract and validate pointer size
                pointer_size = header[7:8].decode('ascii', errors='ignore')
                if pointer_size not in ['_', '-']:
                    return False, f"Invalid pointer size in .blend file header"
                
                # Extract and validate endianness
                endianness = header[8:9].decode('ascii', errors='ignore')
                if endianness not in ['v', 'V']:
                    return False, f"Invalid endianness in .blend file header"
                
                # Extract and validate version
                version = header[9:12].decode('ascii', errors='ignore')
                if not version.isdigit():
                    return False, f"Invalid version in .blend file header"
                
        except Exception as e:
            return False, f"Error reading .blend file header: {e}"
        
        # Use python-magic for deeper validation if available
        try:
            import magic
            mime = magic.Magic(mime=True)
            file_type = mime.from_file(str(file_path))
            
            # Blender files should be application/x-blender or application/octet-stream
            if file_type not in ['application/x-blender', 'application/octet-stream']:
                # Don't fail hard, but warn - some systems might not recognize .blend files
                print(f"⚠️  Warning: Unusual file type detected: {file_type}")
        except ImportError:
            # python-magic not available, skip this check
            pass
        except Exception as e:
            print(f"⚠️  Warning: Could not verify file type with libmagic: {e}")
        
        return True, None
    
    @staticmethod
    def calculate_file_hash(file_path: Path) -> str:
        """
        Calculate SHA256 hash of a file.
        
        Args:
            file_path: Path to the file
            
        Returns:
            Hexadecimal hash string
        """
        hash_sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_sha256.update(chunk)
        return hash_sha256.hexdigest()
    
    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """
        Sanitize a filename to prevent path traversal attacks.
        
        Args:
            filename: Original filename
            
        Returns:
            Sanitized filename
        """
        # Remove path components
        filename = Path(filename).name
        
        # Remove any non-printable characters and limit length
        filename = ''.join(c for c in filename if c.isprintable() and c not in ['\0', '\n', '\r'])
        
        # Limit filename length
        if len(filename) > 255:
            filename = filename[:255]
        
        # Ensure it has .blend extension
        if not filename.lower().endswith('.blend'):
            filename += '.blend'
        
        return filename


class RateLimiter:
    """Simple in-memory rate limiter."""
    
    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        """
        Initialize rate limiter.
        
        Args:
            max_requests: Maximum requests per window
            window_seconds: Time window in seconds
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests = {}
    
    def is_allowed(self, identifier: str) -> bool:
        """
        Check if request is allowed.
        
        Args:
            identifier: Unique identifier (e.g., IP address)
            
        Returns:
            True if allowed, False otherwise
        """
        import time
        
        current_time = time.time()
        
        if identifier not in self.requests:
            self.requests[identifier] = []
        
        # Remove old requests outside the window
        self.requests[identifier] = [
            timestamp for timestamp in self.requests[identifier]
            if current_time - timestamp < self.window_seconds
        ]
        
        # Check if limit exceeded
        if len(self.requests[identifier]) >= self.max_requests:
            return False
        
        # Add current request
        self.requests[identifier].append(current_time)
        return True
    
    def reset(self, identifier: str) -> None:
        """Reset rate limit for identifier."""
        if identifier in self.requests:
            del self.requests[identifier]