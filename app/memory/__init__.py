"""UCI Course Advisor memory module.

Public API:
    get_memory_manager() — fetch the singleton MemoryManager
    MemoryProvider       — abstract base class for new backends
"""

from app.memory.manager import get_memory_manager
from app.memory.base import MemoryProvider

__all__ = ["get_memory_manager", "MemoryProvider"]
