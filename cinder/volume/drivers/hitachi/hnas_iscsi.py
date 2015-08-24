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
import os
import six
from xml.etree import ElementTree as ETree

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import units


from cinder import exception
from cinder.i18n import _, _LE, _LI, _LW
from cinder import utils as cinder_utils
from cinder.volume import driver
from cinder.volume.drivers.hitachi import hnas_backend
from cinder.volume import utils
from cinder.volume import volume_types

HDS_HNAS_ISCSI_VERSION = '4.0.0'

LOG = logging.getLogger(__name__)

iSCSI_OPTS = [
    cfg.StrOpt('hds_hnas_iscsi_config_file',
               default='/opt/hds/hnas/cinder_iscsi_conf.xml',
               help='Configuration file for HDS iSCSI cinder plugin')]

CONF = cfg.CONF
CONF.register_opts(iSCSI_OPTS)

HNAS_DEFAULT_CONFIG = {'hnas_cmd': 'ssc',
                       'chap_enabled': 'True',
                       'ssh_port': '22'}
MAX_HNAS_ISCSI_TARGETS = 32


def factory_bend(drv_configs):
    return hnas_backend.HnasBackend(drv_configs)


def _loc_info(loc):
    """Parse info from location string."""

    LOG.info(_LI("Parse_loc: %s"), loc)
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
        LOG.info(_LI("%(element)s: %(val)s"),
                 {'element': element,
                  'val': val if element != 'password' else '***'})
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
    """Read hds driver specific xml config file."""

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
    opt_parameters = ['hnas_cmd', 'ssh_enabled', 'chap_enabled',
                      'cluster_admin_ip0']
    for req in opt_parameters:
        config[req] = _xml_read(root, req)

    if config['chap_enabled'] is None:
        config['chap_enabled'] = HNAS_DEFAULT_CONFIG['chap_enabled']

    if config['ssh_enabled'] == 'True':
        config['ssh_private_key'] = _xml_read(root, 'ssh_private_key', 'check')
        config['ssh_port'] = _xml_read(root, 'ssh_port')
        config['password'] = _xml_read(root, 'password')
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
        for arg in ['volume_type', 'hdp', 'iscsi_ip']:
            service[arg] = _xml_read(root, svc + '/' + arg, 'check')
        config['services'][service['volume_type']] = service
        config['hdp'][service['hdp']] = service['hdp']

    # at least one service required!
    if config['services'].keys() is None:
        raise exception.ParameterNotFound(param="No service found")

    return config


class HDSISCSIDriver(driver.ISCSIDriver):
    """HDS HNAS volume driver.

    Version 1.0.0: Initial driver version
    Version 2.2.0: Added support to SSH authentication
    Version 3.2.0: Added pool aware scheduling
                   Fixed concurrency errors
    Version 3.3.0: Fixed iSCSI target limitation error
    Version 4.0.0: Added manage/unmanage features
    """

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
        LOG.info(_LI("Backend type: %s"), self.type)
        self.bend = factory_bend(self.config)

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
                LOG.debug("portal: %(ip)s:%(ipp)s, CTL: %(ctl)s, port: %(pt)s",
                          {'ip': ip, 'ipp': ipp, 'ctl': ctl, 'pt': port})

        return conf

    def _get_service(self, volume):
        """Get the available service parameters

           Get the available service parametersfor a given volume using its
           type.
           :param volume: dictionary volume reference
           :return HDP related to the service
        """

        label = utils.extract_host(volume['host'], level='pool')
        LOG.info(_LI("Using service label: %s"), label)

        if label in self.config['services'].keys():
            svc = self.config['services'][label]
            return svc['hdp']
        else:
            LOG.info(_LI("Available services: %s."),
                     self.config['services'].keys())
            LOG.error(_LE("No configuration found for service: %s."), label)
            raise exception.ParameterNotFound(param=label)

    def _get_service_target(self, volume):
        """Get the available service parameters

           Get the available service parameters for a given volume using
           its type.
           :param volume: dictionary volume reference
        """

        hdp = self._get_service(volume)
        info = _loc_info(volume['provider_location'])
        (arid, lun_name) = info['id_lu']

        evsid = self.bend.get_evs(self.config['hnas_cmd'],
                                  self.config['mgmt_ip0'],
                                  self.config['username'],
                                  self.config['password'],
                                  hdp)
        svc_label = utils.extract_host(volume['host'], level='pool')
        svc = self.config['services'][svc_label]

        LOG.info(_LI("_get_service_target hdp: %s."), hdp)
        LOG.info(_LI("config[services]: %s."), self.config['services'])

        mapped, lunid, tgt = self.bend.check_lu(self.config['hnas_cmd'],
                                                self.config['mgmt_ip0'],
                                                self.config['username'],
                                                self.config['password'],
                                                lun_name, hdp)

        LOG.info(_LI("Target is %(map)s! Targetlist = %(tgtl)s."),
                 {'map': "mapped" if mapped else "not mapped", 'tgtl': tgt})

        # The volume is already mapped to a LUN, so no need to create any
        # targets
        if mapped:
            service = (svc['iscsi_ip'], svc['iscsi_port'], svc['ctl'],
                       svc['port'], hdp, tgt['alias'], tgt['secret'])
            return service

        # Each EVS can have up to 32 targets. Each target can have up to 32
        # LUNs attached and have the name format 'evs<id>-tgt<0-N>'. We run
        # from the first 'evs1-tgt0' until we find a target that is not already
        # created in the BE or is created but have slots to place new targets.
        found_tgt = False
        for i in range(0, MAX_HNAS_ISCSI_TARGETS):
            tgt_alias = 'evs' + evsid + '-tgt' + six.text_type(i)
            # TODO(erlon): we need to go to the BE 32 times here
            tgt_exist, tgt = self.bend.check_target(self.config['hnas_cmd'],
                                                    self.config['mgmt_ip0'],
                                                    self.config['username'],
                                                    self.config['password'],
                                                    hdp, tgt_alias)
            if tgt_exist and len(tgt['luns']) < 32 or not tgt_exist:
                # Target exists and has free space or, target does not exist
                # yet. Proceed and use the target or create a target using this
                # name.
                found_tgt = True
                break

        # If we've got here and found_tgt is not True, we run out of targets,
        # raise and go away.
        if not found_tgt:
            LOG.error(_LE("No more targets avaliable."))
            raise exception.NoMoreTargets(param=tgt_alias)

        LOG.info(_LI("Using target label: %s."), tgt_alias)

        # Check if we have a secret stored for this target so we don't have to
        # go to BE on every query
        if 'targets' not in self.config.keys():
            self.config['targets'] = {}

        if tgt_alias not in self.config['targets'].keys():
            self.config['targets'][tgt_alias] = {}

        tgt_info = self.config['targets'][tgt_alias]

        # HNAS - one time lookup
        # see if the client supports CHAP authentication and if
        # iscsi_secret has already been set, retrieve the secret if
        # available, otherwise generate and store
        if self.config['chap_enabled'] == 'True':
            # It may not exist, create and set secret.
            if 'iscsi_secret' not in tgt_info.keys():
                LOG.info(_LI("Retrieving secret for service: %s."),
                         tgt_alias)

                out = self.bend.get_targetsecret(self.config['hnas_cmd'],
                                                 self.config['mgmt_ip0'],
                                                 self.config['username'],
                                                 self.config['password'],
                                                 tgt_alias, hdp)
                tgt_info['iscsi_secret'] = out
                if tgt_info['iscsi_secret'] == "":
                    randon_secret = utils.generate_password()[0:15]
                    tgt_info['iscsi_secret'] = randon_secret
                    self.bend.set_targetsecret(self.config['hnas_cmd'],
                                               self.config['mgmt_ip0'],
                                               self.config['username'],
                                               self.config['password'],
                                               tgt_alias, hdp,
                                               tgt_info['iscsi_secret'])

                    LOG.info(_LI("Set tgt CHAP secret for service: %s."),
                             tgt_alias)
        else:
            # We set blank password when the client does not
            # support CHAP. Later on, if the client tries to create a new
            # target that does not exists in the backend, we check for this
            # value and use a temporary dummy password.
            if 'iscsi_secret' not in tgt_info.keys():
                # Warns in the first time
                LOG.info(_LI("CHAP authentication disabled."))

            tgt_info['iscsi_secret'] = ""

        if 'tgt_iqn' not in tgt_info:
            LOG.info(_LI("Retrieving target for service: %s."), tgt_alias)

            out = self.bend.get_targetiqn(self.config['hnas_cmd'],
                                          self.config['mgmt_ip0'],
                                          self.config['username'],
                                          self.config['password'],
                                          tgt_alias, hdp,
                                          tgt_info['iscsi_secret'])
            tgt_info['tgt_iqn'] = out

        self.config['targets'][tgt_alias] = tgt_info

        service = (svc['iscsi_ip'], svc['iscsi_port'], svc['ctl'],
                   svc['port'], hdp, tgt_alias, tgt_info['iscsi_secret'])

        return service

    def _get_stats(self):
        """Get HDP stats from HNAS."""

        hnas_stat = {}
        be_name = self.configuration.safe_get('volume_backend_name')
        hnas_stat["volume_backend_name"] = be_name or 'HDSISCSIDriver'
        hnas_stat["vendor_name"] = 'HDS'
        hnas_stat["driver_version"] = HDS_HNAS_ISCSI_VERSION
        hnas_stat["storage_protocol"] = 'iSCSI'
        hnas_stat['reserved_percentage'] = 0

        for pool in self.pools:
            out = self.bend.get_hdp_info(self.config['hnas_cmd'],
                                         self.config['mgmt_ip0'],
                                         self.config['username'],
                                         self.config['password'],
                                         pool['hdp'])

            LOG.debug('Query for pool %(pool)s: %(out)s.',
                      {'pool': pool['pool_name'], 'out': out})

            (hdp, size, _ign, used) = out.split()[1:5]  # in MB
            pool['total_capacity_gb'] = int(size) / units.Ki
            pool['free_capacity_gb'] = (int(size) - int(used)) / units.Ki
            pool['allocated_capacity_gb'] = int(used) / units.Ki
            pool['QoS_support'] = 'False'
            pool['reserved_percentage'] = 0

        hnas_stat['pools'] = self.pools

        LOG.info(_LI("stats: stats: %s."), hnas_stat)
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
        LOG.info(_LI("HDP list: %s"), hdp_list)
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
                LOG.error(_LE("HDP not found: %s"), hdp)
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

        service_list = self.config['services'].keys()
        for svc in service_list:
            svc = self.config['services'][svc]
            pool = {}
            pool['pool_name'] = svc['volume_type']
            pool['service_label'] = svc['volume_type']
            pool['hdp'] = svc['hdp']

            self.pools.append(pool)

        LOG.info(_LI("Configured pools: %s"), self.pools)

        iscsi_info = self._get_iscsi_info()
        LOG.info(_LI("do_setup: %s"), iscsi_info)
        for svc in self.config['services'].keys():
            svc_ip = self.config['services'][svc]['iscsi_ip']
            if svc_ip in iscsi_info.keys():
                LOG.info(_LI("iSCSI portal found for service: %s"), svc_ip)
                self.config['services'][svc]['port'] = \
                    iscsi_info[svc_ip]['port']
                self.config['services'][svc]['ctl'] = iscsi_info[svc_ip]['ctl']
                self.config['services'][svc]['iscsi_port'] = \
                    iscsi_info[svc_ip]['iscsi_port']
            else:          # config iscsi address not found on device!
                LOG.error(_LE("iSCSI portal not found "
                              "for service: %s"), svc_ip)
                raise exception.ParameterNotFound(param=svc_ip)

    def ensure_export(self, context, volume):
        pass

    def create_export(self, context, volume, connector):
        """Create an export. Moved to initialize_connection.

        :param context:
        :param volume: volume reference
        """

        name = volume['name']
        LOG.debug("create_export %s", name)

        pass

    def remove_export(self, context, volume):
        """Disconnect a volume from an attached instance.

        :param context: context
        :param volume: dictionary volume reference
        """

        provider = volume['provider_location']
        name = volume['name']
        LOG.debug("remove_export provider %(provider)s on %(name)s",
                  {'provider': provider, 'name': name})

        pass

    def create_volume(self, volume):
        """Create a LU on HNAS.

        :param volume: dictionary volume reference
        """

        hdp = self._get_service(volume)
        out = self.bend.create_lu(self.config['hnas_cmd'],
                                  self.config['mgmt_ip0'],
                                  self.config['username'],
                                  self.config['password'],
                                  hdp,
                                  '%s' % (int(volume['size']) * units.Ki),
                                  volume['name'])

        LOG.info(_LI("create_volume: create_lu returns %s"), out)

        lun = self.arid + '.' + out.split()[1]
        sz = int(out.split()[5])

        # Example: 92210013.volume-44d7e29b-2aa4-4606-8bc4-9601528149fd
        LOG.info(_LI("LUN %(lun)s of size %(sz)s MB is created."),
                 {'lun': lun, 'sz': sz})
        return {'provider_location': lun}

    def create_cloned_volume(self, dst, src):
        """Create a clone of a volume.

        :param dst: ditctionary destination volume reference
        :param src: ditctionary source volume reference
        """

        if src['size'] != dst['size']:
            msg = 'clone volume size mismatch'
            raise exception.VolumeBackendAPIException(data=msg)
        hdp = self._get_service(dst)
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

        LOG.debug("LUN %(lun)s of size %(size)s MB is cloned.",
                  {'lun': lun, 'size': size})
        return {'provider_location': lun}

    def extend_volume(self, volume, new_size):
        """Extend an existing volume.

       :param volume: dictionary volume reference
       :param new_size: int size in GB to extend
       """

        hdp = self._get_service(volume)
        (arid, lun) = _loc_info(volume['provider_location'])['id_lu']
        self.bend.extend_vol(self.config['hnas_cmd'],
                             self.config['mgmt_ip0'],
                             self.config['username'],
                             self.config['password'],
                             hdp, lun,
                             '%s' % (new_size * units.Ki),
                             volume['name'])

        LOG.info(_LI("LUN %(lun)s extended to %(size)s GB."),
                 {'lun': lun, 'size': new_size})

    def delete_volume(self, volume):
        """Delete an LU on HNAS.

        :param volume: dictionary volume reference
        """

        prov_loc = volume['provider_location']
        if prov_loc is None:
            LOG.error(_LE("delete_vol: provider location empty."))
            return
        info = _loc_info(prov_loc)
        (arid, lun) = info['id_lu']
        if 'tgt' in info.keys():  # connected?
            LOG.info(_LI("delete lun loc %s"), info['tgt'])
            # loc = id.lun
            (_portal, iqn, loc, ctl, port, hlun) = info['tgt']
            self.bend.del_iscsi_conn(self.config['hnas_cmd'],
                                     self.config['mgmt_ip0'],
                                     self.config['username'],
                                     self.config['password'],
                                     ctl, iqn, hlun)

        name = self.hnas_name

        LOG.debug("delete lun %(lun)s on %(name)s", {'lun': lun, 'name': name})

        hdp = self._get_service(volume)
        self.bend.delete_lu(self.config['hnas_cmd'],
                            self.config['mgmt_ip0'],
                            self.config['username'],
                            self.config['password'],
                            hdp, lun)

    @cinder_utils.synchronized('volume_mapping')
    def initialize_connection(self, volume, connector):
        """Map the created volume to connector['initiator'].

           :param volume: dictionary volume reference
           :param connector: dictionary connector reference
        """

        LOG.info(_LI("initialize volume %(vol)s connector %(conn)s"),
                 {'vol': volume, 'conn': connector})

        # connector[ip, host, wwnns, unititator, wwp/

        service_info = self._get_service_target(volume)
        (ip, ipp, ctl, port, _hdp, tgtalias, secret) = service_info
        info = _loc_info(volume['provider_location'])

        if 'tgt' in info.keys():  # spurious repeat connection
            # print info.keys()
            LOG.debug("initiate_conn: tgt already set %s", info['tgt'])
        (arid, lun_name) = info['id_lu']
        loc = arid + '.' + lun_name
        # sps, use target if provided
        try:
            out = self.bend.add_iscsi_conn(self.config['hnas_cmd'],
                                           self.config['mgmt_ip0'],
                                           self.config['username'],
                                           self.config['password'],
                                           lun_name, _hdp, port, tgtalias,
                                           connector['initiator'])
        except processutils.ProcessExecutionError:
            msg = _("Error attaching volume %s. "
                    "Target limit might be reached!") % volume['id']
            raise exception.ISCSITargetAttachFailed(message=msg)

        hnas_portal = ip + ':' + ipp
        # sps need hlun, fulliqn
        hlun = out.split()[1]
        fulliqn = out.split()[13]
        tgt = hnas_portal + ',' + tgtalias + ',' + loc + ',' + ctl + ','
        tgt += port + ',' + hlun

        LOG.info(_LI("initiate: connection %s"), tgt)

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

        conn_info = {'driver_volume_type': 'iscsi', 'data': properties}
        LOG.debug("initialize_connection: conn_info: %s.", conn_info)
        return conn_info

    @cinder_utils.synchronized('volume_mapping')
    def terminate_connection(self, volume, connector, **kwargs):
        """Terminate a connection to a volume.

        :param volume: dictionary volume reference
        :param connector: dictionary connector reference
        """

        info = _loc_info(volume['provider_location'])
        if 'tgt' not in info.keys():  # spurious disconnection
            LOG.warning(_LW("terminate_conn: provider location empty."))
            return
        (arid, lun) = info['id_lu']
        (_portal, tgtalias, loc, ctl, port, hlun) = info['tgt']
        LOG.info(_LI("terminate: connection %s"), volume['provider_location'])
        self.bend.del_iscsi_conn(self.config['hnas_cmd'],
                                 self.config['mgmt_ip0'],
                                 self.config['username'],
                                 self.config['password'],
                                 ctl, tgtalias, hlun)
        self._update_vol_location(volume['id'], loc)

        return {'provider_location': loc}

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a volume from a snapshot.

        :param volume: dictionary volume reference
        :param snapshot: dictionary snapshot reference
        """

        size = int(snapshot['volume_size']) * units.Ki
        (arid, slun) = _loc_info(snapshot['provider_location'])['id_lu']
        hdp = self._get_service(volume)
        out = self.bend.create_dup(self.config['hnas_cmd'],
                                   self.config['mgmt_ip0'],
                                   self.config['username'],
                                   self.config['password'],
                                   slun, hdp, '%s' % (size),
                                   volume['name'])
        lun = self.arid + '.' + out.split()[1]
        sz = int(out.split()[5])

        LOG.debug("LUN %(lun)s of size %(sz)s MB is created from snapshot.",
                  {'lun': lun, 'sz': sz})
        return {'provider_location': lun}

    def create_snapshot(self, snapshot):
        """Create a snapshot.

        :param snapshot: dictionary snapshot reference
        """

        source_vol = self._id_to_vol(snapshot['volume_id'])
        hdp = self._get_service(source_vol)
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

        LOG.debug("LUN %(lun)s of size %(size)s MB is created.",
                  {'lun': lun, 'size': size})
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
        hdp = self._get_service(source_vol)
        myid = self.arid

        if arid != myid:
            LOG.error(_LE("Array mismatch %(myid)s vs %(arid)s"),
                      {'myid': myid, 'arid': arid})
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
                    pass
                return metadata['service_label']

    def _check_pool_and_fs(self, volume, fs_label):
        """Validation of the pool and filesystem.

        Checks if the file system for the volume-type chosen matches the
        one passed in the volume reference. Also, checks if the pool
        for the volume type matches the pool for the host passed.

        :param volume: Reference to the volume.
        :param fs_label: Label of the file system.
        """
        pool_from_vol_type = self.get_pool(volume)

        pool_from_host = utils.extract_host(volume['host'], level='pool')

        if self.config['services'][pool_from_vol_type]['hdp'] != fs_label:
            msg = (_("Failed to manage existing volume because the pool of "
                     "the volume type chosen does not match the file system "
                     "passed in the volume reference."),
                   {'File System passed': fs_label,
                    'File System for volume type':
                        self.config['services'][pool_from_vol_type]['hdp']})
            raise exception.ManageExistingVolumeTypeMismatch(reason=msg)

        if pool_from_host != pool_from_vol_type:
            msg = (_("Failed to manage existing volume because the pool of "
                     "the volume type chosen does not match the pool of "
                     "the host."),
                   {'Pool of the volume type': pool_from_vol_type,
                    'Pool of the host': pool_from_host})
            raise exception.ManageExistingVolumeTypeMismatch(reason=msg)

    def _get_info_from_vol_ref(self, vol_ref):
        """Gets information from the volume reference.

        Returns the information (File system and volume name) taken from
        the volume reference.

        :param vol_ref: existing volume to take under management
        """
        vol_info = vol_ref.strip().split('/')

        if len(vol_info) == 2 and '' not in vol_info:
            fs_label = vol_info[0]
            vol_name = vol_info[1]

            return fs_label, vol_name
        else:
            msg = (_("The reference to the volume in the backend should have "
                     "the format file_system/volume_name (volume_name cannot "
                     "contain '/')"))
            raise exception.ManageExistingInvalidReference(
                existing_ref=vol_ref, reason=msg)

    def manage_existing_get_size(self, volume, existing_vol_ref):
        """Gets the size to manage_existing.

        Returns the size of volume to be managed by manage_existing.

        :param volume:           cinder volume to manage
        :param existing_vol_ref: existing volume to take under management
        """
        # Check that the reference is valid.
        if 'source-name' not in existing_vol_ref:
            reason = _('Reference must contain source-name element.')
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_vol_ref, reason=reason)

        ref_name = existing_vol_ref['source-name']
        fs_label, vol_name = self._get_info_from_vol_ref(ref_name)

        LOG.debug("File System: %(fs_label)s "
                  "Volume name: %(vol_name)s.",
                  {'fs_label': fs_label, 'vol_name': vol_name})

        vol_name = "'{}'".format(vol_name)

        lu_info = self.bend.get_existing_lu_info(self.config['hnas_cmd'],
                                                 self.config['mgmt_ip0'],
                                                 self.config['username'],
                                                 self.config['password'],
                                                 fs_label, vol_name)

        if fs_label in lu_info:
            aux = lu_info.split('\n')[3]
            size = aux.split(':')[1]
            size_unit = size.split(' ')[2]

            if size_unit == 'TB':
                return int(size.split(' ')[1]) * units.k
            else:
                return int(size.split(' ')[1])
        else:
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_vol_ref,
                reason=_('Volume not found on configured storage backend. '
                         'If your volume name contains "/", please rename it '
                         'and try to manage again.'))

    def manage_existing(self, volume, existing_vol_ref):
        """Manages an existing volume.

        The specified Cinder volume is to be taken into Cinder management.
        The driver will verify its existence and then rename it to the
        new Cinder volume name. It is expected that the existing volume
        reference is a File System and some volume_name;
        e.g., openstack/vol_to_manage

        :param volume:           cinder volume to manage
        :param existing_vol_ref: driver-specific information used to identify a
                                 volume
        """
        ref_name = existing_vol_ref['source-name']
        fs_label, vol_name = self._get_info_from_vol_ref(ref_name)

        LOG.debug("Asked to manage ISCSI volume %(vol)s, with vol "
                  "ref %(ref)s.", {'vol': volume['id'],
                                   'ref': existing_vol_ref['source-name']})

        self._check_pool_and_fs(volume, fs_label)

        vol_name = "'{}'".format(vol_name)

        self.bend.rename_existing_lu(self.config['hnas_cmd'],
                                     self.config['mgmt_ip0'],
                                     self.config['username'],
                                     self.config['password'], fs_label,
                                     volume['name'], vol_name)

        LOG.info(_LI("Set newly managed Cinder volume name to %(name)s."),
                 {'name': volume['name']})

        lun = self.arid + '.' + volume['name']

        return {'provider_location': lun}

    def unmanage(self, volume):
        """Unmanages a volume from cinder.

        Removes the specified volume from Cinder management.
        Does not delete the underlying backend storage object. A log entry
        will be made to notify the Admin that the volume is no longer being
        managed.

        :param volume: cinder volume to unmanage
        """
        svc = self._get_service(volume)

        new_name = 'unmanage-' + volume['name']
        vol_path = svc + '/' + volume['name']

        self.bend.rename_existing_lu(self.config['hnas_cmd'],
                                     self.config['mgmt_ip0'],
                                     self.config['username'],
                                     self.config['password'], svc, new_name,
                                     volume['name'])

        LOG.info(_LI("Cinder ISCSI volume with current path %(path)s is "
                     "no longer being managed. The new name is %(unm)s."),
                 {'path': vol_path, 'unm': new_name})
