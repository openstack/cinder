# Copyright (c) 2014 Fusion-io, Inc.
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
Fusion-io Driver for the ioControl Hybrid storage subsystem
"""

import copy
import hashlib
import json
import random
import uuid

from oslo.config import cfg
import requests

from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import log as logging
from cinder.openstack.common import loopingcall
from cinder.openstack.common import units
from cinder.volume.drivers.san.san import SanISCSIDriver
from cinder.volume import qos_specs
from cinder.volume import volume_types

LOG = logging.getLogger(__name__)

fusionio_iocontrol_opts = [
    cfg.IntOpt('fusionio_iocontrol_targetdelay',
               default=5,
               help='amount of time wait for iSCSI target to come online'),
    cfg.IntOpt('fusionio_iocontrol_retry',
               default=3,
               help='number of retries for GET operations'),
    cfg.BoolOpt('fusionio_iocontrol_verify_cert',
                default=True,
                help='verify the array certificate on each transaction'), ]

CONF = cfg.CONF
CONF.register_opts(fusionio_iocontrol_opts)


class FIOconnection(object):
    """Connection class for connection to ioControl array."""

    APIVERSION = '1.1'

    def _complete_uri(self, suburi=None, ver='1', loc='en'):
        uri = "https://" + self.array_addr + "/API/"
        if ver is not None:
            uri = uri + ver + "/"
        if loc is not None:
            uri = uri + loc + "/"
        if suburi is not None:
            uri = uri + suburi
        return uri

    def __init__(self, array_addr, array_login, array_passwd, retry, verify):
        self.client = "client=openstack"
        self.defhdrs = {"User-Agent": "OpenStack-agent",
                        "Content-Type": "application/json"}
        self.array_addr = array_addr
        self.array_login = array_login
        self.hashpass = hashlib.md5()
        self.hashpass.update(array_passwd)
        self.login_content = ("username=" + array_login + "&hash=" +
                              self.hashpass.hexdigest())
        self.retry = retry
        self.verify = verify
        # check the version of the API on the array. We only support 1.1
        # for now.
        resp = requests.get(url=("https://" + array_addr + "/AUTH/Version"),
                            headers=self.defhdrs, verify=self.verify)
        resp.raise_for_status()
        dictresp = resp.json()
        if dictresp["Version"] != self.APIVERSION:
            msg = _("FIO ioControl API version not supported")
            raise exception.VolumeDriverException(message=msg)
        LOG.debug('FIO Connection initialized to %s' % array_addr)

    def _create_session(self):
        # get the session id
        res = requests.post(url=("https://" + self.array_addr +
                                 "/AUTH/SESSION"),
                            data=self.client,
                            headers=self.defhdrs,
                            verify=self.verify)
        res.raise_for_status()
        result = res.json()
        session_key = result["id"]
        hdrs = copy.deepcopy(self.defhdrs)
        hdrs["Cookie"] = "session=" + session_key
        # Authenticate the session
        res = requests.put(url=("https://" + self.array_addr +
                                "/AUTH/SESSION/" + session_key),
                           data=self.login_content,
                           headers=self.defhdrs,
                           verify=self.verify)
        try:
            res.raise_for_status()
        except requests.exceptions:
            self._delete_session(hdrs)
            raise
        result = res.json()
        if result["Status"] != 1:
            # Authentication error delete the session ID
            self._delete_session(hdrs)
            msg = (_('FIO ioControl Authentication Error: %s') % (result))
            raise exception.VolumeDriverException(message=msg)
        return hdrs

    def _delete_session(self, hdrs):
        session = hdrs["Cookie"].split('=')[1]
        requests.delete(url=("https://" + self.array_addr +
                             "/AUTH/SESSION/" + session),
                        headers=self.defhdrs,
                        verify=self.verify)

    def get(self, suburl):
        session_hdrs = self._create_session()
        trynum = 0
        try:
            while (trynum < self.retry):
                trynum += 1
                res = requests.get(url=self._complete_uri(suburl),
                                   headers=session_hdrs,
                                   verify=self.verify)
                res.raise_for_status()
                # work around a bug whereby bad json is returned by the array
                try:
                    jres = res.json()
                    break
                except Exception:
                    if (trynum == self.retry):
                        # this shouldn't happen, but check for it
                        msg = (_('FIO ioControl persistent json Error.'))
                        raise exception.VolumeDriverException(message=msg)
                    pass
        finally:
            # deal with the bad result here
            self._delete_session(session_hdrs)
        return jres

    def put(self, suburl, content=None):
        session_hdrs = self._create_session()
        try:
            result = requests.put(url=self._complete_uri(suburl),
                                  data=json.dumps(content,
                                                  sort_keys=True),
                                  headers=session_hdrs,
                                  verify=self.verify)
            result.raise_for_status()
        finally:
            self._delete_session(session_hdrs)
        return

    def post(self, suburl, content=None):
        session_hdrs = self._create_session()
        try:
            result = requests.post(url=self._complete_uri(suburl),
                                   data=json.dumps(content,
                                                   sort_keys=True),
                                   headers=session_hdrs,
                                   verify=self.verify)
            result.raise_for_status()
        finally:
            self._delete_session(session_hdrs)
        return

    def delete(self, suburl,):
        session_hdrs = self._create_session()
        try:
            result = requests.delete(url=self._complete_uri(suburl),
                                     headers=session_hdrs,
                                     verify=self.verify)
            result.raise_for_status()
        finally:
            self._delete_session(session_hdrs)
        return


class FIOioControlDriver(SanISCSIDriver):
    """Fusion-io ioControl iSCSI volume driver."""

    VERSION = '1.0.0'

    def __init__(self, *args, **kwargs):
        super(FIOioControlDriver, self).__init__(*args, **kwargs)
        LOG.debug('FIO __init__ w/ %s' % kwargs)
        self.configuration.append_config_values(fusionio_iocontrol_opts)
        self.fio_qos_dict = {}

    def _get_volume_by_name(self, name):
        result = self.conn.get("TierStore/Volumes/by-id/")
        vol = [x for x in result
               if x['Name'] == name]
        if len(vol) == 1:
            return vol[0]
        elif len(vol) == 0:
            raise exception.VolumeNotFound(name)
        else:
            msg = (_("FIO _get_volume_by_name Error: %(name)s, %(len)s") %
                   {'name': name,
                    'len': len(vol)})
            raise exception.VolumeDriverException(msg)

    def _get_acl_by_name(self, name):
        result = self.conn.get("TierStore/ACLGroup/by-id/")
        acl = [x for x in result
               if x['GroupName'] == name]
        if len(acl) == 1:
            return acl[0]
        elif len(acl) == 0:
            return []
        else:
            msg = (_("FIO _get_acl_by_name Error: %(name)s, %(len)s") %
                   {'name': name,
                    'len': len(acl), })
            raise exception.VolumeDriverException(message=msg)

    def _get_snapshot_by_name(self, name):
        result = self.conn.get("TierStore/Snapshots/by-id/")
        snap = [x for x in result
                if x['Name'] == name]
        if len(snap) == 1:
            return snap[0]
        elif len(snap) == 0:
            raise exception.SnapshotNotFound(name)
        else:
            msg = (_("FIO _get_snapshot_by_name Error: %(name)s, %(len)s") %
                   {'name': name,
                    'len': len(snap), })
            raise exception.VolumeDriverException(message=msg)

    def _set_qos_presets(self, volume):
        valid_presets = self.fio_qos_dict.keys()

        presets = [i.value for i in volume.get('volume_metadata')
                   if i.key == 'fio-qos' and i.value in valid_presets]
        if len(presets) > 0:
            if len(presets) > 1:
                LOG.warning(_('More than one valid preset was '
                              'detected, using %s') % presets[0])
            return self.fio_qos_dict[presets[0]]

    def _set_qos_by_volume_type(self, type_id):
        valid_presets = self.fio_qos_dict.keys()
        volume_type = volume_types.get_volume_type(ctxt=None,
                                                   id=type_id)
        qos_specs_id = volume_type.get('qos_specs_id')
        specs = volume_type.get('extra_specs')
        if qos_specs_id is not None:
            kvs = qos_specs.get_qos_specs(ctxt=None,
                                          id=qos_specs_id)['specs']
        else:
            kvs = specs
        for key, value in kvs.iteritems():
            if ':' in key:
                fields = key.split(':')
                key = fields[1]
            if 'fio-qos' in key:
                if value in valid_presets:
                    return self.fio_qos_dict[value]

    def do_setup(self, context):
        LOG.debug('FIO do_setup() called')
        required_flags = ['san_ip',
                          'san_login',
                          'san_password', ]
        for flag in required_flags:
            if not getattr(self.configuration, flag, None):
                raise exception.InvalidInput(reason=_('%s is not set') % flag)
        if not (self.configuration.san_ip and
                self.configuration.san_login and
                self.configuration.san_password):
            raise exception.InvalidInput(
                reason=_('All of '
                         'san_ip '
                         'san_login '
                         'san_password '
                         'must be set'))
        self.conn = FIOconnection(self.configuration.san_ip,
                                  self.configuration.san_login,
                                  self.configuration.san_password,
                                  self.configuration.fusionio_iocontrol_retry,
                                  (self.configuration.
                                   fusionio_iocontrol_verify_cert))
        result = self.conn.get("TierStore/Policies/by-id/")
        for x in result:
            self.fio_qos_dict[x['Name']] = x['id']

    def check_for_setup_error(self):
        pass

    def create_volume(self, volume):
        LOG.debug('FIO create_volume() called: %s' % (volume['id']))
        # Roughly we pick the less full pool.
        # Someday change the default the policy to be configurable
        qos = self.fio_qos_dict['Policy 5']
        result = self.conn.get("TierStore/Pools/by-id/")
        poola = result[0]['PagingTotalMB'] - result[0]['ExportedVolumeMB']
        poolb = result[1]['PagingTotalMB'] - result[1]['ExportedVolumeMB']
        if poola >= poolb:
            pool = result[0]['id']
        else:
            pool = result[1]['id']
        if volume.get('volume_metadata')is not None:
            qos = self._set_qos_presets(volume)

        type_id = volume['volume_type_id']
        if type_id is not None:
            qos = self._set_qos_by_volume_type(type_id)

        cmd = {"Size": int(volume['size']) * units.Gi,
               "PolicyUUID": qos,
               "PoolUUID": pool,
               "Name": volume['id'], }
        self.conn.post("TierStore/Volumes/by-id/", cmd)
        LOG.debug(('FIO create_vol(%(id)s) on %(pool)s vals %(poola)s '
                   '%(poolb)s') %
                  {'id': volume['id'],
                   'pool': pool,
                   'poola': poola,
                   'poolb': poolb})

    def delete_volume(self, volume):
        LOG.debug('FIO delete_volume() volID %s' % (volume['id']))
        vol = self._get_volume_by_name(volume['id'])
        self.conn.delete("TierStore/Volumes/by-id/" + vol['id'])

    def ensure_export(self, context, volume):
        pass

    def create_export(self, context, volume):
        pass

    def remove_export(self, context, volume):
        pass

    def initialize_connection(self, volume, connector):
        LOG.debug('FIO init_connection() w/ %(id)s and %(conn)s' %
                  {'id': volume['id'],
                   'conn': connector['initiator']})
        # setup the access group each initiator will go in a unique access
        # group.
        # TODO(ebalduf) implement w/ CHAP
        volumedata = self._get_volume_by_name(volume['id'])
        cmd = {"GroupName": connector['initiator'],
               "InitiatorList": [connector['initiator']]}
        self.conn.post("TierStore/ACLGroup/by-id/", cmd)

        acl = self._get_acl_by_name(connector['initiator'])
        if acl is not []:
            cmd = {"AclGroupList": [str(acl['id'])], }
            self.conn.put("TierStore/Volumes/by-id/" + volumedata['id'], cmd)
        else:
            # this should never happen, but check for it in case
            msg = _('FIO: ACL does not exist!')
            raise exception.VolumeDriverException(message=msg)
        # handle the fact that the Application of the ACL to the volume
        # is asynchronous.  In the future we'll add a call back to the API

        def _wait_routine():
            # unfortunately, the array API at this time doesn't have any
            # way to poll.  In the future we will add that ability and
            # this routine is where were will poll for ready.
            if self._looping_count == 0:
                self._looping_count += 1
            else:
                raise loopingcall.LoopingCallDone()

        # time.sleep(self.configuration.fusionio_iocontrol_targetdelay)
        self._looping_count = 0
        timer = loopingcall.FixedIntervalLoopingCall(_wait_routine)
        timer.start(
            interval=self.configuration.fusionio_iocontrol_targetdelay).wait()
        volumedata = self._get_volume_by_name(volume['id'])

        properties = {}
        properties['target_discovered'] = False
        properties['target_iqn'] = volumedata['IQN']
        properties['target_lun'] = 0
        properties['volume_id'] = volume['id']

        result = self.conn.get("System/Network/by-id/")

        # probably way too complicated, but pick a random network interface
        # on the controller this LUN is owned by
        networksinfo = [x for x in result
                        if x['OperationalState'] == 'up'
                        if x['IsManagementPort'] is not True
                        if x['IsReplicationPort'] is not True
                        if x['ControllerUID'] ==
                        volumedata['CurrentOwnerUUID']]
        LOG.debug('NetworkInfo %s' % (networksinfo))
        if len(networksinfo):
            ipaddr = (networksinfo[random.randint(0, len(networksinfo) - 1)]
                      ['NetworkAddress'])
        else:
            msg = _('No usable Networks found: %s') % (result)
            raise exception.VolumeDriverException(message=msg)
        properties['target_portal'] = unicode('%s:%s' % (ipaddr, '3260'))

        auth = volume['provider_auth']
        if auth:
            (auth_method, auth_username, auth_secret) = auth.split()

            properties['auth_method'] = auth_method
            properties['auth_username'] = auth_username
            properties['auth_password'] = auth_secret

        LOG.debug('Result from initialize connection: %s' % properties)
        return {
            'driver_volume_type': 'iscsi',
            'data': properties,
        }

    def create_snapshot(self, snapshot):
        LOG.debug(('FIO create_snapshot() vol ID: %(volID)s snapID '
                   '%(snapID)s') %
                  {'volID': snapshot['volume_id'],
                   'snapID': snapshot['id']})
        vol = self._get_volume_by_name(snapshot['volume_id'])
        cmd = {"VolumeUUID": vol['id'],
               "Name": snapshot['id'], }
        self.conn.post("TierStore/Snapshots/by-id/", cmd)

    def delete_snapshot(self, snapshot):
        LOG.debug('FIO delete_snapshot() SnapID: %s' % (snapshot['id']))
        snap = self._get_snapshot_by_name(snapshot['id'])
        self.conn.delete("TierStore/Snapshots/by-id/" + snap['id'])

    def create_volume_from_snapshot(self, volume, snapshot):
        LOG.debug('FIO create_volume_from_snapshot()  w/ %s' %
                  volume['id'])

        qos = self.fio_qos_dict['Policy 5']
        if volume.get('volume_metadata')is not None:
            qos = self._set_qos_presets(volume)

        type_id = volume['volume_type_id']
        if type_id is not None:
            qos = self._set_qos_by_volume_type(type_id)
        snap = self._get_snapshot_by_name(snapshot['id'])
        cmd = {"ParentLayerId": snap['id'],
               "Name": volume['id'],
               "PolicyUUID": qos}
        self.conn.put("TierStore/Snapshots/functions/CloneSnapshot", cmd)

    def _delete_acl_by_name(self, name):
        aclname = self._get_acl_by_name(name)
        if aclname is []:
            return
        result = self.conn.get("TierStore/Volumes/by-id/")
        inuse = False
        for vol in result:
            for acl in vol['AclGroupList']:
                if int(acl) == aclname['id']:
                    inuse = True
                    break
            if inuse:
                break
        if not inuse:
            result = self.conn.delete("TierStore/ACLGroup/by-id/" +
                                      str(aclname['id']))

    def terminate_connection(self, volume, connector, **kwargs):
        LOG.debug('FIO terminate_connection() w/ %(id)s %(conn)s ' %
                  {'id': volume['id'],
                   'conn': connector['initiator']})
        vol = self._get_volume_by_name(volume['id'])
        acl = self._get_acl_by_name("Deny Access")
        if acl is []:
            msg = _('FIO: ACL does not exist!')
            raise exception.VolumeDriverException(message=msg)
        cmd = {"AclGroupList": [str(acl['id'])], }
        self.conn.put("TierStore/Volumes/by-id/" + vol['id'], cmd)
        self._delete_acl_by_name(connector['initiator'])

    def create_cloned_volume(self, volume, src_vref):
        LOG.debug('FIO create_cloned_volume() w/ %(id)s %(src)s' %
                  {'id': volume['id'],
                   'src': src_vref})
        qos = self.fio_qos_dict['Policy 5']
        # take a snapshot of the volume (use random UUID for name)
        snapshotname = str(uuid.uuid4())
        vol = self._get_volume_by_name(src_vref['id'])
        cmd = {"VolumeUUID": vol['id'],
               "Name": snapshotname, }
        self.conn.post("TierStore/Snapshots/by-id/", cmd)

        # create a volume from the snapshot with the new name.
        # Rollback = Delete the snapshot if needed.
        if volume.get('volume_metadata')is not None:
            qos = self._set_qos_presets(volume)

        type_id = volume['volume_type_id']
        if type_id is not None:
            qos = self._set_qos_by_volume_type(type_id)

        snap = self._get_snapshot_by_name(snapshotname)
        cmd = {"ParentLayerId": snap['id'],
               "Name": volume['id'],
               "PolicyUUID": qos, }
        try:
            # watch for any issues here, and if there are, clean up the
            # snapshot and re-raise
            self.conn.put("TierStore/Snapshots/functions/CloneSnapshot", cmd)
        except Exception:
            snap = self._get_snapshot_by_name(snapshotname)
            self.conn.delete("TierStore/Snapshots/by-id/" + snap['id'])
            raise

    def get_volume_stats(self, refresh=False):
        """Retrieve status info from volume group."""
        LOG.debug("FIO Updating volume status")
        if refresh:
            result = self.conn.get("TierStore/Pools/by-id/")
            data = {}
            backend_name = self.configuration.safe_get('volume_backend_name')
            data["volume_backend_name"] = (backend_name
                                           or self.__class__.__name__)
            data["vendor_name"] = 'Fusion-io Inc'
            data["driver_version"] = self.VERSION
            data["storage_protocol"] = 'iSCSI'
            data['total_capacity_gb'] = (result[0]['PagingTotalMB'] +
                                         result[1]['PagingTotalMB'])
            data['free_capacity_gb'] = (max((result[0]['PagingTotalMB'] -
                                             result[0]['ExportedVolumeMB']),
                                            (result[1]['PagingTotalMB'] -
                                             result[1]['ExportedVolumeMB'])))
            data['reserved_percentage'] = 10
            data['QoS_support'] = True
            self._stats = data

        LOG.debug('Result from status: %s' % data)
        return self._stats

    def extend_volume(self, volume, new_size):
        LOG.debug("FIO extend_volume %(id)s to %(size)s" %
                  {'id': volume['id'],
                   'size': new_size})
        cmd = {"Size": int(new_size) * units.Gi}
        vol = self._get_volume_by_name(volume['id'])
        self.conn.put("TierStore/Volumes/by-id/" + vol['id'], cmd)
