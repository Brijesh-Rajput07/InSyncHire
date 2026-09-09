# LOCATION: shared/permissions/permissions/__init__.py

"""
Canonical PERMISSION_MATRIX (FIX-M3). Every service's auth/role
enforcement imports from here instead of defining permissions inline.
"""

from .matrix import PERMISSION_MATRIX, find_matrix_entry, is_allowed

__all__ = ["PERMISSION_MATRIX", "find_matrix_entry", "is_allowed"]
