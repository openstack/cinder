#
# Copyright (c) 2016 NEC Corporation.
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

from lxml import etree

from oslo_utils import units

from cinder.tests.unit.volume.drivers.nec import cli_test
from cinder.volume.drivers.nec import volume_common


class MStorageVolCommDummy(object):
    def __init__(self, configuration, host, driver_name):
        super(MStorageVolCommDummy, self).__init__()
        self._properties = self.get_conf_properties()
        self._context = None

    def set_context(self, context):
        self._context = context

    def get_conf(self, host):
        return self.get_conf_properties()

    def get_conf_properties(self, conf=None):
        conf = {
            'cli': None,
            'cli_fip': '10.64.169.250',
            'cli_user': 'sysadmin',
            'cli_password': 'sys123',
            'cli_privkey': 'sys123',
            'pool_pools': [0, 1],
            'pool_backup_pools': [2, 3],
            'pool_actual_free_capacity': 50000000000,
            'ldset_name': 'LX:OpenStack0',
            'ldset_controller_node_name': 'LX:node0',
            'ld_name_format': 'LX:%s',
            'ld_backupname_format': 'LX:%s_back',
            'ld_backend_max_count': 1024,
            'thread_timeout': 5,
            'ismview_dir': 'view',
            'ismview_alloptimize': '',
            'ssh_pool_port_number': 22,
            'diskarray_name': 'node0',
            'queryconfig_view': '',
            'ismview_path': None,
            'driver_name': 'MStorageISCSIDriver',
            'config_group': '',
            'configuration': '',
            'vendor_name': 'nec',
            'products': '',
            'backend_name': '',
            'portal_number': 2
        }
        conf['cli'] = cli_test.MStorageISMCLI(conf)
        return conf

    @staticmethod
    def get_ldname(volid, volformat):
        return volume_common.MStorageVolumeCommon.get_ldname(volid, volformat)

    def get_diskarray_max_ld_count(self):
        return 8192

    def get_pool_config(self, xml, root):
        pools = {}
        for xmlobj in root.xpath('./'
                                 'CMD_REQUEST/'
                                 'CHAPTER[@name="Pool"]/'
                                 'OBJECT[@name="Pool"]'):
            section = xmlobj.find('./SECTION[@name="Pool Detail Information"]')
            unit = section.find('./UNIT[@name="Pool No.(h)"]')
            pool_num = int(unit.text, 16)
            unit = section.find('UNIT[@name="Pool Capacity"]')
            total = int(unit.text, 10)
            unit = section.find('UNIT[@name="Free Pool Capacity"]')
            free = int(unit.text, 10)
            if self._properties['pool_actual_free_capacity']:
                unit = section.find('UNIT[@name="Used Pool Capacity"]')
                used = int(unit.text, 10)
                for section in xmlobj.xpath('./SECTION[@name='
                                            '"Virtual Capacity Pool '
                                            'Information"]'):
                    unit = section.find('UNIT[@name="Actual Capacity"]')
                    total = int(unit.text, 10)
                    free = total - used
            pool = {'pool_num': pool_num,
                    'total': total,
                    'free': free,
                    'ld_list': []}
            pools[pool_num] = pool
        return pools

    def get_ld_config(self, xml, root, pools):
        lds = {}
        used_ldns = []
        for section in root.xpath('./'
                                  'CMD_REQUEST/'
                                  'CHAPTER[@name="Logical Disk"]/'
                                  'OBJECT[@name="Logical Disk"]/'
                                  'SECTION[@name="LD Detail Information"]'):
            unit = section.find('./UNIT[@name="LDN(h)"]')
            ldn = int(unit.text, 16)
            unit = section.find('./UNIT[@name="OS Type"]')
            ostype = unit.text if unit.text is not None else ''
            unit = section.find('./UNIT[@name="LD Name"]')
            ldname = ostype + ':' + unit.text
            unit = section.find('./UNIT[@name="Pool No.(h)"]')
            pool_num = int(unit.text, 16)

            unit = section.find('./UNIT[@name="LD Capacity"]')

            # byte capacity transform GB capacity.
            ld_capacity = int(unit.text, 10) // units.Gi

            unit = section.find('./UNIT[@name="RPL Attribute"]')
            rplatr = unit.text

            unit = section.find('./UNIT[@name="Purpose"]')
            purpose = unit.text

            ld = {'ldname': ldname,
                  'ldn': ldn,
                  'pool_num': pool_num,
                  'ld_capacity': ld_capacity,
                  'RPL Attribute': rplatr,
                  'Purpose': purpose}
            pools[pool_num]['ld_list'].append(ld)
            lds[ldname] = ld
            used_ldns.append(ldn)
        return lds, used_ldns

    def get_iscsi_ldset_config(self, xml, root):
        ldsets = {}
        for xmlobj in root.xpath('./'
                                 'CMD_REQUEST/'
                                 'CHAPTER[@name="Access Control"]/'
                                 'OBJECT[@name="LD Set(iSCSI)"]'):
            ldsetlds = {}
            portals = []
            for unit in xmlobj.xpath('./SECTION[@name="Portal"]/'
                                     'UNIT[@name="Portal"]'):
                if not unit.text.startswith('0.0.0.0:'):
                    portals.append(unit.text)
            section = xmlobj.find('./SECTION[@name="LD Set(iSCSI)'
                                  ' Information"]')
            if section is None:
                return ldsets
            unit = section.find('./UNIT[@name="Platform"]')
            platform = unit.text
            unit = section.find('./UNIT[@name="LD Set Name"]')
            ldsetname = platform + ':' + unit.text
            unit = section.find('./UNIT[@name="Target Mode"]')
            tmode = unit.text
            if tmode == 'Normal':
                unit = section.find('./UNIT[@name="Target Name"]')
                iqn = unit.text
                for section in xmlobj.xpath('./SECTION[@name="LUN/LD List"]'):
                    unit = section.find('./UNIT[@name="LDN(h)"]')
                    ldn = int(unit.text, 16)
                    unit = section.find('./UNIT[@name="LUN(h)"]')
                    lun = int(unit.text, 16)
                    ld = {'ldn': ldn,
                          'lun': lun,
                          'iqn': iqn}
                    ldsetlds[ldn] = ld
            elif tmode == 'Multi-Target':
                for section in xmlobj.xpath('./SECTION[@name='
                                            '"Target Information For '
                                            'Multi-Target Mode"]'):
                    unit = section.find('./UNIT[@name="Target Name"]')
                    iqn = unit.text
                    unit = section.find('./UNIT[@name="LDN(h)"]')
                    if unit.text.startswith('-'):
                        continue
                    ldn = int(unit.text, 16)
                    unit = section.find('./UNIT[@name="LUN(h)"]')
                    if unit.text.startswith('-'):
                        continue
                    lun = int(unit.text, 16)
                    ld = {'ldn': ldn,
                          'lun': lun,
                          'iqn': iqn}
                    ldsetlds[ldn] = ld
            ldset = {'ldsetname': ldsetname,
                     'protocol': 'iSCSI',
                     'portal_list': portals,
                     'lds': ldsetlds}
            ldsets[ldsetname] = ldset
        return ldsets

    def get_fc_ldset_config(self, xml, root):
        ldsets = {}
        for xmlobj in root.xpath('./'
                                 'CMD_REQUEST/'
                                 'CHAPTER[@name="Access Control"]/'
                                 'OBJECT[@name="LD Set(FC)"]'):
            ldsetlds = {}
            section = xmlobj.find('./SECTION[@name="LD Set(FC)'
                                  ' Information"]')
            if section is None:
                return ldsets
            unit = section.find('./UNIT[@name="Platform"]')
            platform = unit.text
            unit = section.find('./UNIT[@name="LD Set Name"]')
            ldsetname = platform + ':' + unit.text
            wwpns = []
            ports = []
            for section in xmlobj.xpath('./SECTION[@name="Path List"]'):
                unit = section.find('./UNIT[@name="Path"]')
                if unit.text.find('(') != -1:
                    ports.append(unit.text)
                else:
                    wwpns.append(unit.text)
            for section in xmlobj.xpath('./SECTION[@name="LUN/LD List"]'):
                unit = section.find('./UNIT[@name="LDN(h)"]')
                ldn = int(unit.text, 16)
                unit = section.find('./UNIT[@name="LUN(h)"]')
                lun = int(unit.text, 16)
                ld = {'ldn': ldn,
                      'lun': lun}
                ldsetlds[ldn] = ld
            ldset = {'ldsetname': ldsetname,
                     'lds': ldsetlds,
                     'protocol': 'FC',
                     'wwpn': wwpns,
                     'port': ports}
            ldsets[ldsetname] = ldset
        return ldsets

    def get_hostport_config(self, xml, root):
        hostports = {}
        for section in root.xpath('./'
                                  'CMD_REQUEST/'
                                  'CHAPTER[@name="Controller"]/'
                                  'OBJECT[@name="Host Port"]/'
                                  'SECTION[@name="Host Director'
                                  '/Host Port Information"]'):
            unit = section.find('./UNIT[@name="Port No.(h)"]')
            units = unit.text.split('-')
            director = int(units[0], 16)
            port = int(units[1], 16)
            unit = section.find('./UNIT[@name="IP Address"]')
            if unit is not None:
                ip = unit.text
                protocol = 'iSCSI'
                wwpn = None
            else:
                ip = '0.0.0.0'
                protocol = 'FC'
                unit = section.find('./UNIT[@name="WWPN"]')
                wwpn = unit.text

            # Port Link Status check Start.
            unit = section.find('./UNIT[@name="Link Status"]')
            hostport = {
                'director': director,
                'port': port,
                'ip': ip,
                'protocol': protocol,
                'wwpn': wwpn
            }
            if director not in hostports:
                hostports[director] = []
            hostports[director].append(hostport)
        return hostports

    def configs(self, xml):
        root = etree.fromstring(xml)
        pools = self.get_pool_config(xml, root)
        lds, used_ldns = self.get_ld_config(xml, root, pools)
        iscsi_ldsets = self.get_iscsi_ldset_config(xml, root)
        fc_ldsets = self.get_fc_ldset_config(xml, root)
        hostports = self.get_hostport_config(xml, root)
        diskarray_max_ld_count = self.get_diskarray_max_ld_count()

        ldsets = {}
        ldsets.update(iscsi_ldsets)
        ldsets.update(fc_ldsets)

        return pools, lds, ldsets, used_ldns, hostports, diskarray_max_ld_count

    def get_volume_type_qos_specs(self, volume):
        return {}

    def check_io_parameter(self, specs):
        pass
