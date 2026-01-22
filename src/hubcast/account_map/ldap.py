import logging
from contextlib import contextmanager
from typing import Optional, Union

import ldap
import ldap.sasl

from .abc import AccountMap

log = logging.getLogger(__name__)

# 5 seconds (default is ~30, which is too long)
ldap.set_option(ldap.OPT_NETWORK_TIMEOUT, 5)


@contextmanager
def ldap_connection(uri: str):
    """
    Manages context for python-ldap connections.
    Yields the connection and unbinds on exit.
    """

    conn = ldap.initialize(uri)
    try:
        yield conn
    finally:
        try:
            conn.unbind_s()
        except ldap.LDAPError:
            log.exception("Failed to unbind LDAP connection")


class LDAPMap(AccountMap):
    """
    A user map pairing two LDAP attributes within a search scope. For example: githubId: uid.

    Attributes
    ----------
    uri : str
        the LDAP URI, eg: "ldaps://dir-server.example.com:636"
    search_base : str
        the distinguished name to search from, eg:
        ou=accounts,dc=example,dc=com
    input_attr: str
        the attribute to search for in the directory, eg: githubId
    output_attr : str
        the attribute to select as output, eg: uid
    search_scope : int
        one of ldap.SCOPE_BASE, ldap.SCOPE_ONELEVEL, ldap.SCOPE_SUBTREE
    bind_dn : Optional[str]
        optional DN for simple bind (falls back to GSSAPI if None)
    bind_password : Optional[str]
        password for simple bind (ignored when using GSSAPI)
    """

    def __init__(
        self,
        uri: str,
        search_base: str,
        input_attr: str,
        output_attr: str,
        search_scope: int,
        bind_dn: Optional[str] = None,
        bind_password: Optional[str] = None,
    ):
        self.uri = uri
        self.search_base = search_base
        self.input_attr = input_attr
        self.output_attr = output_attr
        self.search_scope = search_scope
        self.bind_dn = bind_dn
        self.bind_password = bind_password

    def __call__(self, input_val: str) -> Union[str, None]:
        """
        searches the LDAP endpoint for input_val within the search_base and returns
        the value of output_attr.
        Simple bind auth is used if bind_dn is set; otherwise uses SASL/GSSAPI (kerberos).

        Returns None if not found or on error.
        """

        filterstr = f"({self.input_attr}={input_val})"
        try:
            with ldap_connection(self.uri) as conn:
                if self.bind_dn:
                    log.debug("performing simple bind", extra={"bind_dn": self.bind_dn})
                    conn.simple_bind_s(self.bind_dn, self.bind_password or "")
                else:
                    log.debug("performing SASL/GSSAPI bind (kerberos)")
                    sasl_creds = ldap.sasl.gssapi()
                    conn.sasl_interactive_bind_s("", sasl_creds)

                result = conn.search_s(
                    self.search_base,
                    self.search_scope,
                    filterstr,
                    attrlist=[self.output_attr],
                )

            if not result:
                log.debug(
                    "no LDAP entry found",
                    extra={
                        "base": self.search_base,
                        "filterstr": filterstr,
                        "output_attr": self.output_attr,
                    },
                )
                return None

            # attrs is a map between attributes (str) and values (list of encoded strings)
            attrs = result[0][1]
            values = attrs.get(self.output_attr)
            if not values:
                log.error(
                    "attribute not present in LDAP entry",
                    extra={
                        "base": self.search_base,
                        "filterstr": filterstr,
                        "output_attr": self.output_attr,
                    },
                )
                return None

            # selecting first value (input/output attributes should be a unique mapping)
            val = values[0]
            return val.decode() if isinstance(val, bytes) else val

        except ldap.LDAPError:
            log.exception(
                "LDAP query failed",
                extra={"base": self.search_base, "filterstr": filterstr},
            )

        return None
