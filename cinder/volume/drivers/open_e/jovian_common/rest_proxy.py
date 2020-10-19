#    Copyright (c) 2020 Open-E, Inc.
#    All Rights Reserved.
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

"""Network connection handling class for JovianDSS driver."""

import json
import time

from oslo_log import log as logging
from oslo_utils import netutils as o_netutils
import requests
import urllib3

from cinder import exception
from cinder.i18n import _
from cinder.volume.drivers.open_e.jovian_common import exception as jexc


LOG = logging.getLogger(__name__)


class JovianRESTProxy(object):
    """Jovian REST API proxy."""

    def __init__(self, config):
        """:param config: config is like dict."""

        self.proto = 'http'
        if config.get('driver_use_ssl', True):
            self.proto = 'https'

        self.hosts = config.safe_get('san_hosts')
        self.port = str(config.get('san_api_port', 82))

        self.active_host = 0

        for host in self.hosts:
            if o_netutils.is_valid_ip(host) is False:
                err_msg = ('Invalid value of jovian_host property: '
                           '%(addr)s, IP address expected.' %
                           {'addr': host})

                LOG.debug(err_msg)
                raise exception.InvalidConfigurationValue(err_msg)

        self.api_path = "/api/v3"
        self.delay = config.get('jovian_recovery_delay', 40)

        self.pool = config.safe_get('jovian_pool')

        self.user = config.get('san_login', 'admin')
        self.password = config.get('san_password', 'admin')
        self.auth = requests.auth.HTTPBasicAuth(self.user, self.password)
        self.verify = False
        self.retry_n = config.get('jovian_rest_send_repeats', 3)
        self.header = {'connection': 'keep-alive',
                       'Content-Type': 'application/json',
                       'authorization': 'Basic '}
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def _get_pool_url(self, host):
        url = ('%(proto)s://%(host)s:%(port)s/api/v3/pools/%(pool)s' % {
            'proto': self.proto,
            'host': host,
            'port': self.port,
            'pool': self.pool})
        return url

    def _get_url(self, host):
        url = ('%(proto)s://%(host)s:%(port)s/api/v3' % {
            'proto': self.proto,
            'host': host,
            'port': self.port})
        return url

    def request(self, request_method, req, json_data=None):
        """Send request to the specific url.

        :param request_method: GET, POST, DELETE
        :param url: where to send
        :param json_data: data
        """
        for j in range(self.retry_n):
            for i in range(len(self.hosts)):
                host = self.hosts[self.active_host]
                url = self._get_url(host) + req

                LOG.debug(
                    "sending request of type %(type)s to %(url)s "
                    "attempt: %(num)s.",
                    {'type': request_method,
                     'url': url,
                     'num': j})

                if json_data is not None:
                    LOG.debug(
                        "sending data: %s.", json_data)
                try:

                    ret = self._request_routine(url, request_method, json_data)
                    if len(ret) == 0:
                        self.active_host = ((self.active_host + 1)
                                            % len(self.hosts))
                        continue
                    return ret

                except requests.ConnectionError as err:
                    LOG.debug("Connection error %s", err)
                    self.active_host = (self.active_host + 1) % len(self.hosts)
                    continue
            time.sleep(self.delay)

        msg = (_('%(times)s faild in a row') % {'times': j})

        raise jexc.JDSSRESTProxyException(host=url, reason=msg)

    def pool_request(self, request_method, req, json_data=None):
        """Send request to the specific url.

        :param request_method: GET, POST, DELETE
        :param url: where to send
        :param json_data: data
        """
        url = ""
        for j in range(self.retry_n):
            for i in range(len(self.hosts)):
                host = self.hosts[self.active_host]
                url = self._get_pool_url(host) + req

                LOG.debug(
                    "sending pool request of type %(type)s to %(url)s "
                    "attempt: %(num)s.",
                    {'type': request_method,
                     'url': url,
                     'num': j})

                if json_data is not None:
                    LOG.debug(
                        "JovianDSS: Sending data: %s.", str(json_data))
                try:

                    ret = self._request_routine(url, request_method, json_data)
                    if len(ret) == 0:
                        self.active_host = ((self.active_host + 1)
                                            % len(self.hosts))
                        continue
                    return ret

                except requests.ConnectionError as err:
                    LOG.debug("Connection error %s", err)
                    self.active_host = (self.active_host + 1) % len(self.hosts)
                    continue
            time.sleep(int(self.delay))

        msg = (_('%(times)s faild in a row') % {'times': j})

        raise jexc.JDSSRESTProxyException(host=url, reason=msg)

    def _request_routine(self, url, request_method, json_data=None):
        """Make an HTTPS request and return the results."""

        ret = None
        for i in range(3):
            ret = dict()
            try:
                response_obj = requests.request(request_method,
                                                auth=self.auth,
                                                url=url,
                                                headers=self.header,
                                                data=json.dumps(json_data),
                                                verify=self.verify)

                LOG.debug('response code: %s', response_obj.status_code)
                LOG.debug('response data: %s', response_obj.text)

                ret['code'] = response_obj.status_code

                if '{' in response_obj.text and '}' in response_obj.text:
                    if "error" in response_obj.text:
                        ret["error"] = json.loads(response_obj.text)["error"]
                    else:
                        ret["error"] = None
                    if "data" in response_obj.text:
                        ret["data"] = json.loads(response_obj.text)["data"]
                    else:
                        ret["data"] = None

                if ret["code"] == 500:
                    if ret["error"] is not None:
                        if (("errno" in ret["error"]) and
                                ("class" in ret["error"])):
                            if (ret["error"]["class"] ==
                                    "opene.tools.scstadmin.ScstAdminError"):
                                LOG.debug("ScstAdminError %(code)d %(msg)s", {
                                    "code": ret["error"]["errno"],
                                    "msg": ret["error"]["message"]})
                                continue
                            if (ret["error"]["class"] ==
                                    "exceptions.OSError"):
                                LOG.debug("OSError %(code)d %(msg)s", {
                                    "code": ret["error"]["errno"],
                                    "msg": ret["error"]["message"]})
                                continue
                break

            except requests.HTTPError as err:
                LOG.debug("HTTP parsing error %s", err)
                self.active_host = (self.active_host + 1) % len(self.hosts)

        return ret

    def get_active_host(self):
        """Return address of currently used host."""
        return self.hosts[self.active_host]
