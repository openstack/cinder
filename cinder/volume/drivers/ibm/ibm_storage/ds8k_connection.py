#  Copyright (c) 2016 IBM Corporation
#  All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
#
import datetime
import hashlib
import re
import ssl

from oslo_log import log as logging
from requests.packages.urllib3 import connection
from requests.packages.urllib3 import connectionpool
from requests.packages.urllib3 import poolmanager

from cinder.i18n import _

LOG = logging.getLogger(__name__)

try:
    from OpenSSL.crypto import FILETYPE_ASN1
    from OpenSSL.crypto import load_certificate
except ImportError:
    load_certificate = None
    FILETYPE_ASN1 = None

_PEM_RE = re.compile(u"""-----BEGIN CERTIFICATE-----\r?
.+?\r?-----END CERTIFICATE-----\r?\n?""", re.DOTALL)


class DS8KHTTPSConnection(connection.VerifiedHTTPSConnection):
    """Extend the HTTPS Connection to do our own Certificate Verification."""

    def _verify_cert(self, sock, ca_certs):
        # If they asked us to not verify the Certificate then nothing to do
        if not ca_certs:
            return

        # Retrieve the Existing Certificates from the File in Binary Form
        peercert = sock.getpeercert(True)
        try:
            with open(ca_certs, 'r') as f:
                certs_str = f.read()
        except Exception:
            raise ssl.SSLError(_("Failed to read certificate from %s")
                               % ca_certs)

        # Verify the Existing Certificates
        found = False
        certs = [match.group(0) for match in _PEM_RE.finditer(certs_str)]
        for cert in certs:
            existcert = ssl.PEM_cert_to_DER_cert(cert)
            # First check to make sure the 2 certificates are the same ones
            if (hashlib.sha256(existcert).digest() ==
                    hashlib.sha256(peercert).digest()):
                found = True
                break
        if not found:
            raise ssl.SSLError(
                _("The certificate doesn't match the trusted one "
                    "in %s.") % ca_certs)

        if load_certificate is None and FILETYPE_ASN1 is None:
            raise ssl.SSLError(
                _("Missing 'pyOpenSSL' python module, ensure the "
                    "library is installed."))

        # Throw an exception if the certificate given to us has expired
        x509 = load_certificate(FILETYPE_ASN1, peercert)
        if x509.has_expired():
            raise ssl.SSLError(
                _("The certificate expired: %s") % x509.get_notAfter())

    def connect(self):
        """Override the Connect Method to fix the Certificate Verification."""
        # Add certificate verification
        conn = self._new_conn()

        if getattr(self, '_tunnel_host', None):
            # _tunnel_host was added in Python 2.6.3
            # (See: http://hg.python.org/cpython/rev/0f57b30a152f)

            self.sock = conn
            # Calls self._set_hostport(), so self.host is
            # self._tunnel_host below.
            #
            # disable pylint because pylint doesn't support importing
            # from six.moves yet. see:
            # https://bitbucket.org/logilab/pylint/issue/550/
            self._tunnel()  # pylint: disable=E1101
            # Mark this connection as not reusable
            self.auto_open = 0

        # The RECENT_DATE is originally taken from requests. The date is just
        # an arbitrary value that is used as a sanity test to identify hosts
        # that are using the default time after bootup (e.g. 1970), and
        # provides information for debugging
        RECENT_DATE = datetime.date(2014, 1, 1)
        is_time_off = datetime.date.today() < RECENT_DATE
        if is_time_off:
            LOG.warning('System time is way off (before %s). This will '
                        'probably lead to SSL verification errors.',
                        RECENT_DATE)

        # Wrap socket using verification with the root certs in
        # trusted_root_certs
        context = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
        self.sock = context.wrap_socket(conn)

        self._verify_cert(self.sock, self.ca_certs)
        self.is_verified = True

    def putrequest(self, method, url, **kwargs):
        """Override the Put Request method take the DS8K off of the URL."""
        if url and url.startswith('httpsds8k://'):
            url = 'https://' + url[12:]
        return super(DS8KHTTPSConnection,
                     self).putrequest(method, url, **kwargs)

    def request(self, method, url, **kwargs):
        """Override the Request method take the DS8K off of the URL."""
        if url and url.startswith('httpsds8k://'):
            url = 'https://' + url[12:]
        return super(DS8KHTTPSConnection, self).request(method, url, **kwargs)


class DS8KConnectionPool(connectionpool.HTTPSConnectionPool):
    """Extend the HTTPS Connection Pool to our own Certificate verification."""

    scheme = 'httpsds8k'
    ConnectionCls = DS8KHTTPSConnection

    def urlopen(self, method, url, **kwargs):
        """Override URL Open method to take DS8K out of the URL protocol."""
        if url and url.startswith('httpsds8k://'):
            url = 'https://' + url[12:]
        return super(DS8KConnectionPool, self).urlopen(method, url, **kwargs)

if hasattr(poolmanager, 'key_fn_by_scheme'):
    poolmanager.key_fn_by_scheme["httpsds8k"] = (
        poolmanager.key_fn_by_scheme["https"])
poolmanager.pool_classes_by_scheme["httpsds8k"] = DS8KConnectionPool
