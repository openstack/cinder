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
Common class for Hitachi storage drivers.

"""

from contextlib import nested
import re
import threading

from oslo.config import cfg
import six

from cinder.db.sqlalchemy import api
from cinder.db.sqlalchemy import models
from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import excutils
from cinder.openstack.common import log as logging
from cinder import utils
from cinder.volume.drivers.hitachi import hbsd_basiclib as basic_lib
from cinder.volume.drivers.hitachi import hbsd_horcm as horcm
from cinder.volume.drivers.hitachi import hbsd_snm2 as snm2
from cinder.volume import utils as volume_utils


VERSION = '1.0.0'

PARAM_RANGE = {
    'hitachi_copy_check_interval': {'min': 1, 'max': 600},
    'hitachi_async_copy_check_interval': {'min': 1, 'max': 600},
    'hitachi_copy_speed': {'min': 1, 'max': 15},
}

DEFAULT_LDEV_RANGE = [0, 65535]

COPY_METHOD = ('FULL', 'THIN')
VALID_DP_VOLUME_STATUS = ['available', 'in-use']
VALID_V_VOLUME_STATUS = ['available']
SYSTEM_LOCK_FILE = basic_lib.LOCK_DIR + 'system'
SERVICE_LOCK_PATH_BASE = basic_lib.LOCK_DIR + 'service_'
STORAGE_LOCK_PATH_BASE = basic_lib.LOCK_DIR + 'storage_'

LOG = logging.getLogger(__name__)

volume_opts = [
    cfg.StrOpt('hitachi_serial_number',
               default=None,
               help='Serial number of storage system'),
    cfg.StrOpt('hitachi_unit_name',
               default=None,
               help='Name of an array unit'),
    cfg.IntOpt('hitachi_pool_id',
               default=None,
               help='Pool ID of storage system'),
    cfg.IntOpt('hitachi_thin_pool_id',
               default=None,
               help='Thin pool ID of storage system'),
    cfg.StrOpt('hitachi_ldev_range',
               default=None,
               help='Range of logical device of storage system'),
    cfg.StrOpt('hitachi_default_copy_method',
               default='FULL',
               help='Default copy method of storage system'),
    cfg.IntOpt('hitachi_copy_speed',
               default=3,
               help='Copy speed of storage system'),
    cfg.IntOpt('hitachi_copy_check_interval',
               default=3,
               help='Interval to check copy'),
    cfg.IntOpt('hitachi_async_copy_check_interval',
               default=10,
               help='Interval to check copy asynchronously'),
    cfg.StrOpt('hitachi_target_ports',
               default=None,
               help='Control port names for HostGroup or iSCSI Target'),
    cfg.StrOpt('hitachi_group_range',
               default=None,
               help='Range of group number'),
    cfg.BoolOpt('hitachi_group_request',
                default=False,
                secret=True,
                help='Request for creating HostGroup or iSCSI Target'),
]

CONF = cfg.CONF
CONF.register_opts(volume_opts)


class TryLock(object):

    def __init__(self):
        self.lock = threading.RLock()
        self.desc = None

    def set_desc(self, description):
        self.desc = description

    def __enter__(self):
        if not self.lock.acquire(False):
            msg = basic_lib.output_err(660, desc=self.desc)
            raise exception.HBSDError(message=msg)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.lock.release()


class HBSDCommon(object):

    def __init__(self, conf, parent, context, db):
        self.configuration = conf
        self.generated_from = parent
        self.context = context
        self.db = db

        self.system_lock_file = SYSTEM_LOCK_FILE
        self.service_lock_file = '%s%s' % (SERVICE_LOCK_PATH_BASE,
                                           conf.config_group)
        if conf.hitachi_serial_number:
            self.storage_lock_file = '%s%s' % (STORAGE_LOCK_PATH_BASE,
                                               six.text_type(
                                                   conf.hitachi_serial_number))
        elif conf.hitachi_unit_name:
            self.storage_lock_file = '%s%s' % (STORAGE_LOCK_PATH_BASE,
                                               six.text_type(
                                                   conf.hitachi_unit_name))

        self.storage_obj_lock = threading.Lock()
        self.volinfo_lock = threading.Lock()
        self.volume_info = {}
        self.output_first = True

    def get_volume(self, volume_id):
        return self.db.volume_get(self.context, volume_id)

    def get_volume_metadata(self, volume_id):
        return self.db.volume_metadata_get(self.context, volume_id)

    def get_snapshot_metadata(self, snapshot_id):
        return self.db.snapshot_metadata_get(self.context, snapshot_id)

    def get_ldev(self, obj):
        if not obj:
            return None

        ldev = obj.get('provider_location')
        if not ldev or not ldev.isdigit():
            return None
        else:
            return int(ldev)

    def get_value(self, obj, name, key):
        if not obj:
            return None

        if obj.get(name):
            for i in obj[name]:
                if i['key'] == key:
                    return i['value']
        return None

    def get_is_vvol(self, obj, name):
        return self.get_value(obj, name, 'type') == 'V-VOL'

    def get_volume_is_vvol(self, volume):
        return self.get_is_vvol(volume, 'volume_metadata')

    def get_snapshot_is_vvol(self, snapshot):
        return self.get_is_vvol(snapshot, 'snapshot_metadata')

    def get_copy_method(self, volume):
        method = self.get_value(volume, 'volume_metadata', 'copy_method')
        if method:
            if method not in COPY_METHOD:
                msg = basic_lib.output_err(602, meta='copy_method')
                raise exception.HBSDError(message=msg)
            elif (method == 'THIN'
                  and self.configuration.hitachi_thin_pool_id is None):
                msg = basic_lib.output_err(601, param='hitachi_thin_pool_id')
                raise exception.HBSDError(message=msg)
        else:
            method = self.configuration.hitachi_default_copy_method
        return method

    def _range2list(self, conf, param):
        str = getattr(conf, param)
        lists = str.split('-')
        if len(lists) != 2:
            msg = basic_lib.output_err(601, param=param)
            raise exception.HBSDError(message=msg)

        first_type = None
        for i in range(len(lists)):
            if lists[i].isdigit():
                lists[i] = int(lists[i], 10)
                if first_type == 'hex':
                    msg = basic_lib.output_err(601, param=param)
                    raise exception.HBSDError(message=msg)
                first_type = 'dig'
            else:
                if (first_type == 'dig'
                        or not re.match('\w\w:\w\w:\w\w', lists[i])):
                    msg = basic_lib.output_err(601, param=param)
                    raise exception.HBSDError(message=msg)
                try:
                    lists[i] = int(lists[i].replace(':', ''), 16)
                    first_type = 'hex'
                except Exception:
                    msg = basic_lib.output_err(601, param=param)
                    raise exception.HBSDError(message=msg)
        if lists[0] > lists[1]:
            msg = basic_lib.output_err(601, param=param)
            raise exception.HBSDError(message=msg)
        return lists

    def output_param_to_log(self, storage_protocol):
        essential_inherited_param = ['volume_backend_name', 'volume_driver']
        conf = self.configuration

        msg = basic_lib.set_msg(1, config_group=conf.config_group)
        LOG.info(msg)
        version = self.command.get_comm_version()
        if conf.hitachi_unit_name:
            prefix = 'HSNM2 version'
        else:
            prefix = 'RAID Manager version'
        LOG.info('\t%-35s%s' % (prefix + ': ', six.text_type(version)))
        for param in essential_inherited_param:
            value = conf.safe_get(param)
            LOG.info('\t%-35s%s' % (param + ': ', six.text_type(value)))
        for opt in volume_opts:
            if not opt.secret:
                value = getattr(conf, opt.name)
                LOG.info('\t%-35s%s' % (opt.name + ': ',
                         six.text_type(value)))

        if storage_protocol == 'iSCSI':
            value = getattr(conf, 'hitachi_group_request')
            LOG.info('\t%-35s%s' % ('hitachi_group_request: ',
                     six.text_type(value)))

    def check_param(self):
        conf = self.configuration

        if conf.hitachi_unit_name and conf.hitachi_serial_number:
            msg = basic_lib.output_err(604)
            raise exception.HBSDError(message=msg)

        if not conf.hitachi_unit_name and not conf.hitachi_serial_number:
            msg = basic_lib.output_err(605)
            raise exception.HBSDError(message=msg)

        if conf.hitachi_pool_id is None:
            msg = basic_lib.output_err(601, param='hitachi_pool_id')
            raise exception.HBSDError(message=msg)

        for param in PARAM_RANGE.keys():
            _value = getattr(conf, param)
            if (_value and
                    (not PARAM_RANGE[param]['min'] <= _value <=
                     PARAM_RANGE[param]['max'])):
                msg = basic_lib.output_err(601, param=param)
                raise exception.HBSDError(message=msg)

        if conf.hitachi_default_copy_method not in COPY_METHOD:
            msg = basic_lib.output_err(601,
                                       param='hitachi_default_copy_method')
            raise exception.HBSDError(message=msg)

        if (conf.hitachi_default_copy_method == 'THIN'
                and conf.hitachi_thin_pool_id is None):
            msg = basic_lib.output_err(601, param='hitachi_thin_pool_id')
            raise exception.HBSDError(message=msg)

        for param in ('hitachi_ldev_range', 'hitachi_group_range'):
            if not getattr(conf, param):
                continue
            else:
                _value = self._range2list(conf, param)
                setattr(conf, param, _value)

        if conf.hitachi_target_ports:
            conf.hitachi_target_ports = conf.hitachi_target_ports.split(',')

        for opt in volume_opts:
            getattr(conf, opt.name)

        if conf.hitachi_unit_name:
            self.command = snm2.HBSDSNM2(conf)
        else:
            conf.append_config_values(horcm.volume_opts)
            self.command = horcm.HBSDHORCM(conf)
            self.command.check_param()
        self.pair_flock = self.command.set_pair_flock()

    def create_lock_file(self):
        basic_lib.create_empty_file(self.system_lock_file)
        basic_lib.create_empty_file(self.service_lock_file)
        basic_lib.create_empty_file(self.storage_lock_file)
        self.command.create_lock_file()

    def _add_ldev(self, volume_num, capacity, pool_id, is_vvol):
        self.command.comm_add_ldev(pool_id, volume_num, capacity, is_vvol)

    def _get_unused_volume_num(self, ldev_range):
        return self.command.get_unused_ldev(ldev_range)

    def add_volinfo(self, ldev, id=None, type='volume'):
        with self.volinfo_lock:
            if ldev not in self.volume_info:
                self.init_volinfo(self.volume_info, ldev)
            if id:
                desc = '%s %s' % (type, id)
                self.volume_info[ldev]['in_use'].set_desc(desc)

    def delete_pair(self, ldev, all_split=True, is_vvol=None):
        paired_info = self.command.get_paired_info(ldev)
        LOG.debug('paired_info: %s' % six.text_type(paired_info))
        pvol = paired_info['pvol']
        svols = paired_info['svol']
        driver = self.generated_from
        restart = False
        svol_list = []
        try:
            if pvol is None:
                return
            elif pvol == ldev:
                for svol in svols[:]:
                    if svol['is_vvol'] or svol['status'] != basic_lib.PSUS:
                        continue

                    self.command.delete_pair(pvol, svol['lun'], False)
                    restart = True
                    driver.pair_terminate_connection(svol['lun'])
                    svols.remove(svol)

                if all_split and svols:
                    svol_list.append(six.text_type(svols[0]['lun']))
                    for svol in svols[1:]:
                        svol_list.append(', %d' % svol['lun'])

                    msg = basic_lib.output_err(616, pvol=pvol,
                                               svol=''.join(svol_list))
                    raise exception.HBSDBusy(message=msg)

                if not svols:
                    driver.pair_terminate_connection(pvol)

            else:
                self.add_volinfo(pvol)
                if not self.volume_info[pvol]['in_use'].lock.acquire(False):
                    desc = self.volume_info[pvol]['in_use'].desc
                    msg = basic_lib.output_err(660, desc=desc)
                    raise exception.HBSDBusy(message=msg)
                try:
                    paired_info = self.command.get_paired_info(ldev)
                    if paired_info['pvol'] is None:
                        return
                    svol = paired_info['svol'][0]
                    if svol['status'] != basic_lib.PSUS:
                        msg = basic_lib.output_err(616, pvol=pvol, svol=ldev)
                        raise exception.HBSDBusy(message=msg)

                    self.command.delete_pair(pvol, ldev, svol['is_vvol'])
                    if not svol['is_vvol']:
                        restart = True
                    driver.pair_terminate_connection(ldev)
                    paired_info = self.command.get_paired_info(pvol)
                    if paired_info['pvol'] is None:
                        driver.pair_terminate_connection(pvol)
                finally:
                    self.volume_info[pvol]['in_use'].lock.release()
        except Exception:
            with excutils.save_and_reraise_exception():
                if restart:
                    try:
                        self.command.restart_pair_horcm()
                    except Exception as e:
                        LOG.warning(_('Failed to restart horcm: %s') %
                                    six.text_type(e))
        else:
            if (all_split or is_vvol) and restart:
                try:
                    self.command.restart_pair_horcm()
                except Exception as e:
                    LOG.warning(_('Failed to restart horcm: %s') %
                                six.text_type(e))

    def copy_async_data(self, pvol, svol, is_vvol):
        path_list = []
        driver = self.generated_from
        try:
            with self.pair_flock:
                self.delete_pair(pvol, all_split=False, is_vvol=is_vvol)
                paired_info = self.command.get_paired_info(pvol)
                if paired_info['pvol'] is None:
                    driver.pair_initialize_connection(pvol)
                    path_list.append(pvol)
                driver.pair_initialize_connection(svol)
                path_list.append(svol)
                self.command.comm_create_pair(pvol, svol, is_vvol)
        except Exception:
            with excutils.save_and_reraise_exception():
                for ldev in path_list:
                    try:
                        driver.pair_terminate_connection(ldev)
                    except Exception as ex:
                        msg = basic_lib.set_msg(
                            310, ldev=ldev, reason=six.text_type(ex))
                        LOG.warning(msg)

    def copy_sync_data(self, src_ldev, dest_ldev, size):
        src_vol = {'provider_location': six.text_type(src_ldev),
                   'id': 'src_vol'}
        dest_vol = {'provider_location': six.text_type(dest_ldev),
                    'id': 'dest_vol'}
        properties = utils.brick_get_connector_properties()
        driver = self.generated_from
        src_info = None
        dest_info = None
        try:
            dest_info = driver._attach_volume(self.context, dest_vol,
                                              properties)
            src_info = driver._attach_volume(self.context, src_vol,
                                             properties)
            volume_utils.copy_volume(src_info['device']['path'],
                                     dest_info['device']['path'], size * 1024,
                                     self.configuration.volume_dd_blocksize)
        finally:
            if dest_info:
                driver._detach_volume(self.context, dest_info,
                                      dest_vol, properties)
            if src_info:
                driver._detach_volume(self.context, src_info,
                                      src_vol, properties)
        self.command.discard_zero_page(dest_ldev)

    def copy_data(self, pvol, size, p_is_vvol, method):
        type = 'Normal'
        is_vvol = method == 'THIN'
        svol = self._create_volume(size, is_vvol=is_vvol)
        try:
            if p_is_vvol:
                self.copy_sync_data(pvol, svol, size)
            else:
                if is_vvol:
                    type = 'V-VOL'
                self.copy_async_data(pvol, svol, is_vvol)
        except Exception:
            with excutils.save_and_reraise_exception():
                try:
                    self.delete_ldev(svol, is_vvol)
                except Exception as ex:
                    msg = basic_lib.set_msg(
                        313, ldev=svol, reason=six.text_type(ex))
                    LOG.warning(msg)

        return six.text_type(svol), type

    def add_lun(self, command, hostgroups, ldev, is_once=False):
        lock = basic_lib.get_process_lock(self.storage_lock_file)
        with lock:
            self.command.comm_add_lun(command, hostgroups, ldev, is_once)

    def create_ldev(self, size, ldev_range, pool_id, is_vvol):
        LOG.debug('create start (normal)')
        for i in basic_lib.DEFAULT_TRY_RANGE:
            LOG.debug('Try number: %(tries)s / %(max_tries)s' %
                      {'tries': i + 1,
                       'max_tries': len(basic_lib.DEFAULT_TRY_RANGE)})
            new_ldev = self._get_unused_volume_num(ldev_range)
            try:
                self._add_ldev(new_ldev, size, pool_id, is_vvol)
            except exception.HBSDNotFound:
                msg = basic_lib.set_msg(312, resource='LDEV')
                LOG.warning(msg)
                continue
            else:
                break
        else:
            msg = basic_lib.output_err(636)
            raise exception.HBSDError(message=msg)
        LOG.debug('create end (normal: %s)' % six.text_type(new_ldev))
        self.init_volinfo(self.volume_info, new_ldev)
        return new_ldev

    def _create_volume(self, size, is_vvol=False):
        ldev_range = self.configuration.hitachi_ldev_range
        if not ldev_range:
            ldev_range = DEFAULT_LDEV_RANGE
        pool_id = self.configuration.hitachi_pool_id

        lock = basic_lib.get_process_lock(self.storage_lock_file)
        with nested(self.storage_obj_lock, lock):
            ldev = self.create_ldev(size, ldev_range, pool_id, is_vvol)
        return ldev

    def create_volume(self, volume):
        volume_metadata = self.get_volume_metadata(volume['id'])
        volume_metadata['type'] = 'Normal'

        size = volume['size']
        ldev = self._create_volume(size)
        volume_metadata['ldev'] = six.text_type(ldev)

        return {'provider_location': six.text_type(ldev),
                'metadata': volume_metadata}

    def delete_ldev(self, ldev, is_vvol):
        LOG.debug('Call delete_ldev (LDEV: %(ldev)d is_vvol: %(vvol)s)'
                  % {'ldev': ldev, 'vvol': is_vvol})
        with self.pair_flock:
            self.delete_pair(ldev)
        self.command.comm_delete_ldev(ldev, is_vvol)
        with self.volinfo_lock:
            if ldev in self.volume_info:
                self.volume_info.pop(ldev)
        LOG.debug('delete_ldev is finished '
                  '(LDEV: %(ldev)d, is_vvol: %(vvol)s)'
                  % {'ldev': ldev, 'vvol': is_vvol})

    def delete_volume(self, volume):
        ldev = self.get_ldev(volume)
        if ldev is None:
            msg = basic_lib.set_msg(
                304, method='delete_volume', id=volume['id'])
            LOG.warning(msg)
            return
        self.add_volinfo(ldev, volume['id'])
        if not self.volume_info[ldev]['in_use'].lock.acquire(False):
            desc = self.volume_info[ldev]['in_use'].desc
            basic_lib.output_err(660, desc=desc)
            raise exception.VolumeIsBusy(volume_name=volume['name'])
        try:
            is_vvol = self.get_volume_is_vvol(volume)
            try:
                self.delete_ldev(ldev, is_vvol)
            except exception.HBSDNotFound:
                with self.volinfo_lock:
                    if ldev in self.volume_info:
                        self.volume_info.pop(ldev)
                msg = basic_lib.set_msg(
                    305, type='volume', id=volume['id'])
                LOG.warning(msg)
            except exception.HBSDBusy:
                raise exception.VolumeIsBusy(volume_name=volume['name'])
        finally:
            if ldev in self.volume_info:
                self.volume_info[ldev]['in_use'].lock.release()

    def check_volume_status(self, volume, is_vvol):
        if not is_vvol:
            status = VALID_DP_VOLUME_STATUS
        else:
            status = VALID_V_VOLUME_STATUS
        if volume['status'] not in status:
            msg = basic_lib.output_err(654, status=volume['status'])
            raise exception.HBSDError(message=msg)

    def create_snapshot(self, snapshot):
        src_ref = self.get_volume(snapshot['volume_id'])
        pvol = self.get_ldev(src_ref)
        if pvol is None:
            msg = basic_lib.output_err(624, type='volume', id=src_ref['id'])
            raise exception.HBSDError(message=msg)

        self.add_volinfo(pvol, src_ref['id'])
        with self.volume_info[pvol]['in_use']:
            is_vvol = self.get_volume_is_vvol(src_ref)
            self.check_volume_status(src_ref, is_vvol)
            size = snapshot['volume_size']
            snap_metadata = self.get_snapshot_metadata(snapshot['id'])
            method = None if is_vvol else self.get_copy_method(src_ref)

            svol, type = self.copy_data(pvol, size, is_vvol, method)

        if type == 'V-VOL':
            snap_metadata['type'] = type
            snap_metadata['ldev'] = svol

        snapshot_metadata = api._metadata_refs(snap_metadata,
                                               models.SnapshotMetadata)
        return {'provider_location': svol,
                'snapshot_metadata': snapshot_metadata}

    def delete_snapshot(self, snapshot):
        ldev = self.get_ldev(snapshot)
        if ldev is None:
            msg = basic_lib.set_msg(
                304, method='delete_snapshot', id=snapshot['id'])
            LOG.warning(msg)
            return
        self.add_volinfo(ldev, id=snapshot['id'], type='snapshot')
        if not self.volume_info[ldev]['in_use'].lock.acquire(False):
            desc = self.volume_info[ldev]['in_use'].desc
            basic_lib.output_err(660, desc=desc)
            raise exception.SnapshotIsBusy(snapshot_name=snapshot['name'])
        try:
            is_vvol = self.get_snapshot_is_vvol(snapshot)
            try:
                self.delete_ldev(ldev, is_vvol)
            except exception.HBSDNotFound:
                with self.volinfo_lock:
                    if ldev in self.volume_info:
                        self.volume_info.pop(ldev)
                msg = basic_lib.set_msg(
                    305, type='snapshot', id=snapshot['id'])
                LOG.warning(msg)
            except exception.HBSDBusy:
                raise exception.SnapshotIsBusy(snapshot_name=snapshot['name'])
        finally:
            if ldev in self.volume_info:
                self.volume_info[ldev]['in_use'].lock.release()

    def create_cloned_volume(self, volume, src_vref):
        pvol = self.get_ldev(src_vref)
        if pvol is None:
            msg = basic_lib.output_err(624, type='volume', id=src_vref['id'])
            raise exception.HBSDError(message=msg)

        self.add_volinfo(pvol, src_vref['id'])
        with self.volume_info[pvol]['in_use']:
            is_vvol = self.get_volume_is_vvol(src_vref)
            self.check_volume_status(self.get_volume(src_vref['id']), is_vvol)
            size = volume['size']
            src_size = src_vref['size']
            if size != src_size:
                msg = basic_lib.output_err(617, type='volume',
                                           volume_id=volume['id'])
                raise exception.HBSDError(message=msg)

            metadata = self.get_volume_metadata(volume['id'])
            method = None if is_vvol else self.get_copy_method(volume)

            svol, type = self.copy_data(pvol, size, is_vvol, method)

            metadata['type'] = type
            metadata['volume'] = src_vref['id']
            metadata['ldev'] = svol

        return {'provider_location': svol, 'metadata': metadata}

    def create_volume_from_snapshot(self, volume, snapshot):
        pvol = self.get_ldev(snapshot)
        if pvol is None:
            msg = basic_lib.output_err(624, type='snapshot', id=snapshot['id'])
            raise exception.HBSDError(message=msg)

        self.add_volinfo(pvol, id=snapshot['id'], type='snapshot')
        with self.volume_info[pvol]['in_use']:
            is_vvol = self.get_snapshot_is_vvol(snapshot)
            if snapshot['status'] != 'available':
                msg = basic_lib.output_err(655, status=snapshot['status'])
                raise exception.HBSDError(message=msg)

            size = volume['size']
            src_size = snapshot['volume_size']
            if size != src_size:
                msg = basic_lib.output_err(617, type='snapshot',
                                           volume_id=volume['id'])
                raise exception.HBSDError(message=msg)

            metadata = self.get_volume_metadata(volume['id'])
            method = None if is_vvol else self.get_copy_method(volume)
            svol, type = self.copy_data(pvol, size, is_vvol, method)

            metadata['type'] = type
            metadata['snapshot'] = snapshot['id']
            metadata['ldev'] = svol

        return {'provider_location': svol, 'metadata': metadata}

    def _extend_volume(self, ldev, old_size, new_size):
        with self.pair_flock:
            self.delete_pair(ldev)
        self.command.comm_extend_ldev(ldev, old_size, new_size)

    def extend_volume(self, volume, new_size):
        pvol = self.get_ldev(volume)
        self.add_volinfo(pvol, volume['id'])
        with self.volume_info[pvol]['in_use']:
            if self.get_volume_is_vvol(volume):
                msg = basic_lib.output_err(618, volume_id=volume['id'])
                raise exception.HBSDError(message=msg)
            self._extend_volume(pvol, volume['size'], new_size)

    def output_backend_available_once(self):
        if self.output_first:
            self.output_first = False
            msg = basic_lib.set_msg(
                3, config_group=self.configuration.config_group)
            LOG.warning(msg)

    def update_volume_stats(self, storage_protocol):
        data = {}
        total_gb = None
        free_gb = None
        data['volume_backend_name'] = self.configuration.safe_get(
            'volume_backend_name') or 'HBSD%s' % storage_protocol
        data['vendor_name'] = 'Hitachi'
        data['driver_version'] = VERSION
        data['storage_protocol'] = storage_protocol

        try:
            total_gb, free_gb = self.command.comm_get_dp_pool(
                self.configuration.hitachi_pool_id)
        except Exception as ex:
            LOG.error(_('Failed to update volume status: %s') %
                      six.text_type(ex))
            return None

        data['total_capacity_gb'] = total_gb
        data['free_capacity_gb'] = free_gb
        data['reserved_percentage'] = self.configuration.safe_get(
            'reserved_percentage')
        data['QoS_support'] = False

        LOG.debug('Updating volume status (%s)' % data)

        return data

    def init_volinfo(self, vol_info, ldev):
        vol_info[ldev] = {'in_use': TryLock(), 'lock': threading.Lock()}
