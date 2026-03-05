from .file import FileMap

try:
    from .ldap import LDAPMap
except ImportError:
    pass
