# Copyright (c) 2018 Huawei Technologies Co., Ltd.
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
import os
import six

from oslo_log import log as logging
from six.moves import configparser

from cinder import exception
from cinder.i18n import _
from cinder import utils
from cinder.volume.drivers.fusionstorage import constants


LOG = logging.getLogger(__name__)


class FusionStorageConf(object):
    def __init__(self, configuration, host):
        self.configuration = configuration
        self._check_host(host)

    def _check_host(self, host):
        if host and len(host.split('@')) > 1:
            self.host = host.split('@')[1]
        else:
            msg = _("The host %s is not reliable. Please check cinder-volume "
                    "backend.") % host
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)

    def update_config_value(self):
        self._encode_authentication()
        self._pools_name()
        self._san_address()
        self._san_user()
        self._san_password()

    def _encode_authentication(self):
        name_node = self.configuration.safe_get(constants.CONF_USER)
        pwd_node = self.configuration.safe_get(constants.CONF_PWD)

        need_encode = False
        if name_node is not None and not name_node.startswith('!&&&'):
            encoded = base64.b64encode(six.b(name_node)).decode()
            name_node = '!&&&' + encoded
            need_encode = True

        if pwd_node is not None and not pwd_node.startswith('!&&&'):
            encoded = base64.b64encode(six.b(pwd_node)).decode()
            pwd_node = '!&&&' + encoded
            need_encode = True

        if need_encode:
            self._rewrite_conf(name_node, pwd_node)

    def _rewrite_conf(self, name_node, pwd_node):
        if os.path.exists(constants.CONF_PATH):
            utils.execute("chmod", "666", constants.CONF_PATH,
                          run_as_root=True)
            conf = configparser.ConfigParser()
            conf.read(constants.CONF_PATH)
            if name_node:
                conf.set(self.host, constants.CONF_USER, name_node)
            if pwd_node:
                conf.set(self.host, constants.CONF_PWD, pwd_node)
            fh = open(constants.CONF_PATH, 'w')
            conf.write(fh)
            fh.close()
            utils.execute("chmod", "644", constants.CONF_PATH,
                          run_as_root=True)

    def _assert_text_result(self, text, mess):
        if not text:
            msg = _("%s is not configured.") % mess
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)

    def _san_address(self):
        address = self.configuration.safe_get(constants.CONF_ADDRESS)
        self._assert_text_result(address, mess=constants.CONF_ADDRESS)
        setattr(self.configuration, 'san_address', address)

    def _decode_text(self, text):
        return (base64.b64decode(six.b(text[4:])).decode() if
                text.startswith('!&&&') else text)

    def _san_user(self):
        user_text = self.configuration.safe_get(constants.CONF_USER)
        self._assert_text_result(user_text, mess=constants.CONF_USER)
        user = self._decode_text(user_text)
        setattr(self.configuration, 'san_user', user)

    def _san_password(self):
        pwd_text = self.configuration.safe_get(constants.CONF_PWD)
        self._assert_text_result(pwd_text, mess=constants.CONF_PWD)
        pwd = self._decode_text(pwd_text)
        setattr(self.configuration, 'san_password', pwd)

    def _pools_name(self):
        pools_name = self.configuration.safe_get(constants.CONF_POOLS)
        self._assert_text_result(pools_name, mess=constants.CONF_POOLS)
        pools = set(x.strip() for x in pools_name.split(';') if x.strip())
        if not pools:
            msg = _('No valid storage pool configured.')
            LOG.error(msg)
            raise exception.InvalidInput(msg)
        setattr(self.configuration, 'pools_name', list(pools))

    def _manager_ip(self):
        manager_ips = self.configuration.safe_get(constants.CONF_MANAGER_IP)
        self._assert_text_result(manager_ips, mess=constants.CONF_MANAGER_IP)
        setattr(self.configuration, 'manager_ips', manager_ips)
