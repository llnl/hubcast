from .file import FileMap

__all__ = ["FileMap"]

try:
    from .ldap import LDAPMap  # noqa: F401

    __all__.append("LDAPMap")
except ImportError:  # pragma: no cover
    pass  # LDAP support is optional
