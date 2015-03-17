# Copyright (c) 2012 - 2015 EMC Corporation.
# All Rights Reserved.
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

import base64
import httplib
import os
import socket
import ssl
import string
import struct
import urllib

from eventlet import patcher
import OpenSSL
from oslo_log import log as logging
import six

from cinder.i18n import _, _LI

# Handle case where we are running in a monkey patched environment
if patcher.is_monkey_patched('socket'):
    from eventlet.green.OpenSSL import SSL
else:
    raise ImportError

try:
    import pywbem
    pywbemAvailable = True
except ImportError:
    pywbemAvailable = False


LOG = logging.getLogger(__name__)


def to_bytes(s):
    if isinstance(s, six.string_types):
        return six.b(s)
    else:
        return s


def get_default_ca_certs():
    """Gets the default CA certificates if found, otherwise None.

    Try to find out system path with ca certificates. This path is cached and
    returned. If no path is found out, None is returned.
    """
    if not hasattr(get_default_ca_certs, '_path'):
        for path in (
                '/etc/pki/ca-trust/extracted/openssl/ca-bundle.trust.crt',
                '/etc/ssl/certs',
                '/etc/ssl/certificates'):
            if os.path.exists(path):
                get_default_ca_certs._path = path
                break
        else:
            get_default_ca_certs._path = None
    return get_default_ca_certs._path


class OpenSSLConnectionDelegator(object):
    """An OpenSSL.SSL.Connection delegator.

    Supplies an additional 'makefile' method which httplib requires
    and is not present in OpenSSL.SSL.Connection.
    Note: Since it is not possible to inherit from OpenSSL.SSL.Connection
    a delegator must be used.
    """
    def __init__(self, *args, **kwargs):
        self.connection = SSL.GreenConnection(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def makefile(self, *args, **kwargs):
        return socket._fileobject(self.connection, *args, **kwargs)


class HTTPSConnection(httplib.HTTPSConnection):
    def __init__(self, host, port=None, key_file=None, cert_file=None,
                 strict=None, ca_certs=None, no_verification=False):
        if not pywbemAvailable:
            LOG.info(_LI(
                'Module PyWBEM not installed.  '
                'Install PyWBEM using the python-pywbem package.'))
        if six.PY3:
            excp_lst = (TypeError, ssl.SSLError)
        else:
            excp_lst = ()
        try:
            httplib.HTTPSConnection.__init__(self, host, port,
                                             key_file=key_file,
                                             cert_file=cert_file)

            self.key_file = None if key_file is None else key_file
            self.cert_file = None if cert_file is None else cert_file
            self.insecure = no_verification
            self.ca_certs = (
                None if ca_certs is None else six.text_type(ca_certs))
            self.set_context()
            # ssl exceptions are reported in various form in Python 3
            # so to be compatible, we report the same kind as under
            # Python2
        except excp_lst as e:
            raise pywbem.cim_http.Error(six.text_type(e))

    @staticmethod
    def host_matches_cert(host, x509):
        """Verify that the certificate matches host.

        Verify that the x509 certificate we have received
        from 'host' correctly identifies the server we are
        connecting to, ie that the certificate's Common Name
        or a Subject Alternative Name matches 'host'.
        """
        def check_match(name):
            # Directly match the name.
            if name == host:
                return True

            # Support single wildcard matching.
            if name.startswith('*.') and host.find('.') > 0:
                if name[2:] == host.split('.', 1)[1]:
                    return True

        common_name = x509.get_subject().commonName
        # First see if we can match the CN.
        if check_match(common_name):
            return True
            # Also try Subject Alternative Names for a match.
        san_list = None
        for i in range(x509.get_extension_count()):
            ext = x509.get_extension(i)
            if ext.get_short_name() == b'subjectAltName':
                san_list = six.text_type(ext)
                for san in ''.join(san_list.split()).split(','):
                    if san.startswith('DNS:'):
                        if check_match(san.split(':', 1)[1]):
                            return True

        # Server certificate does not match host.
        msg = (_("Host %(host)s does not match x509 certificate contents: "
                 "CommonName %(commonName)s.")
               % {'host': host,
                  'commonName': common_name})

        if san_list is not None:
            msg = (_("%(message)s, subjectAltName: %(sanList)s.")
                   % {'message': msg,
                      'sanList': san_list})
        raise pywbem.cim_http.AuthError(msg)

    def verify_callback(self, connection, x509, errnum,
                        depth, preverify_ok):
        if x509.has_expired():
            msg = msg = (_("SSL Certificate expired on %s.")
                         % x509.get_notAfter())
            raise pywbem.cim_http.AuthError(msg)

        if depth == 0 and preverify_ok:
            # We verify that the host matches against the last
            # certificate in the chain.
            return self.host_matches_cert(self.host, x509)
        else:
            # Pass through OpenSSL's default result.
            return preverify_ok

    def set_context(self):
        """Set up the OpenSSL context."""
        self.context = OpenSSL.SSL.Context(OpenSSL.SSL.SSLv23_METHOD)

        if self.insecure is not True:
            self.context.set_verify(OpenSSL.SSL.VERIFY_PEER,
                                    self.verify_callback)
        else:
            self.context.set_verify(OpenSSL.SSL.VERIFY_NONE,
                                    lambda *args: True)

        if self.cert_file:
            try:
                self.context.use_certificate_file(self.cert_file)
            except Exception as e:
                msg = (_("Unable to load cert from %(cert)s %(e)s.")
                       % {'cert': self.cert_file,
                          'e': e})
                raise pywbem.cim_http.AuthError(msg)
            if self.key_file is None:
                # We support having key and cert in same file.
                try:
                    self.context.use_privatekey_file(self.cert_file)
                except Exception as e:
                    msg = (_("No key file specified and unable to load key "
                             "from %(cert)s %(e)s.")
                           % {'cert': self.cert_file,
                              'e': e})
                    raise pywbem.cim_http.AuthError(msg)

        if self.key_file:
            try:
                self.context.use_privatekey_file(self.key_file)
            except Exception as e:
                msg = (_("Unable to load key from %(cert)s %(e)s.")
                       % {'cert': self.cert_file,
                          'e': e})
                raise pywbem.cim_http.AuthError(msg)

        if self.ca_certs:
            try:
                self.context.load_verify_locations(to_bytes(self.ca_certs))
            except Exception as e:
                msg = (_("Unable to load CA from %(cert)s %(e)s.")
                       % {'cert': self.cert_file,
                          'e': e})
                raise pywbem.cim_http.AuthError(msg)
        else:
            self.context.set_default_verify_paths()

    def connect(self):
        result = socket.getaddrinfo(self.host, self.port, 0,
                                    socket.SOCK_STREAM)
        if result:
            socket_family = result[0][0]
            if socket_family == socket.AF_INET6:
                sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            else:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        else:
            # If due to some reason the address lookup fails - we still
            # connect to IPv4 socket. This retains the older behavior.
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if self.timeout is not None:
            # '0' microseconds
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVTIMEO,
                            struct.pack('LL', 0, 0))
        self.sock = OpenSSLConnectionDelegator(self.context, sock)
        self.sock.connect((self.host, self.port))


def wbem_request(url, data, creds, headers=None, debug=0, x509=None,
                 verify_callback=None, ca_certs=None,
                 no_verification=False):
    """Send request over HTTP.

    Send XML data over HTTP to the specified url. Return the
    response in XML.  Uses Python's build-in httplib.  x509 may be a
    dictionary containing the location of the SSL certificate and key
    files.
    """

    if headers is None:
        headers = []

    host, port, use_ssl = pywbem.cim_http.parse_url(url)
    key_file = None
    cert_file = None
    if use_ssl and x509 is not None:
        cert_file = x509.get('cert_file')
        key_file = x509.get('key_file')

    numTries = 0
    localAuthHeader = None
    tryLimit = 5

    if isinstance(data, unicode):
        data = data.encode('utf-8')
    data = '<?xml version="1.0" encoding="utf-8" ?>\n' + data

    if not no_verification and ca_certs is None:
        ca_certs = get_default_ca_certs()
    elif no_verification:
        ca_certs = None

    if use_ssl:
        h = HTTPSConnection(
            host,
            port=port,
            key_file=key_file,
            cert_file=cert_file,
            ca_certs=ca_certs,
            no_verification=no_verification)

    locallogin = None
    while numTries < tryLimit:
        numTries = numTries + 1

        h.putrequest('POST', '/cimom')
        h.putheader('Content-type', 'application/xml; charset="utf-8"')
        h.putheader('Content-length', len(data))
        if localAuthHeader is not None:
            h.putheader(*localAuthHeader)
        elif creds is not None:
            h.putheader('Authorization', 'Basic %s' %
                        base64.encodestring('%s:%s' % (creds[0], creds[1]))
                        .replace('\n', ''))
        elif locallogin is not None:
            h.putheader('PegasusAuthorization', 'Local "%s"' % locallogin)

        for hdr in headers:
            if isinstance(hdr, unicode):
                hdr = hdr.encode('utf-8')
            s = map(lambda x: string.strip(x), string.split(hdr, ":", 1))
            h.putheader(urllib.quote(s[0]), urllib.quote(s[1]))

        try:
            h.endheaders()
            try:
                h.send(data)
            except socket.error as arg:
                if arg[0] != 104 and arg[0] != 32:
                    raise

            response = h.getresponse()
            body = response.read()

            if response.status != 200:
                raise pywbem.cim_http.Error('HTTP error')

        except httplib.BadStatusLine as arg:
            msg = (_("Bad Status line returned: %(arg)s.")
                   % {'arg': arg})
            raise pywbem.cim_http.Error(msg)
        except socket.error as arg:
            msg = (_("Socket error:: %(arg)s.")
                   % {'arg': arg})
            raise pywbem.cim_http.Error(msg)
        except socket.sslerror as arg:
            msg = (_("SSL error: %(arg)s.")
                   % {'arg': arg})
            raise pywbem.cim_http.Error(msg)

        break

    return body
