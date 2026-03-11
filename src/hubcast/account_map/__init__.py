from .file import FileMap

__all__ = ["FileMap"]

try:
    from .ldap import LDAPMap

    __all__.append("LDAPMap")
except ImportError:
    pass
