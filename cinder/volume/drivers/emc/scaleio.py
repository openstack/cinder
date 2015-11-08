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
from cinder.i18n import _, _LI, _LW
from cinder.image import image_utils
from cinder import utils
from cinder.volume import driver
from cinder.volume.drivers.san import san
from cinder.volume import volume_types

CONF = cfg.CONF

LOG = logging.getLogger(__name__)

scaleio_opts = [
    cfg.StrOpt('sio_rest_server_port',
               default='443',
               help='REST server port.'),
    cfg.BoolOpt('sio_verify_server_certificate',
                default=False,
                help='Whether to verify server certificate.'),
    cfg.StrOpt('sio_server_certificate_path',
               help='Server certificate path.'),
    cfg.BoolOpt('sio_round_volume_capacity',
                default=True,
                help='Whether to round volume capacity.'),
    cfg.BoolOpt('sio_force_delete',
                default=False,
                help='Whether to allow force delete.'),
    cfg.BoolOpt('sio_unmap_volume_before_deletion',
                default=False,
                help='Whether to unmap volume before deletion.'),
    cfg.StrOpt('sio_protection_domain_id',
               help='Protection domain id.'),
    cfg.StrOpt('sio_protection_domain_name',
               help='Protection domain name.'),
    cfg.StrOpt('sio_storage_pools',
               help='Storage pools.'),
    cfg.StrOpt('sio_storage_pool_name',
               help='Storage pool name.'),
    cfg.StrOpt('sio_storage_pool_id',
               help='Storage pool id.')
]

CONF.register_opts(scaleio_opts)

STORAGE_POOL_NAME = 'sio:sp_name'
STORAGE_POOL_ID = 'sio:sp_id'
PROTECTION_DOMAIN_NAME = 'sio:pd_name'
PROTECTION_DOMAIN_ID = 'sio:pd_id'
PROVISIONING_KEY = 'sio:provisioning'
IOPS_LIMIT_KEY = 'sio:iops_limit'
BANDWIDTH_LIMIT = 'sio:bandwidth_limit'

BLOCK_SIZE = 8
OK_STATUS_CODE = 200
VOLUME_NOT_FOUND_ERROR = 78
VOLUME_NOT_MAPPED_ERROR = 84
VOLUME_ALREADY_MAPPED_ERROR = 81


class ScaleIODriver(driver.VolumeDriver):
    """EMC ScaleIO Driver."""

    VERSION = "2.0"

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
            "REST server IP: %(ip)s, port: %(port)s, username: %(user)s. "
            "Verify server's certificate: %(verify_cert)s."),
            {'ip': self.server_ip,
             'port': self.server_port,
             'user': self.server_username,
             'verify_cert': self.verify_server_certificate})

        self.storage_pools = None
        if self.configuration.sio_storage_pools:
            self.storage_pools = [
                e.strip() for e in
                self.configuration.sio_storage_pools.split(',')
            ]

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
            # TODO(xyang): Change 'SCALEIO' to connector.SCALEIO after
            # os-brick 0.4.0 is released.
            'SCALEIO', utils.get_root_helper(),
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
            msg = _(
                "Must specify storage pools. Option: sio_storage_pools."
            )
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

    def _find_iops_limit(self, storage_type):
        return storage_type.get(IOPS_LIMIT_KEY)

    def _find_bandwidth_limit(self, storage_type):
        return storage_type.get(BANDWIDTH_LIMIT)

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
        LOG.debug(
            "Converted id %(id)s to scaleio name %(name)s.",
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
            "Volume type: %(volume_type)s, storage pool name: %(pool_name)s, "
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
                    "Cannot create volume of size %s: not multiple of 8GB.") %
                    size)
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
        LOG.info(_LI("Snapshot volume response: %s."), response)
        if r.status_code != OK_STATUS_CODE and "errorCode" in response:
            msg = (_("Failed creating snapshot for volume %(volname)s: "
                     "%(response)s.") %
                   {'volname': vol_id,
                    'response': response['message']})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        return {'provider_id': response['volumeIdList'][0]}

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
        """Extends the size of an existing available ScaleIO volume."""

        self._check_volume_size(new_size)

        vol_id = volume['provider_id']
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
        volume_new_size = new_size
        params = {'sizeInGB': six.text_type(volume_new_size)}
        r = requests.post(
            request,
            data=json.dumps(params),
            headers=self._get_headers(),
            auth=(self.server_username,
                  self.server_token),
            verify=self._get_verify_cert())
        r = self._check_response(r, request, False, params)

        if r.status_code != OK_STATUS_CODE:
            response = r.json()
            msg = (_("Error extending volume %(vol)s: %(err)s.")
                   % {'vol': vol_id,
                      'err': response['message']})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def create_cloned_volume(self, volume, src_vref):
        """Creates a cloned volume."""
        volume_id = src_vref['provider_id']
        snapname = self._id_to_base64(volume.id)
        LOG.info(_LI(
            "ScaleIO create cloned volume: source volume %(src)s to target "
            "volume %(tgt)s."),
            {'src': volume_id,
             'tgt': snapname})

        return self._snapshot_volume(volume_id, snapname)

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
                "Trying to unmap volume from all sdcs before deletion: %s."),
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
            if error_code == 78:
                force_delete = self.configuration.sio_force_delete
                if force_delete:
                    LOG.warning(_LW(
                        "Ignoring error in delete volume %s: volume not found "
                        "due to force delete settings."), vol_id)
                else:
                    msg = (_("Error deleting volume %s: volume not found.") %
                           vol_id)
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)
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
        storage_type = self._get_volumetype_extraspecs(volume)
        LOG.info(_LI("Volume type is %s."), storage_type)
        iops_limit = self._find_iops_limit(storage_type)
        LOG.info(_LI("iops limit is: %s."), iops_limit)
        bandwidth_limit = self._find_bandwidth_limit(storage_type)
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
        stats['QoS_support'] = False

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
                    'QoS_support': False,
                    'reserved_percentage': 0
                    }

            pools.append(pool)
            if free_capacity_gb > max_free_capacity:
                max_free_capacity = free_capacity_gb
            total_capacity = total_capacity + total_capacity_gb

        stats['volume_backend_name'] = backend_name or 'scaleio'
        stats['vendor_name'] = 'EMC'
        stats['driver_version'] = self.VERSION
        stats['storage_protocol'] = 'scaleio'
        # Use zero capacities here so we always use a pool.
        stats['total_capacity_gb'] = total_capacity
        stats['free_capacity_gb'] = max_free_capacity
        LOG.info(_LI(
            "Free capacity for backend is: %(free)s, total capacity: "
            "%(total)s."),
            {'free': max_free_capacity,
             'total': total_capacity})

        stats['reserved_percentage'] = 0
        stats['QoS_support'] = False
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
