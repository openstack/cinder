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

import six
import socket
import uuid

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import importutils
from oslo_utils import units


from cinder import exception
from cinder.i18n import _, _LW, _LI
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
    cfg.BoolOpt('drbdmanage_devs_on_controller',
                default=True,
                help='''If set, the c-vol node will receive a useable
                /dev/drbdX device, even if the actual data is stored on
                other nodes only.
                This is useful for debugging, maintenance, and to be
                able to do the iSCSI export from the c-vol node.''')
    # TODO(PM): offsite_redundancy?
    # TODO(PM): choose DRBDmanage storage pool?
]


CONF = cfg.CONF
CONF.register_opts(drbd_opts)


AUX_PROP_CINDER_VOL_ID = "cinder-id"
DM_VN_PREFIX = 'CV_'  # sadly 2CV isn't allowed by DRBDmanage
DM_SN_PREFIX = 'SN_'


class DrbdManageDriver(driver.VolumeDriver):
    """Cinder driver that uses DRBDmanage for storage."""

    VERSION = '1.0.0'
    drbdmanage_dbus_name = 'org.drbd.drbdmanaged'
    drbdmanage_dbus_interface = '/interface'

    def __init__(self, *args, **kwargs):
        self.empty_list = dbus.Array([], signature="a(s)")
        self.empty_dict = dbus.Array([], signature="a(ss)")
        super(DrbdManageDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(drbd_opts)
        if not self.drbdmanage_dbus_name:
            self.drbdmanage_dbus_name = 'org.drbd.drbdmanaged'
        if not self.drbdmanage_dbus_interface:
            self.drbdmanage_dbus_interface = '/interface'
        self.drbdmanage_redundancy = int(getattr(self.configuration,
                                                 'drbdmanage_redundancy', 1))
        self.drbdmanage_devs_on_controller = bool(
            getattr(self.configuration,
                    'drbdmanage_devs_on_controller',
                    True))
        self.dm_control_vol = ".drbdctrl"

        # Copied from the LVM driver, see
        # I43190d1dac33748fe55fa00f260f32ab209be656
        target_driver = self.target_mapping[
            self.configuration.safe_get('iscsi_helper')]

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
        """Call DBUS function; on a disconnect try once to reconnect."""
        try:
            return fn(*args)
        except dbus.DBusException as e:
            LOG.warning(_LW("Got disconnected; trying to reconnect. (%s)"), e)
            self.dbus_connect()
            # Old function object is invalid, get new one.
            return getattr(self.odm, fn._method_name)(*args)

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
        id = id.replace("{", "")
        id = id.replace("}", "")
        return id

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

    # DRBDmanage works in kiB units; Cinder uses GiB.
    def _vol_size_to_dm(self, size):
        return int(size * units.Gi / units.Ki)

    def _vol_size_to_cinder(self, size):
        return int(size * units.Ki / units.Gi)

    def is_clean_volume_name(self, name, prefix):
        try:
            if (name.startswith(CONF.volume_name_template % "") and
                    uuid.UUID(name[7:]) is not None):
                return prefix + name[7:]
        except ValueError:
            return None

        try:
            if uuid.UUID(name) is not None:
                return prefix + name
        except ValueError:
            return None

    def _priv_hash_from_volume(self, volume):
        return dm_utils.dict_to_aux_props({
            AUX_PROP_CINDER_VOL_ID: volume['id'],
        })

    def snapshot_name_from_cinder_snapshot(self, snapshot):
        sn_name = self.is_clean_volume_name(snapshot['id'], DM_SN_PREFIX)
        return sn_name

    def _res_and_vl_data_for_volume(self, volume, empty_ok=False):
        """Find DRBD resource and volume ID.

        A DRBD resource might consist of several "volumes"
        (think consistency groups).
        So we have to find the number of the volume within one resource.
        Returns resource name, volume number, and resource
        and volume properties.
        """

        # If we get a string, use it as-is.
        # Else it's a dictionary; then get the ID.
        if isinstance(volume, six.string_types):
            v_uuid = volume
        else:
            v_uuid = volume['id']

        res, rl = self.call_or_reconnect(self.odm.list_volumes,
                                         self.empty_dict,
                                         0,
                                         dm_utils.dict_to_aux_props(
                                             {AUX_PROP_CINDER_VOL_ID: v_uuid}),
                                         self.empty_dict)
        self._check_result(res)

        if (not rl) or (len(rl) == 0):
            if empty_ok:
                LOG.debug("No volume %s found.", v_uuid)
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

        LOG.debug("volume %(uuid)s is %(res)s/%(nr)d; %(rprop)s, %(vprop)s",
                  {'uuid': v_uuid, 'res': r_name, 'nr': v_nr,
                   'rprop': r_props, 'vprop': v_props})

        return r_name, v_nr, r_props, v_props

    def _resource_and_snap_data_from_snapshot(self, snapshot, empty_ok=False):
        """Find DRBD resource and snapshot name from the snapshot ID."""
        s_uuid = snapshot['id']
        res, rs = self.call_or_reconnect(self.odm.list_snapshots,
                                         self.empty_dict,
                                         self.empty_dict,
                                         0,
                                         dm_utils.dict_to_aux_props(
                                             {AUX_PROP_CINDER_VOL_ID: s_uuid}),
                                         self.empty_dict)
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

        LOG.debug("snapshot %(uuid)s is %(res)s/%(snap)s",
                  {'uuid': s_uuid, 'res': r_name, 'snap': s_name})

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
        dres = self.is_clean_volume_name(volume['id'], DM_VN_PREFIX)

        res = self.call_or_reconnect(self.odm.create_resource,
                                     dres,
                                     self.empty_dict)
        self._check_result(res, ignore=[dm_exc.DM_EEXIST], ret=None)

        # If we get DM_EEXIST, then the volume already exists, eg. because
        # deploy gave an error on a previous try (like ENOSPC).
        # Still, there might or might not be the volume in the resource -
        # we have to check that explicitly.
        (_, drbd_vol) = self._resource_name_volnr_for_volume(volume,
                                                             empty_ok=True)
        if not drbd_vol:
            props = self._priv_hash_from_volume(volume)
            # TODO(PM): properties - redundancy, etc
            res = self.call_or_reconnect(self.odm.create_volume,
                                         dres,
                                         self._vol_size_to_dm(volume['size']),
                                         props)
            self._check_result(res)

        # If we crashed between create_volume and the deploy call,
        # the volume might be defined but not exist on any server. Oh my.
        res = self.call_or_reconnect(self.odm.auto_deploy,
                                     dres, self.drbdmanage_redundancy,
                                     0, True)
        self._check_result(res)

        if self.drbdmanage_devs_on_controller:
            # FIXME: Consistency groups, vol#
            res = self.call_or_reconnect(self.odm.assign,
                                         socket.gethostname(),
                                         dres,
                                         self.empty_dict)
            self._check_result(res, ignore=[dm_exc.DM_EEXIST])

        return 0

    def delete_volume(self, volume):
        """Deletes a resource."""
        dres, dvol = self._resource_name_volnr_for_volume(
            volume,
            empty_ok=True)

        if not dres:
            # OK, already gone.
            return True

        # TODO(PM): check if in use? Ask whether Primary, or just check result?
        res = self.call_or_reconnect(self.odm.remove_volume, dres, dvol, False)
        self._check_result(res, ignore=[dm_exc.DM_ENOENT])

        res, rl = self.call_or_reconnect(self.odm.list_volumes,
                                         [dres],
                                         0,
                                         self.empty_dict,
                                         self.empty_list)
        self._check_result(res)

        # We expect the _resource_ to be here still (we just got a volnr from
        # it!), so just query the volumes.
        # If the resource has no volumes anymore, the current DRBDmanage
        # version (errorneously, IMO) returns no *resource*, too.
        if len(rl) > 1:
            message = _('DRBDmanage expected one resource ("%(res)s"), '
                        'got %(n)d') % {'res': dres, 'n': len(rl)}
            raise exception.VolumeBackendAPIException(data=message)

        # Delete resource, if empty
        if (not rl) or (not rl[0]) or (len(rl[0][2]) == 0):
            res = self.call_or_reconnect(self.odm.remove_resource, dres, False)
            self._check_result(res, ignore=[dm_exc.DM_ENOENT])

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""

        LOG.debug("create vol from snap: from %(snap)s make %(vol)s",
                  {'snap': snapshot['id'], 'vol': volume['id']})
        # TODO(PM): Consistency groups.
        dres, sname, sprop = self._resource_and_snap_data_from_snapshot(
            snapshot)

        new_res = self.is_clean_volume_name(volume['id'], DM_VN_PREFIX)

        r_props = self.empty_dict
        # TODO(PM): consistency groups => different volume number possible
        v_props = [(0, self._priv_hash_from_volume(volume))]

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

        self.create_snapshot({'id': temp_id, 'volume_id': src_vref['id']})

        self.create_volume_from_snapshot(volume, snapshot)

        self.delete_snapshot(snapshot)

    def _update_volume_stats(self):
        data = {}

        data["vendor_name"] = 'Open Source'
        data["driver_version"] = self.VERSION
        data["storage_protocol"] = self.target_driver.protocol
        # This has to match the name set in the cinder volume driver spec,
        # so keep it lowercase
        data["volume_backend_name"] = "drbdmanage"
        data["pools"] = []

        res, free, total = self.call_or_reconnect(self.odm.cluster_free_query,
                                                  self.drbdmanage_redundancy)
        self._check_result(res)

        location_info = ('DrbdManageDriver:%(cvol)s:%(dbus)s' %
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

    def get_volume_stats(self, refresh=True):
        """Get volume status."""

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

        dres, dvol = self._resource_name_volnr_for_volume(
            snapshot["volume_id"])

        res, data = self.call_or_reconnect(self.odm.list_assignments,
                                           self.empty_dict,
                                           [dres],
                                           0,
                                           self.empty_dict,
                                           self.empty_dict)
        self._check_result(res)

        nodes = [d[0] for d in data]
        if len(nodes) < 1:
            raise exception.VolumeBackendAPIException(
                _('Snapshot res "%s" that is not deployed anywhere?') %
                (dres))

        props = self._priv_hash_from_volume(snapshot)
        res = self.call_or_reconnect(self.odm.create_snapshot,
                                     dres, sn_name, nodes, props)
        self._check_result(res)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""

        dres, sname, _ = self._resource_and_snap_data_from_snapshot(
            snapshot, empty_ok=True)

        if not dres:
            # resource already gone?
            LOG.warning(_LW("snapshot: %s not found, "
                            "skipping delete operation"), snapshot['id'])
            LOG.info(_LI('Successfully deleted snapshot: %s'), snapshot['id'])
            return True

        res = self.call_or_reconnect(self.odm.remove_snapshot,
                                     dres, sname, True)
        return self._check_result(res, ignore=[dm_exc.DM_ENOENT])

    # #######  Interface methods for DataPath (Target Driver) ########

    def ensure_export(self, context, volume):
        volume_path = self.local_path(volume)
        return self.target_driver.ensure_export(
            context,
            volume,
            volume_path)

    def create_export(self, context, volume, connector):
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
