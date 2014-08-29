# Copyright (C) 2014, Hitachi, Ltd.
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
iSCSI Cinder volume driver for Hitachi storage.

"""

from contextlib import nested
import os
import threading

from oslo.config import cfg
import six

from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import log as logging
from cinder import utils
import cinder.volume.driver
from cinder.volume.drivers.hitachi import hbsd_basiclib as basic_lib
from cinder.volume.drivers.hitachi import hbsd_common as common

LOG = logging.getLogger(__name__)

CHAP_METHOD = ('None', 'CHAP None', 'CHAP')

volume_opts = [
    cfg.BoolOpt('hitachi_add_chap_user',
                default=False,
                help='Add CHAP user'),
    cfg.StrOpt('hitachi_auth_method',
               default=None,
               help='iSCSI authentication method'),
    cfg.StrOpt('hitachi_auth_user',
               default='%sCHAP-user' % basic_lib.NAME_PREFIX,
               help='iSCSI authentication username'),
    cfg.StrOpt('hitachi_auth_password',
               default='%sCHAP-password' % basic_lib.NAME_PREFIX,
               help='iSCSI authentication password'),
]

CONF = cfg.CONF
CONF.register_opts(volume_opts)


class HBSDISCSIDriver(cinder.volume.driver.ISCSIDriver):
    VERSION = common.VERSION

    def __init__(self, *args, **kwargs):
        os.environ['LANG'] = 'C'
        super(HBSDISCSIDriver, self).__init__(*args, **kwargs)
        self.db = kwargs.get('db')
        self.common = None
        self.configuration.append_config_values(common.volume_opts)
        self._stats = {}
        self.context = None
        self.do_setup_status = threading.Event()

    def _check_param(self):
        self.configuration.append_config_values(volume_opts)
        if (self.configuration.hitachi_auth_method and
                self.configuration.hitachi_auth_method not in CHAP_METHOD):
            msg = basic_lib.output_err(601, param='hitachi_auth_method')
            raise exception.HBSDError(message=msg)
        if self.configuration.hitachi_auth_method == 'None':
            self.configuration.hitachi_auth_method = None
        for opt in volume_opts:
            getattr(self.configuration, opt.name)

    def check_param(self):
        try:
            self.common.check_param()
            self._check_param()
        except exception.HBSDError:
            raise
        except Exception as ex:
            msg = basic_lib.output_err(601, param=six.text_type(ex))
            raise exception.HBSDError(message=msg)

    def output_param_to_log(self):
        lock = basic_lib.get_process_lock(self.common.system_lock_file)

        with lock:
            self.common.output_param_to_log('iSCSI')
            for opt in volume_opts:
                if not opt.secret:
                    value = getattr(self.configuration, opt.name)
                    LOG.info('\t%-35s%s' % (opt.name + ': ',
                             six.text_type(value)))

    def _delete_lun_iscsi(self, hostgroups, ldev):
        try:
            self.common.command.comm_delete_lun_iscsi(hostgroups, ldev)
        except exception.HBSDNotFound:
            msg = basic_lib.set_msg(301, ldev=ldev)
            LOG.warning(msg)

    def _add_target(self, hostgroups, ldev):
        self.common.add_lun('autargetmap', hostgroups, ldev)

    def _add_initiator(self, hgs, port, gid, host_iqn):
        self.common.command.comm_add_initiator(port, gid, host_iqn)
        hgs.append({'port': port, 'gid': int(gid), 'detected': True})
        LOG.debug("Create iSCSI target for %s" % hgs)

    def _get_unused_gid_iscsi(self, port):
        group_range = self.configuration.hitachi_group_range
        if not group_range:
            group_range = basic_lib.DEFAULT_GROUP_RANGE
        return self.common.command.get_unused_gid_iscsi(group_range, port)

    def _delete_iscsi_target(self, port, target_no, target_alias):
        ret, _stdout, _stderr = self.common.command.delete_iscsi_target(
            port, target_no, target_alias)
        if ret:
            msg = basic_lib.set_msg(
                307, port=port, tno=target_no, alias=target_alias)
            LOG.warning(msg)

    def _delete_chap_user(self, port):
        ret, _stdout, _stderr = self.common.command.delete_chap_user(port)
        if ret:
            msg = basic_lib.set_msg(
                303, user=self.configuration.hitachi_auth_user)
            LOG.warning(msg)

    def _get_hostgroup_info_iscsi(self, hgs, host_iqn):
        return self.common.command.comm_get_hostgroup_info_iscsi(
            hgs, host_iqn, self.configuration.hitachi_target_ports)

    def _discovery_iscsi_target(self, hostgroups):
        for hostgroup in hostgroups:
            ip_addr, ip_port = self.common.command.comm_get_iscsi_ip(
                hostgroup['port'])
            target_iqn = self.common.command.comm_get_target_iqn(
                hostgroup['port'], hostgroup['gid'])
            hostgroup['ip_addr'] = ip_addr
            hostgroup['ip_port'] = ip_port
            hostgroup['target_iqn'] = target_iqn
            LOG.debug("ip_addr=%(addr)s ip_port=%(port)s target_iqn=%(iqn)s"
                      % {'addr': ip_addr, 'port': ip_port, 'iqn': target_iqn})

    def _fill_groups(self, hgs, ports, target_iqn, target_alias, add_iqn):
        for port in ports:
            added_hostgroup = False
            added_user = False
            LOG.debug('Create target (hgs: %(hgs)s port: %(port)s '
                      'target_iqn: %(tiqn)s target_alias: %(alias)s '
                      'add_iqn: %(aiqn)s)' %
                      {'hgs': hgs, 'port': port, 'tiqn': target_iqn,
                       'alias': target_alias, 'aiqn': add_iqn})
            gid = self.common.command.get_gid_from_targetiqn(
                target_iqn, target_alias, port)
            if gid is None:
                for retry_cnt in basic_lib.DEFAULT_TRY_RANGE:
                    gid = None
                    try:
                        gid = self._get_unused_gid_iscsi(port)
                        self.common.command.comm_add_hostgrp_iscsi(
                            port, gid, target_alias, target_iqn)
                        added_hostgroup = True
                    except exception.HBSDNotFound:
                        msg = basic_lib.set_msg(312, resource='GID')
                        LOG.warning(msg)
                        continue
                    except Exception as ex:
                        msg = basic_lib.set_msg(
                            309, port=port, alias=target_alias,
                            reason=six.text_type(ex))
                        LOG.warning(msg)
                        break
                    else:
                        LOG.debug('Completed to add target'
                                  '(port: %(port)s gid: %(gid)d)'
                                  % {'port': port, 'gid': gid})
                        break
            if gid is None:
                LOG.error(_('Failed to add target(port: %s)') % port)
                continue
            try:
                if added_hostgroup:
                    if self.configuration.hitachi_auth_method:
                        added_user = self.common.command.set_chap_authention(
                            port, gid)
                    self.common.command.comm_set_hostgrp_reportportal(
                        port, target_alias)
                self._add_initiator(hgs, port, gid, add_iqn)
            except Exception as ex:
                msg = basic_lib.set_msg(
                    316, port=port, reason=six.text_type(ex))
                LOG.warning(msg)
                if added_hostgroup:
                    if added_user:
                        self._delete_chap_user(port)
                    self._delete_iscsi_target(port, gid, target_alias)

    def add_hostgroup_core(self, hgs, ports, target_iqn,
                           target_alias, add_iqn):
        if ports:
            self._fill_groups(hgs, ports, target_iqn, target_alias, add_iqn)

    def add_hostgroup_master(self, hgs, master_iqn, host_ip, security_ports):
        target_ports = self.configuration.hitachi_target_ports
        group_request = self.configuration.hitachi_group_request
        target_alias = '%s%s' % (basic_lib.NAME_PREFIX, host_ip)
        if target_ports and group_request:
            target_iqn = '%s.target' % master_iqn

            diff_ports = []
            for port in security_ports:
                for hostgroup in hgs:
                    if hostgroup['port'] == port:
                        break
                else:
                    diff_ports.append(port)

            self.add_hostgroup_core(hgs, diff_ports, target_iqn,
                                    target_alias, master_iqn)
        if not hgs:
            msg = basic_lib.output_err(649)
            raise exception.HBSDError(message=msg)

    def add_hostgroup(self):
        properties = utils.brick_get_connector_properties()
        if 'initiator' not in properties:
            msg = basic_lib.output_err(650, resource='HBA')
            raise exception.HBSDError(message=msg)
        LOG.debug("initiator: %s" % properties['initiator'])
        hostgroups = []
        security_ports = self._get_hostgroup_info_iscsi(
            hostgroups, properties['initiator'])
        self.add_hostgroup_master(hostgroups, properties['initiator'],
                                  properties['ip'], security_ports)

    def _get_properties(self, volume, hostgroups):
        conf = self.configuration
        properties = {}
        self._discovery_iscsi_target(hostgroups)
        hostgroup = hostgroups[0]

        properties['target_discovered'] = True
        properties['target_portal'] = "%s:%s" % (hostgroup['ip_addr'],
                                                 hostgroup['ip_port'])
        properties['target_iqn'] = hostgroup['target_iqn']
        properties['target_lun'] = hostgroup['lun']

        if conf.hitachi_auth_method:
            properties['auth_method'] = 'CHAP'
            properties['auth_username'] = conf.hitachi_auth_user
            properties['auth_password'] = conf.hitachi_auth_password

        return properties

    def do_setup(self, context):
        self.context = context
        self.common = common.HBSDCommon(self.configuration, self,
                                        context, self.db)

        self.check_param()

        self.common.create_lock_file()

        self.common.command.connect_storage()

        lock = basic_lib.get_process_lock(self.common.service_lock_file)
        with lock:
            self.add_hostgroup()

        self.output_param_to_log()
        self.do_setup_status.set()

    def check_for_setup_error(self):
        pass

    def extend_volume(self, volume, new_size):
        self.do_setup_status.wait()
        self.common.extend_volume(volume, new_size)

    def get_volume_stats(self, refresh=False):
        if refresh:
            if self.do_setup_status.isSet():
                self.common.output_backend_available_once()
                _stats = self.common.update_volume_stats("iSCSI")
                if _stats:
                    self._stats = _stats
        return self._stats

    def create_volume(self, volume):
        self.do_setup_status.wait()
        metadata = self.common.create_volume(volume)
        return metadata

    def delete_volume(self, volume):
        self.do_setup_status.wait()
        self.common.delete_volume(volume)

    def create_snapshot(self, snapshot):
        self.do_setup_status.wait()
        metadata = self.common.create_snapshot(snapshot)
        return metadata

    def delete_snapshot(self, snapshot):
        self.do_setup_status.wait()
        self.common.delete_snapshot(snapshot)

    def create_cloned_volume(self, volume, src_vref):
        self.do_setup_status.wait()
        metadata = self.common.create_cloned_volume(volume, src_vref)
        return metadata

    def create_volume_from_snapshot(self, volume, snapshot):
        self.do_setup_status.wait()
        metadata = self.common.create_volume_from_snapshot(volume, snapshot)
        return metadata

    def _initialize_connection(self, ldev, connector, src_hgs=None):
        LOG.debug("Call _initialize_connection "
                  "(config_group: %(group)s ldev: %(ldev)d)"
                  % {'group': self.configuration.config_group, 'ldev': ldev})
        if src_hgs:
            hostgroups = src_hgs[:]
        else:
            hostgroups = []
            security_ports = self._get_hostgroup_info_iscsi(
                hostgroups, connector['initiator'])
            self.add_hostgroup_master(hostgroups, connector['initiator'],
                                      connector['ip'], security_ports)

        self._add_target(hostgroups, ldev)

        return hostgroups

    def initialize_connection(self, volume, connector):
        self.do_setup_status.wait()
        ldev = self.common.get_ldev(volume)
        if ldev is None:
            msg = basic_lib.output_err(619, volume_id=volume['id'])
            raise exception.HBSDError(message=msg)
        self.common.add_volinfo(ldev, volume['id'])
        with nested(self.common.volume_info[ldev]['lock'],
                    self.common.volume_info[ldev]['in_use']):
            hostgroups = self._initialize_connection(ldev, connector)
            protocol = 'iscsi'
            properties = self._get_properties(volume, hostgroups)
            LOG.debug('Initialize volume_info: %s'
                      % self.common.volume_info)

        LOG.debug('HFCDrv: properties=%s' % properties)
        return {
            'driver_volume_type': protocol,
            'data': properties
        }

    def _terminate_connection(self, ldev, connector, src_hgs):
        LOG.debug("Call _terminate_connection(config_group: %s)"
                  % self.configuration.config_group)
        hostgroups = src_hgs[:]
        self._delete_lun_iscsi(hostgroups, ldev)

        LOG.debug("*** _terminate_ ***")

    def terminate_connection(self, volume, connector, **kwargs):
        self.do_setup_status.wait()
        ldev = self.common.get_ldev(volume)
        if ldev is None:
            msg = basic_lib.set_msg(302, volume_id=volume['id'])
            LOG.warning(msg)
            return

        if 'initiator' not in connector:
            msg = basic_lib.output_err(650, resource='HBA')
            raise exception.HBSDError(message=msg)

        hostgroups = []
        self._get_hostgroup_info_iscsi(hostgroups,
                                       connector['initiator'])
        if not hostgroups:
            msg = basic_lib.output_err(649)
            raise exception.HBSDError(message=msg)

        self.common.add_volinfo(ldev, volume['id'])
        with nested(self.common.volume_info[ldev]['lock'],
                    self.common.volume_info[ldev]['in_use']):
            self._terminate_connection(ldev, connector, hostgroups)

    def create_export(self, context, volume):
        pass

    def ensure_export(self, context, volume):
        pass

    def remove_export(self, context, volume):
        pass

    def pair_initialize_connection(self, unused_ldev):
        pass

    def pair_terminate_connection(self, unused_ldev):
        pass

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        self.do_setup_status.wait()
        if (volume['instance_uuid'] or volume['attached_host']):
            desc = 'volume %s' % volume['id']
            msg = basic_lib.output_err(660, desc=desc)
            raise exception.HBSDError(message=msg)
        super(HBSDISCSIDriver, self).copy_volume_to_image(context, volume,
                                                          image_service,
                                                          image_meta)
