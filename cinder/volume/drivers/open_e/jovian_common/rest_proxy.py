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

from oslo_log import log as logging
from oslo_utils import netutils as o_netutils
import requests
import urllib3

from cinder import exception
from cinder.i18n import _
from cinder.utils import retry
from cinder.volume.drivers.open_e.jovian_common import exception as jexc


LOG = logging.getLogger(__name__)


class JovianRESTProxy(object):
    """Jovian REST API proxy."""

    def __init__(self, config):
        """:param config: list of config values."""

        self.proto = 'http'
        if config.get('driver_use_ssl', True):
            self.proto = 'https'

        self.hosts = config.get('san_hosts', [])
        self.port = str(config.get('san_api_port', 82))

        for host in self.hosts:
            if o_netutils.is_valid_ip(host) is False:
                err_msg = ('Invalid value of jovian_host property: '
                           '%(addr)s, IP address expected.' %
                           {'addr': host})

                LOG.debug(err_msg)
                raise exception.InvalidConfigurationValue(err_msg)

        self.active_host = 0

        self.delay = config.get('jovian_recovery_delay', 40)

        self.pool = config.get('jovian_pool', 'Pool-0')

        self.user = config.get('san_login', 'admin')
        self.password = config.get('san_password', 'admin')
        self.verify = config.get('driver_ssl_cert_verify', True)
        self.cert = config.get('driver_ssl_cert_path')

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        self.session = self._get_session()

    def _get_session(self):
        """Create and init new session object"""

        session = requests.Session()
        session.auth = (self.user, self.password)
        session.headers.update({'Connection': 'keep-alive',
                                'Content-Type': 'application/json',
                                'Authorization': 'Basic'})
        session.hooks['response'] = [JovianRESTProxy._handle_500]
        session.verify = self.verify
        if self.verify and self.cert:
            session.verify = self.cert
        return session

    def _get_base_url(self):
        """Get url prefix with active host"""

        url = ('%(proto)s://%(host)s:%(port)s/api/v3' % {
            'proto': self.proto,
            'host': self.hosts[self.active_host],
            'port': self.port})

        return url

    def _next_host(self):
        """Set next host as active"""

        self.active_host = (self.active_host + 1) % len(self.hosts)

    def request(self, request_method, req, json_data=None):
        """Send request to the specific url.

        :param request_method: GET, POST, DELETE
        :param url: where to send
        :param json_data: data
        """
        out = None
        for i in range(len(self.hosts)):
            try:
                addr = "%(base)s%(req)s" % {'base': self._get_base_url(),
                                            'req': req}
                LOG.debug("Sending %(t)s to %(addr)s",
                          {'t': request_method, 'addr': addr})
                r = None
                if json_data:
                    r = requests.Request(request_method,
                                         addr,
                                         data=json.dumps(json_data))
                else:
                    r = requests.Request(request_method, addr)

                pr = self.session.prepare_request(r)
                out = self._send(pr)
            except requests.exceptions.ConnectionError:
                self._next_host()
                continue
            break

        LOG.debug("Geting %(data)s from %(t)s to %(addr)s",
                  {'data': out, 't': request_method, 'addr': addr})
        return out

    def pool_request(self, request_method, req, json_data=None):
        """Send request to the specific url.

        :param request_method: GET, POST, DELETE
        :param url: where to send
        :param json_data: data
        """
        req = "/pools/{pool}{req}".format(pool=self.pool, req=req)
        addr = "{base}{req}".format(base=self._get_base_url(), req=req)
        LOG.debug("Sending pool request %(t)s to %(addr)s",
                  {'t': request_method, 'addr': addr})
        return self.request(request_method, req, json_data=json_data)

    @retry((requests.exceptions.ConnectionError,
            jexc.JDSSOSException),
           interval=2,
           backoff_rate=2,
           retries=7)
    def _send(self, pr):
        """Send prepared request

        :param pr: prepared request
        """
        ret = dict()

        response_obj = self.session.send(pr)

        ret['code'] = response_obj.status_code

        try:
            data = json.loads(response_obj.text)
            ret["error"] = data.get("error")
            ret["data"] = data.get("data")
        except json.JSONDecodeError:
            pass

        return ret

    @staticmethod
    def _handle_500(resp, *args, **kwargs):
        """Handle OS error on a storage side"""

        error = None
        if resp.status_code == 500:
            try:
                data = json.loads(resp.text)
                error = data.get("error")
            except json.JSONDecodeError:
                return
        else:
            return

        if error:
            if "class" in error:
                if error["class"] == "opene.tools.scstadmin.ScstAdminError":
                    LOG.debug("ScstAdminError %(code)d %(msg)s",
                              {'code': error["errno"],
                               'msg': error["message"]})
                    raise jexc.JDSSOSException(_(error["message"]))

                if error["class"] == "exceptions.OSError":
                    LOG.debug("OSError %(code)d %(msg)s",
                              {'code': error["errno"],
                               'msg': error["message"]})
                    raise jexc.JDSSOSException(_(error["message"]))

    def get_active_host(self):
        """Return address of currently used host."""
        return self.hosts[self.active_host]
