# Copyright (c) 2016 Huawei Technologies Co., Ltd.
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

"""Sets Huawei private configuration into Configuration object.

For conveniently get private configuration. We parse Huawei config file
and set every property into Configuration object as an attribute.
"""

import base64
import os
import re

from lxml import etree as ET
from oslo_log import log as logging
import six

from cinder import exception
from cinder.i18n import _
from cinder.volume.drivers.huawei import constants

LOG = logging.getLogger(__name__)


class HuaweiConf(object):
    def __init__(self, conf):
        self.conf = conf
        self.last_modify_time = None

    def update_config_value(self):
        file_time = os.stat(self.conf.cinder_huawei_conf_file).st_mtime
        if self.last_modify_time == file_time:
            return

        self.last_modify_time = file_time
        tree = ET.parse(self.conf.cinder_huawei_conf_file)
        xml_root = tree.getroot()
        self._encode_authentication(tree, xml_root)

        attr_funcs = (
            self._san_address,
            self._san_user,
            self._san_password,
            self._san_vstore,
            self._san_product,
            self._ssl_cert_path,
            self._ssl_cert_verify,
            self._iscsi_info,
            self._fc_info,
            self._hypermetro_devices,
            self._replication_devices,
            self._lun_type,
            self._lun_ready_wait_interval,
            self._lun_copy_wait_interval,
            self._lun_timeout,
            self._lun_write_type,
            self._lun_prefetch,
            self._lun_policy,
            self._lun_read_cache_policy,
            self._lun_write_cache_policy,
            self._storage_pools,
        )

        for f in attr_funcs:
            f(xml_root)

    def _encode_authentication(self, tree, xml_root):
        name_node = xml_root.find('Storage/UserName')
        pwd_node = xml_root.find('Storage/UserPassword')
        vstore_node = xml_root.find('Storage/vStoreName')

        need_encode = False
        if name_node is not None and not name_node.text.startswith('!$$$'):
            encoded = base64.b64encode(six.b(name_node.text)).decode()
            name_node.text = '!$$$' + encoded
            need_encode = True

        if pwd_node is not None and not pwd_node.text.startswith('!$$$'):
            encoded = base64.b64encode(six.b(pwd_node.text)).decode()
            pwd_node.text = '!$$$' + encoded
            need_encode = True

        if vstore_node is not None and not vstore_node.text.startswith('!$$$'):
            encoded = base64.b64encode(six.b(vstore_node.text)).decode()
            vstore_node.text = '!$$$' + encoded
            need_encode = True

        if need_encode:
            tree.write(self.conf.cinder_huawei_conf_file, 'UTF-8')

    def _san_address(self, xml_root):
        text = xml_root.findtext('Storage/RestURL')
        if not text:
            msg = _("RestURL is not configured.")
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)

        addrs = list(set([x.strip() for x in text.split(';') if x.strip()]))
        setattr(self.conf, 'san_address', addrs)

    def _san_user(self, xml_root):
        text = xml_root.findtext('Storage/UserName')
        if not text:
            msg = _("UserName is not configured.")
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)

        user = base64.b64decode(six.b(text[4:])).decode()
        setattr(self.conf, 'san_user', user)

    def _san_password(self, xml_root):
        text = xml_root.findtext('Storage/UserPassword')
        if not text:
            msg = _("UserPassword is not configured.")
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)

        pwd = base64.b64decode(six.b(text[4:])).decode()
        setattr(self.conf, 'san_password', pwd)

    def _san_vstore(self, xml_root):
        vstore = None
        text = xml_root.findtext('Storage/vStoreName')
        if text:
            vstore = base64.b64decode(six.b(text[4:])).decode()
        setattr(self.conf, 'vstore_name', vstore)

    def _ssl_cert_path(self, xml_root):
        text = xml_root.findtext('Storage/SSLCertPath')
        setattr(self.conf, 'ssl_cert_path', text)

    def _ssl_cert_verify(self, xml_root):
        value = False
        text = xml_root.findtext('Storage/SSLCertVerify')
        if text:
            if text.lower() in ('true', 'false'):
                value = text.lower() == 'true'
            else:
                msg = _("SSLCertVerify configured error.")
                LOG.error(msg)
                raise exception.InvalidInput(reason=msg)

        setattr(self.conf, 'ssl_cert_verify', value)

    def _set_extra_constants_by_product(self, product):
        extra_constants = {}
        if product == 'Dorado':
            extra_constants['QOS_SPEC_KEYS'] = (
                'maxIOPS', 'maxBandWidth', 'IOType')
            extra_constants['QOS_IOTYPES'] = ('2',)
            extra_constants['SUPPORT_LUN_TYPES'] = ('Thin',)
            extra_constants['DEFAULT_LUN_TYPE'] = 'Thin'
        else:
            extra_constants['QOS_SPEC_KEYS'] = (
                'maxIOPS', 'minIOPS', 'minBandWidth',
                'maxBandWidth', 'latency', 'IOType')
            extra_constants['QOS_IOTYPES'] = ('0', '1', '2')
            extra_constants['SUPPORT_LUN_TYPES'] = ('Thick', 'Thin')
            extra_constants['DEFAULT_LUN_TYPE'] = 'Thick'

        for k in extra_constants:
            setattr(constants, k, extra_constants[k])

    def _san_product(self, xml_root):
        text = xml_root.findtext('Storage/Product')
        if not text:
            msg = _("SAN product is not configured.")
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)

        product = text.strip()
        if product not in constants.VALID_PRODUCT:
            msg = _("Invalid SAN product %(text)s, SAN product must be "
                    "in %(valid)s.") % {'text': product,
                                        'valid': constants.VALID_PRODUCT}
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)

        self._set_extra_constants_by_product(product)
        setattr(self.conf, 'san_product', product)

    def _lun_type(self, xml_root):
        lun_type = constants.DEFAULT_LUN_TYPE
        text = xml_root.findtext('LUN/LUNType')
        if text:
            lun_type = text.strip()
            if lun_type not in constants.LUN_TYPE_MAP:
                msg = _("Invalid lun type %s is configured.") % lun_type
                LOG.error(msg)
                raise exception.InvalidInput(reason=msg)

            if lun_type not in constants.SUPPORT_LUN_TYPES:
                msg = _("%(array)s array requires %(valid)s lun type, "
                        "but %(conf)s is specified."
                        ) % {'array': self.conf.san_product,
                             'valid': constants.SUPPORT_LUN_TYPES,
                             'conf': lun_type}
                LOG.error(msg)
                raise exception.InvalidInput(reason=msg)

        setattr(self.conf, 'lun_type', constants.LUN_TYPE_MAP[lun_type])

    def _lun_ready_wait_interval(self, xml_root):
        text = xml_root.findtext('LUN/LUNReadyWaitInterval')
        interval = text.strip() if text else constants.DEFAULT_WAIT_INTERVAL
        setattr(self.conf, 'lun_ready_wait_interval', int(interval))

    def _lun_copy_wait_interval(self, xml_root):
        text = xml_root.findtext('LUN/LUNcopyWaitInterval')
        interval = text.strip() if text else constants.DEFAULT_WAIT_INTERVAL
        setattr(self.conf, 'lun_copy_wait_interval', int(interval))

    def _lun_timeout(self, xml_root):
        text = xml_root.findtext('LUN/Timeout')
        interval = text.strip() if text else constants.DEFAULT_WAIT_TIMEOUT
        setattr(self.conf, 'lun_timeout', int(interval))

    def _lun_write_type(self, xml_root):
        text = xml_root.findtext('LUN/WriteType')
        if text and text.strip():
            setattr(self.conf, 'write_type', text.strip())

    def _lun_prefetch(self, xml_root):
        node = xml_root.find('LUN/Prefetch')
        if node is not None:
            if 'Type' in node.attrib:
                prefetch_type = node.attrib['Type'].strip()
                setattr(self.conf, 'prefetch_type', prefetch_type)

            if 'Value' in node.attrib:
                prefetch_value = node.attrib['Value'].strip()
                setattr(self.conf, 'prefetch_value', prefetch_value)

    def _lun_policy(self, xml_root):
        setattr(self.conf, 'lun_policy', '0')

    def _lun_read_cache_policy(self, xml_root):
        setattr(self.conf, 'lun_read_cache_policy', '2')

    def _lun_write_cache_policy(self, xml_root):
        setattr(self.conf, 'lun_write_cache_policy', '5')

    def _storage_pools(self, xml_root):
        text = xml_root.findtext('LUN/StoragePool')
        if not text:
            msg = _('Storage pool is not configured.')
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)

        pools = set(x.strip() for x in text.split(';') if x.strip())
        if not pools:
            msg = _('No valid storage pool configured.')
            LOG.error(msg)
            raise exception.InvalidInput(msg)

        setattr(self.conf, 'storage_pools', list(pools))

    def _iscsi_info(self, xml_root):
        iscsi_info = {
            'default_target_ips': [],
            'CHAPinfo': xml_root.findtext('iSCSI/CHAPinfo'),
            'ALUA': xml_root.findtext('iSCSI/ALUA'),
            'FAILOVERMODE': xml_root.findtext('iSCSI/FAILOVERMODE'),
            'SPECIALMODETYPE': xml_root.findtext('iSCSI/SPECIALMODETYPE'),
            'PATHTYPE': xml_root.findtext('iSCSI/PATHTYPE'),
        }

        text = xml_root.findtext('iSCSI/DefaultTargetIP')
        if text:
            iscsi_info['default_target_ips'] = [
                ip.strip() for ip in text.split(';') if ip.strip()]

        initiators = {}
        nodes = xml_root.findall('iSCSI/Initiator')
        for node in nodes or []:
            if 'Name' not in node.attrib:
                msg = _('Name must be specified for initiator.')
                LOG.error(msg)
                raise exception.InvalidInput(msg)

            initiators[node.attrib['Name']] = node.attrib

        iscsi_info['initiators'] = initiators
        setattr(self.conf, 'iscsi_info', iscsi_info)

    def _fc_info(self, xml_root):
        fc_info = {
            'ALUA': xml_root.findtext('FC/ALUA'),
            'FAILOVERMODE': xml_root.findtext('FC/FAILOVERMODE'),
            'SPECIALMODETYPE': xml_root.findtext('FC/SPECIALMODETYPE'),
            'PATHTYPE': xml_root.findtext('FC/PATHTYPE'),
        }

        initiators = {}
        nodes = xml_root.findall('FC/Initiator')
        for node in nodes or []:
            if 'Name' not in node.attrib:
                msg = _('Name must be specified for initiator.')
                LOG.error(msg)
                raise exception.InvalidInput(msg)

            initiators[node.attrib['Name']] = node.attrib

        fc_info['initiators'] = initiators
        setattr(self.conf, 'fc_info', fc_info)

    def _parse_remote_initiator_info(self, dev, ini_type):
        ini_info = {'default_target_ips': []}

        if dev.get('iscsi_default_target_ip'):
            ini_info['default_target_ips'] = dev[
                'iscsi_default_target_ip'].split(';')

        initiators = {}
        if ini_type in dev:
            # Analyze initiators configure text, convert to:
            # [{'Name':'xxx'}, {'Name':'xxx','CHAPinfo':'mm-usr#mm-pwd'}]
            ini_list = re.split(r'\s', dev[ini_type])

            def _convert_one_iscsi_info(ini_text):
                # get initiator configure attr list
                attr_list = re.split('[{;}]', ini_text)

                # get initiator configures
                ini = {}
                for attr in attr_list:
                    if not attr:
                        continue

                    pair = attr.split(':', 1)
                    if pair[0] == 'CHAPinfo':
                        value = pair[1].replace('#', ';', 1)
                    else:
                        value = pair[1]
                    ini[pair[0]] = value

                if 'Name' not in ini:
                    msg = _('Name must be specified for initiator.')
                    LOG.error(msg)
                    raise exception.InvalidInput(msg)

                return ini

            for text in ini_list:
                ini = _convert_one_iscsi_info(text)
                initiators[ini['Name']] = ini

        ini_info['initiators'] = initiators
        return ini_info

    def _hypermetro_devices(self, xml_root):
        dev = self.conf.safe_get('hypermetro_device')
        config = {}

        if dev:
            config = {
                'san_address': dev['san_address'].split(';'),
                'san_user': dev['san_user'],
                'san_password': dev['san_password'],
                'vstore_name': dev.get('vstore_name'),
                'metro_domain': dev['metro_domain'],
                'storage_pools': dev['storage_pool'].split(';')[:1],
                'iscsi_info': self._parse_remote_initiator_info(
                    dev, 'iscsi_info'),
                'fc_info': self._parse_remote_initiator_info(
                    dev, 'fc_info'),
            }

        setattr(self.conf, 'hypermetro', config)

    def _replication_devices(self, xml_root):
        replication_devs = self.conf.safe_get('replication_device')
        config = {}

        if replication_devs:
            dev = replication_devs[0]
            config = {
                'backend_id': dev['backend_id'],
                'san_address': dev['san_address'].split(';'),
                'san_user': dev['san_user'],
                'san_password': dev['san_password'],
                'vstore_name': dev.get('vstore_name'),
                'storage_pools': dev['storage_pool'].split(';')[:1],
                'iscsi_info': self._parse_remote_initiator_info(
                    dev, 'iscsi_info'),
                'fc_info': self._parse_remote_initiator_info(
                    dev, 'fc_info'),
            }

        setattr(self.conf, 'replication', config)
