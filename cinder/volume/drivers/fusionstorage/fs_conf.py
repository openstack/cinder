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
        storage_info = self.configuration.safe_get(constants.CONF_STORAGE)
        self._pools_name(storage_info)
        self._san_address(storage_info)
        self._encode_authentication(storage_info)
        self._san_user(storage_info)
        self._san_password(storage_info)

    def _encode_authentication(self, storage_info):
        name_node = storage_info.get(constants.CONF_USER)
        pwd_node = storage_info.get(constants.CONF_PWD)

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
            self._rewrite_conf(storage_info, name_node, pwd_node)

    def _rewrite_conf(self, storage_info, name_node, pwd_node):
        storage_info.update({constants.CONF_USER: name_node,
                             constants.CONF_PWD: pwd_node})
        storage_info = ("\n  %(conf_name)s: %(name)s,"
                        "\n  %(conf_pwd)s: %(pwd)s,"
                        "\n  %(conf_url)s: %(url)s,"
                        "\n  %(conf_pool)s: %(pool)s"
                        % {"conf_name": constants.CONF_USER,
                           "conf_pwd": constants.CONF_PWD,
                           "conf_url": constants.CONF_ADDRESS,
                           "conf_pool": constants.CONF_POOLS,
                           "name": name_node,
                           "pwd": pwd_node,
                           "url": storage_info.get(constants.CONF_ADDRESS),
                           "pool": storage_info.get(constants.CONF_POOLS)})
        if os.path.exists(constants.CONF_PATH):
            utils.execute("chmod", "666", constants.CONF_PATH,
                          run_as_root=True)
            conf = configparser.ConfigParser()
            conf.read(constants.CONF_PATH)
            conf.set(self.host, constants.CONF_STORAGE, storage_info)
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

    def _san_address(self, storage_info):
        address = storage_info.get(constants.CONF_ADDRESS)
        self._assert_text_result(address, mess=constants.CONF_ADDRESS)
        setattr(self.configuration, 'san_address', address)

    def _san_user(self, storage_info):
        user_text = storage_info.get(constants.CONF_USER)
        self._assert_text_result(user_text, mess=constants.CONF_USER)
        user = base64.b64decode(six.b(user_text[4:])).decode()
        setattr(self.configuration, 'san_user', user)

    def _san_password(self, storage_info):
        pwd_text = storage_info.get(constants.CONF_PWD)
        self._assert_text_result(pwd_text, mess=constants.CONF_PWD)
        pwd = base64.b64decode(six.b(pwd_text[4:])).decode()
        setattr(self.configuration, 'san_password', pwd)

    def _pools_name(self, storage_info):
        pools_name = storage_info.get(constants.CONF_POOLS)
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
