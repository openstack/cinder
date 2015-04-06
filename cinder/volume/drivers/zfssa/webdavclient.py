# Copyright (c) 2014, Oracle and/or its affiliates. All rights reserved.
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

import httplib
import time
import urllib2

from oslo_log import log

from cinder import exception
from cinder.i18n import _, _LE

LOG = log.getLogger(__name__)

bad_gateway_err = _('Check the state of the http service. Also ensure that '
                    'the https port number is the same as the one specified '
                    'in cinder.conf.')

WebDAVHTTPErrors = {
    httplib.UNAUTHORIZED: _('User not authorized to perform WebDAV '
                            'operations.'),
    httplib.BAD_GATEWAY: bad_gateway_err,
    httplib.FORBIDDEN: _('Check access permissions for the ZFS share assigned '
                         'to this driver.'),
    httplib.NOT_FOUND: _('The source volume for this WebDAV operation not '
                         'found.'),
    httplib.INSUFFICIENT_STORAGE: _('Not enough storage space in the ZFS '
                                    'share to perform this operation.')
}

WebDAVErrors = {
    'BadStatusLine': _('http service may have been abruptly disabled or put '
                       'to maintenance state in the middle of this '
                       'operation.'),
    'Bad_Gateway': bad_gateway_err
}


class ZFSSAWebDAVClient(object):
    def __init__(self, url, auth_str, **kwargs):
        """Initialize WebDAV Client"""
        self.https_path = url
        self.auth_str = auth_str

    def _lookup_error(self, error):
        msg = ''
        if error in httplib.responses:
            msg = httplib.responses[error]

        if error in WebDAVHTTPErrors:
            msg = WebDAVHTTPErrors[error]
        elif error in WebDAVErrors:
            msg = WebDAVErrors[error]

        return msg

    def request(self, src_file="", dst_file="", method="", maxretries=10):
        retry = 0
        src_url = self.https_path + "/" + src_file
        dst_url = self.https_path + "/" + dst_file
        request = urllib2.Request(src_url)

        if dst_file != "":
            request.add_header('Destination', dst_url)

        request.add_header("Authorization", "Basic %s" % self.auth_str)

        request.get_method = lambda: method

        LOG.debug('Sending WebDAV request:%s %s %s' % (method, src_url,
                  dst_url))

        while retry < maxretries:
            try:
                response = urllib2.urlopen(request, timeout=None)
            except urllib2.HTTPError as err:
                LOG.error(_LE('WebDAV returned with %(code)s error during '
                              '%(method)s call.')
                          % {'code': err.code,
                             'method': method})

                if err.code == httplib.INTERNAL_SERVER_ERROR:
                    exception_msg = (_('WebDAV operation failed with '
                                       'error code: %(code)s '
                                       'reason: %(reason)s '
                                       'Retry attempt %(retry)s in progress.')
                                     % {'code': err.code,
                                        'reason': err.reason,
                                        'retry': retry})
                    LOG.error(exception_msg)
                    if retry < maxretries:
                        retry += 1
                        time.sleep(1)
                        continue

                msg = self._lookup_error(err.code)
                raise exception.WebDAVClientError(msg=msg, code=err.code,
                                                  src=src_file, dst=dst_file,
                                                  method=method)

            except httplib.BadStatusLine as err:
                msg = self._lookup_error('BadStatusLine')
                raise exception.WebDAVClientError(msg=msg,
                                                  code='httplib.BadStatusLine',
                                                  src=src_file, dst=dst_file,
                                                  method=method)

            except urllib2.URLError as err:
                reason = ''
                if getattr(err, 'reason'):
                    reason = err.reason

                msg = self._lookup_error('Bad_Gateway')
                raise exception.WebDAVClientError(msg=msg,
                                                  code=reason, src=src_file,
                                                  dst=dst_file, method=method)

            break
        return response
