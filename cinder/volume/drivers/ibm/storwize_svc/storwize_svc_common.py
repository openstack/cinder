# Copyright 2015 IBM Corp.
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
#

import math
import paramiko
import random
import re
import time
import unicodedata

from eventlet import greenthread
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils as json
from oslo_service import loopingcall
from oslo_utils import excutils
from oslo_utils import strutils
from oslo_utils import units
import six

from cinder import context
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder.objects import fields
from cinder import ssh_utils
from cinder import utils as cinder_utils
from cinder.volume import configuration
from cinder.volume import driver
from cinder.volume.drivers.ibm.storwize_svc import (
    replication as storwize_rep)
from cinder.volume.drivers.ibm.storwize_svc import storwize_const
from cinder.volume.drivers.san import san
from cinder.volume import qos_specs
from cinder.volume import utils
from cinder.volume import volume_types


INTERVAL_1_SEC = 1
DEFAULT_TIMEOUT = 15
LOG = logging.getLogger(__name__)

storwize_svc_opts = [
    cfg.ListOpt('storwize_svc_volpool_name',
                default=['volpool'],
                help='Comma separated list of storage system storage '
                     'pools for volumes.'),
    cfg.IntOpt('storwize_svc_vol_rsize',
               default=2,
               min=-1, max=100,
               help='Storage system space-efficiency parameter for volumes '
                    '(percentage)'),
    cfg.IntOpt('storwize_svc_vol_warning',
               default=0,
               min=-1, max=100,
               help='Storage system threshold for volume capacity warnings '
                    '(percentage)'),
    cfg.BoolOpt('storwize_svc_vol_autoexpand',
                default=True,
                help='Storage system autoexpand parameter for volumes '
                     '(True/False)'),
    cfg.IntOpt('storwize_svc_vol_grainsize',
               default=256,
               help='Storage system grain size parameter for volumes '
                    '(32/64/128/256)'),
    cfg.BoolOpt('storwize_svc_vol_compression',
                default=False,
                help='Storage system compression option for volumes'),
    cfg.BoolOpt('storwize_svc_vol_easytier',
                default=True,
                help='Enable Easy Tier for volumes'),
    cfg.StrOpt('storwize_svc_vol_iogrp',
               default='0',
               help='The I/O group in which to allocate volumes. It can be a '
               'comma-separated list in which case the driver will select an '
               'io_group based on least number of volumes associated with the '
               'io_group.'),
    cfg.IntOpt('storwize_svc_flashcopy_timeout',
               default=120,
               min=1, max=600,
               help='Maximum number of seconds to wait for FlashCopy to be '
                    'prepared.'),
    cfg.BoolOpt('storwize_svc_multihostmap_enabled',
                default=True,
                help='This option no longer has any affect. It is deprecated '
                     'and will be removed in the next release.',
                deprecated_for_removal=True),
    cfg.BoolOpt('storwize_svc_allow_tenant_qos',
                default=False,
                help='Allow tenants to specify QOS on create'),
    cfg.StrOpt('storwize_svc_stretched_cluster_partner',
               default=None,
               help='If operating in stretched cluster mode, specify the '
                    'name of the pool in which mirrored copies are stored.'
                    'Example: "pool2"'),
    cfg.StrOpt('storwize_san_secondary_ip',
               default=None,
               help='Specifies secondary management IP or hostname to be '
                    'used if san_ip is invalid or becomes inaccessible.'),
    cfg.BoolOpt('storwize_svc_vol_nofmtdisk',
                default=False,
                help='Specifies that the volume not be formatted during '
                     'creation.'),
    cfg.IntOpt('storwize_svc_flashcopy_rate',
               default=50,
               min=1, max=100,
               help='Specifies the Storwize FlashCopy copy rate to be used '
               'when creating a full volume copy. The default is rate '
               'is 50, and the valid rates are 1-100.'),
    cfg.StrOpt('storwize_svc_mirror_pool',
               default=None,
               help='Specifies the name of the pool in which mirrored copy '
                    'is stored. Example: "pool2"'),
    cfg.IntOpt('cycle_period_seconds',
               default=300,
               min=60, max=86400,
               help='This defines an optional cycle period that applies to '
               'Global Mirror relationships with a cycling mode of multi. '
               'A Global Mirror relationship using the multi cycling_mode '
               'performs a complete cycle at most once each period. '
               'The default is 300 seconds, and the valid seconds '
               'are 60-86400.'),
]

CONF = cfg.CONF
CONF.register_opts(storwize_svc_opts, group=configuration.SHARED_CONF_GROUP)


class StorwizeSSH(object):
    """SSH interface to IBM Storwize family and SVC storage systems."""
    def __init__(self, run_ssh):
        self._ssh = run_ssh

    def _run_ssh(self, ssh_cmd):
        try:
            return self._ssh(ssh_cmd)
        except processutils.ProcessExecutionError as e:
            msg = (_('CLI Exception output:\n command: %(cmd)s\n '
                     'stdout: %(out)s\n stderr: %(err)s.') %
                   {'cmd': ssh_cmd,
                    'out': e.stdout,
                    'err': e.stderr})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def run_ssh_info(self, ssh_cmd, delim='!', with_header=False):
        """Run an SSH command and return parsed output."""
        raw = self._run_ssh(ssh_cmd)
        return CLIResponse(raw, ssh_cmd=ssh_cmd, delim=delim,
                           with_header=with_header)

    def run_ssh_assert_no_output(self, ssh_cmd):
        """Run an SSH command and assert no output returned."""
        out, err = self._run_ssh(ssh_cmd)
        if len(out.strip()) != 0:
            msg = (_('Expected no output from CLI command %(cmd)s, '
                     'got %(out)s.') % {'cmd': ' '.join(ssh_cmd), 'out': out})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def run_ssh_check_created(self, ssh_cmd):
        """Run an SSH command and return the ID of the created object."""
        out, err = self._run_ssh(ssh_cmd)
        try:
            match_obj = re.search(r'\[([0-9]+)\],? successfully created', out)
            return match_obj.group(1)
        except (AttributeError, IndexError):
            msg = (_('Failed to parse CLI output:\n command: %(cmd)s\n '
                     'stdout: %(out)s\n stderr: %(err)s.') %
                   {'cmd': ssh_cmd,
                    'out': out,
                    'err': err})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def lsnode(self, node_id=None):
        with_header = True
        ssh_cmd = ['svcinfo', 'lsnode', '-delim', '!']
        if node_id:
            with_header = False
            ssh_cmd.append(node_id)
        return self.run_ssh_info(ssh_cmd, with_header=with_header)

    def lslicense(self):
        ssh_cmd = ['svcinfo', 'lslicense', '-delim', '!']
        return self.run_ssh_info(ssh_cmd)[0]

    def lsguicapabilities(self):
        ssh_cmd = ['svcinfo', 'lsguicapabilities', '-delim', '!']
        return self.run_ssh_info(ssh_cmd)[0]

    def lssystem(self):
        ssh_cmd = ['svcinfo', 'lssystem', '-delim', '!']
        return self.run_ssh_info(ssh_cmd)[0]

    def lsmdiskgrp(self, pool):
        ssh_cmd = ['svcinfo', 'lsmdiskgrp', '-bytes', '-delim', '!',
                   '"%s"' % pool]
        try:
            return self.run_ssh_info(ssh_cmd)[0]
        except exception.VolumeBackendAPIException as ex:
            LOG.warning("Failed to get pool %(pool)s info. "
                        "Exception: %(ex)s.", {'pool': pool,
                                               'ex': ex})
            return None

    def lsiogrp(self):
        ssh_cmd = ['svcinfo', 'lsiogrp', '-delim', '!']
        return self.run_ssh_info(ssh_cmd, with_header=True)

    def lsportip(self):
        ssh_cmd = ['svcinfo', 'lsportip', '-delim', '!']
        return self.run_ssh_info(ssh_cmd, with_header=True)

    @staticmethod
    def _create_port_arg(port_type, port_name):
        if port_type == 'initiator':
            port = ['-iscsiname']
        else:
            port = ['-hbawwpn']
        port.append(port_name)
        return port

    def mkhost(self, host_name, port_type, port_name):
        port = self._create_port_arg(port_type, port_name)
        ssh_cmd = ['svctask', 'mkhost', '-force'] + port
        ssh_cmd += ['-name', '"%s"' % host_name]
        return self.run_ssh_check_created(ssh_cmd)

    def addhostport(self, host, port_type, port_name):
        port = self._create_port_arg(port_type, port_name)
        ssh_cmd = ['svctask', 'addhostport', '-force'] + port + ['"%s"' % host]
        self.run_ssh_assert_no_output(ssh_cmd)

    def lshost(self, host=None):
        with_header = True
        ssh_cmd = ['svcinfo', 'lshost', '-delim', '!']
        if host:
            with_header = False
            ssh_cmd.append('"%s"' % host)
        return self.run_ssh_info(ssh_cmd, with_header=with_header)

    def add_chap_secret(self, secret, host):
        ssh_cmd = ['svctask', 'chhost', '-chapsecret', secret, '"%s"' % host]
        self.run_ssh_assert_no_output(ssh_cmd)

    def lsiscsiauth(self):
        ssh_cmd = ['svcinfo', 'lsiscsiauth', '-delim', '!']
        return self.run_ssh_info(ssh_cmd, with_header=True)

    def lsfabric(self, wwpn=None, host=None):
        ssh_cmd = ['svcinfo', 'lsfabric', '-delim', '!']
        if wwpn:
            ssh_cmd.extend(['-wwpn', wwpn])
        elif host:
            ssh_cmd.extend(['-host', '"%s"' % host])
        else:
            msg = (_('Must pass wwpn or host to lsfabric.'))
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)
        return self.run_ssh_info(ssh_cmd, with_header=True)

    def mkvdiskhostmap(self, host, vdisk, lun, multihostmap):
        """Map vdisk to host.

        If vdisk already mapped and multihostmap is True, use the force flag.
        """
        ssh_cmd = ['svctask', 'mkvdiskhostmap', '-host', '"%s"' % host, vdisk]

        if lun:
            ssh_cmd.insert(ssh_cmd.index(vdisk), '-scsi')
            ssh_cmd.insert(ssh_cmd.index(vdisk), lun)

        if multihostmap:
            ssh_cmd.insert(ssh_cmd.index('mkvdiskhostmap') + 1, '-force')
        try:
            self.run_ssh_check_created(ssh_cmd)
            result_lun = self.get_vdiskhostmapid(vdisk, host)
            if result_lun is None or (lun and lun != result_lun):
                msg = (_('mkvdiskhostmap error:\n command: %(cmd)s\n '
                       'lun: %(lun)s\n result_lun: %(result_lun)s') %
                       {'cmd': ssh_cmd,
                        'lun': lun,
                        'result_lun': result_lun})
                LOG.error(msg)
                raise exception.VolumeDriverException(message=msg)
            return result_lun
        except Exception as ex:
            if (not multihostmap and hasattr(ex, 'message') and
                    'CMMVC6071E' in ex.message):
                LOG.error('storwize_svc_multihostmap_enabled is set '
                          'to False, not allowing multi host mapping.')
                raise exception.VolumeDriverException(
                    message=_('CMMVC6071E The VDisk-to-host mapping was not '
                              'created because the VDisk is already mapped '
                              'to a host.\n"'))
            with excutils.save_and_reraise_exception():
                LOG.error('Error mapping VDisk-to-host')

    def mkrcrelationship(self, master, aux, system, asyncmirror,
                         cyclingmode=False):
        ssh_cmd = ['svctask', 'mkrcrelationship', '-master', master,
                   '-aux', aux, '-cluster', system]
        if asyncmirror:
            ssh_cmd.append('-global')
        if cyclingmode:
            ssh_cmd.extend(['-cyclingmode', 'multi'])
        return self.run_ssh_check_created(ssh_cmd)

    def rmrcrelationship(self, relationship, force=False):
        ssh_cmd = ['svctask', 'rmrcrelationship']
        if force:
            ssh_cmd += ['-force']
        ssh_cmd += [relationship]
        self.run_ssh_assert_no_output(ssh_cmd)

    def switchrelationship(self, relationship, aux=True):
        primary = 'aux' if aux else 'master'
        ssh_cmd = ['svctask', 'switchrcrelationship', '-primary',
                   primary, relationship]
        self.run_ssh_assert_no_output(ssh_cmd)

    def startrcrelationship(self, rc_rel, primary=None):
        ssh_cmd = ['svctask', 'startrcrelationship', '-force']
        if primary:
            ssh_cmd.extend(['-primary', primary])
        ssh_cmd.append(rc_rel)
        self.run_ssh_assert_no_output(ssh_cmd)

    def ch_rcrelationship_cycleperiod(self, relationship,
                                      cycle_period_seconds):
        # Note: Can only change one attribute at a time,
        # so define two ch_rcrelationship_xxx here
        if cycle_period_seconds:
            ssh_cmd = ['svctask', 'chrcrelationship']
            ssh_cmd.extend(['-cycleperiodseconds',
                            six.text_type(cycle_period_seconds)])
            ssh_cmd.append(relationship)
            self.run_ssh_assert_no_output(ssh_cmd)

    def ch_rcrelationship_changevolume(self, relationship,
                                       changevolume, master):
        # Note: Can only change one attribute at a time,
        # so define two ch_rcrelationship_xxx here
        if changevolume:
            ssh_cmd = ['svctask', 'chrcrelationship']
            if master:
                ssh_cmd.extend(['-masterchange', changevolume])
            else:
                ssh_cmd.extend(['-auxchange', changevolume])
            ssh_cmd.append(relationship)
            self.run_ssh_assert_no_output(ssh_cmd)

    def stoprcrelationship(self, relationship, access=False):
        ssh_cmd = ['svctask', 'stoprcrelationship']
        if access:
            ssh_cmd.append('-access')
        ssh_cmd.append(relationship)
        self.run_ssh_assert_no_output(ssh_cmd)

    def lsrcrelationship(self, rc_rel):
        ssh_cmd = ['svcinfo', 'lsrcrelationship', '-delim', '!', rc_rel]
        return self.run_ssh_info(ssh_cmd)

    def lspartnership(self, system_name):
        key_value = 'name=%s' % system_name
        ssh_cmd = ['svcinfo', 'lspartnership', '-filtervalue',
                   key_value, '-delim', '!']
        return self.run_ssh_info(ssh_cmd, with_header=True)

    def lspartnershipcandidate(self):
        ssh_cmd = ['svcinfo', 'lspartnershipcandidate', '-delim', '!']
        return self.run_ssh_info(ssh_cmd, with_header=True)

    def mkippartnership(self, ip_v4, bandwith=1000, backgroundcopyrate=50):
        ssh_cmd = ['svctask', 'mkippartnership', '-type', 'ipv4',
                   '-clusterip', ip_v4, '-linkbandwidthmbits',
                   six.text_type(bandwith),
                   '-backgroundcopyrate', six.text_type(backgroundcopyrate)]
        return self.run_ssh_assert_no_output(ssh_cmd)

    def mkfcpartnership(self, system_name, bandwith=1000,
                        backgroundcopyrate=50):
        ssh_cmd = ['svctask', 'mkfcpartnership', '-linkbandwidthmbits',
                   six.text_type(bandwith),
                   '-backgroundcopyrate', six.text_type(backgroundcopyrate),
                   system_name]
        return self.run_ssh_assert_no_output(ssh_cmd)

    def chpartnership(self, partnership_id, start=True):
        action = '-start' if start else '-stop'
        ssh_cmd = ['svctask', 'chpartnership', action, partnership_id]
        return self.run_ssh_assert_no_output(ssh_cmd)

    def rmvdiskhostmap(self, host, vdisk):
        ssh_cmd = ['svctask', 'rmvdiskhostmap', '-host', '"%s"' % host,
                   '"%s"' % vdisk]
        self.run_ssh_assert_no_output(ssh_cmd)

    def lsvdiskhostmap(self, vdisk):
        ssh_cmd = ['svcinfo', 'lsvdiskhostmap', '-delim', '!', '"%s"' % vdisk]
        return self.run_ssh_info(ssh_cmd, with_header=True)

    def lshostvdiskmap(self, host):
        ssh_cmd = ['svcinfo', 'lshostvdiskmap', '-delim', '!', '"%s"' % host]
        return self.run_ssh_info(ssh_cmd, with_header=True)

    def get_vdiskhostmapid(self, vdisk, host):
        resp = self.lsvdiskhostmap(vdisk)
        for mapping_info in resp:
            if mapping_info['host_name'] == host:
                lun_id = mapping_info['SCSI_id']
                return lun_id
        return None

    def rmhost(self, host):
        ssh_cmd = ['svctask', 'rmhost', '"%s"' % host]
        self.run_ssh_assert_no_output(ssh_cmd)

    def mkvdisk(self, name, size, units, pool, opts, params):
        ssh_cmd = ['svctask', 'mkvdisk', '-name', '"%s"' % name, '-mdiskgrp',
                   '"%s"' % pool, '-iogrp', six.text_type(opts['iogrp']),
                   '-size', size, '-unit', units] + params
        try:
            return self.run_ssh_check_created(ssh_cmd)
        except Exception as ex:
            if hasattr(ex, 'msg') and 'CMMVC6372W' in ex.msg:
                vdisk = self.lsvdisk(name)
                if vdisk:
                    LOG.warning('CMMVC6372W The virtualized storage '
                                'capacity that the cluster is using is '
                                'approaching the virtualized storage '
                                'capacity that is licensed.')
                    return vdisk['id']
            with excutils.save_and_reraise_exception():
                LOG.exception('Failed to create vdisk %(vol)s.',
                              {'vol': name})

    def rmvdisk(self, vdisk, force=True):
        ssh_cmd = ['svctask', 'rmvdisk']
        if force:
            ssh_cmd += ['-force']
        ssh_cmd += ['"%s"' % vdisk]
        self.run_ssh_assert_no_output(ssh_cmd)

    def lsvdisk(self, vdisk):
        """Return vdisk attributes or None if it doesn't exist."""
        ssh_cmd = ['svcinfo', 'lsvdisk', '-bytes', '-delim', '!',
                   '"%s"' % vdisk]
        out, err = self._ssh(ssh_cmd, check_exit_code=False)
        if not err:
            return CLIResponse((out, err), ssh_cmd=ssh_cmd, delim='!',
                               with_header=False)[0]
        if 'CMMVC5754E' in err:
            return None
        msg = (_('CLI Exception output:\n command: %(cmd)s\n '
                 'stdout: %(out)s\n stderr: %(err)s.') %
               {'cmd': ssh_cmd,
                'out': out,
                'err': err})
        LOG.error(msg)
        raise exception.VolumeBackendAPIException(data=msg)

    def lsvdisks_from_filter(self, filter_name, value):
        """Performs an lsvdisk command, filtering the results as specified.

        Returns an iterable for all matching vdisks.
        """
        ssh_cmd = ['svcinfo', 'lsvdisk', '-bytes', '-delim', '!',
                   '-filtervalue', '%s=%s' % (filter_name, value)]
        return self.run_ssh_info(ssh_cmd, with_header=True)

    def chvdisk(self, vdisk, params):
        ssh_cmd = ['svctask', 'chvdisk'] + params + ['"%s"' % vdisk]
        self.run_ssh_assert_no_output(ssh_cmd)

    def movevdisk(self, vdisk, iogrp):
        ssh_cmd = ['svctask', 'movevdisk', '-iogrp', iogrp, '"%s"' % vdisk]
        self.run_ssh_assert_no_output(ssh_cmd)

    def expandvdisksize(self, vdisk, amount):
        ssh_cmd = (
            ['svctask', 'expandvdisksize', '-size', six.text_type(amount),
             '-unit', 'gb', '"%s"' % vdisk])
        self.run_ssh_assert_no_output(ssh_cmd)

    def mkfcmap(self, source, target, full_copy, copy_rate, consistgrp=None):
        ssh_cmd = ['svctask', 'mkfcmap', '-source', '"%s"' % source, '-target',
                   '"%s"' % target, '-autodelete']
        if not full_copy:
            ssh_cmd.extend(['-copyrate', '0'])
        else:
            ssh_cmd.extend(['-copyrate', six.text_type(copy_rate)])
        if consistgrp:
            ssh_cmd.extend(['-consistgrp', consistgrp])
        out, err = self._ssh(ssh_cmd, check_exit_code=False)
        if 'successfully created' not in out:
            msg = (_('CLI Exception output:\n command: %(cmd)s\n '
                     'stdout: %(out)s\n stderr: %(err)s.') %
                   {'cmd': ssh_cmd,
                    'out': out,
                    'err': err})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        try:
            match_obj = re.search(r'FlashCopy Mapping, id \[([0-9]+)\], '
                                  'successfully created', out)
            fc_map_id = match_obj.group(1)
        except (AttributeError, IndexError):
            msg = (_('Failed to parse CLI output:\n command: %(cmd)s\n '
                     'stdout: %(out)s\n stderr: %(err)s.') %
                   {'cmd': ssh_cmd,
                    'out': out,
                    'err': err})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        return fc_map_id

    def prestartfcmap(self, fc_map_id):
        ssh_cmd = ['svctask', 'prestartfcmap', fc_map_id]
        self.run_ssh_assert_no_output(ssh_cmd)

    def startfcmap(self, fc_map_id):
        ssh_cmd = ['svctask', 'startfcmap', fc_map_id]
        self.run_ssh_assert_no_output(ssh_cmd)

    def prestartfcconsistgrp(self, fc_consist_group):
        ssh_cmd = ['svctask', 'prestartfcconsistgrp', fc_consist_group]
        self.run_ssh_assert_no_output(ssh_cmd)

    def startfcconsistgrp(self, fc_consist_group):
        ssh_cmd = ['svctask', 'startfcconsistgrp', fc_consist_group]
        self.run_ssh_assert_no_output(ssh_cmd)

    def stopfcconsistgrp(self, fc_consist_group):
        ssh_cmd = ['svctask', 'stopfcconsistgrp', fc_consist_group]
        self.run_ssh_assert_no_output(ssh_cmd)

    def chfcmap(self, fc_map_id, copyrate='50', autodel='on'):
        ssh_cmd = ['svctask', 'chfcmap', '-copyrate', copyrate,
                   '-autodelete', autodel, fc_map_id]
        self.run_ssh_assert_no_output(ssh_cmd)

    def stopfcmap(self, fc_map_id):
        ssh_cmd = ['svctask', 'stopfcmap', fc_map_id]
        self.run_ssh_assert_no_output(ssh_cmd)

    def rmfcmap(self, fc_map_id):
        ssh_cmd = ['svctask', 'rmfcmap', '-force', fc_map_id]
        self.run_ssh_assert_no_output(ssh_cmd)

    def lsvdiskfcmappings(self, vdisk):
        ssh_cmd = ['svcinfo', 'lsvdiskfcmappings', '-delim', '!',
                   '"%s"' % vdisk]
        return self.run_ssh_info(ssh_cmd, with_header=True)

    def lsfcmap(self, fc_map_id):
        ssh_cmd = ['svcinfo', 'lsfcmap', '-filtervalue',
                   'id=%s' % fc_map_id, '-delim', '!']
        return self.run_ssh_info(ssh_cmd, with_header=True)

    def lsfcconsistgrp(self, fc_consistgrp):
        ssh_cmd = ['svcinfo', 'lsfcconsistgrp', '-delim', '!', fc_consistgrp]
        out, err = self._ssh(ssh_cmd)
        return CLIResponse((out, err), ssh_cmd=ssh_cmd, delim='!',
                           with_header=False)

    def mkfcconsistgrp(self, fc_consist_group):
        ssh_cmd = ['svctask', 'mkfcconsistgrp', '-name', fc_consist_group]
        return self.run_ssh_check_created(ssh_cmd)

    def rmfcconsistgrp(self, fc_consist_group):
        ssh_cmd = ['svctask', 'rmfcconsistgrp', '-force', fc_consist_group]
        return self.run_ssh_assert_no_output(ssh_cmd)

    def addvdiskcopy(self, vdisk, dest_pool, params, auto_delete):
        ssh_cmd = (['svctask', 'addvdiskcopy'] + params + ['-mdiskgrp',
                   '"%s"' % dest_pool])
        if auto_delete:
            ssh_cmd += ['-autodelete']
        ssh_cmd += ['"%s"' % vdisk]
        return self.run_ssh_check_created(ssh_cmd)

    def lsvdiskcopy(self, vdisk, copy_id=None):
        ssh_cmd = ['svcinfo', 'lsvdiskcopy', '-delim', '!']
        with_header = True
        if copy_id:
            ssh_cmd += ['-copy', copy_id]
            with_header = False
        ssh_cmd += ['"%s"' % vdisk]
        return self.run_ssh_info(ssh_cmd, with_header=with_header)

    def lsvdisksyncprogress(self, vdisk, copy_id):
        ssh_cmd = ['svcinfo', 'lsvdisksyncprogress', '-delim', '!',
                   '-copy', copy_id, '"%s"' % vdisk]
        return self.run_ssh_info(ssh_cmd, with_header=True)[0]

    def rmvdiskcopy(self, vdisk, copy_id):
        ssh_cmd = ['svctask', 'rmvdiskcopy', '-copy', copy_id, '"%s"' % vdisk]
        self.run_ssh_assert_no_output(ssh_cmd)

    def addvdiskaccess(self, vdisk, iogrp):
        ssh_cmd = ['svctask', 'addvdiskaccess', '-iogrp', iogrp,
                   '"%s"' % vdisk]
        self.run_ssh_assert_no_output(ssh_cmd)

    def rmvdiskaccess(self, vdisk, iogrp):
        ssh_cmd = ['svctask', 'rmvdiskaccess', '-iogrp', iogrp, '"%s"' % vdisk]
        self.run_ssh_assert_no_output(ssh_cmd)

    def lsportfc(self, node_id):
        ssh_cmd = ['svcinfo', 'lsportfc', '-delim', '!',
                   '-filtervalue', 'node_id=%s' % node_id]
        return self.run_ssh_info(ssh_cmd, with_header=True)

    def lstargetportfc(self, own_node_id=None, host_io_permitted=None):
        ssh_cmd = ['svcinfo', 'lstargetportfc', '-delim', '!']
        if own_node_id and host_io_permitted:
            ssh_cmd += ['-filtervalue', '%s:%s' % (
                'owning_node_id=%s' % own_node_id,
                'host_io_permitted=%s' % host_io_permitted)]
        elif own_node_id:
            ssh_cmd += ['-filtervalue', 'owning_node_id=%s' % own_node_id]
        return self.run_ssh_info(ssh_cmd, with_header=True)

    def migratevdisk(self, vdisk, dest_pool, copy_id='0'):
        ssh_cmd = ['svctask', 'migratevdisk', '-mdiskgrp', dest_pool, '-copy',
                   copy_id, '-vdisk', vdisk]
        self.run_ssh_assert_no_output(ssh_cmd)


class StorwizeHelpers(object):

    # All the supported QoS key are saved in this dict. When a new
    # key is going to add, three values MUST be set:
    # 'default': to indicate the value, when the parameter is disabled.
    # 'param': to indicate the corresponding parameter in the command.
    # 'type': to indicate the type of this value.
    WAIT_TIME = 5
    svc_qos_keys = {'IOThrottling': {'default': '0',
                                     'param': 'rate',
                                     'type': int}}

    def __init__(self, run_ssh):
        self.ssh = StorwizeSSH(run_ssh)
        self.check_fcmapping_interval = 3

    @staticmethod
    def handle_keyerror(cmd, out):
        msg = (_('Could not find key in output of command %(cmd)s: %(out)s.')
               % {'out': out, 'cmd': cmd})
        raise exception.VolumeBackendAPIException(data=msg)

    def compression_enabled(self):
        """Return whether or not compression is enabled for this system."""
        resp = self.ssh.lslicense()
        keys = ['license_compression_enclosures',
                'license_compression_capacity']
        for key in keys:
            if resp.get(key, '0') != '0':
                return True

        # lslicense is not used for V9000 compression check
        # compression_enclosures and compression_capacity are
        # always 0. V9000 uses license_scheme 9846 as an
        # indicator and can always do compression
        try:
            resp = self.ssh.lsguicapabilities()
            if resp.get('license_scheme', '0') == '9846':
                return True
        except exception.VolumeBackendAPIException:
            LOG.exception("Failed to fetch licensing scheme.")
        return False

    def replication_licensed(self):
        """Return whether or not replication is enabled for this system."""
        # Uses product_key as an indicator to check
        # whether replication is supported in storage.
        try:
            resp = self.ssh.lsguicapabilities()
            product_key = resp.get('product_key', '0')
            if product_key in storwize_const.REP_CAP_DEVS:
                return True
        except exception.VolumeBackendAPIException as war:
            LOG.warning("Failed to run lsguicapability. Exception: %s.", war)
        return False

    def get_system_info(self):
        """Return system's name, ID, and code level."""
        resp = self.ssh.lssystem()
        level = resp['code_level']
        match_obj = re.search('([0-9].){3}[0-9]', level)
        if match_obj is None:
            msg = _('Failed to get code level (%s).') % level
            raise exception.VolumeBackendAPIException(data=msg)
        code_level = match_obj.group().split('.')
        return {'code_level': tuple([int(x) for x in code_level]),
                'system_name': resp['name'],
                'system_id': resp['id']}

    def get_pool_attrs(self, pool):
        """Return attributes for the specified pool."""
        return self.ssh.lsmdiskgrp(pool)

    def is_pool_defined(self, pool_name):
        """Check if vdisk is defined."""
        attrs = self.get_pool_attrs(pool_name)
        return attrs is not None

    def get_available_io_groups(self):
        """Return list of available IO groups."""
        iogrps = []
        resp = self.ssh.lsiogrp()
        for iogrp in resp:
            try:
                if int(iogrp['node_count']) > 0:
                    iogrps.append(int(iogrp['id']))
            except KeyError:
                self.handle_keyerror('lsiogrp', iogrp)
            except ValueError:
                msg = (_('Expected integer for node_count, '
                         'svcinfo lsiogrp returned: %(node)s.') %
                       {'node': iogrp['node_count']})
                raise exception.VolumeBackendAPIException(data=msg)
        return iogrps

    def get_vdisk_count_by_io_group(self):
        res = {}
        resp = self.ssh.lsiogrp()
        for iogrp in resp:
            try:
                if int(iogrp['node_count']) > 0:
                    res[int(iogrp['id'])] = int(iogrp['vdisk_count'])
            except KeyError:
                self.handle_keyerror('lsiogrp', iogrp)
            except ValueError:
                msg = (_('Expected integer for node_count, '
                         'svcinfo lsiogrp returned: %(node)s') %
                       {'node': iogrp['node_count']})
                raise exception.VolumeBackendAPIException(data=msg)
        return res

    def select_io_group(self, state, opts):
        selected_iog = 0
        iog_list = StorwizeHelpers._get_valid_requested_io_groups(state, opts)
        if len(iog_list) == 0:
            raise exception.InvalidInput(
                reason=_('Given I/O group(s) %(iogrp)s not valid; available '
                         'I/O groups are %(avail)s.')
                % {'iogrp': opts['iogrp'],
                   'avail': state['available_iogrps']})
        iog_vdc = self.get_vdisk_count_by_io_group()
        LOG.debug("IO group current balance %s", iog_vdc)
        min_vdisk_count = iog_vdc[iog_list[0]]
        selected_iog = iog_list[0]
        for iog in iog_list:
            if iog_vdc[iog] < min_vdisk_count:
                min_vdisk_count = iog_vdc[iog]
                selected_iog = iog
        LOG.debug("Selected io_group is %d", selected_iog)
        return selected_iog

    def get_volume_io_group(self, vol_name):
        vdisk = self.ssh.lsvdisk(vol_name)
        if vdisk:
            resp = self.ssh.lsiogrp()
            for iogrp in resp:
                if iogrp['name'] == vdisk['IO_group_name']:
                    return int(iogrp['id'])
        return None

    def get_node_info(self):
        """Return dictionary containing information on system's nodes."""
        nodes = {}
        resp = self.ssh.lsnode()
        for node_data in resp:
            try:
                if node_data['status'] != 'online':
                    continue
                node = {}
                node['id'] = node_data['id']
                node['name'] = node_data['name']
                node['IO_group'] = node_data['IO_group_id']
                node['iscsi_name'] = node_data['iscsi_name']
                node['WWNN'] = node_data['WWNN']
                node['status'] = node_data['status']
                node['WWPN'] = []
                node['ipv4'] = []
                node['ipv6'] = []
                node['enabled_protocols'] = []
                nodes[node['id']] = node
            except KeyError:
                self.handle_keyerror('lsnode', node_data)
        return nodes

    def add_iscsi_ip_addrs(self, storage_nodes):
        """Add iSCSI IP addresses to system node information."""
        resp = self.ssh.lsportip()
        for ip_data in resp:
            try:
                state = ip_data['state']
                if ip_data['node_id'] in storage_nodes and (
                        state == 'configured' or state == 'online'):
                    node = storage_nodes[ip_data['node_id']]
                    if len(ip_data['IP_address']):
                        node['ipv4'].append(ip_data['IP_address'])
                    if len(ip_data['IP_address_6']):
                        node['ipv6'].append(ip_data['IP_address_6'])
            except KeyError:
                self.handle_keyerror('lsportip', ip_data)

    def add_fc_wwpns(self, storage_nodes, code_level):
        """Add FC WWPNs to system node information."""
        for key in storage_nodes:
            node = storage_nodes[key]
            wwpns = set(node['WWPN'])
            # The Storwize/svc release 7.7.0.0 introduced NPIV feature.
            # The virtual wwpns will be included in cli lstargetportfc
            if code_level < (7, 7, 0, 0):
                resp = self.ssh.lsportfc(node_id=node['id'])
                for port_info in resp:
                    if (port_info['type'] == 'fc' and
                            port_info['status'] == 'active'):
                        wwpns.add(port_info['WWPN'])
            else:
                npiv_wwpns = self.get_npiv_wwpns(node_id=node['id'])
                wwpns.update(npiv_wwpns)
            node['WWPN'] = list(wwpns)
            LOG.info('WWPN on node %(node)s: %(wwpn)s.',
                     {'node': node['id'], 'wwpn': node['WWPN']})

    def get_npiv_wwpns(self, node_id=None, host_io=None):
        wwpns = set()
        # In the response of lstargetportfc, the host_io_permitted
        # indicates whether the port can be used for host I/O
        resp = self.ssh.lstargetportfc(own_node_id=node_id,
                                       host_io_permitted=host_io)
        for port_info in resp:
            wwpns.add(port_info['WWPN'])
        return list(wwpns)

    def add_chap_secret_to_host(self, host_name):
        """Generate and store a randomly-generated CHAP secret for the host."""
        chap_secret = utils.generate_password()
        self.ssh.add_chap_secret(chap_secret, host_name)
        return chap_secret

    def get_chap_secret_for_host(self, host_name):
        """Generate and store a randomly-generated CHAP secret for the host."""
        resp = self.ssh.lsiscsiauth()
        host_found = False
        for host_data in resp:
            try:
                if host_data['name'] == host_name:
                    host_found = True
                    if host_data['iscsi_auth_method'] == 'chap':
                        return host_data['iscsi_chap_secret']
            except KeyError:
                self.handle_keyerror('lsiscsiauth', host_data)
        if not host_found:
            msg = _('Failed to find host %s.') % host_name
            raise exception.VolumeBackendAPIException(data=msg)
        return None

    def get_conn_fc_wwpns(self, host):
        wwpns = set()
        resp = self.ssh.lsfabric(host=host)
        for wwpn in resp.select('local_wwpn'):
            if wwpn is not None:
                wwpns.add(wwpn)
        return list(wwpns)

    def get_host_from_connector(self, connector, volume_name=None,
                                iscsi=False):
        """Return the Storwize host described by the connector."""
        LOG.debug('Enter: get_host_from_connector: %s.', connector)

        # If we have FC information, we have a faster lookup option
        host_name = None
        if 'wwpns' in connector and not iscsi:
            for wwpn in connector['wwpns']:
                resp = self.ssh.lsfabric(wwpn=wwpn)
                for wwpn_info in resp:
                    try:
                        if (wwpn_info['remote_wwpn'] and
                                wwpn_info['name'] and
                                wwpn_info['remote_wwpn'].lower() ==
                                wwpn.lower()):
                            host_name = wwpn_info['name']
                            break
                    except KeyError:
                        self.handle_keyerror('lsfabric', wwpn_info)
                if host_name:
                    break
        if host_name:
            LOG.debug('Leave: get_host_from_connector: host %s.', host_name)
            return host_name

        def update_host_list(host, host_list):
            idx = host_list.index(host)
            del host_list[idx]
            host_list.insert(0, host)

        # That didn't work, so try exhaustive search
        hosts_info = self.ssh.lshost()
        host_list = list(hosts_info.select('name'))
        # If we have a "real" connector, we might be able to find the
        # host entry with fewer queries if we move the host entries
        # that contain the connector's host property value to the front
        # of the list
        if 'host' in connector:
            # order host_list such that the host entries that
            # contain the connector's host name are at the
            # beginning of the list
            for host in host_list:
                if re.search(connector['host'], host):
                    update_host_list(host, host_list)
        # If we have a volume name we have a potential fast path
        # for finding the matching host for that volume.
        # Add the host_names that have mappings for our volume to the
        # head of the list of host names to search them first
        if volume_name:
            hosts_map_info = self.ssh.lsvdiskhostmap(volume_name)
            hosts_map_info_list = list(hosts_map_info.select('host_name'))
            # remove the fast path host names from the end of the list
            # and move to the front so they are only searched for once.
            for host in hosts_map_info_list:
                update_host_list(host, host_list)
        found = False
        for name in host_list:
            try:
                resp = self.ssh.lshost(host=name)
            except exception.VolumeBackendAPIException as ex:
                LOG.debug("Exception message: %s", ex.msg)
                if 'CMMVC5754E' in ex.msg:
                    LOG.debug("CMMVC5754E found in CLI exception.")
                    # CMMVC5754E: The specified object does not exist
                    # The host has been deleted while walking the list.
                    # This is a result of a host change on the SVC that
                    # is out of band to this request.
                    continue
                # unexpected error so reraise it
                with excutils.save_and_reraise_exception():
                    pass
            if iscsi:
                if 'initiator' in connector:
                    for iscsi_name in resp.select('iscsi_name'):
                        if iscsi_name == connector['initiator']:
                            host_name = name
                            found = True
                            break
            elif 'wwpns' in connector and len(connector['wwpns']):
                connector_wwpns = [str(x).lower() for x in connector['wwpns']]
                for wwpn in resp.select('WWPN'):
                    if wwpn and wwpn.lower() in connector_wwpns:
                        host_name = name
                        found = True
                        break
            if found:
                break

        LOG.debug('Leave: get_host_from_connector: host %s.', host_name)
        return host_name

    def create_host(self, connector, iscsi=False):
        """Create a new host on the storage system.

        We create a host name and associate it with the given connection
        information.  The host name will be a cleaned up version of the given
        host name (at most 55 characters), plus a random 8-character suffix to
        avoid collisions. The total length should be at most 63 characters.
        """
        LOG.debug('Enter: create_host: host %s.', connector['host'])

        # Before we start, make sure host name is a string and that we have at
        # least one port.
        host_name = connector['host']
        if not isinstance(host_name, six.string_types):
            msg = _('create_host: Host name is not unicode or string.')
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        ports = []
        if iscsi:
            if 'initiator' in connector:
                ports.append(['initiator', '%s' % connector['initiator']])
            else:
                msg = _('create_host: No initiators supplied.')
        else:
            if 'wwpns' in connector:
                for wwpn in connector['wwpns']:
                    ports.append(['wwpn', '%s' % wwpn])
            else:
                msg = _('create_host: No wwpns supplied.')
        if not len(ports):
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        # Build a host name for the Storwize host - first clean up the name
        if isinstance(host_name, six.text_type):
            host_name = unicodedata.normalize('NFKD', host_name).encode(
                'ascii', 'replace').decode('ascii')

        for num in range(0, 128):
            ch = str(chr(num))
            if not ch.isalnum() and ch not in [' ', '.', '-', '_']:
                host_name = host_name.replace(ch, '-')

        # Storwize doesn't like hostname that doesn't starts with letter or _.
        if not re.match('^[A-Za-z]', host_name):
            host_name = '_' + host_name

        # Add a random 8-character suffix to avoid collisions
        rand_id = str(random.randint(0, 99999999)).zfill(8)
        host_name = '%s-%s' % (host_name[:55], rand_id)

        # Create a host with one port
        port = ports.pop(0)
        self.ssh.mkhost(host_name, port[0], port[1])

        # Add any additional ports to the host
        for port in ports:
            self.ssh.addhostport(host_name, port[0], port[1])

        LOG.debug('Leave: create_host: host %(host)s - %(host_name)s.',
                  {'host': connector['host'], 'host_name': host_name})
        return host_name

    def delete_host(self, host_name):
        self.ssh.rmhost(host_name)

    def map_vol_to_host(self, volume_name, host_name, multihostmap):
        """Create a mapping between a volume to a host."""

        LOG.debug('Enter: map_vol_to_host: volume %(volume_name)s to '
                  'host %(host_name)s.',
                  {'volume_name': volume_name, 'host_name': host_name})

        # Check if this volume is already mapped to this host
        result_lun = self.ssh.get_vdiskhostmapid(volume_name, host_name)
        if result_lun is None:
            result_lun = self.ssh.mkvdiskhostmap(host_name, volume_name, None,
                                                 multihostmap)

        LOG.debug('Leave: map_vol_to_host: LUN %(result_lun)s, volume '
                  '%(volume_name)s, host %(host_name)s.',
                  {'result_lun': result_lun,
                   'volume_name': volume_name,
                   'host_name': host_name})
        return int(result_lun)

    def unmap_vol_from_host(self, volume_name, host_name):
        """Unmap the volume and delete the host if it has no more mappings."""

        LOG.debug('Enter: unmap_vol_from_host: volume %(volume_name)s from '
                  'host %(host_name)s.',
                  {'volume_name': volume_name, 'host_name': host_name})

        # Check if the mapping exists
        resp = self.ssh.lsvdiskhostmap(volume_name)
        if not len(resp):
            LOG.warning('unmap_vol_from_host: No mapping of volume '
                        '%(vol_name)s to any host found.',
                        {'vol_name': volume_name})
            return host_name
        if host_name is None:
            if len(resp) > 1:
                LOG.warning('unmap_vol_from_host: Multiple mappings of '
                            'volume %(vol_name)s found, no host '
                            'specified.', {'vol_name': volume_name})
                return
            else:
                host_name = resp[0]['host_name']
        else:
            found = False
            for h in resp.select('host_name'):
                if h == host_name:
                    found = True
            if not found:
                LOG.warning('unmap_vol_from_host: No mapping of volume '
                            '%(vol_name)s to host %(host)s found.',
                            {'vol_name': volume_name, 'host': host_name})
                return host_name
        # We now know that the mapping exists
        self.ssh.rmvdiskhostmap(host_name, volume_name)

        LOG.debug('Leave: unmap_vol_from_host: volume %(volume_name)s from '
                  'host %(host_name)s.',
                  {'volume_name': volume_name, 'host_name': host_name})
        return host_name

    def check_host_mapped_vols(self, host_name):
        return self.ssh.lshostvdiskmap(host_name)

    @staticmethod
    def build_default_opts(config):
        # Ignore capitalization

        cluster_partner = config.storwize_svc_stretched_cluster_partner
        opt = {'rsize': config.storwize_svc_vol_rsize,
               'warning': config.storwize_svc_vol_warning,
               'autoexpand': config.storwize_svc_vol_autoexpand,
               'grainsize': config.storwize_svc_vol_grainsize,
               'compression': config.storwize_svc_vol_compression,
               'easytier': config.storwize_svc_vol_easytier,
               'iogrp': config.storwize_svc_vol_iogrp,
               'qos': None,
               'stretched_cluster': cluster_partner,
               'replication': False,
               'nofmtdisk': config.storwize_svc_vol_nofmtdisk,
               'mirror_pool': config.storwize_svc_mirror_pool,
               'cycle_period_seconds': config.cycle_period_seconds}
        return opt

    @staticmethod
    def check_vdisk_opts(state, opts):
        # Check that grainsize is 32/64/128/256
        if opts['grainsize'] not in [32, 64, 128, 256]:
            raise exception.InvalidInput(
                reason=_('Illegal value specified for '
                         'storwize_svc_vol_grainsize: set to either '
                         '32, 64, 128, or 256.'))

        # Check that compression is supported
        if opts['compression'] and not state['compression_enabled']:
            raise exception.InvalidInput(
                reason=_('System does not support compression.'))

        # Check that rsize is set if compression is set
        if opts['compression'] and opts['rsize'] == -1:
            raise exception.InvalidInput(
                reason=_('If compression is set to True, rsize must '
                         'also be set (not equal to -1).'))

        # Check cycle_period_seconds are in 60-86400
        if opts['cycle_period_seconds'] not in range(60, 86401):
            raise exception.InvalidInput(
                reason=_('cycle_period_seconds should be integer '
                         'between 60 and 86400.'))

        iogs = StorwizeHelpers._get_valid_requested_io_groups(state, opts)

        if len(iogs) == 0:
            raise exception.InvalidInput(
                reason=_('Given I/O group(s) %(iogrp)s not valid; available '
                         'I/O groups are %(avail)s.')
                % {'iogrp': opts['iogrp'],
                   'avail': state['available_iogrps']})

        if opts['nofmtdisk'] and opts['rsize'] != -1:
            raise exception.InvalidInput(
                reason=_('If nofmtdisk is set to True, rsize must '
                         'also be set to -1.'))

    @staticmethod
    def _get_valid_requested_io_groups(state, opts):
        given_iogs = str(opts['iogrp'])
        iog_list = given_iogs.split(',')
        # convert to int
        iog_list = list(map(int, iog_list))
        LOG.debug("Requested iogroups %s", iog_list)
        LOG.debug("Available iogroups %s", state['available_iogrps'])
        filtiog = set(iog_list).intersection(state['available_iogrps'])
        iog_list = list(filtiog)
        LOG.debug("Filtered (valid) requested iogroups %s", iog_list)
        return iog_list

    def _get_opts_from_specs(self, opts, specs):
        qos = {}
        for k, value in specs.items():
            # Get the scope, if using scope format
            key_split = k.split(':')
            if len(key_split) == 1:
                scope = None
                key = key_split[0]
            else:
                scope = key_split[0]
                key = key_split[1]

            # We generally do not look at capabilities in the driver, but
            # replication is a special case where the user asks for
            # a volume to be replicated, and we want both the scheduler and
            # the driver to act on the value.
            if ((not scope or scope == 'capabilities') and
               key == 'replication'):
                scope = None
                key = 'replication'
                words = value.split()
                if not (words and len(words) == 2 and words[0] == '<is>'):
                    LOG.error('Replication must be specified as '
                              '\'<is> True\' or \'<is> False\'.')
                del words[0]
                value = words[0]

            # Add the QoS.
            if scope and scope == 'qos':
                if key in self.svc_qos_keys.keys():
                    try:
                        type_fn = self.svc_qos_keys[key]['type']
                        value = type_fn(value)
                        qos[key] = value
                    except ValueError:
                        continue

            # Any keys that the driver should look at should have the
            # 'drivers' scope.
            if scope and scope != 'drivers':
                continue

            if key in opts:
                this_type = type(opts[key]).__name__
                if this_type == 'int':
                    value = int(value)
                elif this_type == 'bool':
                    value = strutils.bool_from_string(value)
                opts[key] = value
        if len(qos) != 0:
            opts['qos'] = qos
        return opts

    def _get_qos_from_volume_metadata(self, volume_metadata):
        """Return the QoS information from the volume metadata."""
        qos = {}
        for i in volume_metadata:
            k = i.get('key', None)
            value = i.get('value', None)
            key_split = k.split(':')
            if len(key_split) == 1:
                scope = None
                key = key_split[0]
            else:
                scope = key_split[0]
                key = key_split[1]
            # Add the QoS.
            if scope and scope == 'qos':
                if key in self.svc_qos_keys.keys():
                    try:
                        type_fn = self.svc_qos_keys[key]['type']
                        value = type_fn(value)
                        qos[key] = value
                    except ValueError:
                        continue
        return qos

    def _wait_for_a_condition(self, testmethod, timeout=None,
                              interval=INTERVAL_1_SEC,
                              raise_exception=False):
        start_time = time.time()
        if timeout is None:
            timeout = DEFAULT_TIMEOUT

        def _inner():
            try:
                testValue = testmethod()
            except Exception as ex:
                if raise_exception:
                    LOG.exception("_wait_for_a_condition: %s"
                                  " execution failed.",
                                  testmethod.__name__)
                    raise exception.VolumeBackendAPIException(data=ex)
                else:
                    testValue = False
                    LOG.debug('Helper.'
                              '_wait_for_condition: %(method_name)s '
                              'execution failed for %(exception)s.',
                              {'method_name': testmethod.__name__,
                               'exception': ex.message})
            if testValue:
                raise loopingcall.LoopingCallDone()

            if int(time.time()) - start_time > timeout:
                msg = (_('CommandLineHelper._wait_for_condition: %s timeout.')
                       % testmethod.__name__)
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        timer = loopingcall.FixedIntervalLoopingCall(_inner)
        timer.start(interval=interval).wait()

    def get_vdisk_params(self, config, state, type_id,
                         volume_type=None, volume_metadata=None):
        """Return the parameters for creating the vdisk.

        Takes volume type and defaults from config options into account.
        """
        opts = self.build_default_opts(config)
        ctxt = context.get_admin_context()
        if volume_type is None and type_id is not None:
            volume_type = volume_types.get_volume_type(ctxt, type_id)
        if volume_type:
            qos_specs_id = volume_type.get('qos_specs_id')
            specs = dict(volume_type).get('extra_specs')

            # NOTE(vhou): We prefer the qos_specs association
            # and over-ride any existing
            # extra-specs settings if present
            if qos_specs_id is not None:
                kvs = qos_specs.get_qos_specs(ctxt, qos_specs_id)['specs']
                # Merge the qos_specs into extra_specs and qos_specs has higher
                # priority than extra_specs if they have different values for
                # the same key.
                specs.update(kvs)
            opts = self._get_opts_from_specs(opts, specs)
        if (opts['qos'] is None and config.storwize_svc_allow_tenant_qos
                and volume_metadata):
            qos = self._get_qos_from_volume_metadata(volume_metadata)
            if len(qos) != 0:
                opts['qos'] = qos

        self.check_vdisk_opts(state, opts)
        return opts

    @staticmethod
    def _get_vdisk_create_params(opts, add_copies=False):
        easytier = 'on' if opts['easytier'] else 'off'
        if opts['rsize'] == -1:
            params = []
            if opts['nofmtdisk']:
                params.append('-nofmtdisk')
        else:
            params = ['-rsize', '%s%%' % str(opts['rsize']),
                      '-autoexpand', '-warning',
                      '%s%%' % str(opts['warning'])]
            if not opts['autoexpand']:
                params.remove('-autoexpand')

            if opts['compression']:
                params.append('-compressed')
            else:
                params.extend(['-grainsize', str(opts['grainsize'])])

        if add_copies and opts['mirror_pool']:
            params.extend(['-copies', '2'])

        params.extend(['-easytier', easytier])
        return params

    def create_vdisk(self, name, size, units, pool, opts):
        LOG.debug('Enter: create_vdisk: vdisk %s.', name)
        mdiskgrp = pool
        if opts['mirror_pool']:
            if not self.is_pool_defined(opts['mirror_pool']):
                raise exception.InvalidInput(
                    reason=_('The pool %s in which mirrored copy is stored '
                             'is invalid') % opts['mirror_pool'])
            # The syntax of pool SVC expects is pool:mirror_pool in
            # mdiskgrp for mirror volume
            mdiskgrp = '%s:%s' % (pool, opts['mirror_pool'])
        params = self._get_vdisk_create_params(
            opts, add_copies=True if opts['mirror_pool'] else False)
        self.ssh.mkvdisk(name, size, units, mdiskgrp, opts, params)
        LOG.debug('Leave: _create_vdisk: volume %s.', name)

    def get_vdisk_attributes(self, vdisk):
        attrs = self.ssh.lsvdisk(vdisk)
        return attrs

    def is_vdisk_defined(self, vdisk_name):
        """Check if vdisk is defined."""
        attrs = self.get_vdisk_attributes(vdisk_name)
        return attrs is not None

    def find_vdisk_copy_id(self, vdisk, pool):
        resp = self.ssh.lsvdiskcopy(vdisk)
        for copy_id, mdisk_grp in resp.select('copy_id', 'mdisk_grp_name'):
            if mdisk_grp == pool:
                return copy_id
        msg = _('Failed to find a vdisk copy in the expected pool.')
        LOG.error(msg)
        raise exception.VolumeDriverException(message=msg)

    def get_vdisk_copy_attrs(self, vdisk, copy_id):
        return self.ssh.lsvdiskcopy(vdisk, copy_id=copy_id)[0]

    def get_vdisk_copies(self, vdisk):
        copies = {'primary': None,
                  'secondary': None}

        resp = self.ssh.lsvdiskcopy(vdisk)
        for copy_id, status, sync, primary, mdisk_grp in (
            resp.select('copy_id', 'status', 'sync',
                        'primary', 'mdisk_grp_name')):
            copy = {'copy_id': copy_id,
                    'status': status,
                    'sync': sync,
                    'primary': primary,
                    'mdisk_grp_name': mdisk_grp,
                    'sync_progress': None}
            if copy['sync'] != 'yes':
                progress_info = self.ssh.lsvdisksyncprogress(vdisk, copy_id)
                copy['sync_progress'] = progress_info['progress']
            if copy['primary'] == 'yes':
                copies['primary'] = copy
            else:
                copies['secondary'] = copy
        return copies

    def _prepare_fc_map(self, fc_map_id, timeout):
        self.ssh.prestartfcmap(fc_map_id)
        mapping_ready = False
        max_retries = (timeout // self.WAIT_TIME) + 1
        for try_number in range(1, max_retries):
            mapping_attrs = self._get_flashcopy_mapping_attributes(fc_map_id)
            if (mapping_attrs is None or
                    'status' not in mapping_attrs):
                break
            if mapping_attrs['status'] == 'prepared':
                mapping_ready = True
                break
            elif mapping_attrs['status'] == 'stopped':
                self.ssh.prestartfcmap(fc_map_id)
            elif mapping_attrs['status'] != 'preparing':
                msg = (_('Unexecpted mapping status %(status)s for mapping '
                         '%(id)s. Attributes: %(attr)s.')
                       % {'status': mapping_attrs['status'],
                          'id': fc_map_id,
                          'attr': mapping_attrs})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            greenthread.sleep(self.WAIT_TIME)

        if not mapping_ready:
            msg = (_('Mapping %(id)s prepare failed to complete within the'
                     'allotted %(to)d seconds timeout. Terminating.')
                   % {'id': fc_map_id,
                      'to': timeout})
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

    def start_fc_consistgrp(self, fc_consistgrp):
        self.ssh.startfcconsistgrp(fc_consistgrp)

    def create_fc_consistgrp(self, fc_consistgrp):
        self.ssh.mkfcconsistgrp(fc_consistgrp)

    def delete_fc_consistgrp(self, fc_consistgrp):
        self.ssh.rmfcconsistgrp(fc_consistgrp)

    def stop_fc_consistgrp(self, fc_consistgrp):
        self.ssh.stopfcconsistgrp(fc_consistgrp)

    def run_consistgrp_snapshots(self, fc_consistgrp, snapshots, state,
                                 config, timeout):
        model_update = {'status': fields.GroupSnapshotStatus.AVAILABLE}
        snapshots_model_update = []
        try:
            for snapshot in snapshots:
                opts = self.get_vdisk_params(config, state,
                                             snapshot['volume_type_id'])
                volume = snapshot.volume
                if not volume:
                    msg = (_("Can't get volume from snapshot: %(id)s")
                           % {"id": snapshot.id})
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)
                pool = utils.extract_host(volume.host, 'pool')
                self.create_flashcopy_to_consistgrp(snapshot['volume_name'],
                                                    snapshot['name'],
                                                    fc_consistgrp,
                                                    config, opts, False,
                                                    pool=pool)

            self.prepare_fc_consistgrp(fc_consistgrp, timeout)
            self.start_fc_consistgrp(fc_consistgrp)
            # There is CG limitation that could not create more than 128 CGs.
            # After start CG, we delete CG to avoid CG limitation.
            # Cinder general will maintain the CG and snapshots relationship.
            self.delete_fc_consistgrp(fc_consistgrp)
        except exception.VolumeBackendAPIException as err:
            model_update['status'] = fields.GroupSnapshotStatus.ERROR
            # Release cg
            self.delete_fc_consistgrp(fc_consistgrp)
            LOG.error("Failed to create CGSnapshot. "
                      "Exception: %s.", err)

        for snapshot in snapshots:
            snapshots_model_update.append(
                {'id': snapshot['id'],
                 'status': model_update['status']})

        return model_update, snapshots_model_update

    def delete_consistgrp_snapshots(self, fc_consistgrp, snapshots):
        """Delete flashcopy maps and consistent group."""
        model_update = {'status': fields.GroupSnapshotStatus.DELETED}
        snapshots_model_update = []

        try:
            for snapshot in snapshots:
                self.delete_vdisk(snapshot['name'], True)
        except exception.VolumeBackendAPIException as err:
            model_update['status'] = (
                fields.GroupSnapshotStatus.ERROR_DELETING)
            LOG.error("Failed to delete the snapshot %(snap)s of "
                      "CGSnapshot. Exception: %(exception)s.",
                      {'snap': snapshot['name'], 'exception': err})

        for snapshot in snapshots:
            snapshots_model_update.append(
                {'id': snapshot['id'],
                 'status': model_update['status']})

        return model_update, snapshots_model_update

    def prepare_fc_consistgrp(self, fc_consistgrp, timeout):
        """Prepare FC Consistency Group."""
        self.ssh.prestartfcconsistgrp(fc_consistgrp)

        def prepare_fc_consistgrp_success():
            mapping_ready = False
            mapping_attrs = self._get_flashcopy_consistgrp_attr(fc_consistgrp)
            if (mapping_attrs is None or
                    'status' not in mapping_attrs):
                pass
            if mapping_attrs['status'] == 'prepared':
                mapping_ready = True
            elif mapping_attrs['status'] == 'stopped':
                self.ssh.prestartfcconsistgrp(fc_consistgrp)
            elif mapping_attrs['status'] != 'preparing':
                msg = (_('Unexpected mapping status %(status)s for mapping'
                         '%(id)s. Attributes: %(attr)s.') %
                       {'status': mapping_attrs['status'],
                        'id': fc_consistgrp,
                        'attr': mapping_attrs})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            return mapping_ready
        self._wait_for_a_condition(prepare_fc_consistgrp_success, timeout)

    def create_cg_from_source(self, group, fc_consistgrp,
                              sources, targets, state,
                              config, timeout):
        """Create consistence group from source"""
        LOG.debug('Enter: create_cg_from_source: cg %(cg)s'
                  ' source %(source)s, target %(target)s',
                  {'cg': fc_consistgrp, 'source': sources, 'target': targets})
        model_update = {'status': fields.GroupStatus.AVAILABLE}
        ctxt = context.get_admin_context()
        try:
            for source, target in zip(sources, targets):
                opts = self.get_vdisk_params(config, state,
                                             source['volume_type_id'])
                pool = utils.extract_host(target['host'], 'pool')
                self.create_flashcopy_to_consistgrp(source['name'],
                                                    target['name'],
                                                    fc_consistgrp,
                                                    config, opts,
                                                    True, pool=pool)
            self.prepare_fc_consistgrp(fc_consistgrp, timeout)
            self.start_fc_consistgrp(fc_consistgrp)
            self.delete_fc_consistgrp(fc_consistgrp)
            volumes_model_update = self._get_volume_model_updates(
                ctxt, targets, group['id'], model_update['status'])
        except exception.VolumeBackendAPIException as err:
            model_update['status'] = fields.GroupStatus.ERROR
            volumes_model_update = self._get_volume_model_updates(
                ctxt, targets, group['id'], model_update['status'])
            with excutils.save_and_reraise_exception():
                # Release cg
                self.delete_fc_consistgrp(fc_consistgrp)
                LOG.error("Failed to create CG from CGsnapshot. "
                          "Exception: %s", err)
            return model_update, volumes_model_update

        LOG.debug('Leave: create_cg_from_source.')
        return model_update, volumes_model_update

    def _get_volume_model_updates(self, ctxt, volumes, cgId,
                                  status='available'):
        """Update the volume model's status and return it."""
        volume_model_updates = []
        LOG.info("Updating status for CG: %(id)s.",
                 {'id': cgId})
        if volumes:
            for volume in volumes:
                volume_model_updates.append({'id': volume['id'],
                                             'status': status})
        else:
            LOG.info("No volume found for CG: %(cg)s.",
                     {'cg': cgId})
        return volume_model_updates

    def run_flashcopy(self, source, target, timeout, copy_rate,
                      full_copy=True):
        """Create a FlashCopy mapping from the source to the target."""
        LOG.debug('Enter: run_flashcopy: execute FlashCopy from source '
                  '%(source)s to target %(target)s.',
                  {'source': source, 'target': target})

        fc_map_id = self.ssh.mkfcmap(source, target, full_copy, copy_rate)
        self._prepare_fc_map(fc_map_id, timeout)
        self.ssh.startfcmap(fc_map_id)

        LOG.debug('Leave: run_flashcopy: FlashCopy started from '
                  '%(source)s to %(target)s.',
                  {'source': source, 'target': target})

    def create_flashcopy_to_consistgrp(self, source, target, consistgrp,
                                       config, opts, full_copy=False,
                                       pool=None):
        """Create a FlashCopy mapping and add to consistent group."""
        LOG.debug('Enter: create_flashcopy_to_consistgrp: create FlashCopy'
                  ' from source %(source)s to target %(target)s'
                  'Then add the flashcopy to %(cg)s.',
                  {'source': source, 'target': target, 'cg': consistgrp})

        src_attrs = self.get_vdisk_attributes(source)
        if src_attrs is None:
            msg = (_('create_copy: Source vdisk %(src)s '
                     'does not exist.') % {'src': source})
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        src_size = src_attrs['capacity']
        # In case we need to use a specific pool
        if not pool:
            pool = src_attrs['mdisk_grp_name']
        opts['iogrp'] = src_attrs['IO_group_id']
        self.create_vdisk(target, src_size, 'b', pool, opts)

        self.ssh.mkfcmap(source, target, full_copy,
                         config.storwize_svc_flashcopy_rate,
                         consistgrp=consistgrp)

        LOG.debug('Leave: create_flashcopy_to_consistgrp: '
                  'FlashCopy started from  %(source)s to %(target)s.',
                  {'source': source, 'target': target})

    def _get_vdisk_fc_mappings(self, vdisk):
        """Return FlashCopy mappings that this vdisk is associated with."""
        mapping_ids = []
        resp = self.ssh.lsvdiskfcmappings(vdisk)
        for id in resp.select('id'):
            mapping_ids.append(id)
        return mapping_ids

    def _get_flashcopy_mapping_attributes(self, fc_map_id):
        resp = self.ssh.lsfcmap(fc_map_id)
        if not len(resp):
            return None
        return resp[0]

    def _get_flashcopy_consistgrp_attr(self, fc_map_id):
        resp = self.ssh.lsfcconsistgrp(fc_map_id)
        if not len(resp):
            return None
        return resp[0]

    def _check_vdisk_fc_mappings(self, name,
                                 allow_snaps=True, allow_fctgt=False):
        """FlashCopy mapping check helper."""
        LOG.debug('Loopcall: _check_vdisk_fc_mappings(), vdisk %s.', name)
        mapping_ids = self._get_vdisk_fc_mappings(name)
        wait_for_copy = False
        for map_id in mapping_ids:
            attrs = self._get_flashcopy_mapping_attributes(map_id)
            # We should ignore GMCV flash copies
            if not attrs or 'yes' == attrs['rc_controlled']:
                continue
            source = attrs['source_vdisk_name']
            target = attrs['target_vdisk_name']
            copy_rate = attrs['copy_rate']
            status = attrs['status']

            if allow_fctgt and target == name and status == 'copying':
                self.ssh.stopfcmap(map_id)
                attrs = self._get_flashcopy_mapping_attributes(map_id)
                if attrs:
                    status = attrs['status']

            if copy_rate == '0':
                if source == name:
                    # Vdisk with snapshots. Return False if snapshot
                    # not allowed.
                    if not allow_snaps:
                        raise loopingcall.LoopingCallDone(retvalue=False)
                    self.ssh.chfcmap(map_id, copyrate='50', autodel='on')
                    wait_for_copy = True
                else:
                    # A snapshot
                    if target != name:
                        msg = (_('Vdisk %(name)s not involved in '
                                 'mapping %(src)s -> %(tgt)s.') %
                               {'name': name, 'src': source, 'tgt': target})
                        LOG.error(msg)
                        raise exception.VolumeDriverException(message=msg)
                    if status in ['copying', 'prepared']:
                        self.ssh.stopfcmap(map_id)
                        # Need to wait for the fcmap to change to
                        # stopped state before remove fcmap
                        wait_for_copy = True
                    elif status in ['stopping', 'preparing']:
                        wait_for_copy = True
                    else:
                        self.ssh.rmfcmap(map_id)
            # Case 4: Copy in progress - wait and will autodelete
            else:
                if status == 'prepared':
                    self.ssh.stopfcmap(map_id)
                    self.ssh.rmfcmap(map_id)
                elif status in ['idle_or_copied', 'stopped']:
                    # Prepare failed or stopped
                    self.ssh.rmfcmap(map_id)
                else:
                    wait_for_copy = True
        if not wait_for_copy or not len(mapping_ids):
            raise loopingcall.LoopingCallDone(retvalue=True)

    def ensure_vdisk_no_fc_mappings(self, name, allow_snaps=True,
                                    allow_fctgt=False):
        """Ensure vdisk has no flashcopy mappings."""
        timer = loopingcall.FixedIntervalLoopingCall(
            self._check_vdisk_fc_mappings, name,
            allow_snaps, allow_fctgt)
        # Create a timer greenthread. The default volume service heart
        # beat is every 10 seconds. The flashcopy usually takes hours
        # before it finishes. Don't set the sleep interval shorter
        # than the heartbeat. Otherwise volume service heartbeat
        # will not be serviced.
        LOG.debug('Calling _ensure_vdisk_no_fc_mappings: vdisk %s.',
                  name)
        ret = timer.start(interval=self.check_fcmapping_interval).wait()
        timer.stop()
        return ret

    def start_relationship(self, volume_name, primary=None):
        vol_attrs = self.get_vdisk_attributes(volume_name)
        if vol_attrs['RC_name']:
            self.ssh.startrcrelationship(vol_attrs['RC_name'], primary)

    def stop_relationship(self, volume_name, access=False):
        vol_attrs = self.get_vdisk_attributes(volume_name)
        if vol_attrs['RC_name']:
            self.ssh.stoprcrelationship(vol_attrs['RC_name'], access=access)

    def create_relationship(self, master, aux, system, asyncmirror,
                            cyclingmode=False, masterchange=None,
                            cycle_period_seconds=None):
        try:
            rc_id = self.ssh.mkrcrelationship(master, aux, system,
                                              asyncmirror, cyclingmode)
        except exception.VolumeBackendAPIException as e:
            # CMMVC5959E is the code in Stowize storage, meaning that
            # there is a relationship that already has this name on the
            # master cluster.
            if 'CMMVC5959E' not in e:
                # If there is no relation between the primary and the
                # secondary back-end storage, the exception is raised.
                raise
        if rc_id:
            # We need setup master and aux change volumes for gmcv
            # before we can start remote relationship
            # aux change volume must be set on target site
            if cycle_period_seconds:
                self.change_relationship_cycleperiod(master,
                                                     cycle_period_seconds)
            if masterchange:
                self.change_relationship_changevolume(master,
                                                      masterchange, True)
            else:
                self.start_relationship(master)

    def change_relationship_changevolume(self, volume_name,
                                         change_volume, master):
        vol_attrs = self.get_vdisk_attributes(volume_name)
        if vol_attrs['RC_name'] and change_volume:
            self.ssh.ch_rcrelationship_changevolume(vol_attrs['RC_name'],
                                                    change_volume, master)

    def change_relationship_cycleperiod(self, volume_name,
                                        cycle_period_seconds):
        vol_attrs = self.get_vdisk_attributes(volume_name)
        if vol_attrs['RC_name'] and cycle_period_seconds:
            self.ssh.ch_rcrelationship_cycleperiod(vol_attrs['RC_name'],
                                                   cycle_period_seconds)

    def delete_relationship(self, volume_name):
        vol_attrs = self.get_vdisk_attributes(volume_name)
        if vol_attrs['RC_name']:
            self.ssh.rmrcrelationship(vol_attrs['RC_name'], True)

    def get_relationship_info(self, volume_name):
        vol_attrs = self.get_vdisk_attributes(volume_name)
        if not vol_attrs or not vol_attrs['RC_name']:
            LOG.info("Unable to get remote copy information for "
                     "volume %s", volume_name)
            return

        relationship = self.ssh.lsrcrelationship(vol_attrs['RC_name'])
        return relationship[0] if len(relationship) > 0 else None

    def delete_rc_volume(self, volume_name, target_vol=False):
        vol_name = volume_name
        if target_vol:
            vol_name = storwize_const.REPLICA_AUX_VOL_PREFIX + volume_name

        try:
            rel_info = self.get_relationship_info(vol_name)
            if rel_info:
                self.delete_relationship(vol_name)
            # Delete change volume
            self.delete_vdisk(
                storwize_const.REPLICA_CHG_VOL_PREFIX + vol_name, False)
            self.delete_vdisk(vol_name, False)
        except Exception as e:
            msg = (_('Unable to delete the volume for '
                     'volume %(vol)s. Exception: %(err)s.'),
                   {'vol': vol_name, 'err': e})
            LOG.exception(msg)
            raise exception.VolumeDriverException(message=msg)

    def switch_relationship(self, relationship, aux=True):
        self.ssh.switchrelationship(relationship, aux)

    def get_partnership_info(self, system_name):
        partnership = self.ssh.lspartnership(system_name)
        return partnership[0] if len(partnership) > 0 else None

    def get_partnershipcandidate_info(self, system_name):
        candidates = self.ssh.lspartnershipcandidate()
        for candidate in candidates:
            if system_name == candidate['name']:
                return candidate
        return None

    def mkippartnership(self, ip_v4, bandwith=1000, copyrate=50):
        self.ssh.mkippartnership(ip_v4, bandwith, copyrate)

    def mkfcpartnership(self, system_name, bandwith=1000, copyrate=50):
        self.ssh.mkfcpartnership(system_name, bandwith, copyrate)

    def chpartnership(self, partnership_id):
        self.ssh.chpartnership(partnership_id)

    def delete_vdisk(self, vdisk, force):
        """Ensures that vdisk is not part of FC mapping and deletes it."""
        LOG.debug('Enter: delete_vdisk: vdisk %s.', vdisk)
        if not self.is_vdisk_defined(vdisk):
            LOG.info('Tried to delete non-existent vdisk %s.', vdisk)
            return
        self.ensure_vdisk_no_fc_mappings(vdisk, allow_snaps=True,
                                         allow_fctgt=True)
        self.ssh.rmvdisk(vdisk, force=force)
        LOG.debug('Leave: delete_vdisk: vdisk %s.', vdisk)

    def create_copy(self, src, tgt, src_id, config, opts,
                    full_copy, pool=None):
        """Create a new snapshot using FlashCopy."""
        LOG.debug('Enter: create_copy: snapshot %(src)s to %(tgt)s.',
                  {'tgt': tgt, 'src': src})

        src_attrs = self.get_vdisk_attributes(src)
        if src_attrs is None:
            msg = (_('create_copy: Source vdisk %(src)s (%(src_id)s) '
                     'does not exist.') % {'src': src, 'src_id': src_id})
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        src_size = src_attrs['capacity']
        # In case we need to use a specific pool
        if not pool:
            pool = src_attrs['mdisk_grp_name']

        opts['iogrp'] = src_attrs['IO_group_id']
        self.create_vdisk(tgt, src_size, 'b', pool, opts)
        timeout = config.storwize_svc_flashcopy_timeout
        try:
            self.run_flashcopy(src, tgt, timeout,
                               config.storwize_svc_flashcopy_rate,
                               full_copy=full_copy)
        except Exception:
            with excutils.save_and_reraise_exception():
                self.delete_vdisk(tgt, True)

        LOG.debug('Leave: _create_copy: snapshot %(tgt)s from '
                  'vdisk %(src)s.',
                  {'tgt': tgt, 'src': src})

    def extend_vdisk(self, vdisk, amount):
        self.ssh.expandvdisksize(vdisk, amount)

    def add_vdisk_copy(self, vdisk, dest_pool, volume_type, state, config,
                       auto_delete=False):
        """Add a vdisk copy in the given pool."""
        resp = self.ssh.lsvdiskcopy(vdisk)
        if len(resp) > 1:
            msg = (_('add_vdisk_copy failed: A copy of volume %s exists. '
                     'Adding another copy would exceed the limit of '
                     '2 copies.') % vdisk)
            raise exception.VolumeDriverException(message=msg)
        orig_copy_id = resp[0].get("copy_id", None)

        if orig_copy_id is None:
            msg = (_('add_vdisk_copy started without a vdisk copy in the '
                     'expected pool.'))
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        if volume_type is None:
            opts = self.get_vdisk_params(config, state, None)
        else:
            opts = self.get_vdisk_params(config, state, volume_type['id'],
                                         volume_type=volume_type)
        params = self._get_vdisk_create_params(opts)
        try:
            new_copy_id = self.ssh.addvdiskcopy(vdisk, dest_pool, params,
                                                auto_delete)
        except exception.VolumeBackendAPIException as e:
            msg = (_('Unable to add vdiskcopy for volume %(vol)s. '
                     'Exception: %(err)s.'),
                   {'vol': vdisk, 'err': e})
            LOG.exception(msg)
            raise exception.VolumeDriverException(message=msg)
        return (orig_copy_id, new_copy_id)

    def is_vdisk_copy_synced(self, vdisk, copy_id):
        sync = self.ssh.lsvdiskcopy(vdisk, copy_id=copy_id)[0]['sync']
        if sync == 'yes':
            return True
        return False

    def rm_vdisk_copy(self, vdisk, copy_id):
        self.ssh.rmvdiskcopy(vdisk, copy_id)

    def lsvdiskcopy(self, vdisk, copy_id=None):
        return self.ssh.lsvdiskcopy(vdisk, copy_id)

    @staticmethod
    def can_migrate_to_host(host, state):
        if 'location_info' not in host['capabilities']:
            return None
        info = host['capabilities']['location_info']
        try:
            (dest_type, dest_id, dest_pool) = info.split(':')
        except ValueError:
            return None
        if (dest_type != 'StorwizeSVCDriver' or dest_id != state['system_id']):
            return None
        return dest_pool

    def add_vdisk_qos(self, vdisk, qos):
        """Add the QoS configuration to the volume."""
        for key, value in qos.items():
            if key in self.svc_qos_keys.keys():
                param = self.svc_qos_keys[key]['param']
                self.ssh.chvdisk(vdisk, ['-' + param, str(value)])

    def update_vdisk_qos(self, vdisk, qos):
        """Update all the QoS in terms of a key and value.

        svc_qos_keys saves all the supported QoS parameters. Going through
        this dict, we set the new values to all the parameters. If QoS is
        available in the QoS configuration, the value is taken from it;
        if not, the value will be set to default.
        """
        for key, value in self.svc_qos_keys.items():
            param = value['param']
            if key in qos.keys():
                # If the value is set in QoS, take the value from
                # the QoS configuration.
                v = qos[key]
            else:
                # If not, set the value to default.
                v = value['default']
            self.ssh.chvdisk(vdisk, ['-' + param, str(v)])

    def disable_vdisk_qos(self, vdisk, qos):
        """Disable the QoS."""
        for key, value in qos.items():
            if key in self.svc_qos_keys.keys():
                param = self.svc_qos_keys[key]['param']
                # Take the default value.
                value = self.svc_qos_keys[key]['default']
                self.ssh.chvdisk(vdisk, ['-' + param, value])

    def change_vdisk_options(self, vdisk, changes, opts, state):
        if 'warning' in opts:
            opts['warning'] = '%s%%' % str(opts['warning'])
        if 'easytier' in opts:
            opts['easytier'] = 'on' if opts['easytier'] else 'off'
        if 'autoexpand' in opts:
            opts['autoexpand'] = 'on' if opts['autoexpand'] else 'off'

        for key in changes:
            self.ssh.chvdisk(vdisk, ['-' + key, opts[key]])

    def change_vdisk_iogrp(self, vdisk, state, iogrp):
        if state['code_level'] < (6, 4, 0, 0):
            LOG.debug('Ignore change IO group as storage code level is '
                      '%(code_level)s, below the required 6.4.0.0.',
                      {'code_level': state['code_level']})
        else:
            self.ssh.movevdisk(vdisk, str(iogrp[0]))
            self.ssh.addvdiskaccess(vdisk, str(iogrp[0]))
            self.ssh.rmvdiskaccess(vdisk, str(iogrp[1]))

    def vdisk_by_uid(self, vdisk_uid):
        """Returns the properties of the vdisk with the specified UID.

        Returns None if no such disk exists.
        """

        vdisks = self.ssh.lsvdisks_from_filter('vdisk_UID', vdisk_uid)

        if len(vdisks) == 0:
            return None

        if len(vdisks) != 1:
            msg = (_('Expected single vdisk returned from lsvdisk when '
                     'filtering on vdisk_UID.  %(count)s were returned.') %
                   {'count': len(vdisks)})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        vdisk = vdisks.result[0]

        return self.ssh.lsvdisk(vdisk['name'])

    def is_vdisk_in_use(self, vdisk):
        """Returns True if the specified vdisk is mapped to at least 1 host."""
        resp = self.ssh.lsvdiskhostmap(vdisk)
        return len(resp) != 0

    def rename_vdisk(self, vdisk, new_name):
        self.ssh.chvdisk(vdisk, ['-name', new_name])

    def change_vdisk_primary_copy(self, vdisk, copy_id):
        self.ssh.chvdisk(vdisk, ['-primary', copy_id])

    def migratevdisk(self, vdisk, dest_pool, copy_id='0'):
        self.ssh.migratevdisk(vdisk, dest_pool, copy_id)


class CLIResponse(object):
    """Parse SVC CLI output and generate iterable."""

    def __init__(self, raw, ssh_cmd=None, delim='!', with_header=True):
        super(CLIResponse, self).__init__()
        if ssh_cmd:
            self.ssh_cmd = ' '.join(ssh_cmd)
        else:
            self.ssh_cmd = 'None'
        self.raw = raw
        self.delim = delim
        self.with_header = with_header
        self.result = self._parse()

    def select(self, *keys):
        for a in self.result:
            vs = []
            for k in keys:
                v = a.get(k, None)
                if isinstance(v, six.string_types) or v is None:
                    v = [v]
                if isinstance(v, list):
                    vs.append(v)
            for item in zip(*vs):
                if len(item) == 1:
                    yield item[0]
                else:
                    yield item

    def __getitem__(self, key):
        try:
            return self.result[key]
        except KeyError:
            msg = (_('Did not find the expected key %(key)s in %(fun)s: '
                     '%(raw)s.') % {'key': key, 'fun': self.ssh_cmd,
                                    'raw': self.raw})
            raise exception.VolumeBackendAPIException(data=msg)

    def __iter__(self):
        for a in self.result:
            yield a

    def __len__(self):
        return len(self.result)

    def _parse(self):
        def get_reader(content, delim):
            for line in content.lstrip().splitlines():
                line = line.strip()
                if line:
                    yield line.split(delim)
                else:
                    yield []

        if isinstance(self.raw, six.string_types):
            stdout, stderr = self.raw, ''
        else:
            stdout, stderr = self.raw
        reader = get_reader(stdout, self.delim)
        result = []

        if self.with_header:
            hds = tuple()
            for row in reader:
                hds = row
                break
            for row in reader:
                cur = dict()
                if len(hds) != len(row):
                    msg = (_('Unexpected CLI response: header/row mismatch. '
                             'header: %(header)s, row: %(row)s.')
                           % {'header': hds,
                              'row': row})
                    raise exception.VolumeBackendAPIException(data=msg)
                for k, v in zip(hds, row):
                    CLIResponse.append_dict(cur, k, v)
                result.append(cur)
        else:
            cur = dict()
            for row in reader:
                if row:
                    CLIResponse.append_dict(cur, row[0], ' '.join(row[1:]))
                elif cur:  # start new section
                    result.append(cur)
                    cur = dict()
            if cur:
                result.append(cur)
        return result

    @staticmethod
    def append_dict(dict_, key, value):
        key, value = key.strip(), value.strip()
        obj = dict_.get(key, None)
        if obj is None:
            dict_[key] = value
        elif isinstance(obj, list):
            obj.append(value)
            dict_[key] = obj
        else:
            dict_[key] = [obj, value]
        return dict_


class StorwizeSVCCommonDriver(san.SanDriver,
                              driver.ManageableVD,
                              driver.MigrateVD,
                              driver.CloneableImageVD):
    """IBM Storwize V7000 SVC abstract base class for iSCSI/FC volume drivers.

    Version history:

    .. code-block:: none

        1.0 - Initial driver
        1.1 - FC support, create_cloned_volume, volume type support,
              get_volume_stats, minor bug fixes
        1.2.0 - Added retype
        1.2.1 - Code refactor, improved exception handling
        1.2.2 - Fix bug #1274123 (races in host-related functions)
        1.2.3 - Fix Fibre Channel connectivity: bug #1279758 (add delim
                to lsfabric, clear unused data from connections, ensure
                matching WWPNs by comparing lower case
        1.2.4 - Fix bug #1278035 (async migration/retype)
        1.2.5 - Added support for manage_existing (unmanage is inherited)
        1.2.6 - Added QoS support in terms of I/O throttling rate
        1.3.1 - Added support for volume replication
        1.3.2 - Added support for consistency group
        1.3.3 - Update driver to use ABC metaclasses
        2.0 - Code refactor, split init file and placed shared methods
              for FC and iSCSI within the StorwizeSVCCommonDriver class
        2.1 - Added replication V2 support to the global/metro mirror
              mode
        2.1.1 - Update replication to version 2.1
    """

    VERSION = "2.1.1"
    VDISKCOPYOPS_INTERVAL = 600
    DEFAULT_GR_SLEEP = random.randint(20, 500) / 100.0

    def __init__(self, *args, **kwargs):
        super(StorwizeSVCCommonDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(storwize_svc_opts)
        self._backend_name = self.configuration.safe_get('volume_backend_name')
        self.active_ip = self.configuration.san_ip
        self.inactive_ip = self.configuration.storwize_san_secondary_ip
        self._master_backend_helpers = StorwizeHelpers(self._run_ssh)
        self._aux_backend_helpers = None
        self._helpers = self._master_backend_helpers
        self._vdiskcopyops = {}
        self._vdiskcopyops_loop = None
        self.protocol = None
        self._state = {'storage_nodes': {},
                       'enabled_protocols': set(),
                       'compression_enabled': False,
                       'available_iogrps': [],
                       'system_name': None,
                       'system_id': None,
                       'code_level': None,
                       }
        self._active_backend_id = kwargs.get('active_backend_id')

        # This dictionary is used to map each replication target to certain
        # replication manager object.
        self.replica_manager = {}

        # One driver can be configured with only one replication target
        # to failover.
        self._replica_target = {}

        # This boolean is used to indicate whether replication is supported
        # by this storage.
        self._replica_enabled = False

        # This list is used to save the supported replication modes.
        self._supported_replica_types = []

        # This is used to save the available pools in failed-over status
        self._secondary_pools = None

        # Storwize has the limitation that can not burst more than 3 new ssh
        # connections within 1 second. So slow down the initialization.
        time.sleep(1)

    def do_setup(self, ctxt):
        """Check that we have all configuration details from the storage."""
        LOG.debug('enter: do_setup')

        # v2.1 replication setup
        self._get_storwize_config()

        # Update the storwize state
        self._update_storwize_state()

        # Validate that the pool exists
        self._validate_pools_exist()

        # Build the list of in-progress vdisk copy operations
        if ctxt is None:
            admin_context = context.get_admin_context()
        else:
            admin_context = ctxt.elevated()
        volumes = objects.VolumeList.get_all_by_host(admin_context, self.host)

        for volume in volumes:
            metadata = volume.admin_metadata
            curr_ops = metadata.get('vdiskcopyops', None)
            if curr_ops:
                ops = [tuple(x.split(':')) for x in curr_ops.split(';')]
                self._vdiskcopyops[volume['id']] = ops

        # if vdiskcopy exists in database, start the looping call
        if len(self._vdiskcopyops) >= 1:
            self._vdiskcopyops_loop = loopingcall.FixedIntervalLoopingCall(
                self._check_volume_copy_ops)
            self._vdiskcopyops_loop.start(interval=self.VDISKCOPYOPS_INTERVAL)
        LOG.debug('leave: do_setup')

    def _update_storwize_state(self):
        # Get storage system name, id, and code level
        self._state.update(self._helpers.get_system_info())

        # Check if compression is supported
        self._state['compression_enabled'] = (self._helpers.
                                              compression_enabled())

        # Get the available I/O groups
        self._state['available_iogrps'] = (self._helpers.
                                           get_available_io_groups())

        # Get the iSCSI and FC names of the Storwize/SVC nodes
        self._state['storage_nodes'] = self._helpers.get_node_info()

        # Add the iSCSI IP addresses and WWPNs to the storage node info
        self._helpers.add_iscsi_ip_addrs(self._state['storage_nodes'])
        self._helpers.add_fc_wwpns(self._state['storage_nodes'],
                                   self._state['code_level'])

        # For each node, check what connection modes it supports.  Delete any
        # nodes that do not support any types (may be partially configured).
        to_delete = []
        for k, node in self._state['storage_nodes'].items():
            if ((len(node['ipv4']) or len(node['ipv6']))
                    and len(node['iscsi_name'])):
                node['enabled_protocols'].append('iSCSI')
                self._state['enabled_protocols'].add('iSCSI')
            if len(node['WWPN']):
                node['enabled_protocols'].append('FC')
                self._state['enabled_protocols'].add('FC')
            if not len(node['enabled_protocols']):
                to_delete.append(k)
        for delkey in to_delete:
            del self._state['storage_nodes'][delkey]

    def _get_backend_pools(self):
        if not self._active_backend_id:
            return self.configuration.storwize_svc_volpool_name
        elif not self._secondary_pools:
            self._secondary_pools = [self._replica_target.get('pool_name')]
        return self._secondary_pools

    def _validate_pools_exist(self):
        # Validate that the pool exists
        pools = self._get_backend_pools()
        for pool in pools:
            if not self._helpers.is_pool_defined(pool):
                reason = (_('Failed getting details for pool %s.') % pool)
                raise exception.InvalidInput(reason=reason)

    def check_for_setup_error(self):
        """Ensure that the flags are set properly."""
        LOG.debug('enter: check_for_setup_error')

        # Check that we have the system ID information
        if self._state['system_name'] is None:
            exception_msg = (_('Unable to determine system name.'))
            raise exception.VolumeBackendAPIException(data=exception_msg)
        if self._state['system_id'] is None:
            exception_msg = (_('Unable to determine system id.'))
            raise exception.VolumeBackendAPIException(data=exception_msg)

        # Make sure we have at least one node configured
        if not len(self._state['storage_nodes']):
            msg = _('do_setup: No configured nodes.')
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        if self.protocol not in self._state['enabled_protocols']:
            # TODO(mc_nair): improve this error message by looking at
            # self._state['enabled_protocols'] to tell user what driver to use
            raise exception.InvalidInput(
                reason=_('The storage device does not support %(prot)s. '
                         'Please configure the device to support %(prot)s or '
                         'switch to a driver using a different protocol.')
                % {'prot': self.protocol})

        required_flags = ['san_ip', 'san_ssh_port', 'san_login',
                          'storwize_svc_volpool_name']
        for flag in required_flags:
            if not self.configuration.safe_get(flag):
                raise exception.InvalidInput(reason=_('%s is not set.') % flag)

        # Ensure that either password or keyfile were set
        if not (self.configuration.san_password or
                self.configuration.san_private_key):
            raise exception.InvalidInput(
                reason=_('Password or SSH private key is required for '
                         'authentication: set either san_password or '
                         'san_private_key option.'))

        opts = self._helpers.build_default_opts(self.configuration)
        self._helpers.check_vdisk_opts(self._state, opts)

        LOG.debug('leave: check_for_setup_error')

    def _run_ssh(self, cmd_list, check_exit_code=True, attempts=1):
        cinder_utils.check_ssh_injection(cmd_list)
        command = ' '.join(cmd_list)
        if not self.sshpool:
            try:
                self.sshpool = self._set_up_sshpool(self.active_ip)
            except paramiko.SSHException:
                LOG.warning('Unable to use san_ip to create SSHPool. Now '
                            'attempting to use storwize_san_secondary_ip '
                            'to create SSHPool.')
                if self._toggle_ip():
                    self.sshpool = self._set_up_sshpool(self.active_ip)
                else:
                    LOG.warning('Unable to create SSHPool using san_ip '
                                'and not able to use '
                                'storwize_san_secondary_ip since it is '
                                'not configured.')
                    raise
        try:
            return self._ssh_execute(self.sshpool, command,
                                     check_exit_code, attempts)

        except Exception:
            # Need to check if creating an SSHPool storwize_san_secondary_ip
            # before raising an error.
            try:
                if self._toggle_ip():
                    LOG.warning("Unable to execute SSH command with "
                                "%(inactive)s. Attempting to execute SSH "
                                "command with %(active)s.",
                                {'inactive': self.inactive_ip,
                                 'active': self.active_ip})
                    self.sshpool = self._set_up_sshpool(self.active_ip)
                    return self._ssh_execute(self.sshpool, command,
                                             check_exit_code, attempts)
                else:
                    LOG.warning('Not able to use '
                                'storwize_san_secondary_ip since it is '
                                'not configured.')
                    raise
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error("Error running SSH command: %s",
                              command)

    def _set_up_sshpool(self, ip):
        password = self.configuration.san_password
        privatekey = self.configuration.san_private_key
        min_size = self.configuration.ssh_min_pool_conn
        max_size = self.configuration.ssh_max_pool_conn
        sshpool = ssh_utils.SSHPool(
            ip,
            self.configuration.san_ssh_port,
            self.configuration.ssh_conn_timeout,
            self.configuration.san_login,
            password=password,
            privatekey=privatekey,
            min_size=min_size,
            max_size=max_size)

        return sshpool

    def _ssh_execute(self, sshpool, command,
                     check_exit_code = True, attempts=1):
        try:
            with sshpool.item() as ssh:
                while attempts > 0:
                    attempts -= 1
                    try:
                        return processutils.ssh_execute(
                            ssh,
                            command,
                            check_exit_code=check_exit_code)
                    except Exception as e:
                        LOG.error('Error has occurred: %s', e)
                        last_exception = e
                        greenthread.sleep(self.DEFAULT_GR_SLEEP)
                    try:
                        raise processutils.ProcessExecutionError(
                            exit_code=last_exception.exit_code,
                            stdout=last_exception.stdout,
                            stderr=last_exception.stderr,
                            cmd=last_exception.cmd)
                    except AttributeError:
                        raise processutils.ProcessExecutionError(
                            exit_code=-1,
                            stdout="",
                            stderr="Error running SSH command",
                            cmd=command)

        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error("Error running SSH command: %s", command)

    def _toggle_ip(self):
        # Change active_ip if storwize_san_secondary_ip is set.
        if self.configuration.storwize_san_secondary_ip is None:
            return False

        self.inactive_ip, self.active_ip = self.active_ip, self.inactive_ip
        LOG.info('Toggle active_ip from %(old)s to %(new)s.',
                 {'old': self.inactive_ip,
                  'new': self.active_ip})
        return True

    def ensure_export(self, ctxt, volume):
        """Check that the volume exists on the storage.

        The system does not "export" volumes as a Linux iSCSI target does,
        and therefore we just check that the volume exists on the storage.
        """
        vol_name = self._get_target_vol(volume)
        volume_defined = self._helpers.is_vdisk_defined(vol_name)

        if not volume_defined:
            LOG.error('ensure_export: Volume %s not found on storage.',
                      volume['name'])

    def create_export(self, ctxt, volume, connector):
        model_update = None
        return model_update

    def remove_export(self, ctxt, volume):
        pass

    def _get_vdisk_params(self, type_id, volume_type=None,
                          volume_metadata=None):
        return self._helpers.get_vdisk_params(self.configuration,
                                              self._state, type_id,
                                              volume_type=volume_type,
                                              volume_metadata=volume_metadata)

    def create_volume(self, volume):
        LOG.debug('enter: create_volume: volume %s', volume['name'])
        opts = self._get_vdisk_params(volume['volume_type_id'],
                                      volume_metadata=
                                      volume.get('volume_metadata'))
        ctxt = context.get_admin_context()
        rep_type = self._get_volume_replicated_type(ctxt, volume)

        pool = utils.extract_host(volume['host'], 'pool')
        if opts['mirror_pool'] and rep_type:
            reason = _('Create mirror volume with replication enabled is '
                       'not supported.')
            raise exception.InvalidInput(reason=reason)
        opts['iogrp'] = self._helpers.select_io_group(self._state, opts)
        self._helpers.create_vdisk(volume['name'], str(volume['size']),
                                   'gb', pool, opts)
        if opts['qos']:
            self._helpers.add_vdisk_qos(volume['name'], opts['qos'])

        model_update = None

        if rep_type:
            replica_obj = self._get_replica_obj(rep_type)
            replica_obj.volume_replication_setup(ctxt, volume)
            model_update = {'replication_status':
                            fields.ReplicationStatus.ENABLED}

        LOG.debug('leave: create_volume:\n volume: %(vol)s\n '
                  'model_update %(model_update)s',
                  {'vol': volume['name'],
                   'model_update': model_update})
        return model_update

    def delete_volume(self, volume):
        LOG.debug('enter: delete_volume: volume %s', volume['name'])
        ctxt = context.get_admin_context()

        rep_type = self._get_volume_replicated_type(ctxt, volume)
        if rep_type:
            if self._aux_backend_helpers:
                self._aux_backend_helpers.delete_rc_volume(volume['name'],
                                                           target_vol=True)
            if not self._active_backend_id:
                self._master_backend_helpers.delete_rc_volume(volume['name'])
            else:
                # If it's in fail over state, also try to delete the volume
                # in master backend
                try:
                    self._master_backend_helpers.delete_rc_volume(
                        volume['name'])
                except Exception as ex:
                    LOG.error('Failed to get delete volume %(volume)s in '
                              'master backend. Exception: %(err)s.',
                              {'volume': volume['name'],
                               'err': ex})
        else:
            if self._active_backend_id:
                msg = (_('Error: delete non-replicate volume in failover mode'
                         ' is not allowed.'))
                LOG.error(msg)
                raise exception.VolumeDriverException(message=msg)
            else:
                self._helpers.delete_vdisk(volume['name'], False)

        if volume['id'] in self._vdiskcopyops:
            del self._vdiskcopyops[volume['id']]

            if not len(self._vdiskcopyops):
                self._vdiskcopyops_loop.stop()
                self._vdiskcopyops_loop = None
        LOG.debug('leave: delete_volume: volume %s', volume['name'])

    def create_snapshot(self, snapshot):
        ctxt = context.get_admin_context()
        try:
            # TODO(zhaochy): change to use snapshot.volume
            source_vol = self.db.volume_get(ctxt, snapshot['volume_id'])
        except Exception:
            msg = (_('create_snapshot: get source volume failed.'))
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        rep_type = self._get_volume_replicated_type(
            ctxt, None, source_vol['volume_type_id'])
        if rep_type == storwize_const.GMCV:
            # GMCV volume will have problem to failback
            # when it has flash copy relationship besides change volumes
            msg = _('create_snapshot: Create snapshot to '
                    'gmcv replication volume is not allowed.')
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        pool = utils.extract_host(source_vol['host'], 'pool')
        opts = self._get_vdisk_params(source_vol['volume_type_id'])
        self._helpers.create_copy(snapshot['volume_name'], snapshot['name'],
                                  snapshot['volume_id'], self.configuration,
                                  opts, False, pool=pool)

    def delete_snapshot(self, snapshot):
        self._helpers.delete_vdisk(snapshot['name'], False)

    def create_volume_from_snapshot(self, volume, snapshot):
        if snapshot['volume_size'] > volume['size']:
            msg = (_("create_volume_from_snapshot: snapshot %(snapshot_name)s "
                     "size is %(snapshot_size)dGB and doesn't fit in target "
                     "volume %(volume_name)s of size %(volume_size)dGB.") %
                   {'snapshot_name': snapshot['name'],
                    'snapshot_size': snapshot['volume_size'],
                    'volume_name': volume['name'],
                    'volume_size': volume['size']})
            LOG.error(msg)
            raise exception.InvalidInput(message=msg)

        opts = self._get_vdisk_params(volume['volume_type_id'],
                                      volume_metadata=
                                      volume.get('volume_metadata'))
        pool = utils.extract_host(volume['host'], 'pool')
        self._helpers.create_copy(snapshot['name'], volume['name'],
                                  snapshot['id'], self.configuration,
                                  opts, True, pool=pool)
        # The volume size is equal to the snapshot size in most
        # of the cases. But in some scenario, the volume size
        # may be bigger than the source volume size.
        # SVC does not support flashcopy between two volumes
        # with two different size. So use the snapshot size to
        # create volume first and then extend the volume to-
        # the target size.
        if volume['size'] > snapshot['volume_size']:
            # extend the new created target volume to expected size.
            self._extend_volume_op(volume, volume['size'],
                                   snapshot['volume_size'])
        if opts['qos']:
            self._helpers.add_vdisk_qos(volume['name'], opts['qos'])

        ctxt = context.get_admin_context()
        rep_type = self._get_volume_replicated_type(ctxt, volume)

        if rep_type:
            self._validate_replication_enabled()
            replica_obj = self._get_replica_obj(rep_type)
            replica_obj.volume_replication_setup(ctxt, volume)
            return {'replication_status': fields.ReplicationStatus.ENABLED}

    def create_cloned_volume(self, tgt_volume, src_volume):
        """Creates a clone of the specified volume."""

        if src_volume['size'] > tgt_volume['size']:
            msg = (_("create_cloned_volume: source volume %(src_vol)s "
                     "size is %(src_size)dGB and doesn't fit in target "
                     "volume %(tgt_vol)s of size %(tgt_size)dGB.") %
                   {'src_vol': src_volume['name'],
                    'src_size': src_volume['size'],
                    'tgt_vol': tgt_volume['name'],
                    'tgt_size': tgt_volume['size']})
            LOG.error(msg)
            raise exception.InvalidInput(message=msg)

        opts = self._get_vdisk_params(tgt_volume['volume_type_id'],
                                      volume_metadata=
                                      tgt_volume.get('volume_metadata'))
        pool = utils.extract_host(tgt_volume['host'], 'pool')
        self._helpers.create_copy(src_volume['name'], tgt_volume['name'],
                                  src_volume['id'], self.configuration,
                                  opts, True, pool=pool)

        # The source volume size is equal to target volume size
        # in most of the cases. But in some scenarios, the target
        # volume size may be bigger than the source volume size.
        # SVC does not support flashcopy between two volumes
        # with two different sizes. So use source volume size to
        # create target volume first and then extend target
        # volume to original size.
        if tgt_volume['size'] > src_volume['size']:
            # extend the new created target volume to expected size.
            self._extend_volume_op(tgt_volume, tgt_volume['size'],
                                   src_volume['size'])

        if opts['qos']:
            self._helpers.add_vdisk_qos(tgt_volume['name'], opts['qos'])

        ctxt = context.get_admin_context()
        rep_type = self._get_volume_replicated_type(ctxt, tgt_volume)

        if rep_type:
            self._validate_replication_enabled()
            replica_obj = self._get_replica_obj(rep_type)
            replica_obj.volume_replication_setup(ctxt, tgt_volume)
            return {'replication_status': fields.ReplicationStatus.ENABLED}

    def extend_volume(self, volume, new_size):
        self._extend_volume_op(volume, new_size)

    def _extend_volume_op(self, volume, new_size, old_size=None):
        LOG.debug('enter: _extend_volume_op: volume %s', volume['id'])
        volume_name = self._get_target_vol(volume)
        ret = self._helpers.ensure_vdisk_no_fc_mappings(volume_name,
                                                        allow_snaps=False)
        if not ret:
            msg = (_('_extend_volume_op: Extending a volume with snapshots is '
                     'not supported.'))
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        if old_size is None:
            old_size = volume.size
        extend_amt = int(new_size) - old_size

        rel_info = self._helpers.get_relationship_info(volume_name)
        if rel_info:
            LOG.warning('_extend_volume_op: Extending a volume with '
                        'remote copy is not recommended.')
            try:
                rep_type = rel_info['copy_type']
                cyclingmode = rel_info['cycling_mode']
                self._master_backend_helpers.delete_relationship(
                    volume.name)
                tgt_vol = (storwize_const.REPLICA_AUX_VOL_PREFIX +
                           volume.name)
                self._master_backend_helpers.extend_vdisk(volume.name,
                                                          extend_amt)
                self._aux_backend_helpers.extend_vdisk(tgt_vol, extend_amt)
                tgt_sys = self._aux_backend_helpers.get_system_info()
                if storwize_const.GMCV_MULTI == cyclingmode:
                    tgt_change_vol = (
                        storwize_const.REPLICA_CHG_VOL_PREFIX +
                        tgt_vol)
                    source_change_vol = (
                        storwize_const.REPLICA_CHG_VOL_PREFIX +
                        volume.name)
                    self._master_backend_helpers.extend_vdisk(
                        source_change_vol, extend_amt)
                    self._aux_backend_helpers.extend_vdisk(
                        tgt_change_vol, extend_amt)
                    src_change_opts = self._get_vdisk_params(
                        volume.volume_type_id)
                    cycle_period_seconds = src_change_opts.get(
                        'cycle_period_seconds')
                    self._master_backend_helpers.create_relationship(
                        volume.name, tgt_vol, tgt_sys.get('system_name'),
                        True, True, source_change_vol, cycle_period_seconds)
                    self._aux_backend_helpers.change_relationship_changevolume(
                        tgt_vol, tgt_change_vol, False)
                    self._master_backend_helpers.start_relationship(
                        volume.name)
                else:
                    self._master_backend_helpers.create_relationship(
                        volume.name, tgt_vol, tgt_sys.get('system_name'),
                        True if storwize_const.GLOBAL == rep_type else False)
            except Exception as e:
                msg = (_('Failed to extend a volume with remote copy '
                         '%(volume)s. Exception: '
                         '%(err)s.') % {'volume': volume.id,
                                        'err': e})
                LOG.error(msg)
                raise exception.VolumeDriverException(message=msg)
        else:
            self._helpers.extend_vdisk(volume_name, extend_amt)
        LOG.debug('leave: _extend_volume_op: volume %s', volume.id)

    def add_vdisk_copy(self, volume, dest_pool, vol_type, auto_delete=False):
        return self._helpers.add_vdisk_copy(volume, dest_pool,
                                            vol_type, self._state,
                                            self.configuration,
                                            auto_delete=auto_delete)

    def _add_vdisk_copy_op(self, ctxt, volume, new_op):
        metadata = self.db.volume_admin_metadata_get(ctxt.elevated(),
                                                     volume['id'])
        curr_ops = metadata.get('vdiskcopyops', None)
        if curr_ops:
            curr_ops_list = [tuple(x.split(':')) for x in curr_ops.split(';')]
            new_ops_list = curr_ops_list.append(new_op)
        else:
            new_ops_list = [new_op]
        new_ops_str = ';'.join([':'.join(x) for x in new_ops_list])
        self.db.volume_admin_metadata_update(ctxt.elevated(), volume['id'],
                                             {'vdiskcopyops': new_ops_str},
                                             False)
        if volume['id'] in self._vdiskcopyops:
            self._vdiskcopyops[volume['id']].append(new_op)
        else:
            self._vdiskcopyops[volume['id']] = [new_op]

        # We added the first copy operation, so start the looping call
        if len(self._vdiskcopyops) == 1:
            self._vdiskcopyops_loop = loopingcall.FixedIntervalLoopingCall(
                self._check_volume_copy_ops)
            self._vdiskcopyops_loop.start(interval=self.VDISKCOPYOPS_INTERVAL)

    def _rm_vdisk_copy_op(self, ctxt, volume, orig_copy_id, new_copy_id):
        try:
            self._vdiskcopyops[volume['id']].remove((orig_copy_id,
                                                     new_copy_id))
            if not len(self._vdiskcopyops[volume['id']]):
                del self._vdiskcopyops[volume['id']]
            if not len(self._vdiskcopyops):
                self._vdiskcopyops_loop.stop()
                self._vdiskcopyops_loop = None
        except KeyError:
            LOG.error('_rm_vdisk_copy_op: Volume %s does not have any '
                      'registered vdisk copy operations.', volume['id'])
            return
        except ValueError:
            LOG.error('_rm_vdisk_copy_op: Volume %(vol)s does not have '
                      'the specified vdisk copy operation: orig=%(orig)s '
                      'new=%(new)s.',
                      {'vol': volume['id'], 'orig': orig_copy_id,
                       'new': new_copy_id})
            return

        metadata = self.db.volume_admin_metadata_get(ctxt.elevated(),
                                                     volume['id'])
        curr_ops = metadata.get('vdiskcopyops', None)
        if not curr_ops:
            LOG.error('_rm_vdisk_copy_op: Volume metadata %s does not '
                      'have any registered vdisk copy operations.',
                      volume['id'])
            return
        curr_ops_list = [tuple(x.split(':')) for x in curr_ops.split(';')]
        try:
            curr_ops_list.remove((orig_copy_id, new_copy_id))
        except ValueError:
            LOG.error('_rm_vdisk_copy_op: Volume %(vol)s metadata does '
                      'not have the specified vdisk copy operation: '
                      'orig=%(orig)s new=%(new)s.',
                      {'vol': volume['id'], 'orig': orig_copy_id,
                       'new': new_copy_id})
            return

        if len(curr_ops_list):
            new_ops_str = ';'.join([':'.join(x) for x in curr_ops_list])
            self.db.volume_admin_metadata_update(ctxt.elevated(), volume['id'],
                                                 {'vdiskcopyops': new_ops_str},
                                                 False)
        else:
            self.db.volume_admin_metadata_delete(ctxt.elevated(), volume['id'],
                                                 'vdiskcopyops')

    def _check_volume_copy_ops(self):
        LOG.debug("Enter: update volume copy status.")
        ctxt = context.get_admin_context()
        copy_items = list(self._vdiskcopyops.items())
        for vol_id, copy_ops in copy_items:
            try:
                volume = self.db.volume_get(ctxt, vol_id)
            except Exception:
                LOG.warning('Volume %s does not exist.', vol_id)
                del self._vdiskcopyops[vol_id]
                if not len(self._vdiskcopyops):
                    self._vdiskcopyops_loop.stop()
                    self._vdiskcopyops_loop = None
                continue

            for copy_op in copy_ops:
                try:
                    synced = self._helpers.is_vdisk_copy_synced(volume['name'],
                                                                copy_op[1])
                except Exception:
                    LOG.info('_check_volume_copy_ops: Volume %(vol)s does '
                             'not have the specified vdisk copy '
                             'operation: orig=%(orig)s new=%(new)s.',
                             {'vol': volume['id'], 'orig': copy_op[0],
                              'new': copy_op[1]})
                else:
                    if synced:
                        self._helpers.rm_vdisk_copy(volume['name'], copy_op[0])
                        self._rm_vdisk_copy_op(ctxt, volume, copy_op[0],
                                               copy_op[1])
        LOG.debug("Exit: update volume copy status.")

    # #### V2.1 replication methods #### #
    def failover_host(self, context, volumes, secondary_id=None, groups=None):
        LOG.debug('enter: failover_host: secondary_id=%(id)s',
                  {'id': secondary_id})
        if not self._replica_enabled:
            msg = _("Replication is not properly enabled on backend.")
            LOG.error(msg)
            raise exception.UnableToFailOver(reason=msg)

        if storwize_const.FAILBACK_VALUE == secondary_id:
            # In this case the administrator would like to fail back.
            secondary_id, volumes_update = self._replication_failback(context,
                                                                      volumes)
        elif (secondary_id == self._replica_target['backend_id']
                or secondary_id is None):
            # In this case the administrator would like to fail over.
            secondary_id, volumes_update = self._replication_failover(context,
                                                                      volumes)
        else:
            msg = (_("Invalid secondary id %s.") % secondary_id)
            LOG.error(msg)
            raise exception.InvalidReplicationTarget(reason=msg)

        LOG.debug('leave: failover_host: secondary_id=%(id)s',
                  {'id': secondary_id})
        return secondary_id, volumes_update, []

    def _replication_failback(self, ctxt, volumes):
        """Fail back all the volume on the secondary backend."""

        volumes_update = []
        if not self._active_backend_id:
            LOG.info("Host has been failed back. doesn't need "
                     "to fail back again")
            return None, volumes_update

        try:
            self._master_backend_helpers.get_system_info()
        except Exception:
            msg = (_("Unable to failback due to primary is not reachable."))
            LOG.error(msg)
            raise exception.UnableToFailOver(reason=msg)

        unrep_volumes, rep_volumes = self._classify_volume(ctxt, volumes)

        # start synchronize from aux volume to master volume
        self._sync_with_aux(ctxt, rep_volumes)
        self._wait_replica_ready(ctxt, rep_volumes)

        rep_volumes_update = self._failback_replica_volumes(ctxt,
                                                            rep_volumes)
        volumes_update.extend(rep_volumes_update)

        unrep_volumes_update = self._failover_unreplicated_volume(
            unrep_volumes)
        volumes_update.extend(unrep_volumes_update)

        self._helpers = self._master_backend_helpers
        self._active_backend_id = None

        # Update the storwize state
        self._update_storwize_state()
        self._update_volume_stats()
        return storwize_const.FAILBACK_VALUE, volumes_update

    def _failback_replica_volumes(self, ctxt, rep_volumes):
        LOG.debug('enter: _failback_replica_volumes')
        volumes_update = []

        for volume in rep_volumes:
            rep_type = self._get_volume_replicated_type(ctxt, volume)
            replica_obj = self._get_replica_obj(rep_type)
            tgt_volume = storwize_const.REPLICA_AUX_VOL_PREFIX + volume['name']
            rep_info = self._helpers.get_relationship_info(tgt_volume)
            if not rep_info:
                volumes_update.append(
                    {'volume_id': volume['id'],
                     'updates':
                         {'replication_status':
                          fields.ReplicationStatus.ERROR,
                          'status': 'error'}})
                LOG.error('_failback_replica_volumes:no rc-releationship '
                          'is established between master: %(master)s and '
                          'aux %(aux)s. Please re-establish the '
                          'relationship and synchronize the volumes on '
                          'backend storage.',
                          {'master': volume['name'], 'aux': tgt_volume})
                continue
            LOG.debug('_failover_replica_volumes: vol=%(vol)s, master_vol='
                      '%(master_vol)s, aux_vol=%(aux_vol)s, state=%(state)s'
                      'primary=%(primary)s',
                      {'vol': volume['name'],
                       'master_vol': rep_info['master_vdisk_name'],
                       'aux_vol': rep_info['aux_vdisk_name'],
                       'state': rep_info['state'],
                       'primary': rep_info['primary']})
            try:
                model_updates = replica_obj.replication_failback(volume)
                volumes_update.append(
                    {'volume_id': volume['id'],
                     'updates': model_updates})
            except exception.VolumeDriverException:
                LOG.error('Unable to fail back volume %(volume_id)s',
                          {'volume_id': volume.id})
                volumes_update.append(
                    {'volume_id': volume['id'],
                     'updates': {'replication_status':
                                 fields.ReplicationStatus.ERROR,
                                 'status': 'error'}})
        LOG.debug('leave: _failback_replica_volumes '
                  'volumes_update=%(volumes_update)s',
                  {'volumes_update': volumes_update})
        return volumes_update

    def _failover_unreplicated_volume(self, unreplicated_vols):
        volumes_update = []
        for vol in unreplicated_vols:
            if vol.replication_driver_data:
                rep_data = json.loads(vol.replication_driver_data)
                update_status = rep_data['previous_status']
                rep_data = ''
            else:
                update_status = 'error'
                rep_data = json.dumps({'previous_status': vol.status})

            volumes_update.append(
                {'volume_id': vol.id,
                 'updates': {'status': update_status,
                             'replication_driver_data': rep_data}})

        return volumes_update

    def _sync_with_aux(self, ctxt, volumes):
        LOG.debug('enter: _sync_with_aux ')
        try:
            rep_mgr = self._get_replica_mgr()
            rep_mgr.establish_target_partnership()
        except Exception as ex:
            LOG.warning('Fail to establish partnership in backend. '
                        'error=%(ex)s', {'error': ex})
        for volume in volumes:
            tgt_volume = storwize_const.REPLICA_AUX_VOL_PREFIX + volume['name']
            rep_info = self._helpers.get_relationship_info(tgt_volume)
            if not rep_info:
                LOG.error('_sync_with_aux: no rc-releationship is '
                          'established between master: %(master)s and aux '
                          '%(aux)s. Please re-establish the relationship '
                          'and synchronize the volumes on backend '
                          'storage.', {'master': volume['name'],
                                       'aux': tgt_volume})
                continue
            LOG.debug('_sync_with_aux: volume: %(volume)s rep_info:master_vol='
                      '%(master_vol)s, aux_vol=%(aux_vol)s, state=%(state)s, '
                      'primary=%(primary)s',
                      {'volume': volume['name'],
                       'master_vol': rep_info['master_vdisk_name'],
                       'aux_vol': rep_info['aux_vdisk_name'],
                       'state': rep_info['state'],
                       'primary': rep_info['primary']})
            try:
                if (rep_info['state'] not in
                        [storwize_const.REP_CONSIS_SYNC,
                         storwize_const.REP_CONSIS_COPYING]):
                    if rep_info['primary'] == 'master':
                        self._helpers.start_relationship(tgt_volume)
                    else:
                        self._helpers.start_relationship(tgt_volume,
                                                         primary='aux')
            except Exception as ex:
                LOG.warning('Fail to copy data from aux to master. master:'
                            ' %(master)s and aux %(aux)s. Please '
                            're-establish the relationship and synchronize'
                            ' the volumes on backend storage. error='
                            '%(ex)s', {'master': volume['name'],
                                       'aux': tgt_volume,
                                       'error': ex})
        LOG.debug('leave: _sync_with_aux.')

    def _wait_replica_ready(self, ctxt, volumes):
        for volume in volumes:
            tgt_volume = storwize_const.REPLICA_AUX_VOL_PREFIX + volume['name']
            try:
                self._wait_replica_vol_ready(ctxt, tgt_volume)
            except Exception as ex:
                LOG.error('_wait_replica_ready: wait for volume:%(volume)s'
                          ' remote copy synchronization failed due to '
                          'error:%(err)s.', {'volume': tgt_volume,
                                             'err': ex})

    def _wait_replica_vol_ready(self, ctxt, volume):
        LOG.debug('enter: _wait_replica_vol_ready: volume=%(volume)s',
                  {'volume': volume})

        def _replica_vol_ready():
            rep_info = self._helpers.get_relationship_info(volume)
            if not rep_info:
                msg = (_('_wait_replica_vol_ready: no rc-releationship'
                         'is established for volume:%(volume)s. Please '
                         're-establish the rc-relationship and '
                         'synchronize the volumes on backend storage.'),
                       {'volume': volume})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            LOG.debug('_replica_vol_ready:volume: %(volume)s rep_info: '
                      'master_vol=%(master_vol)s, aux_vol=%(aux_vol)s, '
                      'state=%(state)s, primary=%(primary)s',
                      {'volume': volume,
                       'master_vol': rep_info['master_vdisk_name'],
                       'aux_vol': rep_info['aux_vdisk_name'],
                       'state': rep_info['state'],
                       'primary': rep_info['primary']})
            if (rep_info['state'] in
                    [storwize_const.REP_CONSIS_SYNC,
                     storwize_const.REP_CONSIS_COPYING]):
                return True
            elif rep_info['state'] == storwize_const.REP_IDL_DISC:
                msg = (_('Wait synchronize failed. volume: %(volume)s'),
                       {'volume': volume})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            return False

        self._helpers._wait_for_a_condition(
            _replica_vol_ready, timeout=storwize_const.DEFAULT_RC_TIMEOUT,
            interval=storwize_const.DEFAULT_RC_INTERVAL,
            raise_exception=True)
        LOG.debug('leave: _wait_replica_vol_ready: volume=%(volume)s',
                  {'volume': volume})

    def _replication_failover(self, ctxt, volumes):
        volumes_update = []
        if self._active_backend_id:
            LOG.info("Host has been failed over to %s",
                     self._active_backend_id)
            return self._active_backend_id, volumes_update

        try:
            self._aux_backend_helpers.get_system_info()
        except Exception as ex:
            msg = (_("Unable to failover due to replication target is not "
                     "reachable. error=%(ex)s"), {'error': ex})
            LOG.error(msg)
            raise exception.UnableToFailOver(reason=msg)

        unrep_volumes, rep_volumes = self._classify_volume(ctxt, volumes)

        rep_volumes_update = self._failover_replica_volumes(ctxt, rep_volumes)
        volumes_update.extend(rep_volumes_update)

        unrep_volumes_update = self._failover_unreplicated_volume(
            unrep_volumes)
        volumes_update.extend(unrep_volumes_update)

        self._helpers = self._aux_backend_helpers
        self._active_backend_id = self._replica_target['backend_id']
        self._secondary_pools = [self._replica_target['pool_name']]

        # Update the storwize state
        self._update_storwize_state()
        self._update_volume_stats()
        return self._active_backend_id, volumes_update

    def _failover_replica_volumes(self, ctxt, rep_volumes):
        LOG.debug('enter: _failover_replica_volumes')
        volumes_update = []

        for volume in rep_volumes:
            rep_type = self._get_volume_replicated_type(ctxt, volume)
            replica_obj = self._get_replica_obj(rep_type)
            # Try do the fail-over.
            try:
                rep_info = self._aux_backend_helpers.get_relationship_info(
                    storwize_const.REPLICA_AUX_VOL_PREFIX + volume['name'])
                if not rep_info:
                    volumes_update.append(
                        {'volume_id': volume['id'],
                         'updates':
                             {'replication_status':
                              fields.ReplicationStatus.FAILOVER_ERROR,
                              'status': 'error'}})
                    LOG.error('_failover_replica_volumes: no rc-'
                              'releationship is established for master:'
                              '%(master)s. Please re-establish the rc-'
                              'relationship and synchronize the volumes on'
                              ' backend storage.',
                              {'master': volume['name']})
                    continue
                LOG.debug('_failover_replica_volumes: vol=%(vol)s, '
                          'master_vol=%(master_vol)s, aux_vol=%(aux_vol)s, '
                          'state=%(state)s, primary=%(primary)s',
                          {'vol': volume['name'],
                           'master_vol': rep_info['master_vdisk_name'],
                           'aux_vol': rep_info['aux_vdisk_name'],
                           'state': rep_info['state'],
                           'primary': rep_info['primary']})
                model_updates = replica_obj.failover_volume_host(ctxt, volume)
                volumes_update.append(
                    {'volume_id': volume['id'],
                     'updates': model_updates})
            except exception.VolumeDriverException:
                LOG.error('Unable to failover to aux volume. Please make '
                          'sure that the aux volume is ready.')
                volumes_update.append(
                    {'volume_id': volume['id'],
                     'updates': {'status': 'error',
                                 'replication_status':
                                 fields.ReplicationStatus.FAILOVER_ERROR}})
        LOG.debug('leave: _failover_replica_volumes '
                  'volumes_update=%(volumes_update)s',
                  {'volumes_update': volumes_update})
        return volumes_update

    def _classify_volume(self, ctxt, volumes):
        normal_volumes = []
        replica_volumes = []

        for v in volumes:
            volume_type = self._get_volume_replicated_type(ctxt, v)
            if volume_type and v['status'] == 'available':
                replica_volumes.append(v)
            else:
                normal_volumes.append(v)

        return normal_volumes, replica_volumes

    def _get_replica_obj(self, rep_type):
        replica_manager = self.replica_manager[
            self._replica_target['backend_id']]
        return replica_manager.get_replica_obj(rep_type)

    def _get_replica_mgr(self):
        replica_manager = self.replica_manager[
            self._replica_target['backend_id']]
        return replica_manager

    def _get_target_vol(self, volume):
        tgt_vol = volume['name']
        if self._active_backend_id:
            ctxt = context.get_admin_context()
            rep_type = self._get_volume_replicated_type(ctxt, volume)
            if rep_type:
                tgt_vol = (storwize_const.REPLICA_AUX_VOL_PREFIX +
                           volume['name'])
        return tgt_vol

    def _validate_replication_enabled(self):
        if not self._replica_enabled:
            msg = _("Replication is not properly configured on backend.")
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def _get_specs_replicated_type(self, volume_type):
        replication_type = None
        extra_specs = volume_type.get("extra_specs", {})
        rep_val = extra_specs.get('replication_enabled')
        if rep_val == "<is> True":
            replication_type = extra_specs.get('replication_type',
                                               storwize_const.GLOBAL)
            # The format for replication_type in extra spec is in
            # "<in> global". Otherwise, the code will
            # not reach here.
            if replication_type != storwize_const.GLOBAL:
                # Pick up the replication type specified in the
                # extra spec from the format like "<in> global".
                replication_type = replication_type.split()[1]
            if replication_type not in storwize_const.VALID_REP_TYPES:
                msg = (_("Invalid replication type %s.") % replication_type)
                LOG.error(msg)
                raise exception.InvalidInput(reason=msg)
        return replication_type

    def _get_volume_replicated_type(self, ctxt, volume, vol_type_id=None):
        replication_type = None
        volume_type = None
        volume_type_id = volume.volume_type_id if volume else vol_type_id
        if volume_type_id:
            volume_type = objects.VolumeType.get_by_name_or_id(
                ctxt, volume_type_id)
        if volume_type:
            replication_type = self._get_specs_replicated_type(volume_type)
        return replication_type

    def _get_storwize_config(self):
        self._do_replication_setup()

        if self._active_backend_id and self._replica_target:
            self._helpers = self._aux_backend_helpers

        self._replica_enabled = (True if (self._helpers.replication_licensed()
                                          and self._replica_target) else False)
        if self._replica_enabled:
            self._supported_replica_types = storwize_const.VALID_REP_TYPES

    def _do_replication_setup(self):
        rep_devs = self.configuration.safe_get('replication_device')
        if not rep_devs:
            return

        if len(rep_devs) > 1:
            raise exception.InvalidInput(
                reason='Multiple replication devices are configured. '
                       'Now only one replication_device is supported.')

        required_flags = ['san_ip', 'backend_id', 'san_login',
                          'san_password', 'pool_name']
        for flag in required_flags:
            if flag not in rep_devs[0]:
                raise exception.InvalidInput(
                    reason=_('%s is not set.') % flag)

        rep_target = {}
        rep_target['san_ip'] = rep_devs[0].get('san_ip')
        rep_target['backend_id'] = rep_devs[0].get('backend_id')
        rep_target['san_login'] = rep_devs[0].get('san_login')
        rep_target['san_password'] = rep_devs[0].get('san_password')
        rep_target['pool_name'] = rep_devs[0].get('pool_name')

        # Each replication target will have a corresponding replication.
        self._replication_initialize(rep_target)

    def _replication_initialize(self, target):
        rep_manager = storwize_rep.StorwizeSVCReplicationManager(
            self, target, StorwizeHelpers)

        if self._active_backend_id:
            if self._active_backend_id != target['backend_id']:
                msg = (_("Invalid secondary id %s.") % self._active_backend_id)
                LOG.error(msg)
                raise exception.InvalidInput(reason=msg)
        # Setup partnership only in non-failover state
        else:
            try:
                rep_manager.establish_target_partnership()
            except exception.VolumeDriverException:
                LOG.error('The replication src %(src)s has not '
                          'successfully established partnership with the '
                          'replica target %(tgt)s.',
                          {'src': self.configuration.san_ip,
                           'tgt': target['backend_id']})

        self._aux_backend_helpers = rep_manager.get_target_helpers()
        self.replica_manager[target['backend_id']] = rep_manager
        self._replica_target = target

    def migrate_volume(self, ctxt, volume, host):
        """Migrate directly if source and dest are managed by same storage.

        We create a new vdisk copy in the desired pool, and add the original
        vdisk copy to the admin_metadata of the volume to be deleted. The
        deletion will occur using a periodic task once the new copy is synced.

        :param ctxt: Context
        :param volume: A dictionary describing the volume to migrate
        :param host: A dictionary describing the host to migrate to, where
                     host['host'] is its name, and host['capabilities'] is a
                     dictionary of its reported capabilities.
        """
        LOG.debug('enter: migrate_volume: id=%(id)s, host=%(host)s',
                  {'id': volume['id'], 'host': host['host']})

        false_ret = (False, None)
        dest_pool = self._helpers.can_migrate_to_host(host, self._state)
        if dest_pool is None:
            return false_ret

        ctxt = context.get_admin_context()
        volume_type_id = volume['volume_type_id']
        if volume_type_id is not None:
            vol_type = volume_types.get_volume_type(ctxt, volume_type_id)
        else:
            vol_type = None

        resp = self._helpers.lsvdiskcopy(volume.name)
        if len(resp) > 1:
            copies = self._helpers.get_vdisk_copies(volume.name)
            self._helpers.migratevdisk(volume.name, dest_pool,
                                       copies['primary']['copy_id'])
        else:
            self.add_vdisk_copy(volume.name, dest_pool, vol_type,
                                auto_delete=True)

        LOG.debug('leave: migrate_volume: id=%(id)s, host=%(host)s',
                  {'id': volume.id, 'host': host['host']})
        return (True, None)

    def _verify_retype_params(self, volume, new_opts, old_opts, need_copy,
                              change_mirror, new_rep_type, old_rep_type):
        # Some volume parameters can not be changed or changed at the same
        # time during volume retype operation. This function checks the
        # retype parameters.
        resp = self._helpers.lsvdiskcopy(volume.name)
        if old_opts['mirror_pool'] and len(resp) == 1:
            msg = (_('Unable to retype: volume %s is a mirrorred vol. But it '
                     'has only one copy in storage.') % volume.name)
            raise exception.VolumeDriverException(message=msg)

        if need_copy:
            # mirror volume can not add volume-copy again.
            if len(resp) > 1:
                msg = (_('Unable to retype: current action needs volume-copy. '
                         'A copy of volume %s exists. Adding another copy '
                         'would exceed the limit of 2 copies.') % volume.name)
                raise exception.VolumeDriverException(message=msg)
            if old_opts['mirror_pool'] or new_opts['mirror_pool']:
                msg = (_('Unable to retype: current action needs volume-copy, '
                         'it is not allowed for mirror volume '
                         '%s.') % volume.name)
                raise exception.VolumeDriverException(message=msg)

        if change_mirror:
            if (new_opts['mirror_pool'] and
                    not self._helpers.is_pool_defined(
                        new_opts['mirror_pool'])):
                msg = (_('Unable to retype: The pool %s in which mirror copy '
                         'is stored is not valid') % new_opts['mirror_pool'])
                raise exception.VolumeDriverException(message=msg)

        # There are four options for rep_type: None, metro, global, gmcv
        if new_rep_type or old_rep_type:
            # If volume is replicated, can't copy
            if need_copy or new_opts['mirror_pool'] or old_opts['mirror_pool']:
                msg = (_('Unable to retype: current action needs volume-copy, '
                         'it is not allowed for replication type. '
                         'Volume = %s') % volume.id)
                raise exception.VolumeDriverException(message=msg)

        if new_rep_type != old_rep_type:
            old_io_grp = self._helpers.get_volume_io_group(volume.name)
            if (old_io_grp not in
                    StorwizeHelpers._get_valid_requested_io_groups(
                        self._state, new_opts)):
                msg = (_('Unable to retype: it is not allowed to change '
                         'replication type and io group at the same time.'))
                LOG.error(msg)
                raise exception.VolumeDriverException(message=msg)
            if new_rep_type and old_rep_type:
                msg = (_('Unable to retype: it is not allowed to change '
                         '%(old_rep_type)s volume to %(new_rep_type)s '
                         'volume.') %
                       {'old_rep_type': old_rep_type,
                        'new_rep_type': new_rep_type})
                LOG.error(msg)
                raise exception.VolumeDriverException(message=msg)
        elif storwize_const.GMCV == new_rep_type:
            # To gmcv, we may change cycle_period_seconds if needed
            previous_cps = old_opts.get('cycle_period_seconds')
            new_cps = new_opts.get('cycle_period_seconds')
            if previous_cps != new_cps:
                self._helpers.change_relationship_cycleperiod(volume.name,
                                                              new_cps)

    def retype(self, ctxt, volume, new_type, diff, host):
        """Convert the volume to be of the new type.

        Returns a boolean indicating whether the retype occurred.

        :param ctxt: Context
        :param volume: A dictionary describing the volume to migrate
        :param new_type: A dictionary describing the volume type to convert to
        :param diff: A dictionary with the difference between the two types
        :param host: A dictionary describing the host to migrate to, where
                     host['host'] is its name, and host['capabilities'] is a
                     dictionary of its reported capabilities.
        """
        def retype_iogrp_property(volume, new, old):
            if new != old:
                self._helpers.change_vdisk_iogrp(volume['name'],
                                                 self._state, (new, old))

        LOG.debug('enter: retype: id=%(id)s, new_type=%(new_type)s,'
                  'diff=%(diff)s, host=%(host)s', {'id': volume['id'],
                                                   'new_type': new_type,
                                                   'diff': diff,
                                                   'host': host})

        no_copy_keys = ['warning', 'autoexpand', 'easytier']
        copy_keys = ['rsize', 'grainsize', 'compression']
        all_keys = no_copy_keys + copy_keys
        old_opts = self._get_vdisk_params(volume['volume_type_id'],
                                          volume_metadata=
                                          volume.get('volume_matadata'))
        new_opts = self._get_vdisk_params(new_type['id'],
                                          volume_type=new_type)

        vdisk_changes = []
        need_copy = False
        change_mirror = False

        for key in all_keys:
            if old_opts[key] != new_opts[key]:
                if key in copy_keys:
                    need_copy = True
                    break
                elif key in no_copy_keys:
                    vdisk_changes.append(key)

        if (utils.extract_host(volume['host'], 'pool') !=
                utils.extract_host(host['host'], 'pool')):
            need_copy = True

        if old_opts['mirror_pool'] != new_opts['mirror_pool']:
            change_mirror = True

        # Check if retype affects volume replication
        model_update = None
        new_rep_type = self._get_specs_replicated_type(new_type)
        old_rep_type = self._get_volume_replicated_type(ctxt, volume)
        old_io_grp = self._helpers.get_volume_io_group(volume['name'])
        new_io_grp = self._helpers.select_io_group(self._state, new_opts)

        self._verify_retype_params(volume, new_opts, old_opts, need_copy,
                                   change_mirror, new_rep_type, old_rep_type)
        if need_copy:
            self._check_volume_copy_ops()
            dest_pool = self._helpers.can_migrate_to_host(host, self._state)
            if dest_pool is None:
                return False

            retype_iogrp_property(volume,
                                  new_io_grp, old_io_grp)
            try:
                self.add_vdisk_copy(volume['name'], dest_pool, new_type,
                                    auto_delete=True)
            except exception.VolumeDriverException:
                # roll back changing iogrp property
                retype_iogrp_property(volume, old_io_grp, new_io_grp)
                msg = (_('Unable to retype:  A copy of volume %s exists. '
                         'Retyping would exceed the limit of 2 copies.'),
                       volume['id'])
                raise exception.VolumeDriverException(message=msg)
        else:
            retype_iogrp_property(volume, new_io_grp, old_io_grp)

            self._helpers.change_vdisk_options(volume['name'], vdisk_changes,
                                               new_opts, self._state)
            if change_mirror:
                copies = self._helpers.get_vdisk_copies(volume.name)
                if not old_opts['mirror_pool'] and new_opts['mirror_pool']:
                    # retype from non mirror vol to mirror vol
                    self.add_vdisk_copy(volume['name'],
                                        new_opts['mirror_pool'], new_type)
                elif old_opts['mirror_pool'] and not new_opts['mirror_pool']:
                    # retype from mirror vol to non mirror vol
                    secondary = copies['secondary']
                    if secondary:
                        self._helpers.rm_vdisk_copy(
                            volume.name, secondary['copy_id'])
                else:
                    # migrate the second copy to another pool.
                    self._helpers.migratevdisk(
                        volume.name, new_opts['mirror_pool'],
                        copies['secondary']['copy_id'])
        if new_opts['qos']:
            # Add the new QoS setting to the volume. If the volume has an
            # old QoS setting, it will be overwritten.
            self._helpers.update_vdisk_qos(volume['name'], new_opts['qos'])
        elif old_opts['qos']:
            # If the old_opts contain QoS keys, disable them.
            self._helpers.disable_vdisk_qos(volume['name'], old_opts['qos'])

        # Delete replica if needed
        if old_rep_type and not new_rep_type:
            self._aux_backend_helpers.delete_rc_volume(volume['name'],
                                                       target_vol=True)
            if storwize_const.GMCV == old_rep_type:
                self._helpers.delete_vdisk(
                    storwize_const.REPLICA_CHG_VOL_PREFIX + volume['name'],
                    False)
            model_update = {'replication_status':
                            fields.ReplicationStatus.DISABLED,
                            'replication_driver_data': None,
                            'replication_extended_status': None}
        # Add replica if needed
        if not old_rep_type and new_rep_type:
            replica_obj = self._get_replica_obj(new_rep_type)
            replica_obj.volume_replication_setup(ctxt, volume)
            if storwize_const.GMCV == new_rep_type:
                # Set cycle_period_seconds if needed
                self._helpers.change_relationship_cycleperiod(
                    volume['name'],
                    new_opts.get('cycle_period_seconds'))
            model_update = {'replication_status':
                            fields.ReplicationStatus.ENABLED}

        LOG.debug('exit: retype: ild=%(id)s, new_type=%(new_type)s,'
                  'diff=%(diff)s, host=%(host)s', {'id': volume['id'],
                                                   'new_type': new_type,
                                                   'diff': diff,
                                                   'host': host['host']})
        return True, model_update

    def update_migrated_volume(self, ctxt, volume, new_volume,
                               original_volume_status):
        """Return model update from Storwize for migrated volume.

        This method should rename the back-end volume name(id) on the
        destination host back to its original name(id) on the source host.

        :param ctxt: The context used to run the method update_migrated_volume
        :param volume: The original volume that was migrated to this backend
        :param new_volume: The migration volume object that was created on
                           this backend as part of the migration process
        :param original_volume_status: The status of the original volume
        :returns: model_update to update DB with any needed changes
        """
        current_name = CONF.volume_name_template % new_volume['id']
        original_volume_name = CONF.volume_name_template % volume['id']
        try:
            self._helpers.rename_vdisk(current_name, original_volume_name)
            rep_type = self._get_volume_replicated_type(ctxt, new_volume)
            if rep_type:
                rel_info = self._helpers.get_relationship_info(current_name)
                aux_vol = (storwize_const.REPLICA_AUX_VOL_PREFIX +
                           original_volume_name)
                self._aux_backend_helpers.rename_vdisk(
                    rel_info['aux_vdisk_name'], aux_vol)
        except exception.VolumeBackendAPIException:
            LOG.error('Unable to rename the logical volume '
                      'for volume: %s', volume['id'])
            return {'_name_id': new_volume['_name_id'] or new_volume['id']}
        # If the back-end name(id) for the volume has been renamed,
        # it is OK for the volume to keep the original name(id) and there is
        # no need to use the column "_name_id" to establish the mapping
        # relationship between the volume id and the back-end volume
        # name(id).
        # Set the key "_name_id" to None for a successful rename.
        model_update = {'_name_id': None}
        return model_update

    def manage_existing(self, volume, ref):
        """Manages an existing vdisk.

        Renames the vdisk to match the expected name for the volume.
        Error checking done by manage_existing_get_size is not repeated -
        if we got here then we have a vdisk that isn't in use (or we don't
        care if it is in use.
        """
        # Check that the reference is valid
        vdisk = self._manage_input_check(ref)
        vdisk_io_grp = self._helpers.get_volume_io_group(vdisk['name'])
        if vdisk_io_grp not in self._state['available_iogrps']:
            msg = (_("Failed to manage existing volume due to "
                     "the volume to be managed is not in a valid "
                     "I/O group."))
            raise exception.ManageExistingVolumeTypeMismatch(reason=msg)

        # Add replication check
        ctxt = context.get_admin_context()
        rep_type = self._get_volume_replicated_type(ctxt, volume)
        vol_rep_type = None
        rel_info = self._helpers.get_relationship_info(vdisk['name'])
        copies = self._helpers.get_vdisk_copies(vdisk['name'])
        if rel_info:
            vol_rep_type = (
                storwize_const.GMCV if
                storwize_const.GMCV_MULTI == rel_info['cycling_mode']
                else rel_info['copy_type'])

            aux_info = self._aux_backend_helpers.get_system_info()
            if rel_info['aux_cluster_id'] != aux_info['system_id']:
                msg = (_("Failed to manage existing volume due to the aux "
                         "cluster for volume %(volume)s is %(aux_id)s. The "
                         "configured cluster id is %(cfg_id)s") %
                       {'volume': vdisk['name'],
                        'aux_id': rel_info['aux_cluster_id'],
                        'cfg_id': aux_info['system_id']})
                raise exception.ManageExistingVolumeTypeMismatch(reason=msg)

        if vol_rep_type != rep_type:
            msg = (_("Failed to manage existing volume due to "
                     "the replication type of the volume to be managed is "
                     "mismatch with the provided replication type."))
            raise exception.ManageExistingVolumeTypeMismatch(reason=msg)
        elif storwize_const.GMCV == rep_type:
            if volume['volume_type_id']:
                rep_opts = self._get_vdisk_params(
                    volume['volume_type_id'],
                    volume_metadata=volume.get('volume_metadata'))
                # Check cycle_period_seconds
                rep_cps = six.text_type(rep_opts.get('cycle_period_seconds'))
            if rel_info['cycle_period_seconds'] != rep_cps:
                msg = (_("Failed to manage existing volume due to "
                         "the cycle_period_seconds %(vol_cps)s of "
                         "the volume to be managed is mismatch with "
                         "cycle_period_seconds %(type_cps)s in "
                         "the provided gmcv replication type.") %
                       {'vol_cps': rel_info['cycle_period_seconds'],
                        'type_cps': rep_cps})
                raise exception.ManageExistingVolumeTypeMismatch(reason=msg)

        if volume['volume_type_id']:
            opts = self._get_vdisk_params(volume['volume_type_id'],
                                          volume_metadata=
                                          volume.get('volume_metadata'))
            resp = self._helpers.lsvdiskcopy(vdisk['name'])
            expected_copy_num = 2 if opts['mirror_pool'] else 1
            if len(resp) != expected_copy_num:
                msg = (_("Failed to manage existing volume due to mirror type "
                         "mismatch. Volume to be managed has %(resp_len)s "
                         "copies. mirror_pool of the chosen type is "
                         "%(mirror_pool)s.") %
                       {'resp_len': len(resp),
                        'mirror_pool': opts['mirror_pool']})
                raise exception.ManageExistingVolumeTypeMismatch(reason=msg)
            if (opts['mirror_pool']and opts['mirror_pool'] !=
                    copies['secondary']['mdisk_grp_name']):
                msg = (_("Failed to manage existing volume due to mirror pool "
                         "mismatch. The secondary pool of the volume to be "
                         "managed is %(sec_copy_pool)s. mirror_pool of the "
                         "chosen type is %(mirror_pool)s.") %
                       {'sec_copy_pool': copies['secondary']['mdisk_grp_name'],
                        'mirror_pool': opts['mirror_pool']})
                raise exception.ManageExistingVolumeTypeMismatch(
                    reason=msg)

            vdisk_copy = self._helpers.get_vdisk_copy_attrs(vdisk['name'], '0')
            if vdisk_copy['autoexpand'] == 'on' and opts['rsize'] == -1:
                msg = (_("Failed to manage existing volume due to "
                         "the volume to be managed is thin, but "
                         "the volume type chosen is thick."))
                raise exception.ManageExistingVolumeTypeMismatch(reason=msg)

            if not vdisk_copy['autoexpand'] and opts['rsize'] != -1:
                msg = (_("Failed to manage existing volume due to "
                         "the volume to be managed is thick, but "
                         "the volume type chosen is thin."))
                raise exception.ManageExistingVolumeTypeMismatch(reason=msg)

            if (vdisk_copy['compressed_copy'] == 'no' and
                    opts['compression']):
                msg = (_("Failed to manage existing volume due to the "
                         "volume to be managed is not compress, but "
                         "the volume type chosen is compress."))
                raise exception.ManageExistingVolumeTypeMismatch(reason=msg)

            if (vdisk_copy['compressed_copy'] == 'yes' and
                    not opts['compression']):
                msg = (_("Failed to manage existing volume due to the "
                         "volume to be managed is compress, but "
                         "the volume type chosen is not compress."))
                raise exception.ManageExistingVolumeTypeMismatch(reason=msg)

            if (vdisk_io_grp not in
                    StorwizeHelpers._get_valid_requested_io_groups(
                        self._state, opts)):
                msg = (_("Failed to manage existing volume due to "
                         "I/O group mismatch. The I/O group of the "
                         "volume to be managed is %(vdisk_iogrp)s. I/O group"
                         "of the chosen type is %(opt_iogrp)s.") %
                       {'vdisk_iogrp': vdisk['IO_group_name'],
                        'opt_iogrp': opts['iogrp']})
                raise exception.ManageExistingVolumeTypeMismatch(reason=msg)
        pool = utils.extract_host(volume['host'], 'pool')
        if copies['primary']['mdisk_grp_name'] != pool:
            msg = (_("Failed to manage existing volume due to the "
                     "pool of the volume to be managed does not "
                     "match the backend pool. Pool of the "
                     "volume to be managed is %(vdisk_pool)s. Pool "
                     "of the backend is %(backend_pool)s.") %
                   {'vdisk_pool': copies['primary']['mdisk_grp_name'],
                    'backend_pool': pool})
            raise exception.ManageExistingVolumeTypeMismatch(reason=msg)

        model_update = {}
        self._helpers.rename_vdisk(vdisk['name'], volume['name'])
        if vol_rep_type:
            aux_vol = storwize_const.REPLICA_AUX_VOL_PREFIX + volume['name']
            self._aux_backend_helpers.rename_vdisk(rel_info['aux_vdisk_name'],
                                                   aux_vol)
            if storwize_const.GMCV == vol_rep_type:
                self._helpers.rename_vdisk(
                    rel_info['master_change_vdisk_name'],
                    storwize_const.REPLICA_CHG_VOL_PREFIX + volume['name'])
                self._aux_backend_helpers.rename_vdisk(
                    rel_info['aux_change_vdisk_name'],
                    storwize_const.REPLICA_CHG_VOL_PREFIX + aux_vol)
            model_update = {'replication_status':
                            fields.ReplicationStatus.ENABLED}
        return model_update

    def manage_existing_get_size(self, volume, ref):
        """Return size of an existing Vdisk for manage_existing.

        existing_ref is a dictionary of the form:
        {'source-id': <uid of disk>} or
        {'source-name': <name of the disk>}

        Optional elements are:
          'manage_if_in_use':  True/False (default is False)
            If set to True, a volume will be managed even if it is currently
            attached to a host system.
        """

        # Check that the reference is valid
        vdisk = self._manage_input_check(ref)

        # Check if the disk is in use, if we need to.
        manage_if_in_use = ref.get('manage_if_in_use', False)
        if (not manage_if_in_use and
                self._helpers.is_vdisk_in_use(vdisk['name'])):
            reason = _('The specified vdisk is mapped to a host.')
            raise exception.ManageExistingInvalidReference(existing_ref=ref,
                                                           reason=reason)

        return int(math.ceil(float(vdisk['capacity']) / units.Gi))

    def unmanage(self, volume):
        """Remove the specified volume from Cinder management."""
        pass

    def get_volume_stats(self, refresh=False):
        """Get volume stats.

        If we haven't gotten stats yet or 'refresh' is True,
        run update the stats first.
        """
        if not self._stats or refresh:
            self._update_volume_stats()

        return self._stats

    # Add CG capability to generic volume groups
    def create_group(self, context, group):
        """Creates a group.

        :param context: the context of the caller.
        :param group: the group object.
        :returns: model_update
        """

        LOG.debug("Creating group.")
        model_update = {'status': fields.GroupStatus.AVAILABLE}

        for vol_type_id in group.volume_type_ids:
            replication_type = self._get_volume_replicated_type(
                context, None, vol_type_id)
            if replication_type:
                # An unsupported configuration
                LOG.error('Unable to create group: create group with '
                          'replication volume type is not supported.')
                model_update = {'status': fields.GroupStatus.ERROR}
                return model_update

        if utils.is_group_a_cg_snapshot_type(group):
            return {'status': fields.GroupStatus.AVAILABLE}
        # we'll rely on the generic group implementation if it is not a
        # consistency group request.
        raise NotImplementedError()

    def delete_group(self, context, group, volumes):
        """Deletes a group.

        :param context: the context of the caller.
        :param group: the group object.
        :param volumes: a list of volume objects in the group.
        :returns: model_update, volumes_model_update
        """
        LOG.debug("Deleting group.")
        if not utils.is_group_a_cg_snapshot_type(group):
            # we'll rely on the generic group implementation if it is
            # not a consistency group request.
            raise NotImplementedError()

        model_update = {'status': fields.GroupStatus.DELETED}
        volumes_model_update = []

        for volume in volumes:
            try:
                self._helpers.delete_vdisk(volume['name'], True)
                volumes_model_update.append(
                    {'id': volume['id'], 'status': 'deleted'})
            except exception.VolumeBackendAPIException as err:
                model_update['status'] = (
                    fields.GroupStatus.ERROR_DELETING)
                LOG.error("Failed to delete the volume %(vol)s of CG. "
                          "Exception: %(exception)s.",
                          {'vol': volume['name'], 'exception': err})
                volumes_model_update.append(
                    {'id': volume['id'],
                     'status': fields.GroupStatus.ERROR_DELETING})

        return model_update, volumes_model_update

    def update_group(self, context, group, add_volumes=None,
                     remove_volumes=None):
        """Updates a group.

        :param context: the context of the caller.
        :param group: the group object.
        :param add_volumes: a list of volume objects to be added.
        :param remove_volumes: a list of volume objects to be removed.
        :returns: model_update, add_volumes_update, remove_volumes_update
        """

        LOG.debug("Updating group.")
        if utils.is_group_a_cg_snapshot_type(group):
            return None, None, None

        # we'll rely on the generic group implementation if it is not a
        # consistency group request.
        raise NotImplementedError()

    def create_group_from_src(self, context, group, volumes,
                              group_snapshot=None, snapshots=None,
                              source_group=None, source_vols=None):
        """Creates a group from source.

        :param context: the context of the caller.
        :param group: the Group object to be created.
        :param volumes: a list of Volume objects in the group.
        :param group_snapshot: the GroupSnapshot object as source.
        :param snapshots: a list of snapshot objects in group_snapshot.
        :param source_group: the Group object as source.
        :param source_vols: a list of volume objects in the source_group.
        :returns: model_update, volumes_model_update
        """
        LOG.debug('Enter: create_group_from_src.')
        if not utils.is_group_a_cg_snapshot_type(group):
            # we'll rely on the generic volume groups implementation if it is
            # not a consistency group request.
            raise NotImplementedError()

        if group_snapshot and snapshots:
            cg_name = 'cg-' + group_snapshot.id
            sources = snapshots

        elif source_group and source_vols:
            cg_name = 'cg-' + source_group.id
            sources = source_vols

        else:
            error_msg = _("create_group_from_src must be creating from a "
                          "group snapshot, or a source group.")
            raise exception.InvalidInput(reason=error_msg)

        LOG.debug('create_group_from_src: cg_name %(cg_name)s'
                  ' %(sources)s', {'cg_name': cg_name, 'sources': sources})
        self._helpers.create_fc_consistgrp(cg_name)
        timeout = self.configuration.storwize_svc_flashcopy_timeout
        model_update, snapshots_model = (
            self._helpers.create_cg_from_source(group,
                                                cg_name,
                                                sources,
                                                volumes,
                                                self._state,
                                                self.configuration,
                                                timeout))
        LOG.debug("Leave: create_group_from_src.")
        return model_update, snapshots_model

    def create_group_snapshot(self, context, group_snapshot, snapshots):
        """Creates a group_snapshot.

        :param context: the context of the caller.
        :param group_snapshot: the GroupSnapshot object to be created.
        :param snapshots: a list of Snapshot objects in the group_snapshot.
        :returns: model_update, snapshots_model_update
        """
        if not utils.is_group_a_cg_snapshot_type(group_snapshot):
            # we'll rely on the generic group implementation if it is not a
            # consistency group request.
            raise NotImplementedError()

        # Use group_snapshot id as cg name
        cg_name = 'cg_snap-' + group_snapshot.id
        # Create new cg as cg_snapshot
        self._helpers.create_fc_consistgrp(cg_name)

        timeout = self.configuration.storwize_svc_flashcopy_timeout

        model_update, snapshots_model = (
            self._helpers.run_consistgrp_snapshots(cg_name,
                                                   snapshots,
                                                   self._state,
                                                   self.configuration,
                                                   timeout))

        return model_update, snapshots_model

    def delete_group_snapshot(self, context, group_snapshot, snapshots):
        """Deletes a group_snapshot.

        :param context: the context of the caller.
        :param group_snapshot: the GroupSnapshot object to be deleted.
        :param snapshots: a list of snapshot objects in the group_snapshot.
        :returns: model_update, snapshots_model_update
        """

        if not utils.is_group_a_cg_snapshot_type(group_snapshot):
            # we'll rely on the generic group implementation if it is not a
            # consistency group request.
            raise NotImplementedError()

        cgsnapshot_id = group_snapshot.id
        cg_name = 'cg_snap-' + cgsnapshot_id

        model_update, snapshots_model = (
            self._helpers.delete_consistgrp_snapshots(cg_name,
                                                      snapshots))

        return model_update, snapshots_model

    def get_pool(self, volume):
        attr = self._helpers.get_vdisk_attributes(volume['name'])

        if attr is None:
            msg = (_('get_pool: Failed to get attributes for volume '
                     '%s') % volume['name'])
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        return attr['mdisk_grp_name']

    def _update_volume_stats(self):
        """Retrieve stats info from volume group."""

        LOG.debug("Updating volume stats.")
        data = {}

        data['vendor_name'] = 'IBM'
        data['driver_version'] = self.VERSION
        data['storage_protocol'] = self.protocol
        data['pools'] = []

        backend_name = self.configuration.safe_get('volume_backend_name')
        data['volume_backend_name'] = (backend_name or
                                       self._state['system_name'])

        data['pools'] = [self._build_pool_stats(pool)
                         for pool in
                         self._get_backend_pools()]
        if self._replica_enabled:
            data['replication'] = self._replica_enabled
            data['replication_enabled'] = self._replica_enabled
            data['replication_targets'] = self._get_replication_targets()
        self._stats = data

    def _build_pool_stats(self, pool):
        """Build pool status"""
        QoS_support = True
        pool_stats = {}
        try:
            pool_data = self._helpers.get_pool_attrs(pool)
            if pool_data:
                easy_tier = pool_data['easy_tier'] in ['on', 'auto']
                total_capacity_gb = float(pool_data['capacity']) / units.Gi
                free_capacity_gb = float(pool_data['free_capacity']) / units.Gi
                allocated_capacity_gb = (float(pool_data['used_capacity']) /
                                         units.Gi)
                provisioned_capacity_gb = float(
                    pool_data['virtual_capacity']) / units.Gi

                rsize = self.configuration.safe_get(
                    'storwize_svc_vol_rsize')
                # rsize of -1 or 100 means fully allocate the mdisk
                use_thick_provisioning = rsize == -1 or rsize == 100
                over_sub_ratio = self.configuration.safe_get(
                    'max_over_subscription_ratio')
                location_info = ('StorwizeSVCDriver:%(sys_id)s:%(pool)s' %
                                 {'sys_id': self._state['system_id'],
                                  'pool': pool_data['name']})
                multiattach = (self.configuration.
                               storwize_svc_multihostmap_enabled)
                pool_stats = {
                    'pool_name': pool_data['name'],
                    'total_capacity_gb': total_capacity_gb,
                    'free_capacity_gb': free_capacity_gb,
                    'allocated_capacity_gb': allocated_capacity_gb,
                    'provisioned_capacity_gb': provisioned_capacity_gb,
                    'compression_support': self._state['compression_enabled'],
                    'reserved_percentage':
                        self.configuration.reserved_percentage,
                    'QoS_support': QoS_support,
                    'consistencygroup_support': True,
                    'location_info': location_info,
                    'easytier_support': easy_tier,
                    'multiattach': multiattach,
                    'thin_provisioning_support': not use_thick_provisioning,
                    'thick_provisioning_support': use_thick_provisioning,
                    'max_over_subscription_ratio': over_sub_ratio,
                    'consistent_group_snapshot_enabled': True,
                }
            if self._replica_enabled:
                pool_stats.update({
                    'replication_enabled': self._replica_enabled,
                    'replication_type': self._supported_replica_types,
                    'replication_targets': self._get_replication_targets(),
                    'replication_count': len(self._get_replication_targets())
                })

        except exception.VolumeBackendAPIException:
            msg = _('Failed getting details for pool %s.') % pool
            raise exception.VolumeBackendAPIException(data=msg)

        return pool_stats

    def _get_replication_targets(self):
        return [self._replica_target['backend_id']]

    def _manage_input_check(self, ref):
        """Verify the input of manage function."""
        # Check that the reference is valid
        if 'source-name' in ref:
            manage_source = ref['source-name']
            vdisk = self._helpers.get_vdisk_attributes(manage_source)
        elif 'source-id' in ref:
            manage_source = ref['source-id']
            vdisk = self._helpers.vdisk_by_uid(manage_source)
        else:
            reason = _('Reference must contain source-id or '
                       'source-name element.')
            raise exception.ManageExistingInvalidReference(existing_ref=ref,
                                                           reason=reason)

        if vdisk is None:
            reason = (_('No vdisk with the UID specified by ref %s.')
                      % manage_source)
            raise exception.ManageExistingInvalidReference(existing_ref=ref,
                                                           reason=reason)
        return vdisk
