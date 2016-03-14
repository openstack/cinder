# Copyright (c) 2013 - 2015 EMC Corporation.
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
Driver for EMC ScaleIO based on ScaleIO remote CLI.
"""

import base64
import binascii
import json

from os_brick.initiator import connector
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import units
import requests
import six
from six.moves import urllib

from cinder import context
from cinder import exception
from cinder.i18n import _, _LI, _LW, _LE
from cinder.image import image_utils
from cinder import utils
from cinder.volume import driver
from cinder.volume.drivers.san import san
from cinder.volume import qos_specs
from cinder.volume import volume_types

CONF = cfg.CONF

LOG = logging.getLogger(__name__)

scaleio_opts = [
    cfg.StrOpt('sio_rest_server_port',
               default='443',
               help='REST server port.'),
    cfg.BoolOpt('sio_verify_server_certificate',
                default=False,
                help='Verify server certificate.'),
    cfg.StrOpt('sio_server_certificate_path',
               help='Server certificate path.'),
    cfg.BoolOpt('sio_round_volume_capacity',
                default=True,
                help='Round up volume capacity.'),
    cfg.BoolOpt('sio_unmap_volume_before_deletion',
                default=False,
                help='Unmap volume before deletion.'),
    cfg.StrOpt('sio_protection_domain_id',
               help='Protection Domain ID.'),
    cfg.StrOpt('sio_protection_domain_name',
               help='Protection Domain name.'),
    cfg.StrOpt('sio_storage_pools',
               help='Storage Pools.'),
    cfg.StrOpt('sio_storage_pool_name',
               help='Storage Pool name.'),
    cfg.StrOpt('sio_storage_pool_id',
               help='Storage Pool ID.')
]

CONF.register_opts(scaleio_opts)

STORAGE_POOL_NAME = 'sio:sp_name'
STORAGE_POOL_ID = 'sio:sp_id'
PROTECTION_DOMAIN_NAME = 'sio:pd_name'
PROTECTION_DOMAIN_ID = 'sio:pd_id'
PROVISIONING_KEY = 'sio:provisioning_type'
IOPS_LIMIT_KEY = 'sio:iops_limit'
BANDWIDTH_LIMIT = 'sio:bandwidth_limit'
QOS_IOPS_LIMIT_KEY = 'maxIOPS'
QOS_BANDWIDTH_LIMIT = 'maxBWS'

BLOCK_SIZE = 8
OK_STATUS_CODE = 200
VOLUME_NOT_FOUND_ERROR = 79
VOLUME_NOT_MAPPED_ERROR = 84
VOLUME_ALREADY_MAPPED_ERROR = 81


class ScaleIODriver(driver.VolumeDriver):
    """EMC ScaleIO Driver."""

    VERSION = "2.0"
    scaleio_qos_keys = (QOS_IOPS_LIMIT_KEY, QOS_BANDWIDTH_LIMIT)

    def __init__(self, *args, **kwargs):
        super(ScaleIODriver, self).__init__(*args, **kwargs)

        self.configuration.append_config_values(san.san_opts)
        self.configuration.append_config_values(scaleio_opts)
        self.server_ip = self.configuration.san_ip
        self.server_port = self.configuration.sio_rest_server_port
        self.server_username = self.configuration.san_login
        self.server_password = self.configuration.san_password
        self.server_token = None
        self.verify_server_certificate = (
            self.configuration.sio_verify_server_certificate)
        self.server_certificate_path = None
        if self.verify_server_certificate:
            self.server_certificate_path = (
                self.configuration.sio_server_certificate_path)
        LOG.info(_LI(
                 "REST server IP: %(ip)s, port: %(port)s, username: %("
                 "user)s. "
                 "Verify server's certificate: %(verify_cert)s."),
                 {'ip': self.server_ip,
                  'port': self.server_port,
                  'user': self.server_username,
                  'verify_cert': self.verify_server_certificate})

        self.storage_pools = None
        if self.configuration.sio_storage_pools:
            self.storage_pools = [
                e.strip() for e in
                self.configuration.sio_storage_pools.split(',')]

        self.storage_pool_name = self.configuration.sio_storage_pool_name
        self.storage_pool_id = self.configuration.sio_storage_pool_id
        if self.storage_pool_name is None and self.storage_pool_id is None:
            LOG.warning(_LW("No storage pool name or id was found."))
        else:
            LOG.info(_LI(
                     "Storage pools names: %(pools)s, "
                     "storage pool name: %(pool)s, pool id: %(pool_id)s."),
                     {'pools': self.storage_pools,
                      'pool': self.storage_pool_name,
                      'pool_id': self.storage_pool_id})

        self.protection_domain_name = (
            self.configuration.sio_protection_domain_name)
        LOG.info(_LI(
                 "Protection domain name: %(domain_name)s."),
                 {'domain_name': self.protection_domain_name})
        self.protection_domain_id = self.configuration.sio_protection_domain_id
        LOG.info(_LI(
                 "Protection domain id: %(domain_id)s."),
                 {'domain_id': self.protection_domain_id})

        self.connector = connector.InitiatorConnector.factory(
            connector.SCALEIO, utils.get_root_helper(),
            device_scan_attempts=
            self.configuration.num_volume_device_scan_tries
        )

        self.connection_properties = {}
        self.connection_properties['scaleIO_volname'] = None
        self.connection_properties['hostIP'] = None
        self.connection_properties['serverIP'] = self.server_ip
        self.connection_properties['serverPort'] = self.server_port
        self.connection_properties['serverUsername'] = self.server_username
        self.connection_properties['serverPassword'] = self.server_password
        self.connection_properties['serverToken'] = self.server_token
        self.connection_properties['iopsLimit'] = None
        self.connection_properties['bandwidthLimit'] = None

    def check_for_setup_error(self):
        if (not self.protection_domain_name and
                not self.protection_domain_id):
            LOG.warning(_LW("No protection domain name or id "
                            "was specified in configuration."))

        if self.protection_domain_name and self.protection_domain_id:
            msg = _("Cannot specify both protection domain name "
                    "and protection domain id.")
            raise exception.InvalidInput(reason=msg)

        if not self.server_ip:
            msg = _("REST server IP must by specified.")
            raise exception.InvalidInput(reason=msg)

        if not self.server_username:
            msg = _("REST server username must by specified.")
            raise exception.InvalidInput(reason=msg)

        if not self.server_password:
            msg = _("REST server password must by specified.")
            raise exception.InvalidInput(reason=msg)

        if not self.verify_server_certificate:
            LOG.warning(_LW("Verify certificate is not set, using default of "
                            "False."))

        if self.verify_server_certificate and not self.server_certificate_path:
            msg = _("Path to REST server's certificate must be specified.")
            raise exception.InvalidInput(reason=msg)

        if self.storage_pool_name and self.storage_pool_id:
            msg = _("Cannot specify both storage pool name and storage "
                    "pool id.")
            raise exception.InvalidInput(reason=msg)

        if not self.storage_pool_name and not self.storage_pool_id:
            msg = _("Must specify storage pool name or id.")
            raise exception.InvalidInput(reason=msg)

        if not self.storage_pools:
            msg = (_("Must specify storage pools. Option: "
                     "sio_storage_pools."))
            raise exception.InvalidInput(reason=msg)

    def _find_storage_pool_id_from_storage_type(self, storage_type):
        # Default to what was configured in configuration file if not defined.
        return storage_type.get(STORAGE_POOL_ID,
                                self.storage_pool_id)

    def _find_storage_pool_name_from_storage_type(self, storage_type):
        return storage_type.get(STORAGE_POOL_NAME,
                                self.storage_pool_name)

    def _find_protection_domain_id_from_storage_type(self, storage_type):
        # Default to what was configured in configuration file if not defined.
        return storage_type.get(PROTECTION_DOMAIN_ID,
                                self.protection_domain_id)

    def _find_protection_domain_name_from_storage_type(self, storage_type):
        # Default to what was configured in configuration file if not defined.
        return storage_type.get(PROTECTION_DOMAIN_NAME,
                                self.protection_domain_name)

    def _find_provisioning_type(self, storage_type):
        return storage_type.get(PROVISIONING_KEY)

    def _find_limit(self, storage_type, qos_key, extraspecs_key):
        qos_limit = storage_type.get(qos_key)
        extraspecs_limit = storage_type.get(extraspecs_key)
        if extraspecs_limit is not None:
            if qos_limit is not None:
                LOG.warning(_LW("QoS specs are overriding extra_specs."))
            else:
                LOG.info(_LI("Using extra_specs for defining QoS specs "
                             "will be deprecated in the N release "
                             "of OpenStack. Please use QoS specs."))
        return qos_limit if qos_limit is not None else extraspecs_limit

    def _id_to_base64(self, id):
        # Base64 encode the id to get a volume name less than 32 characters due
        # to ScaleIO limitation.
        name = six.text_type(id).replace("-", "")
        try:
            name = base64.b16decode(name.upper())
        except (TypeError, binascii.Error):
            pass
        encoded_name = name
        if isinstance(encoded_name, six.text_type):
            encoded_name = encoded_name.encode('utf-8')
        encoded_name = base64.b64encode(encoded_name)
        if six.PY3:
            encoded_name = encoded_name.decode('ascii')
        LOG.debug("Converted id %(id)s to scaleio name %(name)s.",
                  {'id': id, 'name': encoded_name})
        return encoded_name

    def create_volume(self, volume):
        """Creates a scaleIO volume."""
        self._check_volume_size(volume.size)

        volname = self._id_to_base64(volume.id)

        storage_type = self._get_volumetype_extraspecs(volume)
        storage_pool_name = self._find_storage_pool_name_from_storage_type(
            storage_type)
        storage_pool_id = self._find_storage_pool_id_from_storage_type(
            storage_type)
        protection_domain_id = (
            self._find_protection_domain_id_from_storage_type(storage_type))
        protection_domain_name = (
            self._find_protection_domain_name_from_storage_type(storage_type))
        provisioning_type = self._find_provisioning_type(storage_type)

        LOG.info(_LI(
                 "Volume type: %(volume_type)s, "
                 "storage pool name: %(pool_name)s, "
                 "storage pool id: %(pool_id)s, protection domain id: "
                 "%(domain_id)s, protection domain name: %(domain_name)s."),
                 {'volume_type': storage_type,
                  'pool_name': storage_pool_name,
                  'pool_id': storage_pool_id,
                  'domain_id': protection_domain_id,
                  'domain_name': protection_domain_name})

        verify_cert = self._get_verify_cert()

        if storage_pool_name:
            self.storage_pool_name = storage_pool_name
            self.storage_pool_id = None
        if storage_pool_id:
            self.storage_pool_id = storage_pool_id
            self.storage_pool_name = None
        if protection_domain_name:
            self.protection_domain_name = protection_domain_name
            self.protection_domain_id = None
        if protection_domain_id:
            self.protection_domain_id = protection_domain_id
            self.protection_domain_name = None

        domain_id = self.protection_domain_id
        if not domain_id:
            if not self.protection_domain_name:
                msg = _("Must specify protection domain name or"
                        " protection domain id.")
                raise exception.VolumeBackendAPIException(data=msg)

            domain_name = self.protection_domain_name
            encoded_domain_name = urllib.parse.quote(domain_name, '')
            req_vars = {'server_ip': self.server_ip,
                        'server_port': self.server_port,
                        'encoded_domain_name': encoded_domain_name}
            request = ("https://%(server_ip)s:%(server_port)s"
                       "/api/types/Domain/instances/getByName::"
                       "%(encoded_domain_name)s") % req_vars
            LOG.info(_LI("ScaleIO get domain id by name request: %s."),
                     request)
            r = requests.get(
                request,
                auth=(
                    self.server_username,
                    self.server_token),
                verify=verify_cert)
            r = self._check_response(r, request)

            domain_id = r.json()
            if not domain_id:
                msg = (_("Domain with name %s wasn't found.")
                       % self.protection_domain_name)
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            if r.status_code != OK_STATUS_CODE and "errorCode" in domain_id:
                msg = (_("Error getting domain id from name %(name)s: %(id)s.")
                       % {'name': self.protection_domain_name,
                          'id': domain_id['message']})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        LOG.info(_LI("Domain id is %s."), domain_id)
        pool_name = self.storage_pool_name
        pool_id = self.storage_pool_id
        if pool_name:
            encoded_domain_name = urllib.parse.quote(pool_name, '')
            req_vars = {'server_ip': self.server_ip,
                        'server_port': self.server_port,
                        'domain_id': domain_id,
                        'encoded_domain_name': encoded_domain_name}
            request = ("https://%(server_ip)s:%(server_port)s"
                       "/api/types/Pool/instances/getByName::"
                       "%(domain_id)s,%(encoded_domain_name)s") % req_vars
            LOG.info(_LI("ScaleIO get pool id by name request: %s."), request)
            r = requests.get(
                request,
                auth=(
                    self.server_username,
                    self.server_token),
                verify=verify_cert)
            pool_id = r.json()
            if not pool_id:
                msg = (_("Pool with name %(pool_name)s wasn't found in "
                         "domain %(domain_id)s.")
                       % {'pool_name': pool_name,
                          'domain_id': domain_id})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            if r.status_code != OK_STATUS_CODE and "errorCode" in pool_id:
                msg = (_("Error getting pool id from name %(pool_name)s: "
                         "%(err_msg)s.")
                       % {'pool_name': pool_name,
                          'err_msg': pool_id['message']})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        LOG.info(_LI("Pool id is %s."), pool_id)
        if provisioning_type == 'thin':
            provisioning = "ThinProvisioned"
        # Default volume type is thick.
        else:
            provisioning = "ThickProvisioned"

        # units.Mi = 1024 ** 2
        volume_size_kb = volume.size * units.Mi
        params = {'protectionDomainId': domain_id,
                  'volumeSizeInKb': six.text_type(volume_size_kb),
                  'name': volname,
                  'volumeType': provisioning,
                  'storagePoolId': pool_id}

        LOG.info(_LI("Params for add volume request: %s."), params)
        r = requests.post(
            "https://" +
            self.server_ip +
            ":" +
            self.server_port +
            "/api/types/Volume/instances",
            data=json.dumps(params),
            headers=self._get_headers(),
            auth=(
                self.server_username,
                self.server_token),
            verify=verify_cert)
        response = r.json()
        LOG.info(_LI("Add volume response: %s"), response)

        if r.status_code != OK_STATUS_CODE and "errorCode" in response:
            msg = (_("Error creating volume: %s.") % response['message'])
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.info(_LI("Created volume %(volname)s, volume id %(volid)s."),
                 {'volname': volname, 'volid': volume.id})

        return {'provider_id': response['id']}

    def _check_volume_size(self, size):
        if size % 8 != 0:
            round_volume_capacity = (
                self.configuration.sio_round_volume_capacity)
            if not round_volume_capacity:
                exception_msg = (_(
                                 "Cannot create volume of size %s: "
                                 "not multiple of 8GB.") % size)
                LOG.error(exception_msg)
                raise exception.VolumeBackendAPIException(data=exception_msg)

    def create_snapshot(self, snapshot):
        """Creates a scaleio snapshot."""
        volume_id = snapshot.volume.provider_id
        snapname = self._id_to_base64(snapshot.id)
        return self._snapshot_volume(volume_id, snapname)

    def _snapshot_volume(self, vol_id, snapname):
        LOG.info(_LI("Snapshot volume %(vol)s into snapshot %(id)s.") %
                 {'vol': vol_id, 'id': snapname})
        params = {
            'snapshotDefs': [{"volumeId": vol_id, "snapshotName": snapname}]}
        req_vars = {'server_ip': self.server_ip,
                    'server_port': self.server_port}
        request = ("https://%(server_ip)s:%(server_port)s"
                   "/api/instances/System/action/snapshotVolumes") % req_vars
        r, response = self._execute_scaleio_post_request(params, request)
        LOG.info(_LI("Snapshot volume response: %s."), response)
        if r.status_code != OK_STATUS_CODE and "errorCode" in response:
            msg = (_("Failed creating snapshot for volume %(volname)s: "
                     "%(response)s.") %
                   {'volname': vol_id,
                    'response': response['message']})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        return {'provider_id': response['volumeIdList'][0]}

    def _execute_scaleio_post_request(self, params, request):
        r = requests.post(
            request,
            data=json.dumps(params),
            headers=self._get_headers(),
            auth=(
                self.server_username,
                self.server_token),
            verify=self._get_verify_cert())
        r = self._check_response(r, request, False, params)
        response = r.json()
        return r, response

    def _check_response(self, response, request, is_get_request=True,
                        params=None):
        if response.status_code == 401 or response.status_code == 403:
            LOG.info(_LI("Token is invalid, going to re-login and get "
                         "a new one."))
            login_request = (
                "https://" + self.server_ip +
                ":" + self.server_port + "/api/login")
            verify_cert = self._get_verify_cert()
            r = requests.get(
                login_request,
                auth=(
                    self.server_username,
                    self.server_password),
                verify=verify_cert)
            token = r.json()
            self.server_token = token
            # Repeat request with valid token.
            LOG.info(_LI(
                     "Going to perform request again %s with valid token."),
                     request)
            if is_get_request:
                res = requests.get(request,
                                   auth=(self.server_username,
                                         self.server_token),
                                   verify=verify_cert)
            else:
                res = requests.post(request,
                                    data=json.dumps(params),
                                    headers=self._get_headers(),
                                    auth=(self.server_username,
                                          self.server_token),
                                    verify=verify_cert)
            return res
        return response

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        # We interchange 'volume' and 'snapshot' because in ScaleIO
        # snapshot is a volume: once a snapshot is generated it
        # becomes a new unmapped volume in the system and the user
        # may manipulate it in the same manner as any other volume
        # exposed by the system
        volume_id = snapshot.provider_id
        snapname = self._id_to_base64(volume.id)
        LOG.info(_LI(
                 "ScaleIO create volume from snapshot: snapshot %(snapname)s "
                 "to volume %(volname)s."),
                 {'volname': volume_id,
                  'snapname': snapname})

        return self._snapshot_volume(volume_id, snapname)

    def _get_headers(self):
        return {'content-type': 'application/json'}

    def _get_verify_cert(self):
        verify_cert = False
        if self.verify_server_certificate:
            verify_cert = self.server_certificate_path
        return verify_cert

    def extend_volume(self, volume, new_size):
        """Extends the size of an existing available ScaleIO volume.

        This action will round up the volume to the nearest size that is
        a granularity of 8 GBs.
        """
        return self._extend_volume(volume['provider_id'], volume.size,
                                   new_size)

    def _extend_volume(self, volume_id, old_size, new_size):
        vol_id = volume_id
        LOG.info(_LI(
            "ScaleIO extend volume: volume %(volname)s to size %(new_size)s."),
            {'volname': vol_id,
             'new_size': new_size})

        req_vars = {'server_ip': self.server_ip,
                    'server_port': self.server_port,
                    'vol_id': vol_id}
        request = ("https://%(server_ip)s:%(server_port)s"
                   "/api/instances/Volume::%(vol_id)s"
                   "/action/setVolumeSize") % req_vars
        LOG.info(_LI("Change volume capacity request: %s."), request)

        # Round up the volume size so that it is a granularity of 8 GBs
        # because ScaleIO only supports volumes with a granularity of 8 GBs.
        volume_new_size = self._round_to_8_gran(new_size)
        volume_real_old_size = self._round_to_8_gran(old_size)
        if volume_real_old_size == volume_new_size:
            return

        round_volume_capacity = self.configuration.sio_round_volume_capacity
        if (not round_volume_capacity and not new_size % 8 == 0):
            LOG.warning(_LW("ScaleIO only supports volumes with a granularity "
                            "of 8 GBs. The new volume size is: %d."),
                        volume_new_size)

        params = {'sizeInGB': six.text_type(volume_new_size)}
        r, response = self._execute_scaleio_post_request(params, request)

        if r.status_code != OK_STATUS_CODE:
            response = r.json()
            msg = (_("Error extending volume %(vol)s: %(err)s.")
                   % {'vol': vol_id,
                      'err': response['message']})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def _round_to_8_gran(self, size):
        if size % 8 == 0:
            return size
        return size + 8 - (size % 8)

    def create_cloned_volume(self, volume, src_vref):
        """Creates a cloned volume."""
        volume_id = src_vref['provider_id']
        snapname = self._id_to_base64(volume.id)
        LOG.info(_LI(
                 "ScaleIO create cloned volume: source volume %(src)s to "
                 "target volume %(tgt)s."),
                 {'src': volume_id,
                  'tgt': snapname})

        ret = self._snapshot_volume(volume_id, snapname)
        if volume.size > src_vref.size:
            self._extend_volume(ret['provider_id'], src_vref.size, volume.size)

        return ret

    def delete_volume(self, volume):
        """Deletes a self.logical volume"""
        volume_id = volume['provider_id']
        self._delete_volume(volume_id)

    def _delete_volume(self, vol_id):
        verify_cert = self._get_verify_cert()

        req_vars = {'server_ip': self.server_ip,
                    'server_port': self.server_port,
                    'vol_id': six.text_type(vol_id)}

        unmap_before_delete = (
            self.configuration.sio_unmap_volume_before_deletion)
        # Ensure that the volume is not mapped to any SDC before deletion in
        # case unmap_before_deletion is enabled.
        if unmap_before_delete:
            params = {'allSdcs': ''}
            request = ("https://%(server_ip)s:%(server_port)s"
                       "/api/instances/Volume::%(vol_id)s"
                       "/action/removeMappedSdc") % req_vars
            LOG.info(_LI(
                     "Trying to unmap volume from all sdcs"
                     " before deletion: %s."),
                     request)
            r = requests.post(
                request,
                data=json.dumps(params),
                headers=self._get_headers(),
                auth=(
                    self.server_username,
                    self.server_token),
                verify=verify_cert
            )
            r = self._check_response(r, request, False, params)
            LOG.debug("Unmap volume response: %s.", r.text)

        params = {'removeMode': 'ONLY_ME'}
        request = ("https://%(server_ip)s:%(server_port)s"
                   "/api/instances/Volume::%(vol_id)s"
                   "/action/removeVolume") % req_vars
        r = requests.post(
            request,
            data=json.dumps(params),
            headers=self._get_headers(),
            auth=(self.server_username,
                  self.server_token),
            verify=verify_cert
        )
        r = self._check_response(r, request, False, params)

        if r.status_code != OK_STATUS_CODE:
            response = r.json()
            error_code = response['errorCode']
            if error_code == VOLUME_NOT_FOUND_ERROR:
                LOG.warning(_LW(
                            "Ignoring error in delete volume %s:"
                            " Volume not found."), vol_id)
            elif vol_id is None:
                LOG.warning(_LW(
                            "Volume does not have provider_id thus does not "
                            "map to a ScaleIO volume. "
                            "Allowing deletion to proceed."))
            else:
                msg = (_("Error deleting volume %(vol)s: %(err)s.") %
                       {'vol': vol_id,
                        'err': response['message']})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

    def delete_snapshot(self, snapshot):
        """Deletes a ScaleIO snapshot."""
        snap_id = snapshot.provider_id
        LOG.info(_LI("ScaleIO delete snapshot."))
        return self._delete_volume(snap_id)

    def initialize_connection(self, volume, connector):
        """Initializes the connection and returns connection info.

        The scaleio driver returns a driver_volume_type of 'scaleio'.
        """

        LOG.debug("Connector is %s.", connector)
        connection_properties = dict(self.connection_properties)

        volname = self._id_to_base64(volume.id)
        connection_properties['scaleIO_volname'] = volname
        extra_specs = self._get_volumetype_extraspecs(volume)
        qos_specs = self._get_volumetype_qos(volume)
        storage_type = extra_specs.copy()
        storage_type.update(qos_specs)
        LOG.info(_LI("Volume type is %s."), storage_type)
        iops_limit = self._find_limit(storage_type, QOS_IOPS_LIMIT_KEY,
                                      IOPS_LIMIT_KEY)
        LOG.info(_LI("iops limit is: %s."), iops_limit)
        bandwidth_limit = self._find_limit(storage_type, QOS_BANDWIDTH_LIMIT,
                                           BANDWIDTH_LIMIT)
        LOG.info(_LI("Bandwidth limit is: %s."), bandwidth_limit)
        connection_properties['iopsLimit'] = iops_limit
        connection_properties['bandwidthLimit'] = bandwidth_limit

        return {'driver_volume_type': 'scaleio',
                'data': connection_properties}

    def terminate_connection(self, volume, connector, **kwargs):
        LOG.debug("scaleio driver terminate connection.")

    def _update_volume_stats(self):
        stats = {}

        backend_name = self.configuration.safe_get('volume_backend_name')
        stats['volume_backend_name'] = backend_name or 'scaleio'
        stats['vendor_name'] = 'EMC'
        stats['driver_version'] = self.VERSION
        stats['storage_protocol'] = 'scaleio'
        stats['total_capacity_gb'] = 'unknown'
        stats['free_capacity_gb'] = 'unknown'
        stats['reserved_percentage'] = 0
        stats['QoS_support'] = True
        stats['consistencygroup_support'] = True

        pools = []

        verify_cert = self._get_verify_cert()

        max_free_capacity = 0
        total_capacity = 0

        for sp_name in self.storage_pools:
            splitted_name = sp_name.split(':')
            domain_name = splitted_name[0]
            pool_name = splitted_name[1]
            LOG.debug("domain name is %(domain)s, pool name is %(pool)s.",
                      {'domain': domain_name,
                       'pool': pool_name})
            # Get domain id from name.
            encoded_domain_name = urllib.parse.quote(domain_name, '')
            req_vars = {'server_ip': self.server_ip,
                        'server_port': self.server_port,
                        'encoded_domain_name': encoded_domain_name}
            request = ("https://%(server_ip)s:%(server_port)s"
                       "/api/types/Domain/instances/getByName::"
                       "%(encoded_domain_name)s") % req_vars
            LOG.info(_LI("ScaleIO get domain id by name request: %s."),
                     request)
            LOG.info(_LI("username: %(username)s, verify_cert: %(verify)s."),
                     {'username': self.server_username,
                      'verify': verify_cert})
            r = requests.get(
                request,
                auth=(
                    self.server_username,
                    self.server_token),
                verify=verify_cert)
            r = self._check_response(r, request)
            LOG.info(_LI("Get domain by name response: %s"), r.text)
            domain_id = r.json()
            if not domain_id:
                msg = (_("Domain with name %s wasn't found.")
                       % self.protection_domain_name)
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            if r.status_code != OK_STATUS_CODE and "errorCode" in domain_id:
                msg = (_("Error getting domain id from name %(name)s: "
                         "%(err)s.")
                       % {'name': self.protection_domain_name,
                          'err': domain_id['message']})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            LOG.info(_LI("Domain id is %s."), domain_id)

            # Get pool id from name.
            encoded_pool_name = urllib.parse.quote(pool_name, '')
            req_vars = {'server_ip': self.server_ip,
                        'server_port': self.server_port,
                        'domain_id': domain_id,
                        'encoded_pool_name': encoded_pool_name}
            request = ("https://%(server_ip)s:%(server_port)s"
                       "/api/types/Pool/instances/getByName::"
                       "%(domain_id)s,%(encoded_pool_name)s") % req_vars
            LOG.info(_LI("ScaleIO get pool id by name request: %s."), request)
            r = requests.get(
                request,
                auth=(
                    self.server_username,
                    self.server_token),
                verify=verify_cert)
            pool_id = r.json()
            if not pool_id:
                msg = (_("Pool with name %(pool)s wasn't found in domain "
                         "%(domain)s.")
                       % {'pool': pool_name,
                          'domain': domain_id})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            if r.status_code != OK_STATUS_CODE and "errorCode" in pool_id:
                msg = (_("Error getting pool id from name %(pool)s: "
                         "%(err)s.")
                       % {'pool': pool_name,
                          'err': pool_id['message']})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            LOG.info(_LI("Pool id is %s."), pool_id)
            req_vars = {'server_ip': self.server_ip,
                        'server_port': self.server_port}
            request = ("https://%(server_ip)s:%(server_port)s"
                       "/api/types/StoragePool/instances/action/"
                       "querySelectedStatistics") % req_vars
            params = {'ids': [pool_id], 'properties': [
                "capacityInUseInKb", "capacityLimitInKb"]}
            r = requests.post(
                request,
                data=json.dumps(params),
                headers=self._get_headers(),
                auth=(
                    self.server_username,
                    self.server_token),
                verify=verify_cert)
            response = r.json()
            LOG.info(_LI("Query capacity stats response: %s."), response)
            for res in response.values():
                capacityInUse = res['capacityInUseInKb']
                capacityLimit = res['capacityLimitInKb']
                total_capacity_gb = capacityLimit / units.Mi
                used_capacity_gb = capacityInUse / units.Mi
                free_capacity_gb = total_capacity_gb - used_capacity_gb
                LOG.info(_LI(
                         "free capacity of pool %(pool)s is: %(free)s, "
                         "total capacity: %(total)s."),
                         {'pool': pool_name,
                          'free': free_capacity_gb,
                          'total': total_capacity_gb})
            pool = {'pool_name': sp_name,
                    'total_capacity_gb': total_capacity_gb,
                    'free_capacity_gb': free_capacity_gb,
                    'QoS_support': True,
                    'consistencygroup_support': True,
                    'reserved_percentage': 0
                    }

            pools.append(pool)
            if free_capacity_gb > max_free_capacity:
                max_free_capacity = free_capacity_gb
            total_capacity = total_capacity + total_capacity_gb

        # Use zero capacities here so we always use a pool.
        stats['total_capacity_gb'] = total_capacity
        stats['free_capacity_gb'] = max_free_capacity
        LOG.info(_LI(
                 "Free capacity for backend is: %(free)s, total capacity: "
                 "%(total)s."),
                 {'free': max_free_capacity,
                  'total': total_capacity})

        stats['pools'] = pools

        LOG.info(_LI("Backend name is %s."), stats["volume_backend_name"])

        self._stats = stats

    def get_volume_stats(self, refresh=False):
        """Get volume stats.

        If 'refresh' is True, run update the stats first.
        """
        if refresh:
            self._update_volume_stats()

        return self._stats

    def _get_volumetype_extraspecs(self, volume):
        specs = {}
        ctxt = context.get_admin_context()
        type_id = volume['volume_type_id']
        if type_id:
            volume_type = volume_types.get_volume_type(ctxt, type_id)
            specs = volume_type.get('extra_specs')
            for key, value in specs.items():
                specs[key] = value

        return specs

    def _get_volumetype_qos(self, volume):
        qos = {}
        ctxt = context.get_admin_context()
        type_id = volume['volume_type_id']
        if type_id:
            volume_type = volume_types.get_volume_type(ctxt, type_id)
            qos_specs_id = volume_type.get('qos_specs_id')
            if qos_specs_id is not None:
                specs = qos_specs.get_qos_specs(ctxt, qos_specs_id)['specs']
            else:
                specs = {}
            for key, value in specs.items():
                if key in self.scaleio_qos_keys:
                    qos[key] = value
        return qos

    def _sio_attach_volume(self, volume):
        """Call connector.connect_volume() and return the path. """
        LOG.debug("Calling os-brick to attach ScaleIO volume.")
        connection_properties = dict(self.connection_properties)
        connection_properties['scaleIO_volname'] = self._id_to_base64(
            volume.id)
        device_info = self.connector.connect_volume(connection_properties)

        return device_info['path']

    def _sio_detach_volume(self, volume):
        """Call the connector.disconnect() """
        LOG.info(_LI("Calling os-brick to detach ScaleIO volume."))
        connection_properties = dict(self.connection_properties)
        connection_properties['scaleIO_volname'] = self._id_to_base64(
            volume.id)
        self.connector.disconnect_volume(connection_properties, volume)

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetch the image from image_service and write it to the volume."""
        LOG.info(_LI(
                 "ScaleIO copy_image_to_volume volume: %(vol)s image service: "
                 "%(service)s image id: %(id)s."),
                 {'vol': volume,
                  'service': six.text_type(image_service),
                  'id': six.text_type(image_id)})

        try:
            image_utils.fetch_to_raw(context,
                                     image_service,
                                     image_id,
                                     self._sio_attach_volume(volume),
                                     BLOCK_SIZE,
                                     size=volume['size'])

        finally:
            self._sio_detach_volume(volume)

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        """Copy the volume to the specified image."""
        LOG.info(_LI(
                 "ScaleIO copy_volume_to_image volume: %(vol)s image service: "
                 "%(service)s image meta: %(meta)s."),
                 {'vol': volume,
                  'service': six.text_type(image_service),
                  'meta': six.text_type(image_meta)})
        try:
            image_utils.upload_volume(context,
                                      image_service,
                                      image_meta,
                                      self._sio_attach_volume(volume))
        finally:
            self._sio_detach_volume(volume)

    def update_migrated_volume(self, ctxt, volume, new_volume,
                               original_volume_status):
        """Return the update from ScaleIO migrated volume.

        This method updates the volume name of the new ScaleIO volume to
        match the updated volume ID.
        The original volume is renamed first since ScaleIO does not allow
        multiple volumes to have the same name.
        """
        name_id = None
        location = None
        if original_volume_status == 'available':
            # During migration, a new volume is created and will replace
            # the original volume at the end of the migration. We need to
            # rename the new volume. The current_name of the new volume,
            # which is the id of the new volume, will be changed to the
            # new_name, which is the id of the original volume.
            current_name = new_volume['id']
            new_name = volume['id']
            vol_id = new_volume['provider_id']
            LOG.info(_LI("Renaming %(id)s from %(current_name)s to "
                         "%(new_name)s."),
                     {'id': vol_id, 'current_name': current_name,
                      'new_name': new_name})

            # Original volume needs to be renamed first
            self._rename_volume(volume, "ff" + new_name)
            self._rename_volume(new_volume, new_name)
        else:
            # The back-end will not be renamed.
            name_id = new_volume['_name_id'] or new_volume['id']
            location = new_volume['provider_location']

        return {'_name_id': name_id, 'provider_location': location}

    def _rename_volume(self, volume, new_id):
        new_name = self._id_to_base64(new_id)
        vol_id = volume['provider_id']

        req_vars = {'server_ip': self.server_ip,
                    'server_port': self.server_port,
                    'id': vol_id}
        request = ("https://%(server_ip)s:%(server_port)s"
                   "/api/instances/Volume::%(id)s/action/setVolumeName" %
                   req_vars)
        LOG.info(_LI("ScaleIO rename volume request: %s."), request)

        params = {'newName': new_name}
        r = requests.post(
            request,
            data=json.dumps(params),
            headers=self._get_headers(),
            auth=(self.server_username,
                  self.server_token),
            verify=self._get_verify_cert()
        )
        r = self._check_response(r, request, False, params)

        if r.status_code != OK_STATUS_CODE:
            response = r.json()
            msg = (_("Error renaming volume %(vol)s: %(err)s.") %
                   {'vol': vol_id, 'err': response['message']})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        else:
            LOG.info(_LI("ScaleIO volume %(vol)s was renamed to "
                         "%(new_name)s."),
                     {'vol': vol_id, 'new_name': new_name})

    def manage_existing(self, volume, existing_ref):
        """Manage an existing ScaleIO volume.

        existing_ref is a dictionary of the form:
        {'source-id': <id of ScaleIO volume>}
        """
        request = self._create_scaleio_get_volume_request(volume, existing_ref)
        r, response = self._execute_scaleio_get_request(request)
        LOG.info(_LI("Get Volume response: %s"), response)
        self._manage_existing_check_legal_response(r, existing_ref)
        if response['mappedSdcInfo'] is not None:
            reason = _("manage_existing cannot manage a volume "
                       "connected to hosts. Please disconnect this volume "
                       "from existing hosts before importing")
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref,
                reason=reason
            )
        return {'provider_id': response['id']}

    def manage_existing_get_size(self, volume, existing_ref):
        request = self._create_scaleio_get_volume_request(volume, existing_ref)
        r, response = self._execute_scaleio_get_request(request)
        LOG.info(_LI("Get Volume response: %s"), response)
        self._manage_existing_check_legal_response(r, existing_ref)
        return int(response['sizeInKb'] / units.Mi)

    def _execute_scaleio_get_request(self, request):
        r = requests.get(
            request,
            auth=(
                self.server_username,
                self.server_token),
            verify=self._get_verify_cert())
        r = self._check_response(r, request)
        response = r.json()
        return r, response

    def _create_scaleio_get_volume_request(self, volume, existing_ref):
        """Throws an exception if the input is invalid for manage existing.

        if the input is valid - return a request.
        """
        type_id = volume.get('volume_type_id')
        if 'source-id' not in existing_ref:
            reason = _("Reference must contain source-id.")
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref,
                reason=reason
            )
        if type_id is None:
            reason = _("Volume must have a volume type")
            raise exception.ManageExistingVolumeTypeMismatch(
                existing_ref=existing_ref,
                reason=reason
            )
        vol_id = existing_ref['source-id']
        req_vars = {'server_ip': self.server_ip,
                    'server_port': self.server_port,
                    'id': vol_id}
        request = ("https://%(server_ip)s:%(server_port)s"
                   "/api/instances/Volume::%(id)s" % req_vars)
        LOG.info(_LI("ScaleIO get volume by id request: %s."), request)
        return request

    def _manage_existing_check_legal_response(self, response, existing_ref):
        if response.status_code != OK_STATUS_CODE:
            reason = (_("Error managing volume: %s.") % response.json()[
                'message'])
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref,
                reason=reason
            )

    def create_consistencygroup(self, context, group):
        """Creates a consistency group.

        ScaleIO won't create CG until cg-snapshot creation,
        db will maintain the volumes and CG relationship.
        """
        LOG.info(_LI("Creating Consistency Group"))
        model_update = {'status': 'available'}
        return model_update

    def delete_consistencygroup(self, context, group, volumes):
        """Deletes a consistency group.

        ScaleIO will delete the volumes of the CG.
        """
        LOG.info(_LI("Deleting Consistency Group"))
        model_update = {'status': 'deleted'}
        error_statuses = ['error', 'error_deleting']
        volumes_model_update = []
        for volume in volumes:
            try:
                self._delete_volume(volume['provider_id'])
                update_item = {'id': volume['id'],
                               'status': 'deleted'}
                volumes_model_update.append(update_item)
            except exception.VolumeBackendAPIException as err:
                update_item = {'id': volume['id'],
                               'status': 'error_deleting'}
                volumes_model_update.append(update_item)
                if model_update['status'] not in error_statuses:
                    model_update['status'] = 'error_deleting'
                LOG.error(_LE("Failed to delete the volume %(vol)s of CG. "
                              "Exception: %(exception)s."),
                          {'vol': volume['name'], 'exception': err})
        return model_update, volumes_model_update

    def create_cgsnapshot(self, context, cgsnapshot, snapshots):
        """Creates a cgsnapshot."""
        get_scaleio_snapshot_params = lambda snapshot: {
            'volumeId': snapshot.volume['provider_id'],
            'snapshotName': self._id_to_base64(snapshot['id'])}
        snapshotDefs = list(map(get_scaleio_snapshot_params, snapshots))
        r, response = self._snapshot_volume_group(snapshotDefs)
        LOG.info(_LI("Snapshot volume response: %s."), response)
        if r.status_code != OK_STATUS_CODE and "errorCode" in response:
            msg = (_("Failed creating snapshot for group: "
                     "%(response)s.") %
                   {'response': response['message']})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        snapshot_model_update = []
        for snapshot, scaleio_id in zip(snapshots, response['volumeIdList']):
            update_item = {'id': snapshot['id'],
                           'status': 'available',
                           'provider_id': scaleio_id}
            snapshot_model_update.append(update_item)
        model_update = {'status': 'available'}
        return model_update, snapshot_model_update

    def delete_cgsnapshot(self, context, cgsnapshot, snapshots):
        """Deletes a cgsnapshot."""
        error_statuses = ['error', 'error_deleting']
        model_update = {'status': cgsnapshot['status']}
        snapshot_model_update = []
        for snapshot in snapshots:
            try:
                self._delete_volume(snapshot.provider_id)
                update_item = {'id': snapshot['id'],
                               'status': 'deleted'}
                snapshot_model_update.append(update_item)
            except exception.VolumeBackendAPIException as err:
                update_item = {'id': snapshot['id'],
                               'status': 'error_deleting'}
                snapshot_model_update.append(update_item)
                if model_update['status'] not in error_statuses:
                    model_update['status'] = 'error_deleting'
                LOG.error(_LE("Failed to delete the snapshot %(snap)s "
                              "of cgsnapshot: %(cgsnapshot_id)s. "
                              "Exception: %(exception)s."),
                          {'snap': snapshot['name'],
                           'exception': err,
                           'cgsnapshot_id': cgsnapshot.id})
        model_update['status'] = 'deleted'
        return model_update, snapshot_model_update

    def create_consistencygroup_from_src(self, context, group, volumes,
                                         cgsnapshot=None, snapshots=None,
                                         source_cg=None, source_vols=None):
        """Creates a consistency group from a source."""
        get_scaleio_snapshot_params = lambda src_volume, trg_volume: {
            'volumeId': src_volume['provider_id'],
            'snapshotName': self._id_to_base64(trg_volume['id'])}
        if cgsnapshot and snapshots:
            snapshotDefs = map(get_scaleio_snapshot_params, snapshots, volumes)
        else:
            snapshotDefs = map(get_scaleio_snapshot_params, source_vols,
                               volumes)
        r, response = self._snapshot_volume_group(list(snapshotDefs))
        LOG.info(_LI("Snapshot volume response: %s."), response)
        if r.status_code != OK_STATUS_CODE and "errorCode" in response:
            msg = (_("Failed creating snapshot for group: "
                     "%(response)s.") %
                   {'response': response['message']})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        volumes_model_update = []
        for volume, scaleio_id in zip(volumes, response['volumeIdList']):
            update_item = {'id': volume['id'],
                           'status': 'available',
                           'provider_id': scaleio_id}
            volumes_model_update.append(update_item)
        model_update = {'status': 'available'}
        return model_update, volumes_model_update

    def update_consistencygroup(self, context, group,
                                add_volumes=None, remove_volumes=None):
        """Update a consistency group.

        ScaleIO does not handle volume grouping.
        Cinder maintains volumes and CG relationship.
        """
        return None, None, None

    def _snapshot_volume_group(self, snapshotDefs):
        LOG.info(_LI("ScaleIO snapshot group of volumes"))
        params = {'snapshotDefs': snapshotDefs}
        req_vars = {'server_ip': self.server_ip,
                    'server_port': self.server_port}
        request = ("https://%(server_ip)s:%(server_port)s"
                   "/api/instances/System/action/snapshotVolumes") % req_vars
        return self._execute_scaleio_post_request(params, request)

    def ensure_export(self, context, volume):
        """Driver entry point to get the export info for an existing volume."""
        pass

    def create_export(self, context, volume, connector):
        """Driver entry point to get the export info for a new volume."""
        pass

    def remove_export(self, context, volume):
        """Driver entry point to remove an export for a volume."""
        pass

    def check_for_export(self, context, volume_id):
        """Make sure volume is exported."""
        pass
