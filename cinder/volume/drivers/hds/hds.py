# Copyright (c) 2013 Hitachi Data Systems, Inc.
# Copyright (c) 2013 OpenStack Foundation
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

"""
iSCSI Cinder Volume driver for Hitachi Unified Storage (HUS) platform.
"""

from xml.etree import ElementTree as ETree

from oslo.config import cfg

from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import excutils
from cinder.openstack.common import log as logging
from cinder import utils
from cinder.volume import driver
from cinder.volume.drivers.hds.hus_backend import HusBackend

HDS_VERSION = '1.0.2'

LOG = logging.getLogger(__name__)

HUS_OPTS = [
    cfg.StrOpt('hds_cinder_config_file',
               default='/opt/hds/hus/cinder_hus_conf.xml',
               help='The configuration file for the Cinder HDS driver '
                    'for HUS'), ]

CONF = cfg.CONF
CONF.register_opts(HUS_OPTS)

HI_IQN = 'iqn.1994-04.jp.co.hitachi:'  # fixed string, for now.

HUS_DEFAULT_CONFIG = {'hus_cmd': 'hus-cmd',
                      'lun_start': '0',
                      'lun_end': '8192'}


def factory_bend():
    """Factory over-ride in self-tests."""
    return HusBackend()


def _loc_info(loc):
    """Parse info from location string."""
    info = {}
    tup = loc.split(',')
    if len(tup) < 5:
        info['id_lu'] = tup[0].split('.')
        return info
    info['id_lu'] = tup[2].split('.')
    info['tgt'] = tup
    return info


def _do_lu_range_check(start, end, maxlun):
    """Validate array allocation range."""
    LOG.debug("Range: start LU: %(start)s, end LU: %(end)s"
              % {'start': start,
                 'end': end})
    if int(start) < 0:
        msg = 'start LU limit too low: ' + start
        raise exception.InvalidInput(reason=msg)
    if int(start) >= int(maxlun):
        msg = 'start LU limit high: ' + start + ' max: ' + maxlun
        raise exception.InvalidInput(reason=msg)
    if int(end) <= int(start):
        msg = 'LU end limit too low: ' + end
        raise exception.InvalidInput(reason=msg)
    if int(end) > int(maxlun):
        end = maxlun
        LOG.debug("setting LU upper (end) limit to %s" % maxlun)
    return (start, end)


def _xml_read(root, element, check=None):
    """Read an xml element."""
    try:
        val = root.findtext(element)
        LOG.info(_("%(element)s: %(val)s")
                 % {'element': element,
                    'val': val})
        if val:
            return val.strip()
        if check:
            raise exception.ParameterNotFound(param=element)
        return None
    except ETree.ParseError:
        if check:
            with excutils.save_and_reraise_exception():
                LOG.error(_("XML exception reading parameter: %s") % element)
        else:
            LOG.info(_("XML exception reading parameter: %s") % element)
            return None


def _read_config(xml_config_file):
    """Read hds driver specific xml config file."""
    try:
        root = ETree.parse(xml_config_file).getroot()
    except Exception:
        raise exception.NotFound(message='config file not found: '
                                 + xml_config_file)
    config = {}
    arg_prereqs = ['mgmt_ip0', 'mgmt_ip1', 'username', 'password']
    for req in arg_prereqs:
        config[req] = _xml_read(root, req, 'check')

    config['hdp'] = {}
    config['services'] = {}
    for svc in ['svc_0', 'svc_1', 'svc_2', 'svc_3']:  # min one needed
        if _xml_read(root, svc) is None:
            continue
        service = {}
        service['label'] = svc
        for arg in ['volume_type', 'hdp', 'iscsi_ip']:  # none optional
            service[arg] = _xml_read(root, svc + '/' + arg, 'check')
        config['services'][service['volume_type']] = service
        config['hdp'][service['hdp']] = service['hdp']

    if config['services'].keys() is None:  # at least one service required!
        raise exception.ParameterNotFound(param="No service found")

    config['snapshot_hdp'] = _xml_read(root, 'snapshot/hdp', 'check')

    for arg in ['hus_cmd', 'lun_start', 'lun_end']:  # optional
        config[arg] = _xml_read(root, arg) or HUS_DEFAULT_CONFIG[arg]

    return config


class HUSDriver(driver.ISCSIDriver):
    """HDS HUS volume driver."""

    VERSION = HDS_VERSION

    def _array_info_get(self):
        """Get array parameters."""
        out = self.bend.get_version(self.config['hus_cmd'],
                                    HDS_VERSION,
                                    self.config['mgmt_ip0'],
                                    self.config['mgmt_ip1'],
                                    self.config['username'],
                                    self.config['password'])
        inf = out.split()
        return(inf[1], 'hus_' + inf[1], inf[6])

    def _get_iscsi_info(self):
        """Validate array iscsi parameters."""
        out = self.bend.get_iscsi_info(self.config['hus_cmd'],
                                       HDS_VERSION,
                                       self.config['mgmt_ip0'],
                                       self.config['mgmt_ip1'],
                                       self.config['username'],
                                       self.config['password'])
        lines = out.split('\n')
        conf = {}                 # dict based on iSCSI portal ip addresses
        for line in lines:
            if 'CTL' in line:
                inf = line.split()
                (ctl, port, ip, ipp) = (inf[1], inf[3], inf[5], inf[7])
                conf[ip] = {}
                conf[ip]['ctl'] = ctl
                conf[ip]['port'] = port
                conf[ip]['iscsi_port'] = ipp  # HUS default: 3260
                msg = _('portal: %(ip)s:%(ipp)s, CTL: %(ctl)s, port: %(port)s')
                LOG.debug(msg
                          % {'ip': ip,
                             'ipp': ipp,
                             'ctl': ctl,
                             'port': port})
        return conf

    def _get_service(self, volume):
        """Get the available service parameters for a given volume type."""
        label = None
        if volume['volume_type']:
            label = volume['volume_type']['name']
        label = label or 'default'
        if label in self.config['services'].keys():
            svc = self.config['services'][label]
            service = (svc['iscsi_ip'], svc['iscsi_port'], svc['ctl'],
                       svc['port'], svc['hdp'])  # ip, ipp, ctl, port, hdp
        else:
            LOG.error(_("No configuration found for service: %s") % label)
            raise exception.ParameterNotFound(param=label)
        return service

    def _get_stats(self):
        """Get HDP stats from HUS."""
        total_cap = 0
        total_used = 0
        out = self.bend.get_hdp_info(self.config['hus_cmd'],
                                     HDS_VERSION,
                                     self.config['mgmt_ip0'],
                                     self.config['mgmt_ip1'],
                                     self.config['username'],
                                     self.config['password'])
        for line in out.split('\n'):
            if 'HDP' in line:
                (hdp, size, _ign, used) = line.split()[1:5]  # in MB
                if hdp in self.config['hdp'].keys():
                    total_cap += int(size)
                    total_used += int(used)
        hus_stat = {}
        hus_stat['total_capacity_gb'] = int(total_cap / 1024)  # in GB
        hus_stat['free_capacity_gb'] = int((total_cap - total_used) / 1024)
        be_name = self.configuration.safe_get('volume_backend_name')
        hus_stat["volume_backend_name"] = be_name or 'HUSDriver'
        hus_stat["vendor_name"] = 'HDS'
        hus_stat["driver_version"] = HDS_VERSION
        hus_stat["storage_protocol"] = 'iSCSI'
        hus_stat['QoS_support'] = False
        hus_stat['reserved_percentage'] = 0
        return hus_stat

    def _get_hdp_list(self):
        """Get HDPs from HUS."""
        out = self.bend.get_hdp_info(self.config['hus_cmd'],
                                     HDS_VERSION,
                                     self.config['mgmt_ip0'],
                                     self.config['mgmt_ip1'],
                                     self.config['username'],
                                     self.config['password'])
        hdp_list = []
        for line in out.split('\n'):
            if 'HDP' in line:
                hdp_list.extend(line.split()[1:2])
        return hdp_list

    def _check_hdp_list(self):
        """Verify all HDPs specified in the configuration exist."""
        hdpl = self._get_hdp_list()
        lst = self.config['hdp'].keys()
        lst.extend([self.config['snapshot_hdp'], ])
        for hdp in lst:
            if hdp not in hdpl:
                LOG.error(_("HDP not found: %s") % hdp)
                err = "HDP not found: " + hdp
                raise exception.ParameterNotFound(param=err)

    def _id_to_vol(self, idd):
        """Given the volume id, retrieve the volume object from database."""
        vol = self.db.volume_get(self.context, idd)
        return vol

    def _update_vol_location(self, id, loc):
        """Update the provider location."""
        update = {}
        update['provider_location'] = loc
        self.db.volume_update(self.context, id, update)

    def __init__(self, *args, **kwargs):
        """Initialize, read different config parameters."""
        super(HUSDriver, self).__init__(*args, **kwargs)
        self.driver_stats = {}
        self.context = {}
        self.bend = factory_bend()
        self.configuration.append_config_values(HUS_OPTS)
        self.config = _read_config(self.configuration.hds_cinder_config_file)
        (self.arid, self.hus_name, self.lumax) = self._array_info_get()
        self._check_hdp_list()
        start = self.config['lun_start']
        end = self.config['lun_end']
        maxlun = self.lumax
        (self.start, self.end) = _do_lu_range_check(start, end, maxlun)
        iscsi_info = self._get_iscsi_info()
        for svc in self.config['services'].keys():
            svc_ip = self.config['services'][svc]['iscsi_ip']
            if svc_ip in iscsi_info.keys():
                self.config['services'][svc]['port'] = (
                    iscsi_info[svc_ip]['port'])
                self.config['services'][svc]['ctl'] = iscsi_info[svc_ip]['ctl']
                self.config['services'][svc]['iscsi_port'] = (
                    iscsi_info[svc_ip]['iscsi_port'])
            else:          # config iscsi address not found on device!
                LOG.error(_("iSCSI portal not found for service: %s") % svc_ip)
                raise exception.ParameterNotFound(param=svc_ip)
        return

    def check_for_setup_error(self):
        """Returns an error if prerequisites aren't met."""
        return

    def do_setup(self, context):
        """do_setup.

        Setup and verify HDS HUS storage connection. But moved it to
        __init__ as (setup/errors) could became an infinite loop.
        """
        self.context = context

    def ensure_export(self, context, volume):
        return

    def create_export(self, context, volume):
        """Create an export. Moved to initialize_connection."""
        return

    @utils.synchronized('hds_hus', external=True)
    def create_volume(self, volume):
        """Create a LU on HUS."""
        service = self._get_service(volume)
        (_ip, _ipp, _ctl, _port, hdp) = service
        out = self.bend.create_lu(self.config['hus_cmd'],
                                  HDS_VERSION,
                                  self.config['mgmt_ip0'],
                                  self.config['mgmt_ip1'],
                                  self.config['username'],
                                  self.config['password'],
                                  self.arid, hdp, self.start, self.end,
                                  '%s' % (int(volume['size']) * 1024))
        lun = self.arid + '.' + out.split()[1]
        sz = int(out.split()[5])
        LOG.debug("LUN %(lun)s of size %(sz)s MB is created."
                  % {'lun': lun,
                     'sz': sz})
        return {'provider_location': lun}

    @utils.synchronized('hds_hus', external=True)
    def create_cloned_volume(self, dst, src):
        """Create a clone of a volume."""
        if src['size'] != dst['size']:
            msg = 'clone volume size mismatch'
            raise exception.VolumeBackendAPIException(data=msg)
        service = self._get_service(dst)
        (_ip, _ipp, _ctl, _port, hdp) = service
        size = int(src['size']) * 1024
        source_vol = self._id_to_vol(src['id'])
        (arid, slun) = _loc_info(source_vol['provider_location'])['id_lu']
        out = self.bend.create_dup(self.config['hus_cmd'],
                                   HDS_VERSION,
                                   self.config['mgmt_ip0'],
                                   self.config['mgmt_ip1'],
                                   self.config['username'],
                                   self.config['password'],
                                   arid, slun,
                                   hdp,
                                   self.start, self.end,
                                   '%s' % (size))
        lun = self.arid + '.' + out.split()[1]
        size = int(out.split()[5])
        LOG.debug("LUN %(lun)s of size %(size)s MB is cloned."
                  % {'lun': lun,
                     'size': size})
        return {'provider_location': lun}

    @utils.synchronized('hds_hus', external=True)
    def extend_volume(self, volume, new_size):
        """Extend an existing volume."""
        (arid, lun) = _loc_info(volume['provider_location'])['id_lu']
        self.bend.extend_vol(self.config['hus_cmd'],
                             HDS_VERSION,
                             self.config['mgmt_ip0'],
                             self.config['mgmt_ip1'],
                             self.config['username'],
                             self.config['password'],
                             arid, lun,
                             '%s' % (new_size * 1024))
        LOG.debug("LUN %(lun)s extended to %(size)s GB."
                  % {'lun': lun,
                     'size': new_size})

    @utils.synchronized('hds_hus', external=True)
    def delete_volume(self, volume):
        """Delete an LU on HUS."""
        prov_loc = volume['provider_location']
        if prov_loc is None:
            return
        info = _loc_info(prov_loc)
        (arid, lun) = info['id_lu']
        if 'tgt' in info.keys():  # connected?
            (_portal, iqn, loc, ctl, port) = info['tgt']
            self.bend.del_iscsi_conn(self.config['hus_cmd'],
                                     HDS_VERSION,
                                     self.config['mgmt_ip0'],
                                     self.config['mgmt_ip1'],
                                     self.config['username'],
                                     self.config['password'],
                                     arid, lun, ctl, port, iqn,
                                     '')
        name = self.hus_name
        LOG.debug("delete lun %(lun)s on %(name)s"
                  % {'lun': lun,
                     'name': name})
        self.bend.delete_lu(self.config['hus_cmd'],
                            HDS_VERSION,
                            self.config['mgmt_ip0'],
                            self.config['mgmt_ip1'],
                            self.config['username'],
                            self.config['password'],
                            arid, lun)

    def remove_export(self, context, volume):
        """Disconnect a volume from an attached instance."""
        return

    @utils.synchronized('hds_hus', external=True)
    def initialize_connection(self, volume, connector):
        """Map the created volume to connector['initiator']."""
        service = self._get_service(volume)
        (ip, ipp, ctl, port, _hdp) = service
        info = _loc_info(volume['provider_location'])
        if 'tgt' in info.keys():  # spurious repeat connection
            return
        (arid, lun) = info['id_lu']
        loc = arid + '.' + lun
        iqn = HI_IQN + connector['host']
        out = self.bend.add_iscsi_conn(self.config['hus_cmd'],
                                       HDS_VERSION,
                                       self.config['mgmt_ip0'],
                                       self.config['mgmt_ip1'],
                                       self.config['username'],
                                       self.config['password'],
                                       arid, lun, ctl, port, iqn,
                                       connector['initiator'])
        hus_portal = ip + ':' + ipp
        tgt = hus_portal + ',' + iqn + ',' + loc + ',' + ctl + ',' + port
        properties = {}
        hlun = out.split()[1]
        properties['provider_location'] = tgt
        self._update_vol_location(volume['id'], tgt)
        properties['target_discovered'] = False
        properties['target_portal'] = hus_portal
        properties['target_iqn'] = iqn
        properties['target_lun'] = hlun
        properties['volume_id'] = volume['id']
        return {'driver_volume_type': 'iscsi', 'data': properties}

    @utils.synchronized('hds_hus', external=True)
    def terminate_connection(self, volume, connector, **kwargs):
        """Terminate a connection to a volume."""
        info = _loc_info(volume['provider_location'])
        if 'tgt' not in info.keys():  # spurious disconnection
            return
        (arid, lun) = info['id_lu']
        (_portal, iqn, loc, ctl, port) = info['tgt']

        self.bend.del_iscsi_conn(self.config['hus_cmd'],
                                 HDS_VERSION,
                                 self.config['mgmt_ip0'],
                                 self.config['mgmt_ip1'],
                                 self.config['username'],
                                 self.config['password'],
                                 arid, lun, ctl, port, iqn,
                                 connector['initiator'])
        self._update_vol_location(volume['id'], loc)
        return {'provider_location': loc}

    @utils.synchronized('hds_hus', external=True)
    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a volume from a snapshot."""
        size = int(snapshot['volume_size']) * 1024
        (arid, slun) = _loc_info(snapshot['provider_location'])['id_lu']
        service = self._get_service(volume)
        (_ip, _ipp, _ctl, _port, hdp) = service
        out = self.bend.create_dup(self.config['hus_cmd'],
                                   HDS_VERSION,
                                   self.config['mgmt_ip0'],
                                   self.config['mgmt_ip1'],
                                   self.config['username'],
                                   self.config['password'],
                                   arid, slun, hdp,
                                   self.start, self.end,
                                   '%s' % (size))
        lun = self.arid + '.' + out.split()[1]
        sz = int(out.split()[5])
        LOG.debug("LUN %(lun)s of size %(sz)s MB is created from snapshot."
                  % {'lun': lun,
                     'sz': sz})
        return {'provider_location': lun}

    @utils.synchronized('hds_hus', external=True)
    def create_snapshot(self, snapshot):
        """Create a snapshot."""
        source_vol = self._id_to_vol(snapshot['volume_id'])
        size = int(snapshot['volume_size']) * 1024
        (arid, slun) = _loc_info(source_vol['provider_location'])['id_lu']
        out = self.bend.create_dup(self.config['hus_cmd'],
                                   HDS_VERSION,
                                   self.config['mgmt_ip0'],
                                   self.config['mgmt_ip1'],
                                   self.config['username'],
                                   self.config['password'],
                                   arid, slun,
                                   self.config['snapshot_hdp'],
                                   self.start, self.end,
                                   '%s' % (size))
        lun = self.arid + '.' + out.split()[1]
        size = int(out.split()[5])
        LOG.debug("LUN %(lun)s of size %(size)s MB is created as snapshot."
                  % {'lun': lun,
                     'size': size})
        return {'provider_location': lun}

    @utils.synchronized('hds_hus', external=True)
    def delete_snapshot(self, snapshot):
        """Delete a snapshot."""
        loc = snapshot['provider_location']
        if loc is None:         # to take care of spurious input
            return              # which could cause exception.
        (arid, lun) = loc.split('.')
        self.bend.delete_lu(self.config['hus_cmd'],
                            HDS_VERSION,
                            self.config['mgmt_ip0'],
                            self.config['mgmt_ip1'],
                            self.config['username'],
                            self.config['password'],
                            arid, lun)
        LOG.debug("LUN %s is deleted." % lun)
        return

    @utils.synchronized('hds_hus', external=True)
    def get_volume_stats(self, refresh=False):
        """Get volume stats. If 'refresh', run update the stats first."""
        if refresh:
            self.driver_stats = self._get_stats()
        return self.driver_stats
