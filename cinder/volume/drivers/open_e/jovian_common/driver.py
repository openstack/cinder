#    Copyright (c) 2023 Open-E, Inc.
#    All Rights Reserved.
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

from oslo_log import log as logging
from oslo_utils import units as o_units

from cinder import exception
from cinder.i18n import _
from cinder.volume.drivers.open_e.jovian_common import exception as jexc
from cinder.volume.drivers.open_e.jovian_common import jdss_common as jcom
from cinder.volume.drivers.open_e.jovian_common import rest

LOG = logging.getLogger(__name__)


class JovianDSSDriver(object):

    def __init__(self, config):

        self.configuration = config
        self._pool = self.configuration.get('jovian_pool', 'Pool-0')
        self.jovian_iscsi_target_portal_port = self.configuration.get(
            'target_port', 3260)

        self.jovian_target_prefix = self.configuration.get(
            'target_prefix',
            'iqn.2020-04.com.open-e.cinder:')
        self.jovian_chap_pass_len = self.configuration.get(
            'chap_password_len', 12)
        self.block_size = (
            self.configuration.get('jovian_block_size', '64K'))
        self.jovian_sparse = (
            self.configuration.get('san_thin_provision', True))
        self.jovian_ignore_tpath = self.configuration.get(
            'jovian_ignore_tpath', None)
        self.jovian_hosts = self.configuration.get(
            'san_hosts', [])

        self.ra = rest.JovianRESTAPI(config)

    def rest_config_is_ok(self):
        """Check config correctness by checking pool availability"""

        return self.ra.is_pool_exists()

    def get_active_ifaces(self):
        """Return list of ip addresses for iSCSI connection"""

        return self.jovian_hosts

    def get_provider_location(self, volume_name):
        """Return volume iscsiadm-formatted provider location string."""
        return '%(host)s:%(port)s,1 %(name)s 0' % {
            'host': self.ra.get_active_host(),
            'port': self.jovian_iscsi_target_portal_port,
            'name': self._get_target_name(volume_name)}

    def create_volume(self, volume_id, volume_size, sparse=False,
                      block_size=None):
        """Create a volume.

        :param str volume_id: volume id
        :param int volume_size: size in Gi
        :param bool sparse: thin or thick volume flag (default thin)
        :param int block_size: size of block (default None)

        :return: None
        """
        vname = jcom.vname(volume_id)
        LOG.debug("Create volume:%(name)s with size:%(size)s",
                  {'name': volume_id, 'size': volume_size})

        self.ra.create_lun(vname,
                           volume_size * o_units.Gi,
                           sparse=sparse,
                           block_size=block_size)
        return

    def _promote_newest_delete(self, vname, snapshots=None):
        '''Promotes and delete volume

        This function deletes volume.
        It will promote volume if needed before deletion.

        :param str vname: physical volume id
        :param list snapshots: snapshot data list (default None)

        :return: None
        '''

        if snapshots is None:
            try:
                snapshots = self.ra.get_snapshots(vname)
            except jexc.JDSSResourceNotFoundException:
                LOG.debug('volume %s do not exists, it was already '
                          'deleted', vname)
                return

        bsnaps = self._list_busy_snapshots(vname, snapshots)

        if len(bsnaps) != 0:

            promote_target = None

            sname = jcom.get_newest_snapshot_name(bsnaps)

            for snap in bsnaps:
                if snap['name'] == sname:
                    cvnames = jcom.snapshot_clones(snap)
                    for cvname in cvnames:
                        if jcom.is_volume(cvname):
                            promote_target = cvname
                        if jcom.is_snapshot(cvname):
                            self._promote_newest_delete(cvname)
                        if jcom.is_hidden(cvname):
                            self._promote_newest_delete(cvname)
                    break

            if promote_target is None:
                self._promote_newest_delete(vname)
                return

            self.ra.promote(vname, sname, promote_target)

        self._delete_vol_with_source_snap(vname, recursive=True)

    def _delete_vol_with_source_snap(self, vname, recursive=False):
        '''Delete volume and its source snapshot if required

        This function deletes volume.
        If volume is a clone it will check its source snapshot if
        one is originates from volume to delete.

        :param str vname: physical volume id
        :param bool recursive: recursive flag (default False)

        :return: None
        '''
        vol = None

        try:
            vol = self.ra.get_lun(vname)
        except jexc.JDSSResourceNotFoundException:
            LOG.debug('unable to get volume %s info, '
                      'assume it was already deleted', vname)
            return
        try:
            self.ra.delete_lun(vname,
                               force_umount=True,
                               recursively_children=recursive)
        except jexc.JDSSResourceNotFoundException:
            LOG.debug('volume %s do not exists, it was already '
                      'deleted', vname)
            return

        if vol is not None and \
                'origin' in vol and \
                vol['origin'] is not None:
            if jcom.is_volume(jcom.origin_snapshot(vol)) or \
                    jcom.is_hidden(jcom.origin_snapshot(vol)) or \
                    (jcom.vid_from_sname(jcom.origin_snapshot(vol)) ==
                     jcom.idname(vname)):
                self.ra.delete_snapshot(jcom.origin_volume(vol),
                                        jcom.origin_snapshot(vol),
                                        recursively_children=True,
                                        force_umount=True)

    def _clean_garbage_resources(self, vname, snapshots=None):
        '''Removes resources that is not related to volume

        Goes through volume snapshots and it clones to identify one
        that is clearly not related to vname volume and therefore
        have to be deleted.

        :param str vname: physical volume id
        :param list snapshots: list of snapshot info dictionaries

        :return: updated list of snapshots
        '''

        if snapshots is None:
            try:
                snapshots = self.ra.get_snapshots(vname)
            except jexc.JDSSResourceNotFoundException:
                LOG.debug('volume %s do not exists, it was already '
                          'deleted', vname)
                return
        update = False
        for snap in snapshots:
            if jcom.is_volume(jcom.sname_from_snap(snap)):
                cvnames = jcom.snapshot_clones(snap)
                if len(cvnames) == 0:
                    self._delete_snapshot(vname, jcom.sname_from_snap(snap))
                    update = True
            if jcom.is_snapshot(jcom.sname_from_snap(snap)):
                cvnames = jcom.snapshot_clones(snap)
                for cvname in cvnames:
                    if jcom.is_hidden(cvname):
                        self._promote_newest_delete(cvname)
                        update = True
                    if jcom.is_snapshot(cvname):
                        if jcom.idname(vname) != jcom.vid_from_sname(cvname):
                            self._promote_newest_delete(cvname)
                            update = True
        if update:
            snapshots = self.ra.get_snapshots(vname)
        return snapshots

    def _list_busy_snapshots(self, vname, snapshots,
                             exclude_dedicated_volumes=False) -> list:
        """List all volume snapshots with clones

        Goes through provided list of snapshots.
        If additional parameters are given, will filter list of snapshots
        accordingly.

        Keyword arguments:
        :param str vname: zvol id
        :param list snapshots: list of snapshots data dicts
        :param bool exclude_dedicated_volumes: list snapshots that has clones
                                        (default False)

        :return: filtered list of snapshot data dicts
        :rtype: list
        """

        out = []
        for snap in snapshots:
            clones = jcom.snapshot_clones(snap)
            add = False
            for cvname in clones:
                if exclude_dedicated_volumes and jcom.is_volume(cvname):
                    continue
                add = True
            if add:
                out.append(snap)

        return out

    def _clean_volume_snapshots_mount_points(self, vname, snapshots):
        update = False
        for snap in snapshots:
            clones = jcom.snapshot_clones(snap)
            for cname in [c for c in clones if jcom.is_snapshot(c)]:
                update = True
                self._delete_volume(cname, cascade=True)
        if update:
            snapshots = self.ra.get_snapshots(vname)
        return snapshots

    def _delete_volume(self, vname, cascade=False):
        """_delete_volume delete routine containing delete logic

        :param str vname: physical volume id
        :param bool cascade: flag for cascade volume deletion
            with its snapshots

        :return: None
        """
        try:
            self.ra.delete_lun(vname,
                               force_umount=True,
                               recursively_children=cascade)
        except jexc.JDSSResourceIsBusyException:
            LOG.debug('unable to conduct direct volume %s deletion', vname)
        except jexc.JDSSResourceNotFoundException:
            LOG.debug('volume %s do not exists, it was already '
                      'deleted', vname)
            return
        except jexc.JDSSRESTException as jerr:
            LOG.debug(
                "Unable to delete physical volume %(volume)s "
                "with error %(err)s.", {
                    "volume": vname,
                    "err": jerr})
        else:
            LOG.debug('in place deletion suceeded')
            return

        snapshots = None
        try:
            snapshots = self.ra.get_snapshots(vname)
        except jexc.JDSSResourceNotFoundException:
            LOG.debug('volume %s do not exists, it was already '
                      'deleted', vname)
            return

        if cascade is False:
            bsnaps = self._list_busy_snapshots(vname,
                                               snapshots,
                                               exclude_dedicated_volumes=True)
            if len(bsnaps) > 0:
                raise exception.VolumeIsBusy('Volume has snapshots')

        snaps = self._clean_garbage_resources(vname, snapshots)
        snaps = self._clean_volume_snapshots_mount_points(vname, snapshots)

        self._promote_newest_delete(vname, snapshots=snaps)

    def delete_volume(self, volume_name, cascade=False):
        """Delete volume

        :param volume: volume reference
        :param cascade: remove snapshots of a volume as well
        """
        vname = jcom.vname(volume_name)

        LOG.debug('deleting volume %s', vname)

        self._delete_volume(vname, cascade=cascade)

    def _clone_object(self, cvname, sname, ovname,
                      sparse=None,
                      create_snapshot=False):
        """Creates a clone of specified object

        Will create snapshot if it is not provided

        :param str cvname: clone volume name
        :param str sname: snapshot name
        :param str ovname: original volume name
        :param bool sparse: sparse property of new volume
        :param bool create_snapshot:
        """
        LOG.debug('cloning %(ovname)s to %(coname)s', {
            "ovname": ovname,
            "coname": cvname})

        if create_snapshot:
            self.ra.create_snapshot(ovname, sname)
        try:
            self.ra.create_volume_from_snapshot(
                cvname,
                sname,
                ovname,
                sparse=sparse)
        except jexc.JDSSException as jerr:
            # This is a garbage collecting section responsible for cleaning
            # all the mess of request failed
            if create_snapshot:
                try:
                    self.ra.delete_snapshot(ovname,
                                            cvname,
                                            recursively_children=True,
                                            force_umount=True)
                except jexc.JDSSException as jerrd:
                    LOG.warning("Because of %s physical snapshot %s of volume"
                                " %s have to be removed manually",
                                jerrd,
                                sname,
                                ovname)

            raise jerr

    def resize_volume(self, volume_name, new_size):
        """Extend an existing volume.

        :param str volume_name: volume id
        :param int new_size: volume new size in Gi
        """
        LOG.debug("Extend volume:%(name)s to size:%(size)s",
                  {'name': volume_name, 'size': new_size})

        self.ra.extend_lun(jcom.vname(volume_name),
                           int(new_size) * o_units.Gi)

    def create_cloned_volume(self,
                             clone_name,
                             volume_name,
                             size,
                             snapshot_name=None,
                             sparse=False):
        """Create a clone of the specified volume.

        :param str clone_name: new volume id
        :param volume_name: original volume id
        :param int size: size in Gi
        :param str snapshot_name: openstack snapshot id to use for cloning
        :param bool sparse: sparse flag
        """
        cvname = jcom.vname(clone_name)

        ovname = jcom.vname(volume_name)

        LOG.debug('clone volume %(id)s to %(id_clone)s', {
            "id": volume_name,
            "id_clone": clone_name})

        if snapshot_name:
            sname = jcom.sname(snapshot_name, volume_name)
            self._clone_object(cvname, sname, ovname,
                               create_snapshot=False,
                               sparse=sparse)
        else:
            sname = jcom.vname(clone_name)
            self._clone_object(cvname, sname, ovname,
                               create_snapshot=True,
                               sparse=sparse)

        clone_size = 0

        try:
            clone_size = int(self.ra.get_lun(cvname)['volsize'])
        except jexc.JDSSException as jerr:

            self.delete_volume(clone_name, cascade=False)
            raise exception.VolumeBackendAPIException(
                _("Fail in cloning volume %(vol)s to %(clone)s.") % {
                    'vol': volume_name, 'clone': clone_name}) from jerr

        try:
            if int(clone_size) < o_units.Gi * int(size):
                self.resize_volume(clone_name, int(size))

        except jexc.JDSSException as jerr:
            # If volume can't be set to a proper size make sure to clean it
            # before failing
            try:
                self.delete_volume(clone_name, cascade=False)
            except jexc.JDSSException as jerrex:
                LOG.warning("Error %s during cleaning failed volume %s",
                            jerrex, volume_name)
                raise jerr from jerrex

    def create_snapshot(self, snapshot_name, volume_name):
        """Create snapshot of existing volume.

        :param str snapshot_name: new snapshot id
        :param str volume_name: original volume id
        """
        LOG.debug('create snapshot %(snap)s for volume %(vol)s', {
            'snap': snapshot_name,
            'vol': volume_name})

        vname = jcom.vname(volume_name)
        sname = jcom.sname(snapshot_name, volume_name)

        self.ra.create_snapshot(vname, sname)

    def create_export_snapshot(self, snapshot_name, volume_name,
                               provider_auth):
        """Creates iscsi resources needed to start using snapshot

        :param str snapshot_name: openstack snapshot id
        :param str volume_name: openstack volume id
        :param str provider_auth: space-separated triple
              '<auth method> <auth username> <auth password>'
        """

        sname = jcom.sname(snapshot_name, volume_name)
        ovname = jcom.vname(volume_name)
        self._clone_object(sname, sname, ovname,
                           sparse=True,
                           create_snapshot=False)
        try:
            self._ensure_target_volume(snapshot_name, sname, provider_auth,
                                       ro=True)
        except jexc.JDSSException as jerr:
            self._delete_volume(sname, cascade=True)
            raise jerr

    def remove_export(self, volume_name):
        """Remove iscsi target created to make volume attachable

        :param str volume_name: openstack volume id
        """
        vname = jcom.vname(volume_name)
        try:
            self._remove_target_volume(volume_name, vname)
        except jexc.JDSSException as jerr:
            LOG.warning(jerr)

    def remove_export_snapshot(self, snapshot_name, volume_name):
        """Remove tmp vol and iscsi target created to make snap attachable

        :param str snapshot_name: openstack snapshot id
        :param str volume_name: openstack volume id
        """

        sname = jcom.sname(snapshot_name, volume_name)

        try:
            self._remove_target_volume(snapshot_name, sname)
        except jexc.JDSSException as jerr:
            self._delete_volume(sname, cascade=True)
            raise jerr

        self._delete_volume(sname, cascade=True)

    def _delete_snapshot(self, vname, sname):
        """Delete snapshot

        This method will delete snapshot mount point and snapshot if possible

        :param str vname: zvol name
        :param dict snap: snapshot info dictionary

        :return: None
        """

        try:
            self.ra.delete_snapshot(vname, sname, force_umount=True)
        except jexc.JDSSResourceIsBusyException:
            LOG.debug('Direct deletion of snapshot %s failed', vname)
        else:
            return

        snap = self.ra.get_snapshot(vname, sname)

        clones = jcom.snapshot_clones(snap)
        busy = False
        for cvname in clones:
            if jcom.is_snapshot(cvname):
                self._promote_newest_delete(cvname)
            if jcom.is_volume(cvname):
                LOG.debug('Will not delete snap %(snap)s,'
                          'becasue it is used by %(vol)s',
                          {'snap': sname,
                           'vol': cvname})
                busy = True
        if busy:
            return
        try:
            self.ra.delete_snapshot(vname, sname, force_umount=True)
        except jexc.JDSSResourceIsBusyException:
            LOG.debug('Unable to delete snap %(snap)s because it is busy',
                      {'snap': jcom.sname_from_snap(snap)})

    def delete_snapshot(self, volume_name, snapshot_name):
        """Delete snapshot of existing volume.

        :param str volume_name: volume id
        :param str snapshot_name: snapshot id
        """
        vname = jcom.vname(volume_name)
        sname = jcom.sname(snapshot_name, volume_name)

        self._delete_snapshot(vname, sname)

    def _ensure_target_volume(self, id, vid, provider_auth, ro=False):
        """Checks if target configured properly and volume is attached to it

        :param str id: id that would be used for target naming
        :param str vname: physical volume id
        :param str provider_auth: space-separated triple
              '<auth method> <auth username> <auth password>'
        """
        LOG.debug("ensure volume %s assigned to a proper target", id)

        target_name = self._get_target_name(id)

        if not provider_auth:
            msg = _("volume %s is missing provider_auth") % jcom.idname(id)
            raise jexc.JDSSException(msg)

        if not self.ra.is_target(target_name):

            return self._create_target_volume(id, vid, provider_auth)

        if not self.ra.is_target_lun(target_name, vid):
            self._attach_target_volume(target_name, vid)

        (__, auth_username, auth_secret) = provider_auth.split()
        chap_cred = {"name": auth_username,
                     "password": auth_secret}

        try:
            users = self.ra.get_target_user(target_name)
            if len(users) == 1:
                if users[0]['name'] == chap_cred['name']:
                    return
                self.ra.delete_target_user(
                    target_name,
                    users[0]['name'])
            for user in users:
                self.ra.delete_target_user(
                    target_name,
                    user['name'])
            self._set_target_credentials(target_name, chap_cred)

        except jexc.JDSSException as jerr:
            self.ra.delete_target(target_name)
            raise exception.VolumeBackendAPIException(jerr)

    def _get_target_name(self, volume_id):
        """Return iSCSI target name to access volume."""
        return f'{self.jovian_target_prefix}{volume_id}'

    def _get_iscsi_properties(self, volume_id, provider_auth, multipath=False):
        """Return dict according to cinder/driver.py implementation.

        :param volume_id: UUID of volume, might take snapshot UUID
        :param str provider_auth: space-separated triple
              '<auth method> <auth username> <auth password>'
        :return:
        """
        tname = self._get_target_name(volume_id)
        iface_info = []
        if multipath:
            iface_info = self.get_active_ifaces()
            if not iface_info:
                raise exception.InvalidConfigurationValue(
                    _('No available interfaces '
                      'or config excludes them'))

        iscsi_properties = {}

        if multipath:
            iscsi_properties['target_iqns'] = []
            iscsi_properties['target_portals'] = []
            iscsi_properties['target_luns'] = []
            LOG.debug('tpaths %s.', iface_info)
            for iface in iface_info:
                iscsi_properties['target_iqns'].append(
                    self._get_target_name(volume_id))
                iscsi_properties['target_portals'].append(
                    iface +
                    ":" +
                    str(self.jovian_iscsi_target_portal_port))
                iscsi_properties['target_luns'].append(0)
        else:
            iscsi_properties['target_iqn'] = tname
            iscsi_properties['target_portal'] = (
                self.ra.get_active_host() +
                ":" +
                str(self.jovian_iscsi_target_portal_port))

        iscsi_properties['target_discovered'] = False

        if provider_auth:
            (auth_method, auth_username, auth_secret) = provider_auth.split()

            iscsi_properties['auth_method'] = auth_method
            iscsi_properties['auth_username'] = auth_username
            iscsi_properties['auth_password'] = auth_secret

        iscsi_properties['target_lun'] = 0
        return iscsi_properties

    def _remove_target_volume(self, id, vid):
        """_remove_target_volume

        Ensure that volume is not attached to target and target do not exists.
        """

        target_name = self._get_target_name(id)
        LOG.debug("remove export")
        LOG.debug("detach volume:%(vol)s from target:%(targ)s.", {
            'vol': id,
            'targ': target_name})

        try:
            self.ra.detach_target_vol(target_name, vid)
        except jexc.JDSSResourceNotFoundException as jerrrnf:
            LOG.debug('failed to remove resource %(t)s because of %(err)s', {
                't': target_name,
                'err': jerrrnf.args[0]})
        except jexc.JDSSException as jerr:
            LOG.warning('failed to Terminate_connection for target %(targ)s '
                        'because of: %(err)s', {'targ': target_name,
                                                'err': jerr.args[0]})
            raise jerr

        LOG.debug("delete target: %s", target_name)

        try:
            self.ra.delete_target(target_name)
        except jexc.JDSSResourceNotFoundException as jerrrnf:
            LOG.debug('failed to remove resource %(target)s because '
                      'of %(err)s',
                      {'target': target_name, 'err': jerrrnf.args[0]})

        except jexc.JDSSException as jerr:
            LOG.warning('Failed to Terminate_connection for target %(targ)s '
                        'because of: %(err)s ',
                        {'targ': target_name, 'err': jerr.args[0]})

            raise jerr

    def ensure_export(self, volume_id, provider_auth):

        vname = jcom.vname(volume_id)

        self._ensure_target_volume(volume_id, vname, provider_auth)

    def initialize_connection(self, volume_id, provider_auth,
                              snapshot_id=None,
                              multipath=False):
        """Ensures volume is ready for connection and return connection data

        Ensures that particular volume is ready to be used over iscsi
        with credentials provided in provider_auth
        If snapshot name is provided method will ensure that connection
        leads to read only volume object associated with particular snapshot

        :param str volume_id: Volume id string
        :param str provider_auth: space-separated triple
              '<auth method> <auth username> <auth password>'
        :param str snapshot_id: id of snapshot that should be connected
        :param bool multipath: specifies if multipath should be used
        """

        id_of_disk_to_attach = volume_id
        vid = jcom.vname(volume_id)
        if provider_auth is None:
            raise jexc.JDSSException(_("CHAP credentials missing"))
        if snapshot_id:
            id_of_disk_to_attach = snapshot_id
            vid = jcom.sname(snapshot_id, volume_id)
        iscsi_properties = self._get_iscsi_properties(id_of_disk_to_attach,
                                                      provider_auth,
                                                      multipath=multipath)
        if snapshot_id:
            self._ensure_target_volume(id_of_disk_to_attach,
                                       vid,
                                       provider_auth,
                                       mode='ro')
        else:
            self._ensure_target_volume(id_of_disk_to_attach,
                                       vid,
                                       provider_auth)

        LOG.debug(
            "initialize_connection for physical disk %(vid)s with %(id)s",
            {'vid': vid, 'id': id_of_disk_to_attach})

        return {
            'driver_volume_type': 'iscsi',
            'data': iscsi_properties,
        }

    def _create_target_volume(self, id, vid, provider_auth):
        """Creates target and attach volume to it

        :param id: uuid of particular resource
        :param vid: physical volume id, might identify snapshot mount
        :param str provider_auth: space-separated triple
              '<auth method> <auth username> <auth password>'
        :return:
        """
        LOG.debug("create target and attach volume %s to it", vid)

        target_name = self._get_target_name(id)

        (__, auth_username, auth_secret) = provider_auth.split()
        chap_cred = {"name": auth_username,
                     "password": auth_secret}

        # Create target
        self.ra.create_target(target_name, use_chap=True)

        # Attach volume
        self._attach_target_volume(target_name, vid)

        # Set credentials
        self._set_target_credentials(target_name, chap_cred)

    def _attach_target_volume(self, target_name, vname):
        """Attach target to volume and handles exceptions

        Attempts to set attach volume to specific target.
        In case of failure will remove target.
        :param target_name: name of target
        :param use_chap: flag for using chap
        """
        try:
            self.ra.attach_target_vol(target_name, vname)
        except jexc.JDSSException as jerr:
            msg = ('Unable to attach volume {volume} to target {target} '
                   'because of {error}.')
            LOG.warning(msg, {"volume": vname,
                              "target": target_name,
                              "error": jerr})
            self.ra.delete_target(target_name)
            raise jerr

    def _set_target_credentials(self, target_name, cred):
        """Set CHAP configuration for target and handle exceptions

        Attempts to set CHAP credentials for specific target.
        In case of failure will remove target.
        :param target_name: name of target
        :param cred: CHAP user name and password
        """
        try:
            self.ra.create_target_user(target_name, cred)

        except jexc.JDSSException as jerr:
            try:
                self.ra.delete_target(target_name)
            except jexc.JDSSException:
                pass

            err_msg = (('Unable to create user %(user)s '
                        'for target %(target)s '
                        'because of %(error)s.') % {
                            'target': target_name,
                            'user': cred['name'],
                            'error': jerr})

            LOG.error(err_msg)
            raise jexc.JDSSException(_(err_msg))
