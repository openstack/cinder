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

import errno
from lxml import etree
import os
import re
import traceback

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import units

from cinder import context
from cinder import exception
from cinder.i18n import _
from cinder.volume import configuration
from cinder.volume.drivers.nec import cli
from cinder.volume.drivers.san import san
from cinder.volume import qos_specs
from cinder.volume import volume_types


LOG = logging.getLogger(__name__)

FLAGS = cfg.CONF

mstorage_opts = [
    cfg.IPOpt('nec_ismcli_fip',
              default=None,
              help='FIP address of M-Series Storage iSMCLI.'),
    cfg.StrOpt('nec_ismcli_user',
               default='',
               help='User name for M-Series Storage iSMCLI.'),
    cfg.StrOpt('nec_ismcli_password',
               secret=True,
               default='',
               help='Password for M-Series Storage iSMCLI.'),
    cfg.StrOpt('nec_ismcli_privkey',
               default='',
               help='Filename of RSA private key for '
                    'M-Series Storage iSMCLI.'),
    cfg.StrOpt('nec_ldset',
               default='',
               help='M-Series Storage LD Set name for Compute Node.'),
    cfg.StrOpt('nec_ldname_format',
               default='LX:%s',
               help='M-Series Storage LD name format for volumes.'),
    cfg.StrOpt('nec_backup_ldname_format',
               default='LX:%s',
               help='M-Series Storage LD name format for snapshots.'),
    cfg.StrOpt('nec_diskarray_name',
               default='',
               help='Diskarray name of M-Series Storage.'),
    cfg.StrOpt('nec_ismview_dir',
               default='/tmp/nec/cinder',
               help='Output path of iSMview file.'),
    cfg.StrOpt('nec_ldset_for_controller_node',
               default='',
               help='M-Series Storage LD Set name for Controller Node.'),
    cfg.IntOpt('nec_ssh_pool_port_number',
               default=22,
               help='Port number of ssh pool.'),
    cfg.IntOpt('nec_unpairthread_timeout',
               default=3600,
               help='Timeout value of Unpairthread.'),
    cfg.IntOpt('nec_backend_max_ld_count',
               default=1024,
               help='Maximum number of managing sessions.'),
    cfg.BoolOpt('nec_actual_free_capacity',
                default=False,
                help='Return actual free capacity.'),
    cfg.BoolOpt('nec_ismview_alloptimize',
                default=False,
                help='Use legacy iSMCLI command with optimization.'),
    cfg.ListOpt('nec_pools',
                default=[],
                help='M-Series Storage pool numbers list to be used.'),
    cfg.ListOpt('nec_backup_pools',
                default=[],
                help='M-Series Storage backup pool number to be used.'),
    cfg.BoolOpt('nec_queryconfig_view',
                default=False,
                help='Use legacy iSMCLI command.'),
    cfg.IntOpt('nec_iscsi_portals_per_cont',
               default=1,
               help='Number of iSCSI portals.'),
]

FLAGS.register_opts(mstorage_opts, group=configuration.SHARED_CONF_GROUP)


def convert_to_name(uuid):
    alnum = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    num = int(uuid.replace(("-"), ""), 16)

    convertname = ""
    while num != 0:
        convertname = alnum[num % len(alnum)] + convertname
        num = num - num % len(alnum)
        num = num // len(alnum)
    return convertname


def convert_to_id(value62):
    alnum = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    length = len(value62)

    weight = 0
    value = 0
    index = 0
    for i in reversed(range(0, length)):
        num = alnum.find(value62[i])
        if index != 0:
            value += int(weight * (num))
        else:
            value = num
        index += 1
        weight = 62 ** index

    value = '%032x' % value

    uuid = value[0:8]
    uuid += '-'
    uuid += value[8:12]
    uuid += '-'
    uuid += value[12:16]
    uuid += '-'
    uuid += value[16:20]
    uuid += '-'
    uuid += value[20:]

    return uuid


class MStorageVolumeCommon(object):
    """M-Series Storage volume common class."""

    VERSION = '1.9.2'
    WIKI_NAME = 'NEC_Cinder_CI'

    def do_setup(self, context):
        self._context = context

    def check_for_setup_error(self):
        fip = self._configuration.safe_get('nec_ismcli_fip')
        user = self._configuration.safe_get('nec_ismcli_user')
        pw = self._configuration.safe_get('nec_ismcli_password')
        key = self._configuration.safe_get('nec_ismcli_privkey')
        pools = self._configuration.safe_get('nec_pools')

        if fip is None or fip == '':
            raise exception.ParameterNotFound(param='nec_ismcli_fip')
        if user is None or user == '':
            raise exception.ParameterNotFound(param='nec_ismcli_user')
        if (pw is None or pw == '') and (key is None or key == ''):
            msg = _('nec_ismcli_password nor nec_ismcli_privkey')
            raise exception.ParameterNotFound(param=msg)
        if pools is None or len(pools) == 0:
            raise exception.ParameterNotFound(param='nec_pools')

    def _set_config(self, configuration, host, driver_name):
        self._configuration = configuration
        self._host = host
        self._driver_name = driver_name
        self._numofld_per_pool = 1024

        self._configuration.append_config_values(mstorage_opts)
        self._configuration.append_config_values(san.san_opts)
        self._config_group = self._configuration.config_group

        self._properties = self._set_properties()
        self._cli = self._properties['cli']

    def _create_ismview_dir(self,
                            ismview_dir,
                            diskarray_name,
                            driver_name,
                            host):
        """Create ismview directory."""
        filename = diskarray_name
        if filename == '':
            filename = driver_name + '_' + host

        ismview_path = os.path.join(ismview_dir, filename)
        LOG.debug('ismview_path=%s.', ismview_path)
        try:
            if os.path.exists(ismview_path):
                os.remove(ismview_path)
        except OSError as e:
            with excutils.save_and_reraise_exception() as ctxt:
                if e.errno == errno.ENOENT:
                    ctxt.reraise = False

        try:
            os.makedirs(ismview_dir)
        except OSError as e:
            with excutils.save_and_reraise_exception() as ctxt:
                if e.errno == errno.EEXIST:
                    ctxt.reraise = False

        return ismview_path

    def get_conf_properties(self):
        confobj = self._configuration

        pool_pools = []
        for pool in confobj.safe_get('nec_pools'):
            if pool.endswith('h'):
                pool_pools.append(int(pool[:-1], 16))
            else:
                pool_pools.append(int(pool, 10))
        pool_backup_pools = []
        for pool in confobj.safe_get('nec_backup_pools'):
            if pool.endswith('h'):
                pool_backup_pools.append(int(pool[:-1], 16))
            else:
                pool_backup_pools.append(int(pool, 10))

        return {
            'cli_fip': confobj.safe_get('nec_ismcli_fip'),
            'cli_user': confobj.safe_get('nec_ismcli_user'),
            'cli_password': confobj.safe_get('nec_ismcli_password'),
            'cli_privkey': confobj.safe_get('nec_ismcli_privkey'),
            'pool_pools': pool_pools,
            'pool_backup_pools': pool_backup_pools,
            'pool_actual_free_capacity':
                confobj.safe_get('nec_actual_free_capacity'),
            'ldset_name': confobj.safe_get('nec_ldset'),
            'ldset_controller_node_name':
                confobj.safe_get('nec_ldset_for_controller_node'),
            'ld_name_format': confobj.safe_get('nec_ldname_format'),
            'ld_backupname_format':
                confobj.safe_get('nec_backup_ldname_format'),
            'ld_backend_max_count':
                confobj.safe_get('nec_backend_max_ld_count'),
            'thread_timeout': confobj.safe_get('nec_unpairthread_timeout'),
            'ismview_dir': confobj.safe_get('nec_ismview_dir'),
            'ismview_alloptimize': confobj.safe_get('nec_ismview_alloptimize'),
            'ssh_pool_port_number':
                confobj.safe_get('nec_ssh_pool_port_number'),
            'diskarray_name': confobj.safe_get('nec_diskarray_name'),
            'queryconfig_view': confobj.safe_get('nec_queryconfig_view'),
            'portal_number': confobj.safe_get('nec_iscsi_portals_per_cont')
        }

    def _set_properties(self):
        conf_properties = self.get_conf_properties()

        ismview_path = self._create_ismview_dir(
            conf_properties['ismview_dir'],
            conf_properties['diskarray_name'],
            self._driver_name,
            self._host)

        vendor_name, _product_dict = self.get_oem_parameter()

        backend_name = self._configuration.safe_get('volume_backend_name')
        ssh_timeout = self._configuration.safe_get('ssh_conn_timeout')
        reserved_per = self._configuration.safe_get('reserved_percentage')

        conf_properties['ssh_conn_timeout'] = ssh_timeout
        conf_properties['reserved_percentage'] = reserved_per
        conf_properties['ismview_path'] = ismview_path
        conf_properties['vendor_name'] = vendor_name
        conf_properties['products'] = _product_dict
        conf_properties['backend_name'] = backend_name
        conf_properties['cli'] = cli.MStorageISMCLI(conf_properties)

        return conf_properties

    def get_oem_parameter(self):
        product = os.path.join(os.path.dirname(__file__), 'product.xml')
        try:
            with open(product, 'r') as f:
                xml = f.read()
                root = etree.fromstring(xml)
                vendor_name = root.xpath('./VendorName')[0].text

                product_dict = {}
                product_map = root.xpath('./ProductMap/Product')
                for s in product_map:
                    product_dict[s.attrib['Name']] = int(s.text, 10)

                return vendor_name, product_dict
        except OSError as e:
            with excutils.save_and_reraise_exception() as ctxt:
                if e.errno == errno.ENOENT:
                    ctxt.reraise = False
            raise exception.NotFound(_('%s not found.') % product)

    @staticmethod
    def get_ldname(volid, volformat):
        alnum = ('0123456789'
                 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz')
        ldname = ""
        num = int(volid.replace(("-"), ""), 16)
        while num != 0:
            ldname = alnum[num % len(alnum)] + ldname
            num = num - num % len(alnum)
            num = num // len(alnum)

        return volformat % ldname

    def get_ldset(self, ldsets, metadata=None):
        ldset = None
        if metadata is not None and 'ldset' in metadata:
            ldset_meta = metadata['ldset']
            LOG.debug('ldset(metadata)=%s.', ldset_meta)
            for tldset in ldsets.values():
                if tldset['ldsetname'] == ldset_meta:
                    ldset = ldsets[ldset_meta]
                    LOG.debug('ldset information(metadata specified)=%s.',
                              ldset)
                    break
            if ldset is None:
                msg = _('Logical Disk Set could not be found.')
                LOG.error(msg)
                raise exception.NotFound(msg)
        elif self._properties['ldset_name'] == '':
            nldset = len(ldsets)
            if nldset == 0:
                msg = _('Logical Disk Set could not be found.')
                raise exception.NotFound(msg)
            else:
                ldset = None
        else:
            if self._properties['ldset_name'] not in ldsets:
                msg = (_('Logical Disk Set `%s` could not be found.') %
                       self._properties['ldset_name'])
                raise exception.NotFound(msg)
            ldset = ldsets[self._properties['ldset_name']]
        return ldset

    def get_pool_capacity(self, pools, ldsets):
        pools = [pool for (pn, pool) in pools.items()
                 if len(self._properties['pool_pools']) == 0 or
                 pn in self._properties['pool_pools']]

        free_capacity_gb = 0
        total_capacity_gb = 0
        for pool in pools:
            # Convert to GB.
            tmp_total = int(pool['total'] // units.Gi)
            tmp_free = int(pool['free'] // units.Gi)

            if free_capacity_gb < tmp_free:
                total_capacity_gb = tmp_total
                free_capacity_gb = tmp_free

        return {'total_capacity_gb': total_capacity_gb,
                'free_capacity_gb': free_capacity_gb}

    def set_backend_max_ld_count(self, xml, root):
        section = root.xpath('./CMD_REQUEST')[0]
        version = section.get('version').replace('Version ', '')[0:3]
        version = float(version)
        if version < 9.1:
            if 512 < self._properties['ld_backend_max_count']:
                self._properties['ld_backend_max_count'] = 512
        else:
            if 1024 < self._properties['ld_backend_max_count']:
                self._properties['ld_backend_max_count'] = 1024

    def get_diskarray_max_ld_count(self, xml, root):
        max_ld_count = 0
        for section in root.xpath(
                './'
                'CMD_REQUEST/'
                'CHAPTER[@name="Disk Array"]/'
                'OBJECT[@name="Disk Array"]/'
                'SECTION[@name="Disk Array Detail Information"]'):
            unit = section.find('./UNIT[@name="Product ID"]')
            if unit is None:
                msg = (_('UNIT[@name="Product ID"] not found. '
                         'line=%(line)d out="%(out)s"') %
                       {'line': section.sourceline, 'out': xml})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            else:
                product_id = unit.text
                if product_id in self._properties['products']:
                    max_ld_count = self._properties['products'][product_id]
                else:
                    max_ld_count = 8192
                    LOG.debug('UNIT[@name="Product ID"] unknown id. '
                              'productId=%s', product_id)
                LOG.debug('UNIT[@name="Product ID"] max_ld_count=%d.',
                          max_ld_count)
        return max_ld_count

    def get_pool_config(self, xml, root):
        pools = {}
        for xmlobj in root.xpath('./'
                                 'CMD_REQUEST/'
                                 'CHAPTER[@name="Pool"]/'
                                 'OBJECT[@name="Pool"]'):
            section = xmlobj.find('./SECTION[@name="Pool Detail Information"]')
            if section is None:
                msg = (_('SECTION[@name="Pool Detail Information"] '
                         'not found. line=%(line)d out="%(out)s"') %
                       {'line': xmlobj.sourceline, 'out': xml})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            unit = section.find('./UNIT[@name="Pool No.(h)"]')
            if unit is None:
                msg = (_('UNIT[@name="Pool No.(h)"] not found. '
                         'line=%(line)d out="%(out)s"') %
                       {'line': section.sourceline, 'out': xml})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            pool_num = int(unit.text, 16)
            unit = section.find('UNIT[@name="Pool Capacity"]')
            if unit is None:
                msg = (_('UNIT[@name="Pool Capacity"] not found. '
                         'line=%(line)d out="%(out)s"') %
                       {'line': section.sourceline, 'out': xml})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            total = int(unit.text, 10)
            unit = section.find('UNIT[@name="Free Pool Capacity"]')
            if unit is None:
                msg = (_('UNIT[@name="Free Pool Capacity"] not found. '
                         'line=%(line)d out="%(out)s"') %
                       {'line': section.sourceline, 'out': xml})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            free = int(unit.text, 10)
            if self._properties['pool_actual_free_capacity']:
                unit = section.find('UNIT[@name="Used Pool Capacity"]')
                if unit is None:
                    msg = (_('UNIT[@name="Used Pool Capacity"] not found. '
                             'line=%(line)d out="%(out)s"') %
                           {'line': section.sourceline, 'out': xml})
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)
                used = int(unit.text, 10)
                for section in xmlobj.xpath('./SECTION[@name='
                                            '"Virtual Capacity Pool '
                                            'Information"]'):
                    unit = section.find('UNIT[@name="Actual Capacity"]')
                    if unit is None:
                        msg = (_('UNIT[@name="Actual Capacity"] not found. '
                                 'line=%(line)d out="%(out)s"') %
                               {'line': section.sourceline, 'out': xml})
                        LOG.error(msg)
                        raise exception.VolumeBackendAPIException(data=msg)
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
            if unit is None:
                msg = (_('UNIT[@name="LDN(h)"] not found. '
                         'line=%(line)d out="%(out)s"') %
                       {'line': section.sourceline, 'out': xml})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            ldn = int(unit.text, 16)
            unit = section.find('./UNIT[@name="OS Type"]')
            if unit is None:
                msg = (_('UNIT[@name="OS Type"] not found. '
                         'line=%(line)d out="%(out)s"') %
                       {'line': section.sourceline, 'out': xml})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            ostype = unit.text if unit.text is not None else ''
            unit = section.find('./UNIT[@name="LD Name"]')
            if unit is None:
                msg = (_('UNIT[@name="LD Name"] not found. '
                         'line=%(line)d out="%(out)s"') %
                       {'line': section.sourceline, 'out': xml})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            ldname = ostype + ':' + unit.text
            unit = section.find('./UNIT[@name="Pool No.(h)"]')
            if unit is None:
                msg = (_('UNIT[@name="Pool No.(h)"] not found. '
                         'line=%(line)d out="%(out)s"') %
                       {'line': section.sourceline, 'out': xml})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            pool_num = int(unit.text, 16)

            unit = section.find('./UNIT[@name="LD Capacity"]')
            if unit is None:
                msg = (_('UNIT[@name="LD Capacity"] not found. '
                         'line=%(line)d out="%(out)s"') %
                       {'line': section.sourceline, 'out': xml})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

            # byte capacity transform GB capacity.
            ld_capacity = int(unit.text, 10) // units.Gi

            unit = section.find('./UNIT[@name="RPL Attribute"]')
            if unit is None:
                msg = (_('UNIT[@name="RPL Attribute"] not found. '
                         'line=%(line)d out="%(out)s"') %
                       {'line': section.sourceline, 'out': xml})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            rplatr = unit.text

            unit = section.find('./UNIT[@name="Purpose"]')
            if unit is None:
                msg = (_('UNIT[@name="Purpose"] not found. '
                         'line=%(line)d out="%(out)s"') %
                       {'line': section.sourceline, 'out': xml})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
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
            initiators = []
            for unit in xmlobj.xpath('./SECTION[@name="Portal"]/'
                                     'UNIT[@name="Portal"]'):
                if not unit.text.startswith('0.0.0.0:'):
                    portals.append(unit.text)

            for unit in xmlobj.xpath('./SECTION[@name="Initiator List"]/'
                                     'UNIT[@name="Initiator List"]'):
                initiators.append(unit.text)

            section = xmlobj.find('./SECTION[@name="LD Set(iSCSI)'
                                  ' Information"]')
            if section is None:
                return ldsets
            unit = section.find('./UNIT[@name="Platform"]')
            if unit is None:
                msg = (_('UNIT[@name="Platform"] not found. '
                         'line=%(line)d out="%(out)s"') %
                       {'line': section.sourceline, 'out': xml})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            platform = unit.text
            unit = section.find('./UNIT[@name="LD Set Name"]')
            if unit is None:
                msg = (_('UNIT[@name="LD Set Name"] not found. '
                         'line=%(line)d out="%(out)s"') %
                       {'line': section.sourceline, 'out': xml})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            ldsetname = platform + ':' + unit.text
            unit = section.find('./UNIT[@name="Target Mode"]')
            if unit is None:
                msg = (_('UNIT[@name="Target Mode"] not found. '
                         'line=%(line)d out="%(out)s"') %
                       {'line': section.sourceline, 'out': xml})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            tmode = unit.text
            if tmode == 'Normal':
                unit = section.find('./UNIT[@name="Target Name"]')
                if unit is None:
                    msg = (_('UNIT[@name="Target Name"] not found. '
                             'line=%(line)d out="%(out)s"') %
                           {'line': section.sourceline, 'out': xml})
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)
                iqn = unit.text
                for section in xmlobj.xpath('./SECTION[@name="LUN/LD List"]'):
                    unit = section.find('./UNIT[@name="LDN(h)"]')
                    if unit is None:
                        msg = (_('UNIT[@name="LDN(h)"] not found. '
                                 'line=%(line)d out="%(out)s"') %
                               {'line': section.sourceline, 'out': xml})
                        LOG.error(msg)
                        raise exception.VolumeBackendAPIException(data=msg)
                    ldn = int(unit.text, 16)
                    unit = section.find('./UNIT[@name="LUN(h)"]')
                    if unit is None:
                        msg = (_('UNIT[@name="LUN(h)"] not found. '
                                 'line=%(line)d out="%(out)s"') %
                               {'line': section.sourceline, 'out': xml})
                        LOG.error(msg)
                        raise exception.VolumeBackendAPIException(data=msg)
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
                    if unit is None:
                        msg = (_('UNIT[@name="Target Name"] not found. '
                                 'line=%(line)d out="%(out)s"') %
                               {'line': section.sourceline, 'out': xml})
                        LOG.error(msg)
                        raise exception.VolumeBackendAPIException(data=msg)
                    iqn = unit.text
                    unit = section.find('./UNIT[@name="LDN(h)"]')
                    if unit is None:
                        msg = (_('UNIT[@name="LDN(h)"] not found. '
                                 'line=%(line)d out="%(out)s"') %
                               {'line': section.sourceline, 'out': xml})
                        LOG.error(msg)
                        raise exception.VolumeBackendAPIException(data=msg)
                    if unit.text.startswith('-'):
                        continue
                    ldn = int(unit.text, 16)
                    unit = section.find('./UNIT[@name="LUN(h)"]')
                    if unit is None:
                        msg = (_('UNIT[@name="LUN(h)"] not found. '
                                 'line=%(line)d out="%(out)s"') %
                               {'line': section.sourceline, 'out': xml})
                        LOG.error(msg)
                        raise exception.VolumeBackendAPIException(data=msg)
                    if unit.text.startswith('-'):
                        continue
                    lun = int(unit.text, 16)
                    ld = {'ldn': ldn,
                          'lun': lun,
                          'iqn': iqn}
                    ldsetlds[ldn] = ld
            else:
                LOG.debug('`%(mode)s` Unknown Target Mode. '
                          'line=%(line)d out="%(out)s"',
                          {'mode': tmode, 'line': unit.sourceline, 'out': xml})
            ldset = {'ldsetname': ldsetname,
                     'protocol': 'iSCSI',
                     'portal_list': portals,
                     'lds': ldsetlds,
                     'initiator_list': initiators}
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
            if unit is None:
                msg = (_('UNIT[@name="Platform"] not found. '
                         'line=%(line)d out="%(out)s"') %
                       {'line': section.sourceline, 'out': xml})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            platform = unit.text
            unit = section.find('./UNIT[@name="LD Set Name"]')
            if unit is None:
                msg = (_('UNIT[@name="LD Set Name"] not found. '
                         'line=%(line)d out="%(out)s"') %
                       {'line': section.sourceline, 'out': xml})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            ldsetname = platform + ':' + unit.text
            wwpns = []
            ports = []
            for section in xmlobj.xpath('./SECTION[@name="Path List"]'):
                unit = section.find('./UNIT[@name="Path"]')
                if unit is None:
                    msg = (_('UNIT[@name="Path"] not found. '
                             'line=%(line)d out="%(out)s"') %
                           {'line': section.sourceline, 'out': xml})
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)
                if unit.text.find('(') != -1:
                    ports.append(unit.text)
                else:
                    wwpns.append(unit.text)
            for section in xmlobj.xpath('./SECTION[@name="LUN/LD List"]'):
                unit = section.find('./UNIT[@name="LDN(h)"]')
                if unit is None:
                    msg = (_('UNIT[@name="LDN(h)"] not found. '
                             'line=%(line)d out="%(out)s"') %
                           {'line': section.sourceline, 'out': xml})
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)
                ldn = int(unit.text, 16)
                unit = section.find('./UNIT[@name="LUN(h)"]')
                if unit is None:
                    msg = (_('UNIT[@name="LUN(h)"] not found. '
                             'line=%(line)d out="%(out)s"') %
                           {'line': section.sourceline, 'out': xml})
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)
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
            if unit is None:
                msg = (_('UNIT[@name="Port No.(h)"] not found. '
                         'line=%(line)d out="%(out)s"') %
                       {'line': section.sourceline, 'out': xml})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            units = unit.text.split('-')
            director = int(units[0], 16)
            port = int(units[1], 16)
            unit = section.find('./UNIT[@name="IP Address"]')
            if unit is None:
                unit = section.find('./UNIT[@name="WWPN"]')
                if unit is None:
                    msg = (_('UNIT[@name="WWPN"] not found. '
                             'line=%(line)d out="%(out)s"') %
                           {'line': section.sourceline, 'out': xml})
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)
                wwpn = unit.text
                hostport = {
                    'director': director,
                    'port': port,
                    'wwpn': wwpn,
                    'protocol': 'FC',
                }
            else:
                ip = unit.text
                if ip == '0.0.0.0':
                    continue

                hostport = {
                    'director': director,
                    'port': port,
                    'ip': ip,
                    'protocol': 'iSCSI',
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
        diskarray_max_ld_count = self.get_diskarray_max_ld_count(xml, root)

        self.set_backend_max_ld_count(xml, root)

        ldsets = {}
        ldsets.update(iscsi_ldsets)
        ldsets.update(fc_ldsets)

        return pools, lds, ldsets, used_ldns, hostports, diskarray_max_ld_count

    def get_xml(self):
        ismview_path = self._properties['ismview_path']
        if os.path.exists(ismview_path) and os.path.isfile(ismview_path):
            with open(ismview_path, 'r') as f:
                xml = f.read()
                LOG.debug('loaded from %s.', ismview_path)
        else:
            xml = self._cli.view_all(ismview_path, False, False)
        return xml

    def parse_xml(self):
        try:
            xml = self.get_xml()
            return self.configs(xml)
        except Exception:
            LOG.debug('parse_xml Unexpected error. exception=%s',
                      traceback.format_exc())
            xml = self._cli.view_all(self._properties['ismview_path'], False)
            return self.configs(xml)

    def get_volume_type_qos_specs(self, volume):
        specs = {}

        ctxt = context.get_admin_context()
        type_id = volume.volume_type_id
        if type_id is not None:
            volume_type = volume_types.get_volume_type(ctxt, type_id)

            qos_specs_id = volume_type.get('qos_specs_id')
            if qos_specs_id is not None:
                specs = qos_specs.get_qos_specs(ctxt, qos_specs_id)['specs']

            LOG.debug('get_volume_type_qos_specs '
                      'volume_type=%(volume_type)s, '
                      'qos_specs_id=%(qos_spec_id)s '
                      'specs=%(specs)s',
                      {'volume_type': volume_type,
                       'qos_spec_id': qos_specs_id,
                       'specs': specs})
        return specs

    def check_io_parameter(self, specs):
        if ('upperlimit' not in specs and
                'lowerlimit' not in specs and
                'upperreport' not in specs):
            specs['upperlimit'] = None
            specs['lowerlimit'] = None
            specs['upperreport'] = None
            LOG.debug('qos parameter not found.')
        else:
            if 'upperlimit' in specs and specs['upperlimit'] is not None:
                if self.validates_number(specs['upperlimit']) is True:
                    upper_limit = int(specs['upperlimit'], 10)
                    if ((upper_limit != 0) and
                            ((upper_limit < 10) or (upper_limit > 1000000))):
                        raise exception.InvalidConfigurationValue(
                            value=upper_limit, option='upperlimit')
                else:
                    raise exception.InvalidConfigurationValue(
                        value=specs['upperlimit'], option='upperlimit')
            else:
                specs['upperlimit'] = None

            if 'lowerlimit' in specs and specs['lowerlimit'] is not None:
                if self.validates_number(specs['lowerlimit']) is True:
                    lower_limit = int(specs['lowerlimit'], 10)
                    if (lower_limit != 0 and (lower_limit < 10 or
                                              lower_limit > 1000000)):
                        raise exception.InvalidConfigurationValue(
                            value=lower_limit, option='lowerlimit')
                else:
                    raise exception.InvalidConfigurationValue(
                        value=specs['lowerlimit'], option='lowerlimit')
            else:
                specs['lowerlimit'] = None

            if 'upperreport' in specs:
                if specs['upperreport'] not in ['on', 'off']:
                    LOG.debug('Illegal arguments. '
                              'upperreport is not on or off.'
                              'upperreport=%s', specs['upperreport'])
                    specs['upperreport'] = None
            else:
                specs['upperreport'] = None

    def validates_number(self, value):
        return re.match(r'^(?![-+]0+$)[-+]?([1-9][0-9]*)?[0-9](\.[0-9]+)?$',
                        '%s' % value) and True or False
