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
#

"""
iSCSI Cinder Volume driver for Hitachi Unified Storage (HUS-HNAS) platform.
"""

from xml.etree import ElementTree as ETree

from oslo.config import cfg

from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import excutils
from cinder.openstack.common import log as logging
from cinder.openstack.common import units
from cinder.volume import driver
from cinder.volume.drivers.hds.hnas_backend import HnasBackend
from cinder.volume import utils


HDS_HNAS_ISCSI_VERSION = '1.0.0'

LOG = logging.getLogger(__name__)

iSCSI_OPTS = [
    cfg.StrOpt('hds_hnas_iscsi_config_file',
               default='/opt/hds/hnas/cinder_iscsi_conf.xml',
               help='Configuration file for HDS iSCSI cinder plugin')]

CONF = cfg.CONF
CONF.register_opts(iSCSI_OPTS)

HNAS_DEFAULT_CONFIG = {'hnas_cmd': 'ssc', 'chap_enabled': 'True'}


def factory_bend(type):
    return HnasBackend()


def _loc_info(loc):
    """Parse info from location string."""

    LOG.info("Parse_loc: %s" % loc)
    info = {}
    tup = loc.split(',')
    if len(tup) < 5:
        info['id_lu'] = tup[0].split('.')
        return info
    info['id_lu'] = tup[2].split('.')
    info['tgt'] = tup
    return info


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

    # mandatory parameters
    config = {}
    arg_prereqs = ['mgmt_ip0', 'username', 'password']
    for req in arg_prereqs:
        config[req] = _xml_read(root, req, 'check')

    # optional parameters
    for opt in ['hnas_cmd', 'chap_enabled']:
        config[opt] = _xml_read(root, opt) or\
            HNAS_DEFAULT_CONFIG[opt]

    config['hdp'] = {}
    config['services'] = {}

    # min one needed
    for svc in ['svc_0', 'svc_1', 'svc_2', 'svc_3']:
        if _xml_read(root, svc) is None:
            continue
        service = {'label': svc}

        # none optional
        for arg in ['volume_type', 'hdp', 'iscsi_ip']:
            service[arg] = _xml_read(root, svc + '/' + arg, 'check')
        config['services'][service['volume_type']] = service
        config['hdp'][service['hdp']] = service['hdp']

    # at least one service required!
    if config['services'].keys() is None:
        raise exception.ParameterNotFound(param="No service found")

    return config


class HDSISCSIDriver(driver.ISCSIDriver):
    """HDS HNAS volume driver."""

    def __init__(self, *args, **kwargs):
        """Initialize, read different config parameters."""

        super(HDSISCSIDriver, self).__init__(*args, **kwargs)
        self.driver_stats = {}
        self.context = {}
        self.configuration.append_config_values(iSCSI_OPTS)
        self.config = _read_config(
            self.configuration.hds_hnas_iscsi_config_file)
        self.type = 'HNAS'

        self.platform = self.type.lower()
        LOG.info(_("Backend type: %s") % self.type)
        self.bend = factory_bend(self.type)

    def _array_info_get(self):
        """Get array parameters."""

        out = self.bend.get_version(self.config['hnas_cmd'],
                                    HDS_HNAS_ISCSI_VERSION,
                                    self.config['mgmt_ip0'],
                                    self.config['username'],
                                    self.config['password'])
        inf = out.split()

        return inf[1], 'hnas_' + inf[1], inf[6]

    def _get_iscsi_info(self):
        """Validate array iscsi parameters."""

        out = self.bend.get_iscsi_info(self.config['hnas_cmd'],
                                       self.config['mgmt_ip0'],
                                       self.config['username'],
                                       self.config['password'])
        lines = out.split('\n')

        # dict based on iSCSI portal ip addresses
        conf = {}
        for line in lines:
            # only record up links
            if 'CTL' in line and 'Up' in line:
                inf = line.split()
                (ctl, port, ip, ipp) = (inf[1], inf[3], inf[5], inf[7])
                conf[ip] = {}
                conf[ip]['ctl'] = ctl
                conf[ip]['port'] = port
                conf[ip]['iscsi_port'] = ipp
                msg = ('portal: %(ip)s:%(ipp)s, CTL: %(ctl)s, port: %(port)s')
                LOG.debug(msg
                          % {'ip': ip,
                             'ipp': ipp,
                             'ctl': ctl,
                             'port': port})

        return conf

    def _get_service(self, volume):
        """Get the available service parameters for a given volume using
           its type.
           :param volume: dictionary volume reference
        """

        label = None
        if volume['volume_type']:
            label = volume['volume_type']['name']

        label = label or 'default'
        if label not in self.config['services'].keys():
            # default works if no match is found
            label = 'default'
            LOG.info(_("Using default: instead of %s") % label)
            LOG.info(_("Available services: %s")
                     % self.config['services'].keys())

        if label in self.config['services'].keys():
            svc = self.config['services'][label]
            # HNAS - one time lookup
            # see if the client supports CHAP authentication and if
            # iscsi_secret has already been set, retrieve the secret if
            # available, otherwise generate and store
            if self.config['chap_enabled'] == 'True':
                # it may not exist, create and set secret
                if 'iscsi_secret' not in svc:
                    LOG.info(_("Retrieving secret for service: %s")
                             % label)

                    out = self.bend.get_targetsecret(self.config['hnas_cmd'],
                                                     self.config['mgmt_ip0'],
                                                     self.config['username'],
                                                     self.config['password'],
                                                     'cinder-' + label,
                                                     svc['hdp'])
                    svc['iscsi_secret'] = out
                    if svc['iscsi_secret'] == "":
                        svc['iscsi_secret'] = utils.generate_password()[0:15]
                        self.bend.set_targetsecret(self.config['hnas_cmd'],
                                                   self.config['mgmt_ip0'],
                                                   self.config['username'],
                                                   self.config['password'],
                                                   svc['iscsi_target'],
                                                   svc['hdp'],
                                                   svc['iscsi_secret'])

                        LOG.info("Set tgt CHAP secret for service: %s"
                                 % (label))
            else:
                # We set blank password when the client does not
                # support CHAP. Later on, if the client tries to create a new
                # target that does not exists in the backend, we check for this
                # value and use a temporary dummy password.
                if 'iscsi_secret' not in svc:
                    # Warns in the first time
                    LOG.info("CHAP authentication disabled")

                svc['iscsi_secret'] = ""

            if 'iscsi_target' not in svc:
                LOG.info(_("Retrieving target for service: %s") % label)

                out = self.bend.get_targetiqn(self.config['hnas_cmd'],
                                              self.config['mgmt_ip0'],
                                              self.config['username'],
                                              self.config['password'],
                                              'cinder-' + label,
                                              svc['hdp'],
                                              svc['iscsi_secret'])
                svc['iscsi_target'] = out

            self.config['services'][label] = svc

            service = (svc['iscsi_ip'], svc['iscsi_port'], svc['ctl'],
                       svc['port'], svc['hdp'], svc['iscsi_target'],
                       svc['iscsi_secret'])
        else:
            LOG.info(_("Available services: %s")
                     % self.config['services'].keys())
            LOG.error(_("No configuration found for service: %s")
                      % label)
            raise exception.ParameterNotFound(param=label)

        return service

    def _get_stats(self):
        """Get HDP stats from HNAS."""

        total_cap = 0
        total_used = 0
        out = self.bend.get_hdp_info(self.config['hnas_cmd'],
                                     self.config['mgmt_ip0'],
                                     self.config['username'],
                                     self.config['password'])

        for line in out.split('\n'):
            if 'HDP' in line:
                (hdp, size, _ign, used) = line.split()[1:5]  # in MB
                LOG.debug("stats: looking for: %s", hdp)
                if int(hdp) >= units.Ki:        # HNAS fsid
                    hdp = line.split()[11]
                if hdp in self.config['hdp'].keys():
                    total_cap += int(size)
                    total_used += int(used)

        LOG.info("stats: total: %d used: %d" % (total_cap, total_used))

        hnas_stat = {}
        hnas_stat['total_capacity_gb'] = int(total_cap / units.Ki)  # in GB
        hnas_stat['free_capacity_gb'] = \
            int((total_cap - total_used) / units.Ki)
        be_name = self.configuration.safe_get('volume_backend_name')
        hnas_stat["volume_backend_name"] = be_name or 'HDSISCSIDriver'
        hnas_stat["vendor_name"] = 'HDS'
        hnas_stat["driver_version"] = HDS_HNAS_ISCSI_VERSION
        hnas_stat["storage_protocol"] = 'iSCSI'
        hnas_stat['QoS_support'] = False
        hnas_stat['reserved_percentage'] = 0

        LOG.info(_("stats: stats: %s") % hnas_stat)
        return hnas_stat

    def _get_hdp_list(self):
        """Get HDPs from HNAS."""

        out = self.bend.get_hdp_info(self.config['hnas_cmd'],
                                     self.config['mgmt_ip0'],
                                     self.config['username'],
                                     self.config['password'])

        hdp_list = []
        for line in out.split('\n'):
            if 'HDP' in line:
                inf = line.split()
                if int(inf[1]) >= units.Ki:
                    # HDP fsids start at units.Ki (1024)
                    hdp_list.append(inf[11])
                else:
                    # HDP pools are 2-digits max
                    hdp_list.extend(inf[1:2])

        # returns a list of HDP IDs
        LOG.info(_("HDP list: %s") % hdp_list)
        return hdp_list

    def _check_hdp_list(self):
        """Verify HDPs in HNAS array.

        Verify that all HDPs specified in the configuration files actually
        exists on the storage.
        """

        hdpl = self._get_hdp_list()
        lst = self.config['hdp'].keys()

        for hdp in lst:
            if hdp not in hdpl:
                LOG.error(_("HDP not found: %s") % hdp)
                err = "HDP not found: " + hdp
                raise exception.ParameterNotFound(param=err)
            # status, verify corresponding status is Normal

    def _id_to_vol(self, volume_id):
        """Given the volume id, retrieve the volume object from database.
           :param volume_id: volume id string
        """

        vol = self.db.volume_get(self.context, volume_id)

        return vol

    def _update_vol_location(self, volume_id, loc):
        """Update the provider location.
           :param volume_id: volume id string
           :param loc: string provider location value
        """

        update = {'provider_location': loc}
        self.db.volume_update(self.context, volume_id, update)

    def check_for_setup_error(self):
        """Returns an error if prerequisites aren't met."""

        pass

    def do_setup(self, context):
        """Setup and verify HDS HNAS storage connection."""

        self.context = context
        (self.arid, self.hnas_name, self.lumax) = self._array_info_get()
        self._check_hdp_list()

        iscsi_info = self._get_iscsi_info()
        LOG.info(_("do_setup: %s") % iscsi_info)
        for svc in self.config['services'].keys():
            svc_ip = self.config['services'][svc]['iscsi_ip']
            if svc_ip in iscsi_info.keys():
                LOG.info(_("iSCSI portal found for service: %s") % svc_ip)
                self.config['services'][svc]['port'] = \
                    iscsi_info[svc_ip]['port']
                self.config['services'][svc]['ctl'] = iscsi_info[svc_ip]['ctl']
                self.config['services'][svc]['iscsi_port'] = \
                    iscsi_info[svc_ip]['iscsi_port']
            else:          # config iscsi address not found on device!
                LOG.error(_("iSCSI portal not found for service: %s") % svc_ip)
                raise exception.ParameterNotFound(param=svc_ip)

    def ensure_export(self, context, volume):
        pass

    def create_export(self, context, volume):
        """Create an export. Moved to initialize_connection.
           :param context:
           :param volume: volume reference
        """

        name = volume['name']
        LOG.debug("create_export %(name)s" % {'name': name})

        pass

    def remove_export(self, context, volume):
        """Disconnect a volume from an attached instance.
           :param context: context
           :param volume: dictionary volume referencej
        """

        provider = volume['provider_location']
        name = volume['name']
        LOG.debug("remove_export provider %(provider)s on %(name)s"
                  % {'provider': provider,
                     'name': name})

        pass

    def create_volume(self, volume):
        """Create a LU on HNAS.
           :param volume: ditctionary volume reference
        """

        service = self._get_service(volume)
        (_ip, _ipp, _ctl, _port, hdp, target, secret) = service
        out = self.bend.create_lu(self.config['hnas_cmd'],
                                  self.config['mgmt_ip0'],
                                  self.config['username'],
                                  self.config['password'],
                                  hdp,
                                  '%s' % (int(volume['size']) * units.Ki),
                                  volume['name'])

        LOG.info(_("create_volume: create_lu returns %s") % out)

        lun = self.arid + '.' + out.split()[1]
        sz = int(out.split()[5])

        # Example: 92210013.volume-44d7e29b-2aa4-4606-8bc4-9601528149fd
        LOG.info(_("LUN %(lun)s of size %(sz)s MB is created.")
                 % {'lun': lun, 'sz': sz})
        return {'provider_location': lun}

    def create_cloned_volume(self, dst, src):
        """Create a clone of a volume.
           :param dst: ditctionary destination volume reference
           :param src: ditctionary source volume reference
        """

        if src['size'] != dst['size']:
            msg = 'clone volume size mismatch'
            raise exception.VolumeBackendAPIException(data=msg)
        service = self._get_service(dst)
        (_ip, _ipp, _ctl, _port, hdp, target, secret) = service
        size = int(src['size']) * units.Ki
        source_vol = self._id_to_vol(src['id'])
        (arid, slun) = _loc_info(source_vol['provider_location'])['id_lu']
        out = self.bend.create_dup(self.config['hnas_cmd'],
                                   self.config['mgmt_ip0'],
                                   self.config['username'],
                                   self.config['password'],
                                   slun, hdp, '%s' % size,
                                   dst['name'])

        lun = self.arid + '.' + out.split()[1]
        size = int(out.split()[5])

        LOG.debug("LUN %(lun)s of size %(size)s MB is cloned."
                  % {'lun': lun,
                     'size': size})
        return {'provider_location': lun}

    def extend_volume(self, volume, new_size):
        """Extend an existing volume.

       :param volume: dictionary volume reference
       :param new_size: int size in GB to extend
       """

        service = self._get_service(volume)
        (_ip, _ipp, _ctl, _port, hdp, target, secret) = service
        (arid, lun) = _loc_info(volume['provider_location'])['id_lu']
        self.bend.extend_vol(self.config['hnas_cmd'],
                             self.config['mgmt_ip0'],
                             self.config['username'],
                             self.config['password'],
                             hdp, lun,
                             '%s' % (new_size * units.Ki),
                             volume['name'])

        LOG.info(_("LUN %(lun)s extended to %(size)s GB.")
                 % {'lun': lun, 'size': new_size})

    def delete_volume(self, volume):
        """Delete an LU on HNAS.
        :param volume: dictionary volume reference
        """

        prov_loc = volume['provider_location']
        if prov_loc is None:
            LOG.error("delete_vol: provider location empty.")
            return
        info = _loc_info(prov_loc)
        (arid, lun) = info['id_lu']
        if 'tgt' in info.keys():  # connected?
            LOG.info("delete lun loc %s" % info['tgt'])
            # loc = id.lun
            (_portal, iqn, loc, ctl, port, hlun) = info['tgt']
            self.bend.del_iscsi_conn(self.config['hnas_cmd'],
                                     self.config['mgmt_ip0'],
                                     self.config['username'],
                                     self.config['password'],
                                     ctl, iqn, hlun)

        name = self.hnas_name

        LOG.debug("delete lun %(lun)s on %(name)s"
                  % {'lun': lun,
                     'name': name})

        service = self._get_service(volume)
        (_ip, _ipp, _ctl, _port, hdp, target, secret) = service
        self.bend.delete_lu(self.config['hnas_cmd'],
                            self.config['mgmt_ip0'],
                            self.config['username'],
                            self.config['password'],
                            hdp, lun)

    def initialize_connection(self, volume, connector):
        """Map the created volume to connector['initiator'].

           :param volume: dictionary volume reference
           :param connector: dictionary connector reference
        """

        LOG.info("initialize volume %s connector %s" % (volume, connector))

        # connector[ip, host, wwnns, unititator, wwp/
        service = self._get_service(volume)
        (ip, ipp, ctl, port, _hdp, target, secret) = service
        info = _loc_info(volume['provider_location'])

        if 'tgt' in info.keys():  # spurious repeat connection
            # print info.keys()
            LOG.debug("initiate_conn: tgt already set %s" % info['tgt'])
        (arid, lun) = info['id_lu']
        loc = arid + '.' + lun
        # sps, use target if provided
        iqn = target
        out = self.bend.add_iscsi_conn(self.config['hnas_cmd'],
                                       self.config['mgmt_ip0'],
                                       self.config['username'],
                                       self.config['password'],
                                       lun, _hdp, port, iqn,
                                       connector['initiator'])

        hnas_portal = ip + ':' + ipp
        # sps need hlun, fulliqn
        hlun = out.split()[1]
        fulliqn = out.split()[13]
        tgt = hnas_portal + ',' + iqn + ',' + loc + ',' + ctl + ','
        tgt += port + ',' + hlun

        LOG.info("initiate: connection %s" % tgt)

        properties = {}
        properties['provider_location'] = tgt
        self._update_vol_location(volume['id'], tgt)
        properties['target_discovered'] = False
        properties['target_portal'] = hnas_portal
        properties['target_iqn'] = fulliqn
        properties['target_lun'] = hlun
        properties['volume_id'] = volume['id']
        properties['auth_username'] = connector['initiator']

        if self.config['chap_enabled'] == 'True':
            properties['auth_method'] = 'CHAP'
            properties['auth_password'] = secret

        return {'driver_volume_type': 'iscsi', 'data': properties}

    def terminate_connection(self, volume, connector, **kwargs):
        """Terminate a connection to a volume.

        :param volume: dictionary volume reference
        :param connector: dictionary connector reference
        """

        info = _loc_info(volume['provider_location'])
        if 'tgt' not in info.keys():  # spurious disconnection
            LOG.warn("terminate_conn: provider location empty.")
            return
        (arid, lun) = info['id_lu']
        (_portal, iqn, loc, ctl, port, hlun) = info['tgt']
        LOG.info("terminate: connection %s" % volume['provider_location'])
        self.bend.del_iscsi_conn(self.config['hnas_cmd'],
                                 self.config['mgmt_ip0'],
                                 self.config['username'],
                                 self.config['password'],
                                 ctl, iqn, hlun)
        self._update_vol_location(volume['id'], loc)

        return {'provider_location': loc}

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a volume from a snapshot.

        :param volume: dictionary volume reference
        :param snapshot: dictionary snapshot reference
        """

        size = int(snapshot['volume_size']) * units.Ki
        (arid, slun) = _loc_info(snapshot['provider_location'])['id_lu']
        service = self._get_service(volume)
        (_ip, _ipp, _ctl, _port, hdp, target, secret) = service
        out = self.bend.create_dup(self.config['hnas_cmd'],
                                   self.config['mgmt_ip0'],
                                   self.config['username'],
                                   self.config['password'],
                                   slun, hdp, '%s' % (size),
                                   volume['name'])
        lun = self.arid + '.' + out.split()[1]
        sz = int(out.split()[5])

        LOG.debug("LUN %(lun)s of size %(sz)s MB is created from snapshot."
                  % {'lun': lun, 'sz': sz})
        return {'provider_location': lun}

    def create_snapshot(self, snapshot):
        """Create a snapshot.
        :param snapshot: dictionary snapshot reference
        """

        source_vol = self._id_to_vol(snapshot['volume_id'])
        service = self._get_service(source_vol)
        (_ip, _ipp, _ctl, _port, hdp, target, secret) = service
        size = int(snapshot['volume_size']) * units.Ki
        (arid, slun) = _loc_info(source_vol['provider_location'])['id_lu']
        out = self.bend.create_dup(self.config['hnas_cmd'],
                                   self.config['mgmt_ip0'],
                                   self.config['username'],
                                   self.config['password'],
                                   slun, hdp,
                                   '%s' % (size),
                                   snapshot['name'])
        lun = self.arid + '.' + out.split()[1]
        size = int(out.split()[5])

        LOG.debug("LUN %(lun)s of size %(size)s MB is created."
                  % {'lun': lun, 'size': size})
        return {'provider_location': lun}

    def delete_snapshot(self, snapshot):
        """Delete a snapshot.

       :param snapshot: dictionary snapshot reference
       """

        loc = snapshot['provider_location']

        # to take care of spurious input
        if loc is None:
            # which could cause exception.
            return

        (arid, lun) = loc.split('.')
        source_vol = self._id_to_vol(snapshot['volume_id'])
        service = self._get_service(source_vol)
        (_ip, _ipp, _ctl, _port, hdp, target, secret) = service
        myid = self.arid

        if arid != myid:
            LOG.error(_('Array mismatch %(myid)s vs %(arid)s')
                      % {'myid': myid,
                         'arid': arid})
            msg = 'Array id mismatch in delete snapshot'
            raise exception.VolumeBackendAPIException(data=msg)
        self.bend.delete_lu(self.config['hnas_cmd'],
                            self.config['mgmt_ip0'],
                            self.config['username'],
                            self.config['password'],
                            hdp, lun)

        LOG.debug("LUN %s is deleted.", lun)
        return

    def get_volume_stats(self, refresh=False):
        """Get volume stats. If 'refresh', run update the stats first."""

        if refresh:
            self.driver_stats = self._get_stats()

        return self.driver_stats
