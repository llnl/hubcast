import asyncio
import logging
from collections.abc import Generator
from contextlib import contextmanager

import ldap
import ldap.sasl

from hubcast.exceptions import HubcastError
from hubcast.retry import retry_async

from .abc import AccountMap

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 5

# transient failures worth retrying
RETRYABLE_ERRORS = (
    ldap.SERVER_DOWN,
    ldap.TIMEOUT,
    ldap.BUSY,
    ldap.UNAVAILABLE,
)


@contextmanager
def ldap_connection(
    uri: str, timeout: int = DEFAULT_TIMEOUT
) -> Generator[ldap.ldapobject.LDAPObject, None, None]:
    """
    Manages context for python-ldap connections.
    Yields the connection and unbinds on exit.
    """

    conn = ldap.initialize(uri)
    # OPT_NETWORK_TIMEOUT only covers initial connect, OPT_NETWORK is for bind/search operations
    conn.set_option(ldap.OPT_NETWORK_TIMEOUT, timeout)
    conn.set_option(ldap.OPT_TIMEOUT, timeout)
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
    bind_dn : str | None
        optional DN for simple bind (falls back to GSSAPI if None)
    bind_password : str | None
        password for simple bind (ignored when using GSSAPI)
    timeout : int
        timeout in seconds for operations
    """

    def __init__(
        self,
        uri: str,
        search_base: str,
        input_attr: str,
        output_attr: str,
        search_scope: int,
        bind_dn: str | None = None,
        bind_password: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.uri = uri
        self.search_base = search_base
        self.input_attr = input_attr
        self.output_attr = output_attr
        self.search_scope = search_scope
        self.bind_dn = bind_dn
        self.bind_password = bind_password
        self.timeout = timeout

    async def __call__(self, source_user: str) -> str | None:
        """
        Async wrapper around the blocking python-ldap lookup; runs it in a
        thread to keep the event loop free. Retries on transient LDAP errors.

        Returns None if not found.
        """

        try:
            return await retry_async(
                lambda: asyncio.to_thread(self._query, source_user),
                RETRYABLE_ERRORS,
                name="LDAP query",
            )
        except ldap.LDAPError as e:
            raise HubcastError(
                f"LDAP query failed: {type(e).__name__}: {e}",
                base=self.search_base,
                filterstr=f"({self.input_attr}={source_user})",
            ) from e

    def _query(self, source_user: str) -> str | None:
        """
        searches the LDAP endpoint for source_user within the search_base and returns
        the value of output_attr.
        Simple bind auth is used if bind_dn is set; otherwise uses SASL/GSSAPI (kerberos).

        Returns None if not found; raises ldap.LDAPError on LDAP errors.
        """

        filterstr = f"({self.input_attr}={source_user})"
        with ldap_connection(self.uri, self.timeout) as conn:
            if self.bind_dn:
                log.debug("Performing simple bind", extra={"bind_dn": self.bind_dn})
                conn.simple_bind_s(self.bind_dn, self.bind_password or "")
            else:
                log.debug("Performing SASL/GSSAPI bind (kerberos)")
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
                "No LDAP entry found",
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
                "Attribute not present in LDAP entry",
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
