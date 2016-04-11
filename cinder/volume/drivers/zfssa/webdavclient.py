# Copyright (c) 2014, 2015, Oracle and/or its affiliates. All rights reserved.
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
"""
ZFS Storage Appliance WebDAV Client
"""

import time

from oslo_log import log
from six.moves import http_client
from six.moves import urllib

from cinder import exception
from cinder.i18n import _, _LE

LOG = log.getLogger(__name__)

bad_gateway_err = _('Check the state of the http service. Also ensure that '
                    'the https port number is the same as the one specified '
                    'in cinder.conf.')

WebDAVHTTPErrors = {
    http_client.UNAUTHORIZED: _('User not authorized to perform WebDAV '
                                'operations.'),
    http_client.BAD_GATEWAY: bad_gateway_err,
    http_client.FORBIDDEN: _('Check access permissions for the ZFS share '
                             'assigned to this driver.'),
    http_client.NOT_FOUND: _('The source volume for this WebDAV operation not '
                             'found.'),
    http_client.INSUFFICIENT_STORAGE: _('Not enough storage space in the ZFS '
                                        'share to perform this operation.')
}

WebDAVErrors = {
    'BadStatusLine': _('http service may have been abruptly disabled or put '
                       'to maintenance state in the middle of this '
                       'operation.'),
    'Bad_Gateway': bad_gateway_err
}

propertyupdate_data = """<?xml version="1.0"?>
    <D:propertyupdate xmlns:D="DAV:">
    <D:set>
        <D:prop>
            <D:prop_name>prop_val</D:prop_name>
        </D:prop>
    </D:set>
    </D:propertyupdate>"""


class ZFSSAWebDAVClient(object):
    def __init__(self, url, auth_str, **kwargs):
        """Initialize WebDAV Client"""
        self.https_path = url
        self.auth_str = auth_str

    def _lookup_error(self, error):
        msg = ''
        if error in http_client.responses:
            msg = http_client.responses[error]

        if error in WebDAVHTTPErrors:
            msg = WebDAVHTTPErrors[error]
        elif error in WebDAVErrors:
            msg = WebDAVErrors[error]

        return msg

    def build_data(self, data, propname, value):
        res = data.replace('prop_name', propname)
        res = res.replace('prop_val', value)
        return res

    def set_file_prop(self, filename, propname, propval):
        data = self.build_data(propertyupdate_data, propname, propval)
        return self.request(src_file=filename, data=data, method='PROPPATCH')

    def request(self, src_file="", dst_file="", method="", maxretries=10,
                data=""):
        retry = 0
        src_url = self.https_path + "/" + src_file
        dst_url = self.https_path + "/" + dst_file
        request = urllib.request.Request(url=src_url, data=data)

        if dst_file != "":
            request.add_header('Destination', dst_url)
        if method == "PROPPATCH":
            request.add_header('Translate', 'F')

        request.add_header("Authorization", "Basic %s" % self.auth_str)

        request.get_method = lambda: method

        LOG.debug('Sending WebDAV request:%(method)s %(src)s %(des)s',
                  {'method': method, 'src': src_url, 'des': dst_url})

        while retry < maxretries:
            try:
                response = urllib.request.urlopen(request, timeout=None)
            except urllib.error.HTTPError as err:
                LOG.error(_LE('WebDAV returned with %(code)s error during '
                              '%(method)s call.'),
                          {'code': err.code, 'method': method})

                if err.code == http_client.INTERNAL_SERVER_ERROR:
                    LOG.error(_LE('WebDAV operation failed with error code: '
                                  '%(code)s reason: %(reason)s Retry attempt '
                                  '%(retry)s in progress.'),
                              {'code': err.code,
                               'reason': err.reason,
                               'retry': retry})
                    if retry < maxretries:
                        retry += 1
                        time.sleep(1)
                        continue

                msg = self._lookup_error(err.code)
                raise exception.WebDAVClientError(msg=msg, code=err.code,
                                                  src=src_file, dst=dst_file,
                                                  method=method)

            except http_client.BadStatusLine as err:
                msg = self._lookup_error('BadStatusLine')
                code = 'http_client.BadStatusLine'
                raise exception.WebDAVClientError(msg=msg,
                                                  code=code,
                                                  src=src_file, dst=dst_file,
                                                  method=method)

            except urllib.error.URLError as err:
                reason = ''
                if getattr(err, 'reason'):
                    reason = err.reason

                msg = self._lookup_error('Bad_Gateway')
                raise exception.WebDAVClientError(msg=msg,
                                                  code=reason, src=src_file,
                                                  dst=dst_file, method=method)

            break
        return response
