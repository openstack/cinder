#    Copyright 2014 Objectif Libre
#    Copyright 2015 DotHill Systems
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
Volume driver common utilities for DotHill Storage array
"""

import base64
import six
import uuid

from oslo_config import cfg
from oslo_log import log as logging

from cinder import exception
from cinder.i18n import _, _LE
from cinder.volume.drivers.dothill import dothill_client as dothill

LOG = logging.getLogger(__name__)

common_opts = [
    cfg.StrOpt('dothill_backend_name',
               default='A',
               help="Pool or Vdisk name to use for volume creation."),
    cfg.StrOpt('dothill_backend_type',
               choices=['linear', 'virtual'],
               default='virtual',
               help="linear (for Vdisk) or virtual (for Pool)."),
    cfg.StrOpt('dothill_api_protocol',
               choices=['http', 'https'],
               default='https',
               help="DotHill API interface protocol."),
    cfg.BoolOpt('dothill_verify_certificate',
                default=False,
                help="Whether to verify DotHill array SSL certificate."),
    cfg.StrOpt('dothill_verify_certificate_path',
               help="DotHill array SSL certificate path."),
]

iscsi_opts = [
    cfg.ListOpt('dothill_iscsi_ips',
                default=[],
                help="List of comma-separated target iSCSI IP addresses."),
]

CONF = cfg.CONF
CONF.register_opts(common_opts)
CONF.register_opts(iscsi_opts)


class DotHillCommon(object):
    VERSION = "1.0"

    stats = {}

    def __init__(self, config):
        self.config = config
        self.vendor_name = "DotHill"
        self.backend_name = self.config.dothill_backend_name
        self.backend_type = self.config.dothill_backend_type
        self.api_protocol = self.config.dothill_api_protocol
        ssl_verify = False
        if (self.api_protocol == 'https' and
           self.config.dothill_verify_certificate):
            ssl_verify = self.config.dothill_verify_certificate_path or True
        self.client = dothill.DotHillClient(self.config.san_ip,
                                            self.config.san_login,
                                            self.config.san_password,
                                            self.api_protocol,
                                            ssl_verify)

    def get_version(self):
        return self.VERSION

    def do_setup(self, context):
        self.client_login()
        self._validate_backend()
        self._get_owner_info()
        self._get_serial_number()
        self.client_logout()

    def client_login(self):
        LOG.debug("Connecting to %s Array.", self.vendor_name)
        try:
            self.client.login()
        except exception.DotHillConnectionError as ex:
            msg = _("Failed to connect to %(vendor_name)s Array %(host)s: "
                    "%(err)s") % {'vendor_name': self.vendor_name,
                                  'host': self.config.san_ip,
                                  'err': six.text_type(ex)}
            LOG.error(msg)
            raise exception.DotHillConnectionError(message=msg)
        except exception.DotHillAuthenticationError:
            msg = _("Failed to log on %s Array "
                    "(invalid login?).") % self.vendor_name
            LOG.error(msg)
            raise exception.DotHillAuthenticationError(message=msg)

    def _get_serial_number(self):
        self.serialNumber = self.client.get_serial_number()

    def _get_owner_info(self):
        self.owner = self.client.get_owner_info(self.backend_name,
                                                self.backend_type)

    def _validate_backend(self):
        if not self.client.backend_exists(self.backend_name,
                                          self.backend_type):
            self.client_logout()
            raise exception.DotHillInvalidBackend(backend=self.backend_name)

    def client_logout(self):
        self.client.logout()
        LOG.debug("Disconnected from %s Array.", self.vendor_name)

    def _get_vol_name(self, volume_id):
        volume_name = self._encode_name(volume_id)
        return "v%s" % volume_name

    def _get_snap_name(self, snapshot_id):
        snapshot_name = self._encode_name(snapshot_id)
        return "s%s" % snapshot_name

    def _encode_name(self, name):
        """Get converted DotHill volume name.

        Converts the openstack volume id from
        fceec30e-98bc-4ce5-85ff-d7309cc17cc2
        to
        v_O7DDpi8TOWF_9cwnMF
        We convert the 128(32*4) bits of the uuid into a 24 characters long
        base64 encoded string. This still exceeds the limit of 20 characters
        in some models so we return 19 characters because the
        _get_{vol,snap}_name functions prepend a character.
        """
        uuid_str = name.replace("-", "")
        vol_uuid = uuid.UUID('urn:uuid:%s' % uuid_str)
        vol_encoded = base64.urlsafe_b64encode(vol_uuid.bytes)
        if six.PY3:
            vol_encoded = vol_encoded.decode('ascii')
        return vol_encoded[:19]

    def check_flags(self, options, required_flags):
        for flag in required_flags:
            if not getattr(options, flag, None):
                msg = _('%s configuration option is not set.') % flag
                LOG.error(msg)
                raise exception.InvalidInput(reason=msg)

    def create_volume(self, volume):
        self.client_login()
        # Use base64 to encode the volume name (UUID is too long for DotHill)
        volume_name = self._get_vol_name(volume['id'])
        volume_size = "%dGB" % volume['size']
        LOG.debug("Create Volume having display_name: %(display_name)s "
                  "name: %(name)s id: %(id)s size: %(size)s",
                  {'display_name': volume['display_name'],
                   'name': volume['name'],
                   'id': volume_name,
                   'size': volume_size, })
        try:
            self.client.create_volume(volume_name,
                                      volume_size,
                                      self.backend_name,
                                      self.backend_type)
        except exception.DotHillRequestError as ex:
            LOG.exception(_LE("Creation of volume %s failed."), volume['id'])
            raise exception.Invalid(ex)

        finally:
            self.client_logout()

    def _assert_enough_space_for_copy(self, volume_size):
        """The DotHill creates a snap pool before trying to copy the volume.

        The pool is 5.27GB or 20% of the volume size, whichever is larger.
        Verify that we have enough space for the pool and then copy
        """
        pool_size = max(volume_size * 0.2, 5.27)
        required_size = pool_size + volume_size

        if required_size > self.stats['pools'][0]['free_capacity_gb']:
            raise exception.DotHillNotEnoughSpace(backend=self.backend_name)

    def _assert_source_detached(self, volume):
        """The DotHill requires a volume to be dettached to clone it.

        Make sure that the volume is not in use when trying to copy it.
        """
        if (volume['status'] != "available" or
                volume['attach_status'] == "attached"):
            LOG.error(_LE("Volume must be detached for clone operation."))
            raise exception.VolumeAttached(volume_id=volume['id'])

    def create_cloned_volume(self, volume, src_vref):
        self.get_volume_stats(True)
        self._assert_enough_space_for_copy(volume['size'])
        self._assert_source_detached(src_vref)
        LOG.debug("Cloning Volume %(source_id)s to (%(dest_id)s)",
                  {'source_id': src_vref['id'],
                   'dest_id': volume['id'], })

        if src_vref['name_id']:
            orig_name = self._get_vol_name(src_vref['name_id'])
        else:
            orig_name = self._get_vol_name(src_vref['id'])
        dest_name = self._get_vol_name(volume['id'])

        self.client_login()
        try:
            self.client.copy_volume(orig_name, dest_name,
                                    self.backend_name, self.backend_type)
        except exception.DotHillRequestError as ex:
            LOG.exception(_LE("Cloning of volume %s failed."),
                          src_vref['id'])
            raise exception.Invalid(ex)
        finally:
            self.client_logout()

    def create_volume_from_snapshot(self, volume, snapshot):
        self.get_volume_stats(True)
        self._assert_enough_space_for_copy(volume['size'])
        LOG.debug("Creating Volume from snapshot %(source_id)s to "
                  "(%(dest_id)s)", {'source_id': snapshot['id'],
                                    'dest_id': volume['id'], })

        orig_name = self._get_snap_name(snapshot['id'])
        dest_name = self._get_vol_name(volume['id'])
        self.client_login()
        try:
            self.client.copy_volume(orig_name, dest_name,
                                    self.backend_name, self.backend_type)
        except exception.DotHillRequestError as ex:
            LOG.exception(_LE("Create volume failed from snapshot: %s"),
                          snapshot['id'])
            raise exception.Invalid(ex)
        finally:
            self.client_logout()

    def delete_volume(self, volume):
        LOG.debug("Deleting Volume: %s", volume['id'])
        if volume['name_id']:
            volume_name = self._get_vol_name(volume['name_id'])
        else:
            volume_name = self._get_vol_name(volume['id'])

        self.client_login()
        try:
            self.client.delete_volume(volume_name)
        except exception.DotHillRequestError as ex:
            # if the volume wasn't found, ignore the error
            if 'The volume was not found on this system.' in ex.args:
                return
            LOG.exception(_LE("Deletion of volume %s failed."), volume['id'])
            raise exception.Invalid(ex)
        finally:
            self.client_logout()

    def get_volume_stats(self, refresh):
        if refresh:
            self.client_login()
            try:
                self._update_volume_stats()
            finally:
                self.client_logout()
        return self.stats

    def _update_volume_stats(self):
        # storage_protocol and volume_backend_name are
        # set in the child classes
        stats = {'driver_version': self.VERSION,
                 'storage_protocol': None,
                 'vendor_name': self.vendor_name,
                 'volume_backend_name': None,
                 'pools': []}

        pool = {'QoS_support': False}
        try:
            src_type = "%sVolumeDriver" % self.vendor_name
            backend_stats = self.client.backend_stats(self.backend_name,
                                                      self.backend_type)
            pool.update(backend_stats)
            pool['location_info'] = ('%s:%s:%s:%s' %
                                     (src_type,
                                      self.serialNumber,
                                      self.backend_name,
                                      self.owner))
            pool['pool_name'] = self.backend_name
        except exception.DotHillRequestError:
            err = (_("Unable to get stats for backend_name: %s") %
                   self.backend_name)
            LOG.exception(err)
            raise exception.Invalid(reason=err)

        stats['pools'].append(pool)
        self.stats = stats

    def _assert_connector_ok(self, connector, connector_element):
        if not connector[connector_element]:
            msg = _("Connector does not provide: %s") % connector_element
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)

    def map_volume(self, volume, connector, connector_element):
        self._assert_connector_ok(connector, connector_element)
        if volume['name_id']:
            volume_name = self._get_vol_name(volume['name_id'])
        else:
            volume_name = self._get_vol_name(volume['id'])
        try:
            data = self.client.map_volume(volume_name,
                                          connector,
                                          connector_element)
            return data
        except exception.DotHillRequestError as ex:
            LOG.exception(_LE("Error mapping volume: %s"), volume_name)
            raise exception.Invalid(ex)

    def unmap_volume(self, volume, connector, connector_element):
        self._assert_connector_ok(connector, connector_element)
        if volume['name_id']:
            volume_name = self._get_vol_name(volume['name_id'])
        else:
            volume_name = self._get_vol_name(volume['id'])

        self.client_login()
        try:
            self.client.unmap_volume(volume_name,
                                     connector,
                                     connector_element)
        except exception.DotHillRequestError as ex:
            LOG.exception(_LE("Error unmapping volume: %s"), volume_name)
            raise exception.Invalid(ex)
        finally:
            self.client_logout()

    def get_active_fc_target_ports(self):
        try:
            return self.client.get_active_fc_target_ports()
        except exception.DotHillRequestError as ex:
            LOG.exception(_LE("Error getting active FC target ports."))
            raise exception.Invalid(ex)

    def get_active_iscsi_target_iqns(self):
        try:
            return self.client.get_active_iscsi_target_iqns()
        except exception.DotHillRequestError as ex:
            LOG.exception(_LE("Error getting active ISCSI target iqns."))
            raise exception.Invalid(ex)

    def get_active_iscsi_target_portals(self):
        try:
            return self.client.get_active_iscsi_target_portals()
        except exception.DotHillRequestError as ex:
            LOG.exception(_LE("Error getting active ISCSI target portals."))
            raise exception.Invalid(ex)

    def create_snapshot(self, snapshot):
        LOG.debug("Creating snapshot (%(snap_id)s) from %(volume_id)s)",
                  {'snap_id': snapshot['id'],
                   'volume_id': snapshot['volume_id'], })
        if snapshot['volume']['name_id']:
            vol_name = self._get_vol_name(snapshot['volume']['name_id'])
        else:
            vol_name = self._get_vol_name(snapshot['volume_id'])
        snap_name = self._get_snap_name(snapshot['id'])

        self.client_login()
        try:
            self.client.create_snapshot(vol_name, snap_name)
        except exception.DotHillRequestError as ex:
            LOG.exception(_LE("Creation of snapshot failed for volume: %s"),
                          snapshot['volume_id'])
            raise exception.Invalid(ex)
        finally:
            self.client_logout()

    def delete_snapshot(self, snapshot):
        snap_name = self._get_snap_name(snapshot['id'])
        LOG.debug("Deleting snapshot (%s)", snapshot['id'])

        self.client_login()
        try:
            self.client.delete_snapshot(snap_name)
        except exception.DotHillRequestError as ex:
            # if the volume wasn't found, ignore the error
            if 'The volume was not found on this system.' in ex.args:
                return
            LOG.exception(_LE("Deleting snapshot %s failed"), snapshot['id'])
            raise exception.Invalid(ex)
        finally:
            self.client_logout()

    def extend_volume(self, volume, new_size):
        if volume['name_id']:
            volume_name = self._get_vol_name(volume['name_id'])
        else:
            volume_name = self._get_vol_name(volume['id'])
        old_size = volume['size']
        growth_size = int(new_size) - old_size
        LOG.debug("Extending Volume %(volume_name)s from %(old_size)s to "
                  "%(new_size)s, by %(growth_size)s GB.",
                  {'volume_name': volume_name,
                   'old_size': old_size,
                   'new_size': new_size,
                   'growth_size': growth_size, })
        self.client_login()
        try:
            self.client.extend_volume(volume_name, "%dGB" % growth_size)
        except exception.DotHillRequestError as ex:
            LOG.exception(_LE("Extension of volume %s failed."), volume['id'])
            raise exception.Invalid(ex)
        finally:
            self.client_logout()

    def get_chap_record(self, initiator_name):
        try:
            return self.client.get_chap_record(initiator_name)
        except exception.DotHillRequestError as ex:
            LOG.exception(_LE("Error getting chap record."))
            raise exception.Invalid(ex)

    def create_chap_record(self, initiator_name, chap_secret):
        try:
            self.client.create_chap_record(initiator_name, chap_secret)
        except exception.DotHillRequestError as ex:
            LOG.exception(_LE("Error creating chap record."))
            raise exception.Invalid(ex)

    def migrate_volume(self, volume, host):
        """Migrate directly if source and dest are managed by same storage.

        :param volume: A dictionary describing the volume to migrate
        :param host: A dictionary describing the host to migrate to, where
                     host['host'] is its name, and host['capabilities'] is a
                     dictionary of its reported capabilities.
        :returns (False, None) if the driver does not support migration,
                 (True, None) if successful

        """
        false_ret = (False, None)
        if volume['attach_status'] == "attached":
            return false_ret
        if 'location_info' not in host['capabilities']:
            return false_ret
        info = host['capabilities']['location_info']
        try:
            (dest_type, dest_id,
             dest_back_name, dest_owner) = info.split(':')
        except ValueError:
            return false_ret

        if not (dest_type == 'DotHillVolumeDriver' and
                dest_id == self.serialNumber and
                dest_owner == self.owner):
            return false_ret
        if volume['name_id']:
            source_name = self._get_vol_name(volume['name_id'])
        else:
            source_name = self._get_vol_name(volume['id'])
        # DotHill Array does not support duplicate names
        dest_name = "m%s" % source_name[1:]

        self.client_login()
        try:
            self.client.copy_volume(source_name, dest_name,
                                    dest_back_name, self.backend_type)
            self.client.delete_volume(source_name)
            self.client.modify_volume_name(dest_name, source_name)
            return (True, None)
        except exception.DotHillRequestError as ex:
            LOG.exception(_LE("Error migrating volume: %s"), source_name)
            raise exception.Invalid(ex)
        finally:
            self.client_logout()

    def retype(self, volume, new_type, diff, host):
        ret = self.migrate_volume(volume, host)
        return ret[0]

    def manage_existing(self, volume, existing_ref):
        """Manage an existing non-openstack DotHill volume

        existing_ref is a dictionary of the form:
        {'source-name': <name of the existing DotHill volume>}
        """
        target_vol_name = existing_ref['source-name']
        modify_target_vol_name = self._get_vol_name(volume['id'])

        self.client_login()
        try:
            self.client.modify_volume_name(target_vol_name,
                                           modify_target_vol_name)
        except exception.DotHillRequestError as ex:
            LOG.exception(_LE("Error manage existing volume."))
            raise exception.Invalid(ex)
        finally:
            self.client_logout()

    def manage_existing_get_size(self, volume, existing_ref):
        """Return size of volume to be managed by manage_existing.

        existing_ref is a dictionary of the form:
        {'source-name': <name of the volume>}
        """
        target_vol_name = existing_ref['source-name']

        self.client_login()
        try:
            size = self.client.get_volume_size(target_vol_name)
            return size
        except exception.DotHillRequestError as ex:
            LOG.exception(_LE("Error manage existing get volume size."))
            raise exception.Invalid(ex)
        finally:
            self.client_logout()
