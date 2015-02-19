# Copyright (c) 2014 LINBIT HA Solutions GmbH
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

This driver connects Cinder to an installed DRBDmanage instance, see
  http://oss.linbit.com/drbdmanage/
  http://git.linbit.com/drbdmanage.git/
for more details.

"""

import uuid

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import importutils
from oslo_utils import units
import six


from cinder import exception
from cinder.i18n import _, _LW
from cinder.volume import driver

try:
    import dbus
    import drbdmanage.consts as dm_const
    import drbdmanage.exceptions as dm_exc
    import drbdmanage.utils as dm_utils
except ImportError:
    dbus = None
    dm_const = None
    dm_exc = None
    dm_utils = None


LOG = logging.getLogger(__name__)

drbd_opts = [
    cfg.StrOpt('drbdmanage_redundancy',
               default='1',
               help='Number of nodes that should replicate the data.'),
    # TODO(PM): offsite_redundancy?
    # TODO(PM): choose DRBDmanage storage pool?
]


CONF = cfg.CONF
CONF.register_opts(drbd_opts)


CINDER_AUX_PROP_id = "cinder-id"
DM_VN_PREFIX = 'CV_'  # sadly 2CV isn't allowed by DRBDmanage


class DrbdManageDriver(driver.VolumeDriver):
    """Cinder driver that uses DRBDmanage as data store.
    """

    VERSION = '1.0.0'
    drbdmanage_dbus_name = 'org.drbd.drbdmanaged'
    drbdmanage_dbus_interface = '/interface'

    def __init__(self, execute=None, *args, **kwargs):
        self.empty_list = dbus.Array([], signature="a(ss)")
        super(DrbdManageDriver, self).__init__(*args, **kwargs)
        if self.configuration:
            self.configuration.append_config_values(drbd_opts)
        if not self.drbdmanage_dbus_name:
            self.drbdmanage_dbus_name = 'org.drbd.drbdmanaged'
        if not self.drbdmanage_dbus_interface:
            self.drbdmanage_dbus_interface = '/interface'
        self.drbdmanage_redundancy = int(getattr(self.configuration,
                                                 'drbdmanage_redundancy', 1))
        self.dm_control_vol = ".drbdctrl"

        # Copied from the LVM driver, see
        # I43190d1dac33748fe55fa00f260f32ab209be656
        target_driver = \
            self.target_mapping[self.configuration.safe_get('iscsi_helper')]

        LOG.debug('Attempting to initialize DRBD driver with the '
                  'following target_driver: %s',
                  target_driver)

        self.target_driver = importutils.import_object(
            target_driver,
            configuration=self.configuration,
            db=self.db,
            executor=self._execute)

    def dbus_connect(self):
        self.odm = dbus.SystemBus().get_object(self.drbdmanage_dbus_name,
                                               self.drbdmanage_dbus_interface)
        self.odm.ping()

    def call_or_reconnect(self, fn, *args):
        """Call DBUS function; if it got disconnected,
        try once to reconnect.
        """
        try:
            return apply(fn, args)
        except dbus.DBusException as e:
            LOG.warn(_LW("got disconnected; trying to reconnect. (%s)") %
                     six.text_type(e))
            self.dbus_connect()
            return apply(fn, args)

    def do_setup(self, context):
        """Any initialization the volume driver does while starting."""
        super(DrbdManageDriver, self).do_setup(context)
        self.dbus_connect()

    def check_for_setup_error(self):
        """Verify that requirements are in place to use DRBDmanage driver."""
        if not all((dbus, dm_exc, dm_const, dm_utils)):
            msg = _('DRBDmanage driver setup error: some required '
                    'libraries (dbus, drbdmanage.*) not found.')
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)
        if self.odm.ping() != 0:
            message = _('Cannot ping DRBDmanage backend')
            raise exception.VolumeBackendAPIException(data=message)

    def _clean_uuid(self):
        """Returns a UUID string, WITHOUT braces."""
        # Some uuid library versions put braces around the result!?
        # We don't want them, just a plain [0-9a-f-]+ string.
        id = str(uuid.uuid4())
        return id.translate(None, "{}")

    def _check_result(self, res, ignore=None, ret=0):
        seen_success = False
        seen_error = False
        result = ret
        for (code, fmt, arg_l) in res:
            # convert from DBUS to Python
            arg = dict(arg_l)
            if ignore and code in ignore:
                if not result:
                    result = code
                continue
            if code == dm_exc.DM_SUCCESS:
                seen_success = True
                continue
            seen_error = _("Received error string: %s") % (fmt % arg)

        if seen_error:
            raise exception.VolumeBackendAPIException(data=seen_error)
        if seen_success:
            return ret
        # by default okay - or the ignored error code.
        return ret

    # DRBDmanage works in kiB units; Cinder uses float GiB.
    def _vol_size_to_dm(self, size):
        return int(size * units.Gi / units.Ki)

    def _vol_size_to_cinder(self, size):
        return int(size * units.Ki / units.Gi)

    def is_clean_volume_name(self, name):
        try:
            if name.startswith(CONF.volume_name_template % "") and \
                    uuid.UUID(name[7:]) is not None:
                return DM_VN_PREFIX + name[7:]
        except ValueError:
            return None

        try:
            if uuid.UUID(name) is not None:
                return DM_VN_PREFIX + name
        except ValueError:
            return None

    def _priv_hash_from_volume(self, volume):
        return dm_utils.dict_to_aux_props({
            CINDER_AUX_PROP_id: volume['id'],
        })

    def snapshot_name_from_cinder_snapshot(self, snapshot):
        sn_name = self.is_clean_volume_name(snapshot['id'])
        return sn_name

    def _res_and_vl_data_for_volume(self, volume, empty_ok=False):
        """A DRBD resource might consist of several "volumes"
        (think consistency groups).
        So we have to find the number of the volume within one resource.
        Returns resource name, volume number, and resource
        and volume properties.
        """

        # If we get a string, use it as-is.
        # Else it's a dictionary; then get the ID.
        if type(volume) is str or type(volume) is unicode:
            v_uuid = volume
        else:
            v_uuid = volume['id']

        res, rl = self.call_or_reconnect(self.odm.list_volumes,
                                         self.empty_list,
                                         0,
                                         dm_utils.dict_to_aux_props(
                                             {CINDER_AUX_PROP_id: v_uuid}),
                                         self.empty_list)
        self._check_result(res)

        if (not rl) or (len(rl) == 0):
            if empty_ok:
                LOG.debug("No volume %s found." % v_uuid)
                return None, None, None, None
            raise exception.VolumeBackendAPIException(
                data=_("volume %s not found in drbdmanage") % v_uuid)
        if len(rl) > 1:
            raise exception.VolumeBackendAPIException(
                data=_("multiple resources with name %s found by drbdmanage") %
                v_uuid)

        (r_name, r_props, vols) = rl[0]
        if len(vols) != 1:
            raise exception.VolumeBackendAPIException(
                data=_("not exactly one volume with id %s") %
                v_uuid)

        (v_nr, v_props) = vols[0]

        LOG.debug("volume %s is %s/%d; %s, %s" %
                  (v_uuid, r_name, v_nr, r_props, v_props))

        return r_name, v_nr, r_props, v_props

    def _resource_and_snap_data_from_snapshot(self, snapshot, empty_ok=False):
        """Find the DRBD Resource and the snapshot name
        from the snapshot ID.
        """
        s_uuid = snapshot['id']
        res, rs = self.call_or_reconnect(self.odm.list_snapshots,
                                         self.empty_list,
                                         self.empty_list,
                                         dm_utils.dict_to_aux_props(
                                             {CINDER_AUX_PROP_id: s_uuid}),
                                         self.empty_list)
        self._check_result(res)

        if (not rs) or (len(rs) == 0):
            if empty_ok:
                return None
            else:
                raise exception.VolumeBackendAPIException(
                    data=_("no snapshot with id %s found in drbdmanage") %
                    s_uuid)
        if len(rs) > 1:
            raise exception.VolumeBackendAPIException(
                data=_("multiple resources with snapshot ID %s found") %
                s_uuid)

        (r_name, snaps) = rs[0]
        if len(snaps) != 1:
            raise exception.VolumeBackendAPIException(
                data=_("not exactly one snapshot with id %s") % s_uuid)

        (s_name, s_props) = snaps[0]

        LOG.debug("snapshot %s is %s/%s" % (s_uuid, r_name, s_name))

        return r_name, s_name, s_props

    def _resource_name_volnr_for_volume(self, volume, empty_ok=False):
        res, vol, _, _ = self._res_and_vl_data_for_volume(volume, empty_ok)
        return res, vol

    def local_path(self, volume):
        dres, dvol = self._resource_name_volnr_for_volume(volume)

        res, data = self.call_or_reconnect(self.odm.text_query,
                                           [dm_const.TQ_GET_PATH,
                                            dres,
                                            str(dvol)])
        self._check_result(res)
        if len(data) == 1:
            return data[0]
        message = _('Got bad path information from DRBDmanage! (%s)') % data
        raise exception.VolumeBackendAPIException(data=message)

    def create_volume(self, volume):
        """Creates a DRBD resource.
        We address it later on via the ID that gets stored
        as a private property.
        """

        # TODO(PM): consistency groups
        dres = self.is_clean_volume_name(volume['id'])

        LOG.debug("create vol: make %s" % dres)
        res = self.call_or_reconnect(self.odm.create_resource,
                                     dres,
                                     self.empty_list)
        exist = self._check_result(res, ignore=[dm_exc.DM_EEXIST], ret=None)
        if exist == dm_exc.DM_EEXIST:
            # Volume already exists, eg. because deploy gave an error
            # on a previous try (like ENOSPC)
            pass
        else:

            props = self._priv_hash_from_volume(volume)
            # TODO(PM): properties - redundancy, etc
            res = self.call_or_reconnect(self.odm.create_volume,
                                         dres,
                                         self._vol_size_to_dm(volume['size']),
                                         props)
            self._check_result(res)

            res = self.call_or_reconnect(self.odm.auto_deploy,
                                         dres, self.drbdmanage_redundancy,
                                         0, True)
            self._check_result(res)

        return 0

    def delete_volume(self, volume):
        """Deletes a resource."""
        dres, dvol = self._resource_name_volnr_for_volume(
            volume,
            empty_ok=True)

        if not dres:
            # OK, already gone.
            return 0

        # TODO(PM): check if in use? Ask whether Primary, or just check result?
        res = self.call_or_reconnect(self.odm.remove_volume, dres, dvol, False)
        return self._check_result(res, ignore=[dm_exc.DM_ENOENT])
        # TODO(PM): delete resource if empty?

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""

        LOG.debug("create vol from snap: from %s make %s" %
                  (snapshot['id'], volume['id']))
        # TODO(PM): Consistency groups.
        dres, sname, sprop = self._resource_and_snap_data_from_snapshot(
            snapshot)

        new_res = self.is_clean_volume_name(volume['id'])

        r_props = self.empty_list
        v_props = self._priv_hash_from_volume(volume)

        res = self.call_or_reconnect(self.odm.restore_snapshot,
                                     new_res,
                                     dres,
                                     sname,
                                     r_props,
                                     v_props)
        return self._check_result(res, ignore=[dm_exc.DM_ENOENT])

    def create_cloned_volume(self, volume, src_vref):
        temp_id = self._clean_uuid()
        snapshot = {'id': temp_id}

        self.create_snapshot(dict(snapshot.items() +
                                  [('volume_id', src_vref['id'])]))

        self.create_volume_from_snapshot(volume, snapshot)

        self.delete_snapshot(snapshot)

    def _update_volume_stats(self):
        LOG.debug("Updating volume stats")

        data = {}

        data["vendor_name"] = 'LINBIT'
        data["vendor_name"] = 'Open Source'
        data["driver_version"] = self.VERSION
        data["storage_protocol"] = "iSCSI"
        # This has to match the name set in the cinder volume driver spec,
        # so keep it lowercase
        data["volume_backend_name"] = "drbdmanage"
        data["pools"] = []

        res, free, total = self.call_or_reconnect(self.odm.cluster_free_query,
                                                  self.drbdmanage_redundancy)
        self._check_result(res)

        location_info =\
            ('DrbdManageDriver:%(cvol)s:%(dbus)s' %
             {'cvol': self.dm_control_vol,
              'dbus': self.drbdmanage_dbus_name})

        # TODO(PM): multiple DRBDmanage instances and/or multiple pools
        single_pool = {}
        single_pool.update(dict(
            pool_name=data["volume_backend_name"],
            free_capacity_gb=self._vol_size_to_cinder(free),
            total_capacity_gb=self._vol_size_to_cinder(total),
            reserved_percentage=self.configuration.reserved_percentage,
            location_info=location_info,
            QoS_support=False))

        data["pools"].append(single_pool)

        self._stats = data

    def get_volume_stats(self, refresh=False):
        """Get volume status.

        If 'refresh' is True, run update the stats first.
        """

        if refresh:
            self._update_volume_stats()
        return self._stats

    def extend_volume(self, volume, new_size):
        dres, dvol = self._resource_name_volnr_for_volume(volume)

        res = self.call_or_reconnect(self.odm.resize_volume,
                                     dres, dvol, -1,
                                     {"size": self._vol_size_to_dm(new_size)},
                                     0)
        self._check_result(res)
        return 0

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        sn_name = self.snapshot_name_from_cinder_snapshot(snapshot)

        LOG.debug("create snapshot: from %s make %s" %
                  (snapshot['volume_id'], snapshot['id']))
        dres, dvol = self._resource_name_volnr_for_volume(
            snapshot["volume_id"])

        res, data = self.call_or_reconnect(self.odm.list_assignments,
                                           self.empty_list,
                                           [dres],
                                           0,
                                           self.empty_list,
                                           self.empty_list)
        self._check_result(res)

        nodes = map(lambda d: d[0], data)
        if len(nodes) < 1:
            raise exception.VolumeBackendAPIException(
                _('Snapshot res "%s" that is not deployed anywhere?') %
                (dres))

        props = self._priv_hash_from_volume(snapshot)
        res = self.call_or_reconnect(self.odm.create_snapshot,
                                     dres, sn_name, nodes, props)
        return self._check_result(res)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""

        force = False  # during testing
        dres, sname, _ = self._resource_and_snap_data_from_snapshot(
            snapshot, empty_ok=not force)

        if not dres:
            # resource already gone?
            if force:
                return 0
            raise exception.VolumeBackendAPIException(
                _('Resource "%(res)s" for snapshot "%(sn)s" not found') %
                {"res": dres, "sn": sname})

        res = self.call_or_reconnect(self.odm.remove_snapshot,
                                     dres, sname, force)
        return self._check_result(res, ignore=[dm_exc.DM_ENOENT])

    # #######  Interface methods for DataPath (Target Driver) ########

    def ensure_export(self, context, volume):
        volume_path = self.local_path(volume)
        return self.target_driver.ensure_export(
            context,
            volume,
            volume_path)

    def create_export(self, context, volume):
        volume_path = self.local_path(volume)
        export_info = self.target_driver.create_export(
            context,
            volume,
            volume_path)

        return {'provider_location': export_info['location'],
                'provider_auth': export_info['auth'], }

    def remove_export(self, context, volume):
        return self.target_driver.remove_export(context, volume)

    def initialize_connection(self, volume, connector):
        return self.target_driver.initialize_connection(volume, connector)

    def validate_connector(self, connector):
        return self.target_driver.validate_connector(connector)

    def terminate_connection(self, volume, connector, **kwargs):
        return None
