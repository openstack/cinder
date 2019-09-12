# Copyright (c) 2017-2019 Dell Inc. or its subsidiaries.
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
Driver for Dell EMC VxFlex OS (formerly named Dell EMC ScaleIO).
"""

import base64
import binascii
from distutils import version
import json
import math
import re

from os_brick import initiator
from oslo_config import cfg
from oslo_log import log as logging
from oslo_log import versionutils
from oslo_utils import units
import requests
import six
from six.moves import http_client
from six.moves import urllib

from cinder import context
from cinder import exception
from cinder.i18n import _
from cinder.image import image_utils
from cinder import interface
from cinder import objects
from cinder.objects import fields
from cinder import utils
from cinder.volume import configuration
from cinder.volume import driver
from cinder.volume.drivers.dell_emc.vxflexos import options
from cinder.volume.drivers.dell_emc.vxflexos import simplecache
from cinder.volume.drivers.san import san
from cinder.volume import qos_specs
from cinder.volume import volume_types
from cinder.volume import volume_utils

CONF = cfg.CONF

vxflexos_opts = options.deprecated_opts + options.actual_opts

CONF.register_opts(vxflexos_opts, group=configuration.SHARED_CONF_GROUP)

LOG = logging.getLogger(__name__)


PROVISIONING_KEY = 'provisioning:type'
QOS_IOPS_LIMIT_KEY = 'maxIOPS'
QOS_BANDWIDTH_LIMIT = 'maxBWS'
QOS_IOPS_PER_GB = 'maxIOPSperGB'
QOS_BANDWIDTH_PER_GB = 'maxBWSperGB'

BLOCK_SIZE = 8
VOLUME_NOT_FOUND_ERROR = 79
# This code belongs to older versions of VxFlex OS
OLD_VOLUME_NOT_FOUND_ERROR = 78
VOLUME_NOT_MAPPED_ERROR = 84
ILLEGAL_SYNTAX = 0
VOLUME_ALREADY_MAPPED_ERROR = 81
MIN_BWS_SCALING_SIZE = 128
VXFLEXOS_MAX_OVERSUBSCRIPTION_RATIO = 10.0


@interface.volumedriver
class VxFlexOSDriver(driver.VolumeDriver):
    """Cinder VxFlex OS(formerly named Dell EMC ScaleIO) Driver

    .. code-block:: none

      Version history:
          2.0.1 - Added support for SIO 1.3x in addition to 2.0.x
          2.0.2 - Added consistency group support to generic volume groups
          2.0.3 - Added cache for storage pool and protection domains info
          2.0.4 - Added compatibility with os_brick>1.15.3
          2.0.5 - Change driver name, rename config file options
          3.0.0 - Add support for VxFlex OS 3.0.x and for volumes compression
    """

    VERSION = "3.0.0"
    # ThirdPartySystems wiki
    CI_WIKI_NAME = "DELL_EMC_ScaleIO_CI"

    vxflexos_qos_keys = (QOS_IOPS_LIMIT_KEY, QOS_BANDWIDTH_LIMIT,
                         QOS_IOPS_PER_GB, QOS_BANDWIDTH_PER_GB)

    def __init__(self, *args, **kwargs):
        super(VxFlexOSDriver, self).__init__(*args, **kwargs)

        # simple caches for PD and SP properties
        self.spCache = simplecache.SimpleCache("Storage Pool",
                                               age_minutes=5)
        self.pdCache = simplecache.SimpleCache("Protection Domain",
                                               age_minutes=5)

        self.configuration.append_config_values(san.san_opts)
        self.configuration.append_config_values(vxflexos_opts)
        self.server_ip = self.configuration.san_ip
        self.server_port = self.configuration.vxflexos_rest_server_port
        self.server_username = self.configuration.san_login
        self.server_password = self.configuration.san_password
        self.server_token = None
        self.server_api_version = (
            self.configuration.vxflexos_server_api_version)
        # list of statistics/properties to query from SIO
        self.statisticProperties = None
        self.verify_server_certificate = (
            self.configuration.safe_get("sio_verify_server_certificate") or
            self.configuration.safe_get("driver_ssl_cert_verify"))
        self.server_certificate_path = None
        if self.verify_server_certificate:
            self.server_certificate_path = (
                self.configuration.safe_get(
                    "sio_server_certificate_path") or
                self.configuration.safe_get(
                    "driver_ssl_cert_path"))
        LOG.info("REST server IP: %(ip)s, port: %(port)s, username: %("
                 "user)s. Verify server's certificate: %(verify_cert)s.",
                 {'ip': self.server_ip,
                  'port': self.server_port,
                  'user': self.server_username,
                  'verify_cert': self.verify_server_certificate})
        self.storage_pools = None
        if self.configuration.vxflexos_storage_pools:
            self.storage_pools = [
                e.strip() for e in
                self.configuration.vxflexos_storage_pools.split(',')]
        LOG.info("Storage pools names: %(pools)s.",
                 {'pools': self.storage_pools})

        self.provisioning_type = (
            'thin' if self.configuration.san_thin_provision else 'thick')
        LOG.info("Default provisioning type: %(provisioning_type)s.",
                 {'provisioning_type': self.provisioning_type})
        self.configuration.max_over_subscription_ratio = (
            self.configuration.vxflexos_max_over_subscription_ratio)
        self.connector = initiator.connector.InitiatorConnector.factory(
            initiator.SCALEIO, utils.get_root_helper(),
            self.configuration.num_volume_device_scan_tries
        )

        self.connection_properties = {
            'scaleIO_volname': None,
            'hostIP': None,
            'serverIP': self.server_ip,
            'serverPort': self.server_port,
            'serverUsername': self.server_username,
            'serverPassword': self.server_password,
            'serverToken': self.server_token,
            'iopsLimit': None,
            'bandwidthLimit': None,
        }

    @staticmethod
    def get_driver_options():
        return vxflexos_opts

    def check_for_setup_error(self):
        # make sure the REST gateway is specified
        if not self.server_ip:
            msg = _("REST server IP must be specified.")
            raise exception.InvalidInput(reason=msg)

        # make sure we got a username
        if not self.server_username:
            msg = _("REST server username must be specified.")
            raise exception.InvalidInput(reason=msg)

        # make sure we got a password
        if not self.server_password:
            msg = _("REST server password must be specified.")
            raise exception.InvalidInput(reason=msg)

        # validate certificate settings
        if self.verify_server_certificate and not self.server_certificate_path:
            msg = _("Path to REST server's certificate must be specified.")
            raise exception.InvalidInput(reason=msg)

        # log warning if not using certificates
        if not self.verify_server_certificate:
            LOG.warning("Verify certificate is not set, using default of "
                        "False.")

        # validate oversubscription ration
        if (self.configuration.max_over_subscription_ratio is not None and
            (self.configuration.max_over_subscription_ratio -
             VXFLEXOS_MAX_OVERSUBSCRIPTION_RATIO > 1)):
            msg = (_("Max over subscription is configured to %(ratio)1f "
                     "while VxFlex OS support up to %(vxflexos_ratio)s.") %
                   {'vxflexos_ratio': VXFLEXOS_MAX_OVERSUBSCRIPTION_RATIO,
                    'ratio': self.configuration.max_over_subscription_ratio})
            raise exception.InvalidInput(reason=msg)

        # validate that version of VxFlex OS is supported
        server_api_version = self._get_server_api_version(fromcache=False)
        if not self._version_greater_than_or_equal(
                server_api_version, "2.0.0"):
            # we are running against a pre-2.0.0 VxFlex OS(ScaleIO) instance
            msg = (_("Using VxFlex OS(ScaleIO) versions less "
                     "than v2.0.0 has been deprecated and will be "
                     "removed in a future version"))
            versionutils.report_deprecated_feature(LOG, msg)

        if not self.storage_pools:
            msg = (_("Must specify storage pools. Option: "
                     "vxflexos_storage_pools."))
            raise exception.InvalidInput(reason=msg)

        # validate the storage pools and check if zero padding is enabled
        for pool in self.storage_pools:
            try:
                pd, sp = pool.split(':')
            except (ValueError, IndexError):
                msg = (_("Invalid storage pool name. The correct format is: "
                         "protection_domain:storage_pool. "
                         "Value supplied was: %(pool)s") %
                       {'pool': pool})
                raise exception.InvalidInput(reason=msg)

            try:
                properties = self._get_storage_pool_properties(pd, sp)
                padded = properties['zeroPaddingEnabled']
            except Exception:
                msg = (_("Unable to retrieve properties for pool, %(pool)s") %
                       {'pool': pool})
                raise exception.InvalidInput(reason=msg)

            if not padded:
                LOG.warning("Zero padding is disabled for pool, %s. "
                            "This could lead to existing data being "
                            "accessible on new provisioned volumes. "
                            "Consult the VxFlex OS product documentation "
                            "for information on how to enable zero padding "
                            "and prevent this from occurring.",
                            pool)

    def _get_queryable_statistics(self, sio_type, sio_id):
        if self.statisticProperties is None:
            self.statisticProperties = [
                "snapCapacityInUseInKb",
                "thickCapacityInUseInKb"]
            # VxFlex OS 3.0 provide useful precomputed stats
            if self._version_greater_than_or_equal(
                    self._get_server_api_version(),
                    "3.0"):
                self.statisticProperties.extend([
                    "netCapacityInUseInKb",
                    "netUnusedCapacityInKb",
                    "thinCapacityAllocatedInKb"])
                return self.statisticProperties

            self.statisticProperties.extend(
                ["capacityAvailableForVolumeAllocationInKb",
                 "capacityLimitInKb", "spareCapacityInKb"])
            # version 2.0 of SIO introduced thin volumes
            if self._version_greater_than_or_equal(
                    self._get_server_api_version(),
                    "2.0.0"):
                # check to see if thinCapacityAllocatedInKb is valid
                # needed due to non-backwards compatible API
                req_vars = {'server_ip': self.server_ip,
                            'server_port': self.server_port,
                            'sio_type': sio_type}
                request = ("https://%(server_ip)s:%(server_port)s"
                           "/api/types/%(sio_type)s/instances/action/"
                           "querySelectedStatistics") % req_vars
                params = {'ids': [sio_id],
                          'properties': ["thinCapacityAllocatedInKb"]}
                r, response = self._execute_vxflexos_post_request(params,
                                                                  request)
                if r.status_code == http_client.OK:
                    # is it valid, use it
                    self.statisticProperties.append(
                        "thinCapacityAllocatedInKb")
                else:
                    # it is not valid, assume use of thinCapacityAllocatedInKm
                    self.statisticProperties.append(
                        "thinCapacityAllocatedInKm")

        return self.statisticProperties

    def _find_provisioning_type(self, storage_type):
        provisioning_type = storage_type.get(PROVISIONING_KEY)
        if provisioning_type is not None:
            if provisioning_type not in ('thick', 'thin', 'compressed'):
                msg = _("Illegal provisioning type. The supported "
                        "provisioning types are 'thick', 'thin' "
                        "or 'compressed'.")
                raise exception.VolumeBackendAPIException(data=msg)
            return provisioning_type
        else:
            return self.provisioning_type

    @staticmethod
    def _version_greater_than(ver1, ver2):
        return version.LooseVersion(ver1) > version.LooseVersion(ver2)

    @staticmethod
    def _version_greater_than_or_equal(ver1, ver2):
        return version.LooseVersion(ver1) >= version.LooseVersion(ver2)

    @staticmethod
    def _convert_kb_to_gib(size):
        return int(math.floor(float(size) / units.Mi))

    @staticmethod
    def _id_to_base64(id):
        # Base64 encode the id to get a volume name less than 32 characters due
        # to VxFlex OS limitation.
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
        LOG.debug("Converted id %(id)s to VxFlex OS name %(name)s.",
                  {'id': id, 'name': encoded_name})
        return encoded_name

    def _is_volume_creation_safe(self,
                                 protection_domain,
                                 storage_pool):
        """Checks if volume creation is safe or not.

        Using volumes with zero padding disabled can lead to existing data
        being read off of a newly created volume.
        """
        # if we have been told to allow unsafe volumes
        if self.configuration.vxflexos_allow_non_padded_volumes:
            # Enabled regardless of type, so safe to proceed
            return True

        try:
            properties = self._get_storage_pool_properties(protection_domain,
                                                           storage_pool)
            padded = properties['zeroPaddingEnabled']
        except Exception:
            msg = (_("Unable to retrieve properties for pool, %(pool)s") %
                   {'pool': storage_pool})
            raise exception.InvalidInput(reason=msg)

        # zero padded storage pools are safe
        if padded:
            return True
        # if we got here, it's unsafe
        return False

    def create_volume(self, volume):
        """Creates a VxFlex OS volume."""
        self._check_volume_size(volume.size)

        volname = self._id_to_base64(volume.id)

        pd_sp = volume_utils.extract_host(volume.host, 'pool')
        protection_domain_name = pd_sp.split(':')[0]
        storage_pool_name = pd_sp.split(':')[1]

        storage_type = self._get_volumetype_extraspecs(volume)
        provisioning_type = self._find_provisioning_type(storage_type)

        LOG.info("Volume type: %(volume_type)s, "
                 "storage pool name: %(pool_name)s, "
                 "protection domain name: %(domain_name)s.",
                 {'volume_type': storage_type,
                  'pool_name': storage_pool_name,
                  'domain_name': protection_domain_name})

        domain_id = self._get_protection_domain_id(protection_domain_name)
        LOG.info("Domain id is %s.", domain_id)
        pool_id = self._get_storage_pool_id(protection_domain_name,
                                            storage_pool_name)
        LOG.info("Pool id is %s.", pool_id)

        allowed = self._is_volume_creation_safe(protection_domain_name,
                                                storage_pool_name)
        if not allowed:
            # Do not allow volume creation on this backend.
            # Volumes may leak data between tenants.
            LOG.error("Volume creation rejected due to "
                      "zero padding being disabled for pool, %s:%s. "
                      "This behaviour can be changed by setting "
                      "the configuration option "
                      "vxflexos_allow_non_padded_volumes = True.",
                      protection_domain_name,
                      storage_pool_name)
            msg = _("Volume creation rejected due to "
                    "unsafe backend configuration.")
            raise exception.VolumeBackendAPIException(data=msg)

        provisioning = "ThinProvisioned"
        if (provisioning_type == 'thick' and
                self._check_pool_support_thick_vols(protection_domain_name,
                                                    storage_pool_name)):
            provisioning = "ThickProvisioned"

        # units.Mi = 1024 ** 2
        volume_size_kb = volume.size * units.Mi
        params = {'protectionDomainId': domain_id,
                  'volumeSizeInKb': six.text_type(volume_size_kb),
                  'name': volname,
                  'volumeType': provisioning,
                  'storagePoolId': pool_id}

        if self._check_pool_support_compression(protection_domain_name,
                                                storage_pool_name):
            params['compressionMethod'] = "None"
            if provisioning_type == "compressed":
                params['compressionMethod'] = "Normal"

        LOG.info("Params for add volume request: %s.", params)
        req_vars = {'server_ip': self.server_ip,
                    'server_port': self.server_port}
        request = ("https://%(server_ip)s:%(server_port)s"
                   "/api/types/Volume/instances") % req_vars
        r, response = self._execute_vxflexos_post_request(params, request)

        if r.status_code != http_client.OK and "errorCode" in response:
            msg = (_("Error creating volume: %s.") % response['message'])
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.info("Created volume %(volname)s, volume id %(volid)s.",
                 {'volname': volname, 'volid': volume.id})

        real_size = int(self._round_to_num_gran(volume.size))

        return {'provider_id': response['id'], 'size': real_size}

    def _check_volume_size(self, size):
        if size % 8 != 0:
            round_volume_capacity = (
                self.configuration.vxflexos_round_volume_capacity)
            if not round_volume_capacity:
                exception_msg = (_(
                                 "Cannot create volume of size %s: "
                                 "not multiple of 8GB.") % size)
                LOG.error(exception_msg)
                raise exception.VolumeBackendAPIException(data=exception_msg)

    def create_snapshot(self, snapshot):
        """Creates a VxFlex OS snapshot."""
        volume_id = snapshot.volume.provider_id
        snapname = self._id_to_base64(snapshot.id)
        return self._snapshot_volume(volume_id, snapname)

    def _snapshot_volume(self, vol_id, snapname):
        LOG.info("Snapshot volume %(vol)s into snapshot %(id)s.",
                 {'vol': vol_id, 'id': snapname})
        params = {
            'snapshotDefs': [{"volumeId": vol_id, "snapshotName": snapname}]}
        req_vars = {'server_ip': self.server_ip,
                    'server_port': self.server_port}
        request = ("https://%(server_ip)s:%(server_port)s"
                   "/api/instances/System/action/snapshotVolumes") % req_vars
        r, response = self._execute_vxflexos_post_request(params, request)
        if r.status_code != http_client.OK and "errorCode" in response:
            msg = (_("Failed creating snapshot for volume %(volname)s: "
                     "%(response)s.") %
                   {'volname': vol_id,
                    'response': response['message']})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        return {'provider_id': response['volumeIdList'][0]}

    def _execute_vxflexos_post_request(self, params, request):
        r = requests.post(
            request,
            data=json.dumps(params),
            headers=self._get_headers(),
            auth=(
                self.server_username,
                self.server_token),
            verify=self._get_verify_cert())
        r = self._check_response(r, request, False, params)
        response = None
        try:
            response = r.json()
        except ValueError:
            response = None
        return r, response

    def _check_response(self, response, request, is_get_request=True,
                        params=None):
        if (response.status_code == http_client.UNAUTHORIZED or
                response.status_code == http_client.FORBIDDEN):
            LOG.info("Token is invalid, going to re-login and get "
                     "a new one.")
            login_request = (
                "https://%(server_ip)s:%(server_port)s/api/login" % {
                    "server_ip": self.server_ip,
                    "server_port": self.server_port})
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
            LOG.info("Going to perform request again %s with valid token.",
                     request)
            if is_get_request:
                response = requests.get(request,
                                        auth=(self.server_username,
                                              self.server_token),
                                        verify=verify_cert)
            else:
                response = requests.post(request,
                                         data=json.dumps(params),
                                         headers=self._get_headers(),
                                         auth=(self.server_username,
                                               self.server_token),
                                         verify=verify_cert)

        level = logging.DEBUG
        # for anything other than an OK from the REST API, log an error
        if response.status_code != http_client.OK:
            level = logging.ERROR

        LOG.log(level, "REST Request: %s with params %s",
                request,
                json.dumps(params))
        LOG.log(level, "REST Response: %s with data %s",
                response.status_code,
                response.text)

        return response

    def _get_server_api_version(self, fromcache=True):
        if self.server_api_version is None or fromcache is False:
            request = (
                "https://%(server_ip)s:%(server_port)s/api/version" % {
                    "server_ip": self.server_ip,
                    "server_port": self.server_port})
            r, unused = self._execute_vxflexos_get_request(request)

            if r.status_code == http_client.OK:
                self.server_api_version = r.text.replace('\"', '')
                LOG.info("REST API Version: %(api_version)s",
                         {'api_version': self.server_api_version})
            else:
                msg = (_("Error calling version api "
                         "status code: %d") % r.status_code)
                raise exception.VolumeBackendAPIException(data=msg)

            # make sure the response was valid
            pattern = re.compile(r"^\d+(\.\d+)*$")
            if not pattern.match(self.server_api_version):
                msg = (_("Error calling version api "
                         "response: %s") % r.text)
                raise exception.VolumeBackendAPIException(data=msg)

        return self.server_api_version

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        # We interchange 'volume' and 'snapshot' because in VxFlex OS
        # snapshot is a volume: once a snapshot is generated it
        # becomes a new unmapped volume in the system and the user
        # may manipulate it in the same manner as any other volume
        # exposed by the system
        volume_id = snapshot.provider_id
        snapname = self._id_to_base64(volume.id)
        LOG.info("VxFlex OS create volume from snapshot: "
                 "snapshot %(snapname)s to volume %(volname)s.",
                 {'volname': volume_id,
                  'snapname': snapname})

        ret = self._snapshot_volume(volume_id, snapname)
        if volume.size > snapshot.volume_size:
            LOG.info("Extending volume %(vol)s to size %(size)s",
                     {'vol': ret['provider_id'],
                      'size': volume.size})
            self._extend_volume(ret['provider_id'],
                                snapshot.volume_size, volume.size)

        return ret

    @staticmethod
    def _get_headers():
        return {'content-type': 'application/json'}

    def _get_verify_cert(self):
        verify_cert = False
        if self.verify_server_certificate:
            verify_cert = self.server_certificate_path
        return verify_cert

    def extend_volume(self, volume, new_size):
        """Extends the size of an existing available VxFlex OS volume.

        This action will round up the volume to the nearest size that is
        a granularity of 8 GBs.
        """
        return self._extend_volume(volume['provider_id'], volume.size,
                                   new_size)

    def _extend_volume(self, volume_id, old_size, new_size):
        vol_id = volume_id
        LOG.info(
            "VxFlex OS extend volume: "
            "volume %(volname)s to size %(new_size)s.",
            {'volname': vol_id,
             'new_size': new_size})

        req_vars = {'server_ip': self.server_ip,
                    'server_port': self.server_port,
                    'vol_id': vol_id}
        request = ("https://%(server_ip)s:%(server_port)s"
                   "/api/instances/Volume::%(vol_id)s"
                   "/action/setVolumeSize") % req_vars
        LOG.info("Change volume capacity request: %s.", request)

        # Round up the volume size so that it is a granularity of 8 GBs
        # because VxFlex OS only supports volumes with a granularity of 8 GBs.
        volume_new_size = self._round_to_num_gran(new_size)
        volume_real_old_size = self._round_to_num_gran(old_size)
        if volume_real_old_size == volume_new_size:
            return

        round_volume_capacity = (
            self.configuration.vxflexos_round_volume_capacity)
        if not round_volume_capacity and not new_size % 8 == 0:
            LOG.warning("VxFlex OS only supports volumes with a granularity "
                        "of 8 GBs. The new volume size is: %d.",
                        volume_new_size)

        params = {'sizeInGB': six.text_type(volume_new_size)}
        r, response = self._execute_vxflexos_post_request(params, request)
        if r.status_code != http_client.OK:
            response = r.json()
            msg = (_("Error extending volume %(vol)s: %(err)s.")
                   % {'vol': vol_id,
                      'err': response['message']})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    @staticmethod
    def _round_to_num_gran(size, num=8):
        if size % num == 0:
            return size
        return size + num - (size % num)

    @staticmethod
    def _round_down_to_num_gran(size, num=8):
        return size - (size % num)

    def create_cloned_volume(self, volume, src_vref):
        """Creates a cloned volume."""
        volume_id = src_vref['provider_id']
        snapname = self._id_to_base64(volume.id)
        LOG.info("VxFlex OS create cloned volume: source volume %(src)s to "
                 "target volume %(tgt)s.",
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
        req_vars = {'server_ip': self.server_ip,
                    'server_port': self.server_port,
                    'vol_id': six.text_type(vol_id)}

        unmap_before_delete = (
            self.configuration.vxflexos_unmap_volume_before_deletion)
        # Ensure that the volume is not mapped to any SDC before deletion in
        # case unmap_before_deletion is enabled.
        if unmap_before_delete:
            params = {'allSdcs': ''}
            request = ("https://%(server_ip)s:%(server_port)s"
                       "/api/instances/Volume::%(vol_id)s"
                       "/action/removeMappedSdc") % req_vars
            LOG.info("Trying to unmap volume from all sdcs"
                     " before deletion: %s.",
                     request)
            r, unused = self._execute_vxflexos_post_request(params, request)

        params = {'removeMode': 'ONLY_ME'}
        request = ("https://%(server_ip)s:%(server_port)s"
                   "/api/instances/Volume::%(vol_id)s"
                   "/action/removeVolume") % req_vars
        r, response = self._execute_vxflexos_post_request(params, request)

        if r.status_code != http_client.OK:
            error_code = response['errorCode']
            if error_code == VOLUME_NOT_FOUND_ERROR:
                LOG.warning("Ignoring error in delete volume %s:"
                            " Volume not found.", vol_id)
            elif vol_id is None:
                LOG.warning("Volume does not have provider_id thus does not "
                            "map to a VxFlex OS volume. "
                            "Allowing deletion to proceed.")
            else:
                msg = (_("Error deleting volume %(vol)s: %(err)s.") %
                       {'vol': vol_id,
                        'err': response['message']})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

    def delete_snapshot(self, snapshot):
        """Deletes a VxFlex OS snapshot."""
        snap_id = snapshot.provider_id
        LOG.info("VxFlex OS delete snapshot.")
        return self._delete_volume(snap_id)

    def initialize_connection(self, volume, connector, **kwargs):
        return self._initialize_connection(volume, connector, volume.size)

    def _initialize_connection(self, vol_or_snap, connector, vol_size):
        """Initializes a connection and returns connection info.

        The VxFlex OS driver returns a driver_volume_type of 'scaleio'.
        """

        try:
            ip = connector['ip']
        except Exception:
            ip = 'unknown'

        LOG.debug("Initializing connection for %(vol)s, "
                  "to SDC at %(sdc)s",
                  {'vol': vol_or_snap.id,
                   'sdc': ip})

        connection_properties = dict(self.connection_properties)

        volname = self._id_to_base64(vol_or_snap.id)
        connection_properties['scaleIO_volname'] = volname
        connection_properties['scaleIO_volume_id'] = vol_or_snap.provider_id

        if vol_size is not None:
            extra_specs = self._get_volumetype_extraspecs(vol_or_snap)
            qos_specs = self._get_volumetype_qos(vol_or_snap)
            storage_type = extra_specs.copy()
            storage_type.update(qos_specs)
            round_volume_size = self._round_to_num_gran(vol_size)
            iops_limit = self._get_iops_limit(round_volume_size, storage_type)
            bandwidth_limit = self._get_bandwidth_limit(round_volume_size,
                                                        storage_type)
            LOG.info("iops limit is %s", iops_limit)
            LOG.info("bandwidth limit is %s", bandwidth_limit)
            connection_properties['iopsLimit'] = iops_limit
            connection_properties['bandwidthLimit'] = bandwidth_limit

        return {'driver_volume_type': 'scaleio',
                'data': connection_properties}

    def _get_bandwidth_limit(self, size, storage_type):
        try:
            max_bandwidth = storage_type.get(QOS_BANDWIDTH_LIMIT)
            if max_bandwidth is not None:
                max_bandwidth = (self._round_to_num_gran(int(max_bandwidth),
                                                         units.Ki))
                max_bandwidth = six.text_type(max_bandwidth)
            LOG.info("max bandwidth is: %s", max_bandwidth)
            bw_per_gb = storage_type.get(QOS_BANDWIDTH_PER_GB)
            LOG.info("bandwidth per gb is: %s", bw_per_gb)
            if bw_per_gb is None:
                return max_bandwidth
            # Since VxFlex OS volumes size is in 8GB granularity
            # and BWS limitation is in 1024 KBs granularity, we need to make
            # sure that scaled_bw_limit is in 128 granularity.
            scaled_bw_limit = (size *
                               self._round_to_num_gran(int(bw_per_gb),
                                                       MIN_BWS_SCALING_SIZE))
            if max_bandwidth is None or scaled_bw_limit < int(max_bandwidth):
                return six.text_type(scaled_bw_limit)
            else:
                return max_bandwidth
        except ValueError:
            msg = _("None numeric BWS QoS limitation")
            raise exception.InvalidInput(reason=msg)

    def _get_iops_limit(self, size, storage_type):
        max_iops = storage_type.get(QOS_IOPS_LIMIT_KEY)
        LOG.info("max iops is: %s", max_iops)
        iops_per_gb = storage_type.get(QOS_IOPS_PER_GB)
        LOG.info("iops per gb is: %s", iops_per_gb)
        try:
            if iops_per_gb is None:
                if max_iops is not None:
                    return six.text_type(max_iops)
                else:
                    return None
            scaled_iops_limit = size * int(iops_per_gb)
            if max_iops is None or scaled_iops_limit < int(max_iops):
                return six.text_type(scaled_iops_limit)
            else:
                return six.text_type(max_iops)
        except ValueError:
            msg = _("None numeric IOPS QoS limitation")
            raise exception.InvalidInput(reason=msg)

    def terminate_connection(self, volume, connector, **kwargs):
        self._terminate_connection(volume, connector)

    def _terminate_connection(self, volume_or_snap, connector):
        """Terminate connection to a volume or snapshot

        With VxFlex OS, snaps and volumes are terminated identically
        """
        try:
            ip = connector['ip']
        except Exception:
            ip = 'unknown'

        LOG.debug("Terminating connection for %(vol)s, "
                  "to SDC at %(sdc)s",
                  {'vol': volume_or_snap.id,
                   'sdc': ip})

    def _update_volume_stats(self):
        stats = {}

        backend_name = self.configuration.safe_get('volume_backend_name')
        stats['volume_backend_name'] = backend_name or 'vxflexos'
        stats['vendor_name'] = 'Dell EMC'
        stats['driver_version'] = self.VERSION
        stats['storage_protocol'] = 'scaleio'
        stats['reserved_percentage'] = 0
        stats['QoS_support'] = True
        stats['consistent_group_snapshot_enabled'] = True
        stats['thick_provisioning_support'] = True
        stats['thin_provisioning_support'] = True
        stats['multiattach'] = True
        pools = []

        backend_free_capacity = 0
        backend_total_capacity = 0
        backend_provisioned_capacity = 0

        for sp_name in self.storage_pools:
            splitted_name = sp_name.split(':')
            domain_name = splitted_name[0]
            pool_name = splitted_name[1]
            total_capacity_gb, free_capacity_gb, provisioned_capacity = (
                self._query_pool_stats(domain_name, pool_name))
            pool_support_thick_vols = self._check_pool_support_thick_vols(
                domain_name, pool_name
            )
            pool_support_thin_vols = self._check_pool_support_thin_vols(
                domain_name, pool_name
            )
            pool_support_compression = self._check_pool_support_compression(
                domain_name, pool_name
            )
            pool = {'pool_name': sp_name,
                    'total_capacity_gb': total_capacity_gb,
                    'free_capacity_gb': free_capacity_gb,
                    'QoS_support': True,
                    'consistent_group_snapshot_enabled': True,
                    'reserved_percentage': 0,
                    'thin_provisioning_support': pool_support_thin_vols,
                    'thick_provisioning_support': pool_support_thick_vols,
                    'multiattach': True,
                    'provisioned_capacity_gb': provisioned_capacity,
                    'max_over_subscription_ratio':
                        self.configuration.max_over_subscription_ratio,
                    'compression_support': pool_support_compression}

            pools.append(pool)
            backend_free_capacity += free_capacity_gb
            backend_total_capacity += total_capacity_gb
            backend_provisioned_capacity += provisioned_capacity

        stats['total_capacity_gb'] = backend_total_capacity
        stats['free_capacity_gb'] = backend_free_capacity
        stats['provisioned_capacity_gb'] = backend_provisioned_capacity
        LOG.info("Free capacity for backend '%(backend)s': %(free)s, "
                 "total capacity: %(total)s, "
                 "provisioned capacity: %(prov)s.",
                 {'backend': stats["volume_backend_name"],
                  'free': backend_free_capacity,
                  'total': backend_total_capacity,
                  'prov': backend_provisioned_capacity})

        stats['pools'] = pools

        self._stats = stats

    def _query_pool_stats(self, domain_name, pool_name):
        pool_id = self._get_storage_pool_id(domain_name, pool_name)
        LOG.debug("Query stats for pool with id: %s.", pool_id)

        req_vars = {'server_ip': self.server_ip,
                    'server_port': self.server_port}
        request = ("https://%(server_ip)s:%(server_port)s"
                   "/api/types/StoragePool/instances/action/"
                   "querySelectedStatistics") % req_vars

        props = self._get_queryable_statistics("StoragePool", pool_id)
        params = {'ids': [pool_id], 'properties': props}

        r, response = self._execute_vxflexos_post_request(params, request)
        LOG.debug("Query capacity stats response: %s.", response)
        if r.status_code != http_client.OK:
            msg = (_("Error during query storage pool stats"))
            raise exception.VolumeBackendAPIException(data=msg)
        # there is always exactly one value in response
        raw_pool_stats, = response.values()
        total_capacity_gb, free_capacity_gb, provisioned_capacity = (
            self._compute_pool_stats(raw_pool_stats))
        LOG.info("Free capacity of pool %(pool)s is: %(free)s, "
                 "total capacity: %(total)s, "
                 "provisioned capacity: %(prov)s.",
                 {'pool': "%s:%s" % (domain_name, pool_name),
                  'free': free_capacity_gb,
                  'total': total_capacity_gb,
                  'prov': provisioned_capacity})

        return total_capacity_gb, free_capacity_gb, provisioned_capacity

    def _compute_pool_stats(self, stats):
        if self._version_greater_than_or_equal(
                self._get_server_api_version(),
                "3.0"):
            return self._compute_pool_stats_v3(stats)
        # Divide by two because VxFlex OS creates
        # a copy for each volume
        total_capacity_raw = self._convert_kb_to_gib(
            (stats['capacityLimitInKb'] - stats['spareCapacityInKb']) / 2)

        total_capacity_gb = self._round_down_to_num_gran(total_capacity_raw)
        # This property is already rounded
        # to 8 GB granularity in backend
        free_capacity_gb = self._convert_kb_to_gib(
            stats['capacityAvailableForVolumeAllocationInKb'])
        thin_capacity_allocated = 0
        # some versions of the API had a typo in the response
        try:
            thin_capacity_allocated = stats['thinCapacityAllocatedInKm']
        except (TypeError, KeyError):
            pass
        # some versions of the API respond without a typo
        try:
            thin_capacity_allocated = stats['thinCapacityAllocatedInKb']
        except (TypeError, KeyError):
            pass

        # Divide by two because VxFlex OS creates
        # a copy for each volume
        provisioned_capacity = self._convert_kb_to_gib(
            (stats['thickCapacityInUseInKb'] +
             stats['snapCapacityInUseInKb'] +
             thin_capacity_allocated) / 2)
        return total_capacity_gb, free_capacity_gb, provisioned_capacity

    def _compute_pool_stats_v3(self, stats):
        total_capacity_gb = self._convert_kb_to_gib(
            stats['netCapacityInUseInKb'] + stats['netUnusedCapacityInKb'])
        free_capacity_gb = self._convert_kb_to_gib(
            stats['netUnusedCapacityInKb'])
        provisioned_capacity_gb = self._convert_kb_to_gib(
            (stats['thickCapacityInUseInKb'] +
             stats['snapCapacityInUseInKb'] +
             stats['thinCapacityAllocatedInKb']) / 2)
        return total_capacity_gb, free_capacity_gb, provisioned_capacity_gb

    def _check_pool_support_thick_vols(self, domain_name, pool_name):
        # storage pools with fine granularity doesn't support
        # thick volumes
        return not self._is_fine_granularity_pool(domain_name, pool_name)

    def _check_pool_support_thin_vols(self, domain_name, pool_name):
        # thin volumes available since VxFlex OS 2.x
        return self._version_greater_than_or_equal(
            self._get_server_api_version(),
            "2.0")

    def _check_pool_support_compression(self, domain_name, pool_name):
        # volume compression available only in storage pools
        # with fine granularity
        return self._is_fine_granularity_pool(domain_name, pool_name)

    def _is_fine_granularity_pool(self, domain_name, pool_name):
        if self._version_greater_than_or_equal(
                self._get_server_api_version(),
                "3.0"):
            r = self._get_storage_pool_properties(domain_name, pool_name)
            if r and "dataLayout" in r:
                return r['dataLayout'] == "FineGranularity"
        return False

    def get_volume_stats(self, refresh=False):
        """Get volume stats.

        If 'refresh' is True, run update the stats first.
        """
        if refresh:
            self._update_volume_stats()

        return self._stats

    @staticmethod
    def _get_volumetype_extraspecs(volume):
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
                if key in self.vxflexos_qos_keys:
                    qos[key] = value
        return qos

    def _sio_attach_volume(self, volume):
        """Call connector.connect_volume() and return the path. """
        LOG.debug("Calling os-brick to attach VxFlex OS volume.")
        connection_properties = dict(self.connection_properties)
        connection_properties['scaleIO_volname'] = self._id_to_base64(
            volume.id)
        connection_properties['scaleIO_volume_id'] = volume.provider_id
        device_info = self.connector.connect_volume(connection_properties)
        return device_info['path']

    def _sio_detach_volume(self, volume):
        """Call the connector.disconnect() """
        LOG.info("Calling os-brick to detach VxFlex OS volume.")
        connection_properties = dict(self.connection_properties)
        connection_properties['scaleIO_volname'] = self._id_to_base64(
            volume.id)
        connection_properties['scaleIO_volume_id'] = volume.provider_id
        self.connector.disconnect_volume(connection_properties, volume)

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetch the image from image_service and write it to the volume."""
        LOG.info("VxFlex OS copy_image_to_volume volume: "
                 "%(vol)s image service: %(service)s image id: %(id)s.",
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
        LOG.info("VxFlex OS copy_volume_to_image volume: "
                 "%(vol)s image service: %(service)s image meta: %(meta)s.",
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
        """Return the update from VxFlex OS migrated volume.

        This method updates the volume name of the new VxFlex OS volume to
        match the updated volume ID.
        The original volume is renamed first since VxFlex OS does not allow
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
            LOG.info("Renaming %(id)s from %(current_name)s to "
                     "%(new_name)s.",
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
        LOG.info("VxFlex OS rename volume request: %s.", request)

        params = {'newName': new_name}
        r, response = self._execute_vxflexos_post_request(params, request)

        if r.status_code != http_client.OK:
            error_code = response['errorCode']
            if ((error_code == VOLUME_NOT_FOUND_ERROR or
                 error_code == OLD_VOLUME_NOT_FOUND_ERROR or
                 error_code == ILLEGAL_SYNTAX)):
                LOG.info("Ignoring renaming action because the volume "
                         "%(vol)s is not a VxFlex OS volume.",
                         {'vol': vol_id})
            else:
                msg = (_("Error renaming volume %(vol)s: %(err)s.") %
                       {'vol': vol_id, 'err': response['message']})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
        else:
            LOG.info("VxFlex OS volume %(vol)s was renamed to "
                     "%(new_name)s.",
                     {'vol': vol_id, 'new_name': new_name})

    def _query_vxflexos_volume(self, volume, existing_ref):
        request = self._create_vxflexos_get_volume_request(volume,
                                                           existing_ref)
        r, response = self._execute_vxflexos_get_request(request)
        self._manage_existing_check_legal_response(r, existing_ref)
        return response

    def _get_protection_domain_id(self, domain_name):
        """"Get the id of the protection domain"""

        response = self._get_protection_domain_properties(domain_name)
        if response is None:
            return None

        return response['id']

    def _get_storage_pool_name(self, pool_id):
        """Get the protection domain:storage pool name

        From a storage pool id, get the domain name and
        storage pool names
        """
        req_vars = {'server_ip': self.server_ip,
                    'server_port': self.server_port,
                    'pool_id': pool_id}
        request = ("https://%(server_ip)s:%(server_port)s"
                   "/api/instances/StoragePool::%(pool_id)s") % req_vars
        r, response = self._execute_vxflexos_get_request(request)

        if r.status_code != http_client.OK:
            msg = (_("Error getting pool name from id %(pool_id)s: "
                     "%(err_msg)s.")
                   % {'pool_id': pool_id})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        pool_name = response['name']
        domain_id = response['protectionDomainId']
        domain_name = self._get_protection_domain_name(domain_id)

        pool_name = "{}:{}".format(domain_name, pool_name)

        return pool_name

    def _get_protection_domain_name(self, domain_id):
        """Get the protection domain name

        From a protection domain id, get the domain name
        """
        req_vars = {'server_ip': self.server_ip,
                    'server_port': self.server_port,
                    'domain_id': domain_id}
        request = ("https://%(server_ip)s:%(server_port)s"
                   "/api/instances/ProtectionDomain::%(domain_id)s") % req_vars
        r, response = self._execute_vxflexos_get_request(request)

        if r.status_code != http_client.OK:
            msg = (_("Error getting domain name from id %(domain_id)s: "
                     "%(err_msg)s.")
                   % {'domain_id': domain_id,
                      'err_msg': response})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        domain_name = response['name']

        return domain_name

    def _get_protection_domain_properties(self, domain_name):
        """Get the props of the configured protection domain"""
        if not domain_name:
            msg = _("Error getting domain id from None name.")
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        cached_val = self.pdCache.get_value(domain_name)
        if cached_val is not None:
            return cached_val

        encoded_domain_name = urllib.parse.quote(domain_name, '')
        req_vars = {'server_ip': self.server_ip,
                    'server_port': self.server_port,
                    'encoded_domain_name': encoded_domain_name}
        request = ("https://%(server_ip)s:%(server_port)s"
                   "/api/types/Domain/instances/getByName::"
                   "%(encoded_domain_name)s") % req_vars

        r, domain_id = self._execute_vxflexos_get_request(request)

        if not domain_id:
            msg = (_("Domain with name %s wasn't found.")
                   % domain_name)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        if r.status_code != http_client.OK and "errorCode" in domain_id:
            msg = (_("Error getting domain id from name %(name)s: %(id)s.")
                   % {'name': domain_name,
                      'id': domain_id['message']})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.info("Domain id is %s.", domain_id)

        req_vars = {'server_ip': self.server_ip,
                    'server_port': self.server_port,
                    'domain_id': domain_id}
        request = ("https://%(server_ip)s:%(server_port)s"
                   "/api/instances/ProtectionDomain::%(domain_id)s") % req_vars
        r, response = self._execute_vxflexos_get_request(request)

        if r.status_code != http_client.OK:
            msg = (_("Error getting domain properties from id %(domain_id)s: "
                     "%(err_msg)s.")
                   % {'domain_id': domain_id,
                      'err_msg': response})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        self.pdCache.update(domain_name, response)
        return response

    def _get_storage_pool_properties(self, domain_name, pool_name):
        """Get the props of the configured storage pool"""
        if not domain_name or not pool_name:
            msg = (_("Unable to query the storage pool id for "
                     "Pool %(pool_name)s and Domain %(domain_name)s.")
                   % {'pool_name': pool_name,
                      'domain_name': domain_name})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        fullname = "{}:{}".format(domain_name, pool_name)

        cached_val = self.spCache.get_value(fullname)
        if cached_val is not None:
            return cached_val

        domain_id = self._get_protection_domain_id(domain_name)
        encoded_pool_name = urllib.parse.quote(pool_name, '')
        req_vars = {'server_ip': self.server_ip,
                    'server_port': self.server_port,
                    'domain_id': domain_id,
                    'encoded_pool_name': encoded_pool_name}
        request = ("https://%(server_ip)s:%(server_port)s"
                   "/api/types/Pool/instances/getByName::"
                   "%(domain_id)s,%(encoded_pool_name)s") % req_vars
        LOG.debug("VxFlex OS get pool id by name request: %s.", request)
        r, pool_id = self._execute_vxflexos_get_request(request)

        if not pool_id:
            msg = (_("Pool with name %(pool_name)s wasn't found in "
                     "domain %(domain_id)s.")
                   % {'pool_name': pool_name,
                      'domain_id': domain_id})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        if r.status_code != http_client.OK and "errorCode" in pool_id:
            msg = (_("Error getting pool id from name %(pool_name)s: "
                     "%(err_msg)s.")
                   % {'pool_name': pool_name,
                      'err_msg': pool_id['message']})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.info("Pool id is %s.", pool_id)

        req_vars = {'server_ip': self.server_ip,
                    'server_port': self.server_port,
                    'pool_id': pool_id}
        request = ("https://%(server_ip)s:%(server_port)s"
                   "/api/instances/StoragePool::%(pool_id)s") % req_vars
        r, response = self._execute_vxflexos_get_request(request)

        if r.status_code != http_client.OK:
            msg = (_("Error getting pool properties from id %(pool_id)s: "
                     "%(err_msg)s.")
                   % {'pool_id': pool_id,
                      'err_msg': response})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        self.spCache.update(fullname, response)
        return response

    def _get_storage_pool_id(self, domain_name, pool_name):
        """Get the id of the configured storage pool"""

        response = self._get_storage_pool_properties(domain_name, pool_name)
        if response is None:
            return None

        return response['id']

    def _get_all_vxflexos_volumes(self):
        """Gets list of all VxFlex OS volumes in PD and SP"""

        all_volumes = []
        # check for every storage pool configured
        for sp_name in self.storage_pools:
            splitted_name = sp_name.split(':')
            domain_name = splitted_name[0]
            pool_name = splitted_name[1]

            sp_id = self._get_storage_pool_id(domain_name, pool_name)

            req_vars = {'server_ip': self.server_ip,
                        'server_port': self.server_port,
                        'storage_pool_id': sp_id}
            request = ("https://%(server_ip)s:%(server_port)s"
                       "/api/instances/StoragePool::%(storage_pool_id)s"
                       "/relationships/Volume") % req_vars
            r, volumes = self._execute_vxflexos_get_request(request)

            if r.status_code != http_client.OK:
                msg = (_("Error calling api "
                         "status code: %d") % r.status_code)
                raise exception.VolumeBackendAPIException(data=msg)

            all_volumes.extend(volumes)

        return all_volumes

    def get_manageable_volumes(self, cinder_volumes, marker, limit, offset,
                               sort_keys, sort_dirs):
        """List volumes on the backend available for management by Cinder.

        Rule out volumes that are mapped to an SDC or
        are already in the list of cinder_volumes.
        Return references of the volume ids for any others.
        """

        all_sio_volumes = self._get_all_vxflexos_volumes()

        # Put together a map of existing cinder volumes on the array
        # so we can lookup cinder id's to SIO id
        existing_vols = {}
        for cinder_vol in cinder_volumes:
            provider_id = cinder_vol['provider_id']
            existing_vols[provider_id] = cinder_vol.name_id

        manageable_volumes = []
        for sio_vol in all_sio_volumes:
            cinder_id = existing_vols.get(sio_vol['id'])
            is_safe = True
            reason = None

            if sio_vol['mappedSdcInfo']:
                is_safe = False
                numHosts = len(sio_vol['mappedSdcInfo'])
                reason = _('Volume mapped to %d host(s).') % numHosts

            if cinder_id:
                is_safe = False
                reason = _("Volume already managed.")

            if sio_vol['volumeType'] != 'Snapshot':
                manageable_volumes.append({
                    'reference': {'source-id': sio_vol['id']},
                    'size': self._convert_kb_to_gib(sio_vol['sizeInKb']),
                    'safe_to_manage': is_safe,
                    'reason_not_safe': reason,
                    'cinder_id': cinder_id,
                    'extra_info': {'volumeType': sio_vol['volumeType'],
                                   'name': sio_vol['name']}})

        return volume_utils.paginate_entries_list(
            manageable_volumes, marker, limit, offset, sort_keys, sort_dirs)

    def _is_managed(self, volume_id):
        lst = objects.VolumeList.get_all_by_host(context.get_admin_context(),
                                                 self.host)
        for vol in lst:
            if vol.provider_id == volume_id:
                return True

        return False

    def manage_existing(self, volume, existing_ref):
        """Manage an existing VxFlex OS volume.

        existing_ref is a dictionary of the form:
        {'source-id': <id of VxFlex OS volume>}
        """
        response = self._query_vxflexos_volume(volume, existing_ref)
        return {'provider_id': response['id']}

    def manage_existing_get_size(self, volume, existing_ref):
        return self._get_volume_size(volume, existing_ref)

    def manage_existing_snapshot(self, snapshot, existing_ref):
        """Manage an existing VxFlex OS snapshot.

        :param snapshot: the snapshot to manage
        :param existing_ref: dictionary of the form:
            {'source-id': <id of VxFlex OS snapshot>}
        """
        response = self._query_vxflexos_volume(snapshot, existing_ref)
        not_real_parent = (response.get('orig_parent_overriden') or
                           response.get('is_source_deleted'))
        if not_real_parent:
            reason = (_("The snapshot's parent is not the original parent due "
                        "to deletion or revert action, therefore "
                        "this snapshot cannot be managed."))
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref,
                reason=reason
            )
        ancestor_id = response['ancestorVolumeId']
        volume_id = snapshot.volume.provider_id
        if ancestor_id != volume_id:
            reason = (_("The snapshot's parent in VxFlex OS is %(ancestor)s "
                        "and not %(volume)s.") %
                      {'ancestor': ancestor_id, 'volume': volume_id})
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref,
                reason=reason
            )
        return {'provider_id': response['id']}

    def manage_existing_snapshot_get_size(self, snapshot, existing_ref):
        return self._get_volume_size(snapshot, existing_ref)

    def _get_volume_size(self, volume, existing_ref):
        response = self._query_vxflexos_volume(volume, existing_ref)
        return int(math.ceil(float(response['sizeInKb']) / units.Mi))

    def _execute_vxflexos_get_request(self, request):
        r = requests.get(
            request,
            auth=(
                self.server_username,
                self.server_token),
            verify=self._get_verify_cert())
        r = self._check_response(r, request)
        response = r.json()
        return r, response

    def _create_vxflexos_get_volume_request(self, volume, existing_ref):
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
        LOG.info("VxFlex OS get volume by id request: %s.", request)
        return request

    def _manage_existing_check_legal_response(self, response, existing_ref):
        if response.status_code != http_client.OK:
            reason = (_("Error managing volume: %s.") % response.json()[
                'message'])
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref,
                reason=reason
            )

        # check if it is already managed
        if self._is_managed(response.json()['id']):
            reason = _("manage_existing cannot manage a volume "
                       "that is already being managed.")
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref,
                reason=reason
            )

        if response.json()['mappedSdcInfo'] is not None:
            reason = _("manage_existing cannot manage a volume "
                       "connected to hosts. Please disconnect this volume "
                       "from existing hosts before importing.")
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref,
                reason=reason
            )

    def create_group(self, context, group):
        """Creates a group.

        :param context: the context of the caller.
        :param group: the group object.
        :returns: model_update

        VxFlex OS won't create CG until cg-snapshot creation,
        db will maintain the volumes and CG relationship.
        """

        # let generic volume group support handle non-cgsnapshots
        if not volume_utils.is_group_a_cg_snapshot_type(group):
            raise NotImplementedError()

        LOG.info("Creating Group")
        model_update = {'status': fields.GroupStatus.AVAILABLE}
        return model_update

    def delete_group(self, context, group, volumes):
        """Deletes a group.

        :param context: the context of the caller.
        :param group: the group object.
        :param volumes: a list of volume objects in the group.
        :returns: model_update, volumes_model_update

        VxFlex OS will delete the volumes of the CG.
        """

        # let generic volume group support handle non-cgsnapshots
        if not volume_utils.is_group_a_cg_snapshot_type(group):
            raise NotImplementedError()

        LOG.info("Deleting Group")
        model_update = {'status': fields.GroupStatus.DELETED}
        error_statuses = [fields.GroupStatus.ERROR,
                          fields.GroupStatus.ERROR_DELETING]
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
                LOG.error("Failed to delete the volume %(vol)s of group. "
                          "Exception: %(exception)s.",
                          {'vol': volume['name'], 'exception': err})
        return model_update, volumes_model_update

    def create_group_snapshot(self, context, group_snapshot, snapshots):
        """Creates a group snapshot.

        :param context: the context of the caller.
        :param group_snapshot: the GroupSnapshot object to be created.
        :param snapshots: a list of Snapshot objects in the group_snapshot.
        :returns: model_update, snapshots_model_update
        """

        # let generic volume group support handle non-cgsnapshots
        if not volume_utils.is_group_a_cg_snapshot_type(group_snapshot):
            raise NotImplementedError()

        def get_vxflexos_snapshot_params(snapshot):
            return {
                'volumeId': snapshot.volume['provider_id'],
                'snapshotName': self._id_to_base64(snapshot['id'])
            }

        snapshot_defs = list(map(get_vxflexos_snapshot_params, snapshots))
        r, response = self._snapshot_volume_group(snapshot_defs)
        if r.status_code != http_client.OK and "errorCode" in response:
            msg = (_("Failed creating snapshot for group: "
                     "%(response)s.") %
                   {'response': response['message']})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        snapshot_model_update = []
        for snapshot, vxflexos_id in zip(snapshots, response['volumeIdList']):
            update_item = {'id': snapshot['id'],
                           'status': fields.SnapshotStatus.AVAILABLE,
                           'provider_id': vxflexos_id}
            snapshot_model_update.append(update_item)
        model_update = {'status': fields.GroupStatus.AVAILABLE}
        return model_update, snapshot_model_update

    def delete_group_snapshot(self, context, group_snapshot, snapshots):
        """Deletes a snapshot.

        :param context: the context of the caller.
        :param group_snapshot: the GroupSnapshot object to be deleted.
        :param snapshots: a list of snapshot objects in the group_snapshot.
        :returns: model_update, snapshots_model_update
        """

        # let generic volume group support handle non-cgsnapshots
        if not volume_utils.is_group_a_cg_snapshot_type(group_snapshot):
            raise NotImplementedError()

        error_statuses = [fields.SnapshotStatus.ERROR,
                          fields.SnapshotStatus.ERROR_DELETING]
        model_update = {'status': group_snapshot['status']}
        snapshot_model_update = []
        for snapshot in snapshots:
            try:
                self._delete_volume(snapshot.provider_id)
                update_item = {'id': snapshot['id'],
                               'status': fields.SnapshotStatus.DELETED}
                snapshot_model_update.append(update_item)
            except exception.VolumeBackendAPIException as err:
                update_item = {'id': snapshot['id'],
                               'status': fields.SnapshotStatus.ERROR_DELETING}
                snapshot_model_update.append(update_item)
                if model_update['status'] not in error_statuses:
                    model_update['status'] = (
                        fields.SnapshotStatus.ERROR_DELETING)
                LOG.error("Failed to delete the snapshot %(snap)s "
                          "of snapshot: %(snapshot_id)s. "
                          "Exception: %(exception)s.",
                          {'snap': snapshot['name'],
                           'exception': err,
                           'snapshot_id': group_snapshot.id})
        model_update['status'] = fields.GroupSnapshotStatus.DELETED
        return model_update, snapshot_model_update

    def create_group_from_src(self, context, group, volumes,
                              group_snapshot=None, snapshots=None,
                              source_group=None, source_vols=None):
        """Creates a group from source.

        :param context: the context of the caller.
        :param group: the Group object to be created.
        :param volumes: a list of Volume objects in the group.
        :param group_snapshot: the GroupSnapshot object as source.
        :param snapshots: a list of snapshot objects in group_snapshot.
        :param source_group: the Group object as source.
        :param source_vols: a list of volume objects in the source_group.
        :returns: model_update, volumes_model_update
        """

        # let generic volume group support handle non-cgsnapshots
        if not volume_utils.is_group_a_cg_snapshot_type(group):
            raise NotImplementedError()

        def get_vxflexos_snapshot_params(src_volume, trg_volume):
            return {
                'volumeId': src_volume['provider_id'],
                'snapshotName': self._id_to_base64(trg_volume['id'])
            }

        if group_snapshot and snapshots:
            snapshot_defs = map(get_vxflexos_snapshot_params,
                                snapshots,
                                volumes)
        else:
            snapshot_defs = map(get_vxflexos_snapshot_params,
                                source_vols,
                                volumes)
        r, response = self._snapshot_volume_group(list(snapshot_defs))
        if r.status_code != http_client.OK and "errorCode" in response:
            msg = (_("Failed creating snapshot for group: "
                     "%(response)s.") %
                   {'response': response['message']})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        volumes_model_update = []
        for volume, vxflexos_id in zip(volumes, response['volumeIdList']):
            update_item = {'id': volume['id'],
                           'status': 'available',
                           'provider_id': vxflexos_id}
            volumes_model_update.append(update_item)
        model_update = {'status': fields.GroupStatus.AVAILABLE}
        return model_update, volumes_model_update

    def update_group(self, context, group,
                     add_volumes=None, remove_volumes=None):
        """Update a  group.

        :param context: the context of the caller.
        :param group: the group object.
        :param add_volumes: a list of volume objects to be added.
        :param remove_volumes: a list of volume objects to be removed.
        :returns: model_update, add_volumes_update, remove_volumes_update

        VxFlex OS does not handle volume grouping.
        Cinder maintains volumes and CG relationship.
        """

        if volume_utils.is_group_a_cg_snapshot_type(group):
            return None, None, None

        # we'll rely on the generic group implementation if it is not a
        # consistency group request.
        raise NotImplementedError()

    def _snapshot_volume_group(self, snapshot_defs):
        LOG.info("VxFlex OS snapshot group of volumes")
        params = {'snapshotDefs': snapshot_defs}
        req_vars = {'server_ip': self.server_ip,
                    'server_port': self.server_port}
        request = ("https://%(server_ip)s:%(server_port)s"
                   "/api/instances/System/action/snapshotVolumes") % req_vars
        return self._execute_vxflexos_post_request(params, request)

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

    def initialize_connection_snapshot(self, snapshot, connector, **kwargs):
        # return self._initialize_connection(snapshot, connector)
        """Initializes a connection and returns connection info."""
        try:
            vol_size = snapshot['volume_size']
        except Exception:
            vol_size = None

        return self._initialize_connection(snapshot, connector, vol_size)

    def terminate_connection_snapshot(self, snapshot, connector, **kwargs):
        """Terminates a connection to a snapshot."""
        return self._terminate_connection(snapshot, connector)

    def create_export_snapshot(self, context, volume, connector):
        """Driver entry point to get the export info for a snapshot."""
        pass

    def remove_export_snapshot(self, context, volume):
        """Driver entry point to remove an export for a snapshot."""
        pass

    def backup_use_temp_snapshot(self):
        return True
