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
Fibre channel Cinder volume driver for Hitachi storage.

"""

import os
import threading

from oslo_config import cfg
from oslo_log import log as logging
from oslo_log import versionutils
from oslo_utils import excutils
import six

from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder import utils
from cinder.volume import configuration
import cinder.volume.driver
from cinder.volume.drivers.hitachi import hbsd_basiclib as basic_lib
from cinder.volume.drivers.hitachi import hbsd_common as common
from cinder.zonemanager import utils as fczm_utils

LOG = logging.getLogger(__name__)

volume_opts = [
    cfg.BoolOpt('hitachi_zoning_request',
                default=False,
                help='Request for FC Zone creating HostGroup'),
]

CONF = cfg.CONF
CONF.register_opts(volume_opts, group=configuration.SHARED_CONF_GROUP)


@interface.volumedriver
class HBSDFCDriver(cinder.volume.driver.FibreChannelDriver):
    VERSION = common.VERSION

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = ["Hitachi_HBSD_CI", "Hitachi_HBSD2_CI"]

    SUPPORTED = False

    def __init__(self, *args, **kwargs):
        os.environ['LANG'] = 'C'
        super(HBSDFCDriver, self).__init__(*args, **kwargs)
        self.db = kwargs.get('db')
        self.common = None
        self.configuration.append_config_values(common.volume_opts)
        self._stats = {}
        self.context = None
        self.max_hostgroups = None
        self.pair_hostgroups = []
        self.pair_hostnum = 0
        self.do_setup_status = threading.Event()

    def _check_param(self):
        self.configuration.append_config_values(volume_opts)
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
            self.common.output_param_to_log('FC')
            for opt in volume_opts:
                if not opt.secret:
                    value = getattr(self.configuration, opt.name)
                    LOG.info('\t%(name)-35s : %(value)s',
                             {'name': opt.name, 'value': value})
            self.common.command.output_param_to_log(self.configuration)

    def _add_wwn(self, hgs, port, gid, wwns):
        for wwn in wwns:
            wwn = six.text_type(wwn)
            self.common.command.comm_add_hbawwn(port, gid, wwn)
            detected = self.common.command.is_detected(port, wwn)
            hgs.append({'port': port, 'gid': gid, 'initiator_wwn': wwn,
                        'detected': detected})
        LOG.debug('Create host group for %s', hgs)

    def _add_lun(self, hostgroups, ldev):
        if hostgroups is self.pair_hostgroups:
            is_once = True
        else:
            is_once = False
        self.common.add_lun('auhgmap', hostgroups, ldev, is_once)

    def _delete_lun(self, hostgroups, ldev):
        try:
            self.common.command.comm_delete_lun(hostgroups, ldev)
        except exception.HBSDNotFound:
            LOG.warning(basic_lib.set_msg(301, ldev=ldev))

    def _get_hgname_gid(self, port, host_grp_name):
        return self.common.command.get_hgname_gid(port, host_grp_name)

    def _get_unused_gid(self, port):
        group_range = self.configuration.hitachi_group_range
        if not group_range:
            group_range = basic_lib.DEFAULT_GROUP_RANGE
        return self.common.command.get_unused_gid(group_range, port)

    def _get_hostgroup_info(self, hgs, wwns, login=True):
        target_ports = self.configuration.hitachi_target_ports
        return self.common.command.comm_get_hostgroup_info(
            hgs, wwns, target_ports, login=login)

    def _fill_group(self, hgs, port, host_grp_name, wwns):
        added_hostgroup = False
        LOG.debug('Create host group (hgs: %(hgs)s port: %(port)s '
                  'name: %(name)s wwns: %(wwns)s)',
                  {'hgs': hgs, 'port': port,
                   'name': host_grp_name, 'wwns': wwns})
        gid = self._get_hgname_gid(port, host_grp_name)
        if gid is None:
            for retry_cnt in basic_lib.DEFAULT_TRY_RANGE:
                try:
                    gid = self._get_unused_gid(port)
                    self._add_hostgroup(port, gid, host_grp_name)
                    added_hostgroup = True
                except exception.HBSDNotFound:
                    gid = None
                    LOG.warning(basic_lib.set_msg(312, resource='GID'))
                    continue
                else:
                    LOG.debug('Completed to add host target'
                              '(port: %(port)s gid: %(gid)d)',
                              {'port': port, 'gid': gid})
                    break
            else:
                msg = basic_lib.output_err(641)
                raise exception.HBSDError(message=msg)

        try:
            if wwns:
                self._add_wwn(hgs, port, gid, wwns)
            else:
                hgs.append({'port': port, 'gid': gid, 'initiator_wwn': None,
                            'detected': True})
        except Exception:
            with excutils.save_and_reraise_exception():
                if added_hostgroup:
                    self._delete_hostgroup(port, gid, host_grp_name)

    def add_hostgroup_master(self, hgs, master_wwns, host_ip, security_ports):
        target_ports = self.configuration.hitachi_target_ports
        group_request = self.configuration.hitachi_group_request
        wwns = []
        for wwn in master_wwns:
            wwns.append(wwn.lower())
        if target_ports and group_request:
            host_grp_name = '%s%s' % (basic_lib.NAME_PREFIX, host_ip)
            for port in security_ports:
                wwns_copy = wwns[:]
                for hostgroup in hgs:
                    if (hostgroup['port'] == port and
                            hostgroup['initiator_wwn'].lower() in wwns_copy):
                        wwns_copy.remove(hostgroup['initiator_wwn'].lower())
                if wwns_copy:
                    try:
                        self._fill_group(hgs, port, host_grp_name, wwns_copy)
                    except Exception as ex:
                        LOG.warning('Failed to add host group: %s', ex)
                        LOG.warning(basic_lib.set_msg(
                            308, port=port, name=host_grp_name))

        if not hgs:
            raise exception.HBSDError(message=basic_lib.output_err(649))

    def add_hostgroup_pair(self, pair_hostgroups):
        if self.configuration.hitachi_unit_name:
            return

        properties = utils.brick_get_connector_properties()
        if 'wwpns' not in properties:
            msg = basic_lib.output_err(650, resource='HBA')
            raise exception.HBSDError(message=msg)
        hostgroups = []
        self._get_hostgroup_info(hostgroups, properties['wwpns'],
                                 login=False)
        host_grp_name = '%spair%02x' % (basic_lib.NAME_PREFIX,
                                        self.pair_hostnum)
        for hostgroup in hostgroups:
            gid = self._get_hgname_gid(hostgroup['port'],
                                       host_grp_name)

            # When 'gid' is 0, it should be true.
            # So, it cannot remove 'is not None'.
            if gid is not None:
                pair_hostgroups.append({'port': hostgroup['port'],
                                        'gid': gid, 'initiator_wwn': None,
                                        'detected': True})
                break

        if not pair_hostgroups:
            for hostgroup in hostgroups:
                pair_port = hostgroup['port']
                try:
                    self._fill_group(pair_hostgroups, pair_port,
                                     host_grp_name, None)
                except Exception:
                    if hostgroup is hostgroups[-1]:
                        raise
                else:
                    break

    def add_hostgroup(self):
        properties = utils.brick_get_connector_properties()
        if 'wwpns' not in properties:
            msg = basic_lib.output_err(650, resource='HBA')
            raise exception.HBSDError(message=msg)
        LOG.debug("wwpns: %s", properties['wwpns'])

        hostgroups = []
        security_ports = self._get_hostgroup_info(
            hostgroups, properties['wwpns'], login=False)
        self.add_hostgroup_master(hostgroups, properties['wwpns'],
                                  properties['ip'], security_ports)
        self.add_hostgroup_pair(self.pair_hostgroups)

    def _get_target_wwn(self, port):
        target_wwns = self.common.command.comm_set_target_wwns(
            self.configuration.hitachi_target_ports)
        return target_wwns[port]

    def _add_hostgroup(self, port, gid, host_grp_name):
        self.common.command.comm_add_hostgrp(port, gid, host_grp_name)

    def _delete_hostgroup(self, port, gid, host_grp_name):
        try:
            self.common.command.comm_del_hostgrp(port, gid, host_grp_name)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.warning(basic_lib.set_msg(
                    306, port=port, gid=gid, name=host_grp_name))

    def _check_volume_mapping(self, hostgroup):
        port = hostgroup['port']
        gid = hostgroup['gid']
        if self.common.command.get_hostgroup_luns(port, gid):
            return True
        else:
            return False

    def _build_initiator_target_map(self, hostgroups, terminate=False):
        target_wwns = []
        init_targ_map = {}

        target_ports = self.configuration.hitachi_target_ports
        zoning_request = self.configuration.hitachi_zoning_request

        for hostgroup in hostgroups:
            target_wwn = self._get_target_wwn(hostgroup['port'])

            if target_wwn not in target_wwns:
                target_wwns.append(target_wwn)

            if target_ports and zoning_request:
                if terminate and self._check_volume_mapping(hostgroup):
                    continue

                initiator_wwn = hostgroup['initiator_wwn']
                if initiator_wwn not in init_targ_map:
                    init_targ_map[initiator_wwn] = []

                init_targ_map[initiator_wwn].append(target_wwn)

        return target_wwns, init_targ_map

    def _get_properties(self, volume, hostgroups, terminate=False):
        properties = {}

        target_wwns, init_targ_map = self._build_initiator_target_map(
            hostgroups, terminate)

        properties['target_wwn'] = target_wwns

        if init_targ_map:
            properties['initiator_target_map'] = init_targ_map

        if not terminate:
            properties['target_lun'] = hostgroups[0]['lun']

        return properties

    def do_setup(self, context):
        self.context = context
        self.common = common.HBSDCommon(self.configuration, self,
                                        context, self.db)
        msg = _("The HBSD FC driver is deprecated and "
                "will be removed in P release.")
        versionutils.report_deprecated_feature(LOG, msg)

        self.check_param()

        self.common.create_lock_file()

        self.common.command.connect_storage()
        self.max_hostgroups = self.common.command.get_max_hostgroups()

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
                _stats = self.common.update_volume_stats("FC")
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
                  "(config_group: %(group)s ldev: %(ldev)d)",
                  {'group': self.configuration.config_group, 'ldev': ldev})
        if src_hgs is self.pair_hostgroups:
            hostgroups = src_hgs
        else:
            hostgroups = []
            security_ports = self._get_hostgroup_info(
                hostgroups, connector['wwpns'], login=True)
            self.add_hostgroup_master(hostgroups, connector['wwpns'],
                                      connector['ip'], security_ports)

        if src_hgs is self.pair_hostgroups:
            try:
                self._add_lun(hostgroups, ldev)
            except exception.HBSDNotFound:
                LOG.warning(basic_lib.set_msg(311, ldev=ldev))
                for i in range(self.max_hostgroups + 1):
                    self.pair_hostnum += 1
                    pair_hostgroups = []
                    try:
                        self.add_hostgroup_pair(pair_hostgroups)
                        self.pair_hostgroups.extend(pair_hostgroups)
                    except exception.HBSDNotFound:
                        if i >= self.max_hostgroups:
                            msg = basic_lib.output_err(648, resource='GID')
                            raise exception.HBSDError(message=msg)
                    else:
                        break
                self.pair_initialize_connection(ldev)
        else:
            self._add_lun(hostgroups, ldev)

        return hostgroups

    @fczm_utils.add_fc_zone
    def initialize_connection(self, volume, connector):
        self.do_setup_status.wait()
        ldev = self.common.get_ldev(volume)
        if ldev is None:
            msg = basic_lib.output_err(619, volume_id=volume['id'])
            raise exception.HBSDError(message=msg)
        self.common.add_volinfo(ldev, volume['id'])
        with self.common.volume_info[ldev]['lock'],\
                self.common.volume_info[ldev]['in_use']:
            hostgroups = self._initialize_connection(ldev, connector)
            properties = self._get_properties(volume, hostgroups)
            LOG.debug('Initialize volume_info: %s',
                      self.common.volume_info)

        LOG.debug('HFCDrv: properties=%s', properties)
        return {
            'driver_volume_type': 'fibre_channel',
            'data': properties
        }

    def _terminate_connection(self, ldev, connector, src_hgs):
        LOG.debug("Call _terminate_connection(config_group: %s)",
                  self.configuration.config_group)
        hostgroups = src_hgs[:]
        self._delete_lun(hostgroups, ldev)
        LOG.debug("*** _terminate_ ***")

    @fczm_utils.remove_fc_zone
    def terminate_connection(self, volume, connector, **kwargs):
        self.do_setup_status.wait()
        ldev = self.common.get_ldev(volume)
        if ldev is None:
            LOG.warning(basic_lib.set_msg(302, volume_id=volume['id']))
            return

        if 'wwpns' not in connector:
            msg = basic_lib.output_err(650, resource='HBA')
            raise exception.HBSDError(message=msg)

        hostgroups = []
        self._get_hostgroup_info(hostgroups,
                                 connector['wwpns'], login=False)
        if not hostgroups:
            msg = basic_lib.output_err(649)
            raise exception.HBSDError(message=msg)

        self.common.add_volinfo(ldev, volume['id'])
        with self.common.volume_info[ldev]['lock'],\
                self.common.volume_info[ldev]['in_use']:
            self._terminate_connection(ldev, connector, hostgroups)
            properties = self._get_properties(volume, hostgroups,
                                              terminate=True)
            LOG.debug('Terminate volume_info: %s', self.common.volume_info)

        return {
            'driver_volume_type': 'fibre_channel',
            'data': properties
        }

    def pair_initialize_connection(self, ldev):
        if self.configuration.hitachi_unit_name:
            return
        self._initialize_connection(ldev, None, self.pair_hostgroups)

    def pair_terminate_connection(self, ldev):
        if self.configuration.hitachi_unit_name:
            return
        self._terminate_connection(ldev, None, self.pair_hostgroups)

    def discard_zero_page(self, volume):
        self.common.command.discard_zero_page(self.common.get_ldev(volume))

    def create_export(self, context, volume, connector):
        pass

    def ensure_export(self, context, volume):
        pass

    def remove_export(self, context, volume):
        pass

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        self.do_setup_status.wait()
        super(HBSDFCDriver, self).copy_image_to_volume(context, volume,
                                                       image_service,
                                                       image_id)
        self.discard_zero_page(volume)

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        self.do_setup_status.wait()
        if volume['volume_attachment']:
            desc = 'volume %s' % volume['id']
            msg = basic_lib.output_err(660, desc=desc)
            raise exception.HBSDError(message=msg)
        super(HBSDFCDriver, self).copy_volume_to_image(context, volume,
                                                       image_service,
                                                       image_meta)

    def before_volume_copy(self, context, src_vol, dest_vol, remote=None):
        """Driver-specific actions before copyvolume data.

        This method will be called before _copy_volume_data during volume
        migration
        """
        self.do_setup_status.wait()

    def after_volume_copy(self, context, src_vol, dest_vol, remote=None):
        """Driver-specific actions after copyvolume data.

        This method will be called after _copy_volume_data during volume
        migration
        """
        self.discard_zero_page(dest_vol)

    def manage_existing(self, volume, existing_ref):
        return self.common.manage_existing(volume, existing_ref)

    def manage_existing_get_size(self, volume, existing_ref):
        self.do_setup_status.wait()
        return self.common.manage_existing_get_size(volume, existing_ref)

    def unmanage(self, volume):
        self.do_setup_status.wait()
        self.common.unmanage(volume)
