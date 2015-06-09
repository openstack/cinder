# Copyright (c) 2014 Hitachi Data Systems, Inc.
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

"""
Volume driver for HDS HNAS NFS storage.
"""

import os
import time
from xml.etree import ElementTree as ETree

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import units

from cinder import exception
from cinder.i18n import _, _LE, _LI
from cinder.image import image_utils
from cinder.volume.drivers.hds import hnas_backend
from cinder.volume.drivers import nfs
from cinder.volume import utils
from cinder.volume import volume_types


HDS_HNAS_NFS_VERSION = '3.0.0'

LOG = logging.getLogger(__name__)

NFS_OPTS = [
    cfg.StrOpt('hds_hnas_nfs_config_file',
               default='/opt/hds/hnas/cinder_nfs_conf.xml',
               help='Configuration file for HDS NFS cinder plugin'), ]

CONF = cfg.CONF
CONF.register_opts(NFS_OPTS)

HNAS_DEFAULT_CONFIG = {'hnas_cmd': 'ssc', 'ssh_port': '22'}


def _xml_read(root, element, check=None):
    """Read an xml element.

    :param root: XML object
    :param element: string desired tag
    :param check: string if present, throw exception if element missing
    """

    try:
        val = root.findtext(element)
        LOG.info(_LI("%(element)s: %(val)s"), {'element': element, 'val': val})
        if val:
            return val.strip()
        if check:
            raise exception.ParameterNotFound(param=element)
        return None
    except ETree.ParseError:
        if check:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("XML exception reading parameter: %s"), element)
        else:
            LOG.info(_LI("XML exception reading parameter: %s"), element)
            return None


def _read_config(xml_config_file):
    """Read hds driver specific xml config file.

    :param xml_config_file: string filename containing XML configuration
    """

    if not os.access(xml_config_file, os.R_OK):
        msg = (_("Can't open config file: %s") % xml_config_file)
        raise exception.NotFound(message=msg)

    try:
        root = ETree.parse(xml_config_file).getroot()
    except Exception:
        msg = (_("Error parsing config file: %s") % xml_config_file)
        raise exception.ConfigNotFound(message=msg)

    # mandatory parameters
    config = {}
    arg_prereqs = ['mgmt_ip0', 'username']
    for req in arg_prereqs:
        config[req] = _xml_read(root, req, 'check')

    # optional parameters
    opt_parameters = ['hnas_cmd', 'ssh_enabled', 'cluster_admin_ip0']
    for req in opt_parameters:
        config[req] = _xml_read(root, req)

    if config['ssh_enabled'] == 'True':
        config['ssh_private_key'] = _xml_read(root, 'ssh_private_key', 'check')
        config['password'] = _xml_read(root, 'password')
        config['ssh_port'] = _xml_read(root, 'ssh_port')
        if config['ssh_port'] is None:
            config['ssh_port'] = HNAS_DEFAULT_CONFIG['ssh_port']
    else:
        # password is mandatory when not using SSH
        config['password'] = _xml_read(root, 'password', 'check')

    if config['hnas_cmd'] is None:
        config['hnas_cmd'] = HNAS_DEFAULT_CONFIG['hnas_cmd']

    config['hdp'] = {}
    config['services'] = {}

    # min one needed
    for svc in ['svc_0', 'svc_1', 'svc_2', 'svc_3']:
        if _xml_read(root, svc) is None:
            continue
        service = {'label': svc}

        # none optional
        for arg in ['volume_type', 'hdp']:
            service[arg] = _xml_read(root, svc + '/' + arg, 'check')
        config['services'][service['volume_type']] = service
        config['hdp'][service['hdp']] = service['hdp']

    # at least one service required!
    if config['services'].keys() is None:
        raise exception.ParameterNotFound(param="No service found")

    return config


def factory_bend(drv_config):
    """Factory over-ride in self-tests."""

    return hnas_backend.HnasBackend(drv_config)


class HDSNFSDriver(nfs.NfsDriver):
    """Base class for Hitachi NFS driver.
    Executes commands relating to Volumes.

    Version 1.0.0: Initial driver version
    Version 2.2.0:  Added support to SSH authentication

    """

    def __init__(self, *args, **kwargs):
        # NOTE(vish): db is set by Manager
        self._execute = None
        self.context = None
        self.configuration = kwargs.get('configuration', None)

        if self.configuration:
            self.configuration.append_config_values(NFS_OPTS)
            self.config = _read_config(
                self.configuration.hds_hnas_nfs_config_file)

        super(HDSNFSDriver, self).__init__(*args, **kwargs)
        self.bend = factory_bend(self.config)

    def _array_info_get(self):
        """Get array parameters."""

        out = self.bend.get_version(self.config['hnas_cmd'],
                                    HDS_HNAS_NFS_VERSION,
                                    self.config['mgmt_ip0'],
                                    self.config['username'],
                                    self.config['password'])

        inf = out.split()
        return inf[1], 'nfs_' + inf[1], inf[6]

    def _id_to_vol(self, volume_id):
        """Given the volume id, retrieve the volume object from database.

        :param volume_id: string volume id
        """

        vol = self.db.volume_get(self.context, volume_id)

        return vol

    def _get_service(self, volume):
        """Get the available service parameters for a given volume using
           its type.

        :param volume: dictionary volume reference
        """

        LOG.debug("_get_service: volume: %s", volume)
        label = utils.extract_host(volume['host'], level='pool')

        if label in self.config['services'].keys():
            svc = self.config['services'][label]
            LOG.info(_LI("Get service: %(lbl)s->%(svc)s"),
                     {'lbl': label, 'svc': svc['fslabel']})
            service = (svc['hdp'], svc['path'], svc['fslabel'])
        else:
            LOG.info(_LI("Available services: %s"),
                     self.config['services'].keys())
            LOG.error(_LE("No configuration found for service: %s"),
                      label)
            raise exception.ParameterNotFound(param=label)

        return service

    def set_execute(self, execute):
        self._execute = execute

    def extend_volume(self, volume, new_size):
        """Extend an existing volume.

        :param volume: dictionary volume reference
        :param new_size: int size in GB to extend
        """

        nfs_mount = self._get_provider_location(volume['id'])
        path = self._get_volume_path(nfs_mount, volume['name'])

        # Resize the image file on share to new size.
        LOG.debug("Checking file for resize")

        if self._is_file_size_equal(path, new_size):
            return
        else:
            LOG.info(_LI("Resizing file to %sG"), new_size)
            image_utils.resize_image(path, new_size)
            if self._is_file_size_equal(path, new_size):
                LOG.info(_LI("LUN %(id)s extended to %(size)s GB."),
                         {'id': volume['id'], 'size': new_size})
                return
            else:
                raise exception.InvalidResults(
                    _("Resizing image file failed."))

    def _is_file_size_equal(self, path, size):
        """Checks if file size at path is equal to size."""

        data = image_utils.qemu_img_info(path)
        virt_size = data.virtual_size / units.Gi

        if virt_size == size:
            return True
        else:
            return False

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""

        LOG.debug("create_volume_from %s", volume)
        vol_size = volume['size']
        snap_size = snapshot['volume_size']

        if vol_size != snap_size:
            msg = _("Cannot create volume of size %(vol_size)s from "
                    "snapshot of size %(snap_size)s")
            msg_fmt = {'vol_size': vol_size, 'snap_size': snap_size}
            raise exception.CinderException(msg % msg_fmt)

        self._clone_volume(snapshot['name'],
                           volume['name'],
                           snapshot['volume_id'])
        share = self._get_volume_location(snapshot['volume_id'])

        return {'provider_location': share}

    def create_snapshot(self, snapshot):
        """Create a snapshot.

        :param snapshot: dictionary snapshot reference
        """

        self._clone_volume(snapshot['volume_name'],
                           snapshot['name'],
                           snapshot['volume_id'])
        share = self._get_volume_location(snapshot['volume_id'])
        LOG.debug('Share: %s', share)

        # returns the mount point (not path)
        return {'provider_location': share}

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot.

        :param snapshot: dictionary snapshot reference
        """

        nfs_mount = self._get_provider_location(snapshot['volume_id'])

        if self._volume_not_present(nfs_mount, snapshot['name']):
            return True

        self._execute('rm', self._get_volume_path(nfs_mount, snapshot['name']),
                      run_as_root=True)

    def _get_volume_location(self, volume_id):
        """Returns NFS mount address as <nfs_ip_address>:<nfs_mount_dir>.

        :param volume_id: string volume id
        """

        nfs_server_ip = self._get_host_ip(volume_id)
        export_path = self._get_export_path(volume_id)

        return nfs_server_ip + ':' + export_path

    def _get_provider_location(self, volume_id):
        """Returns provider location for given volume.

        :param volume_id: string volume id
        """

        volume = self.db.volume_get(self.context, volume_id)

        # same format as _get_volume_location
        return volume.provider_location

    def _get_host_ip(self, volume_id):
        """Returns IP address for the given volume.

        :param volume_id: string volume id
        """

        return self._get_provider_location(volume_id).split(':')[0]

    def _get_export_path(self, volume_id):
        """Returns NFS export path for the given volume.

        :param volume_id: string volume id
        """

        return self._get_provider_location(volume_id).split(':')[1]

    def _volume_not_present(self, nfs_mount, volume_name):
        """Check if volume exists.

        :param volume_name: string volume name
        """

        try:
            self._try_execute('ls', self._get_volume_path(nfs_mount,
                                                          volume_name))
        except processutils.ProcessExecutionError:
            # If the volume isn't present
            return True

        return False

    def _try_execute(self, *command, **kwargs):
        # NOTE(vish): Volume commands can partially fail due to timing, but
        #             running them a second time on failure will usually
        #             recover nicely.
        tries = 0
        while True:
            try:
                self._execute(*command, **kwargs)
                return True
            except processutils.ProcessExecutionError:
                tries += 1
                if tries >= self.configuration.num_shell_tries:
                    raise
                LOG.exception(_LE("Recovering from a failed execute.  "
                                  "Try number %s"), tries)
                time.sleep(tries ** 2)

    def _get_volume_path(self, nfs_share, volume_name):
        """Get volume path (local fs path) for given volume name on given nfs
        share.

        :param nfs_share string, example 172.18.194.100:/var/nfs
        :param volume_name string,
            example volume-91ee65ec-c473-4391-8c09-162b00c68a8c
        """

        return os.path.join(self._get_mount_point_for_share(nfs_share),
                            volume_name)

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume.

        :param volume: dictionary volume reference
        :param src_vref: dictionary src_vref reference
        """

        vol_size = volume['size']
        src_vol_size = src_vref['size']

        if vol_size != src_vol_size:
            msg = _("Cannot create clone of size %(vol_size)s from "
                    "volume of size %(src_vol_size)s")
            msg_fmt = {'vol_size': vol_size, 'src_vol_size': src_vol_size}
            raise exception.CinderException(msg % msg_fmt)

        self._clone_volume(src_vref['name'], volume['name'], src_vref['id'])
        share = self._get_volume_location(src_vref['id'])

        return {'provider_location': share}

    def get_volume_stats(self, refresh=False):
        """Get volume stats.

        if 'refresh' is True, update the stats first.
        """

        _stats = super(HDSNFSDriver, self).get_volume_stats(refresh)
        _stats["vendor_name"] = 'HDS'
        _stats["driver_version"] = HDS_HNAS_NFS_VERSION
        _stats["storage_protocol"] = 'NFS'

        for pool in self.pools:
            capacity, free, used = self._get_capacity_info(pool['hdp'])
            pool['total_capacity_gb'] = capacity / float(units.Gi)
            pool['free_capacity_gb'] = free / float(units.Gi)
            pool['allocated_capacity_gb'] = used / float(units.Gi)
            pool['QoS_support'] = 'False'
            pool['reserved_percentage'] = 0

        _stats['pools'] = self.pools

        LOG.info(_LI('Driver stats: %s'), _stats)

        return _stats

    def _get_nfs_info(self):
        out = self.bend.get_nfs_info(self.config['hnas_cmd'],
                                     self.config['mgmt_ip0'],
                                     self.config['username'],
                                     self.config['password'])
        lines = out.split('\n')

        # dict based on NFS exports addresses
        conf = {}
        for line in lines:
            if 'Export' in line:
                inf = line.split()
                (export, path, fslabel, hdp, ip1) = \
                    inf[1], inf[3], inf[5], inf[7], inf[11]
                # 9, 10, etc are IP addrs
                key = ip1 + ':' + export
                conf[key] = {}
                conf[key]['path'] = path
                conf[key]['hdp'] = hdp
                conf[key]['fslabel'] = fslabel
                LOG.info(_LI("nfs_info: %(key)s: %(path)s, HDP: %(fslabel)s "
                             "FSID: %(hdp)s"),
                         {'key': key, 'path': path,
                          'fslabel': fslabel, 'hdp': hdp})

        return conf

    def do_setup(self, context):
        """Perform internal driver setup."""

        self.context = context
        self._load_shares_config(getattr(self.configuration,
                                         self.driver_prefix +
                                         '_shares_config'))
        LOG.info(_LI("Review shares: %s"), self.shares)

        nfs_info = self._get_nfs_info()

        LOG.debug("nfs_info: %s", nfs_info)

        for share in self.shares:
            if share in nfs_info.keys():
                LOG.info(_LI("share: %(share)s -> %(info)s"),
                         {'share': share, 'info': nfs_info[share]['path']})

                for svc in self.config['services'].keys():
                    if share == self.config['services'][svc]['hdp']:
                        self.config['services'][svc]['path'] = \
                            nfs_info[share]['path']
                        # don't overwrite HDP value
                        self.config['services'][svc]['fsid'] = \
                            nfs_info[share]['hdp']
                        self.config['services'][svc]['fslabel'] = \
                            nfs_info[share]['fslabel']
                        LOG.info(_LI("Save service info for"
                                     " %(svc)s -> %(hdp)s, %(path)s"),
                                 {'svc': svc, 'hdp': nfs_info[share]['hdp'],
                                  'path': nfs_info[share]['path']})
                        break
                if share != self.config['services'][svc]['hdp']:
                    LOG.error(_LE("NFS share %(share)s has no service entry:"
                                  " %(svc)s -> %(hdp)s"),
                              {'share': share, 'svc': svc,
                               'hdp': self.config['services'][svc]['hdp']})
                    raise exception.ParameterNotFound(param=svc)
            else:
                LOG.info(_LI("share: %s incorrect entry"), share)

        LOG.debug("self.config['services'] = %s", self.config['services'])

        service_list = self.config['services'].keys()
        for svc in service_list:
            svc = self.config['services'][svc]
            pool = {}
            pool['pool_name'] = svc['volume_type']
            pool['service_label'] = svc['volume_type']
            pool['hdp'] = svc['hdp']

            self.pools.append(pool)

        LOG.info(_LI("Configured pools: %s"), self.pools)

    def _clone_volume(self, volume_name, clone_name, volume_id):
        """Clones mounted volume using the HNAS file_clone.

        :param volume_name: string volume name
        :param clone_name: string clone name (or snapshot)
        :param volume_id: string volume id
        """

        export_path = self._get_export_path(volume_id)
        # volume-ID snapshot-ID, /cinder
        LOG.info(_LI("Cloning with volume_name %(vname)s clone_name %(cname)s"
                     " export_path %(epath)s"), {'vname': volume_name,
                                                 'cname': clone_name,
                                                 'epath': export_path})

        source_vol = self._id_to_vol(volume_id)
        # sps; added target
        (_hdp, _path, _fslabel) = self._get_service(source_vol)
        target_path = '%s/%s' % (_path, clone_name)
        source_path = '%s/%s' % (_path, volume_name)
        out = self.bend.file_clone(self.config['hnas_cmd'],
                                   self.config['mgmt_ip0'],
                                   self.config['username'],
                                   self.config['password'],
                                   _fslabel, source_path, target_path)

        return out

    def get_pool(self, volume):
        if not volume['volume_type']:
            return 'default'
        else:
            metadata = {}
            type_id = volume['volume_type_id']
            if type_id is not None:
                metadata = volume_types.get_volume_type_extra_specs(type_id)
            if not metadata.get('service_label'):
                return 'default'
            else:
                if metadata['service_label'] not in \
                        self.config['services'].keys():
                    return 'default'
                else:
                    return metadata['service_label']

    def create_volume(self, volume):
        """Creates a volume.

        :param volume: volume reference
        """
        self._ensure_shares_mounted()

        (_hdp, _path, _fslabel) = self._get_service(volume)

        volume['provider_location'] = _hdp

        LOG.info(_LI("Volume service: %(label)s. Casted to: %(loc)s"),
                 {'label': _fslabel, 'loc': volume['provider_location']})

        self._do_create_volume(volume)

        return {'provider_location': volume['provider_location']}
