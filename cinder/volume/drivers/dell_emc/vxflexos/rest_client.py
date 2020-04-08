# Copyright (c) 2020 Dell Inc. or its subsidiaries.
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
import json
import re

from oslo_log import log as logging
from oslo_utils import units
import requests
import six
from six.moves import http_client
from six.moves import urllib

from cinder import exception
from cinder.i18n import _
from cinder.utils import retry
from cinder.volume.drivers.dell_emc.vxflexos import simplecache
from cinder.volume.drivers.dell_emc.vxflexos import utils as flex_utils

LOG = logging.getLogger(__name__)


VOLUME_NOT_FOUND_ERROR = 79
OLD_VOLUME_NOT_FOUND_ERROR = 78
ILLEGAL_SYNTAX = 0


class RestClient(object):
    def __init__(self, configuration):
        self.configuration = configuration
        self.spCache = simplecache.SimpleCache("Storage Pool", age_minutes=5)
        self.pdCache = simplecache.SimpleCache("Protection Domain",
                                               age_minutes=5)
        self.rest_ip = None
        self.rest_port = None
        self.rest_username = None
        self.rest_password = None
        self.rest_token = None
        self.rest_api_version = None
        self.verify_certificate = None
        self.certificate_path = None
        self.base_url = None
        self.is_configured = False

    @staticmethod
    def _get_headers():
        return {"content-type": "application/json"}

    @property
    def connection_properties(self):
        return {
            "scaleIO_volname": None,
            "hostIP": None,
            "serverIP": self.rest_ip,
            "serverPort": self.rest_port,
            "serverUsername": self.rest_username,
            "serverPassword": self.rest_password,
            "serverToken": self.rest_token,
            "iopsLimit": None,
            "bandwidthLimit": None,
        }

    def do_setup(self):
        self.rest_port = self.configuration.vxflexos_rest_server_port
        self.verify_certificate = (
            self.configuration.safe_get("sio_verify_server_certificate") or
            self.configuration.safe_get("driver_ssl_cert_verify")
        )
        self.rest_ip = self.configuration.safe_get("san_ip")
        self.rest_username = self.configuration.safe_get("san_login")
        self.rest_password = self.configuration.safe_get("san_password")
        if self.verify_certificate:
            self.certificate_path = (
                self.configuration.safe_get("sio_server_certificate_path") or
                self.configuration.safe_get("driver_ssl_cert_path")
            )
        if not all([self.rest_ip, self.rest_username, self.rest_password]):
            msg = _("REST server IP, username and password must be specified.")
            raise exception.InvalidInput(reason=msg)
        # validate certificate settings
        if self.verify_certificate and not self.certificate_path:
            msg = _("Path to REST server's certificate must be specified.")
            raise exception.InvalidInput(reason=msg)
        # log warning if not using certificates
        if not self.verify_certificate:
            LOG.warning("Verify certificate is not set, using default of "
                        "False.")
        self.base_url = ("https://%(server_ip)s:%(server_port)s/api" %
                         {
                             "server_ip": self.rest_ip,
                             "server_port": self.rest_port
                         })
        LOG.info("REST server IP: %(ip)s, port: %(port)s, "
                 "username: %(user)s. Verify server's certificate: "
                 "%(verify_cert)s.",
                 {
                     "ip": self.rest_ip,
                     "port": self.rest_port,
                     "user": self.rest_username,
                     "verify_cert": self.verify_certificate,
                 })
        self.is_configured = True

    def query_rest_api_version(self, fromcache=True):
        url = "/version"

        if self.rest_api_version is None or fromcache is False:
            r, unused = self.execute_vxflexos_get_request(url)
            if r.status_code == http_client.OK:
                self.rest_api_version = r.text.replace('\"', "")
                LOG.info("REST API Version: %(api_version)s.",
                         {"api_version": self.rest_api_version})
            else:
                msg = (_("Failed to query REST API version. "
                         "Status code: %d.") % r.status_code)
                raise exception.VolumeBackendAPIException(data=msg)
            # make sure the response was valid
            pattern = re.compile(r"^\d+(\.\d+)*$")
            if not pattern.match(self.rest_api_version):
                msg = (_("Failed to query REST API version. Response: %s.") %
                       r.text)
                raise exception.VolumeBackendAPIException(data=msg)
        return self.rest_api_version

    def query_volume(self, vol_id):
        url = "/instances/Volume::%(vol_id)s"

        r, response = self.execute_vxflexos_get_request(url, vol_id=vol_id)
        if r.status_code != http_client.OK and "errorCode" in response:
            msg = (_("Failed to query volume: %s.") % response["message"])
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        return response

    def create_volume(self,
                      protection_domain_name,
                      storage_pool_name,
                      volume,
                      provisioning,
                      compression):
        url = "/types/Volume/instances"

        domain_id = self._get_protection_domain_id(protection_domain_name)
        LOG.info("Protection Domain id: %s.", domain_id)
        pool_id = self.get_storage_pool_id(protection_domain_name,
                                           storage_pool_name)
        LOG.info("Storage Pool id: %s.", pool_id)
        volume_name = flex_utils.id_to_base64(volume.id)
        # units.Mi = 1024 ** 2
        volume_size_kb = volume.size * units.Mi
        params = {
            "protectionDomainId": domain_id,
            "storagePoolId": pool_id,
            "name": volume_name,
            "volumeType": provisioning,
            "volumeSizeInKb": six.text_type(volume_size_kb),
            "compressionMethod": compression,
        }
        r, response = self.execute_vxflexos_post_request(url, params)
        if r.status_code != http_client.OK and "errorCode" in response:
            msg = (_("Failed to create volume: %s.") % response["message"])
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        return response["id"]

    def snapshot_volume(self, volume_provider_id, snapshot_id):
        url = "/instances/System/action/snapshotVolumes"

        snap_name = flex_utils.id_to_base64(snapshot_id)
        params = {
            "snapshotDefs": [
                {
                    "volumeId": volume_provider_id,
                    "snapshotName": snap_name,
                },
            ],
        }
        r, response = self.execute_vxflexos_post_request(url, params)
        if r.status_code != http_client.OK and "errorCode" in response:
            msg = (_("Failed to create snapshot for volume %(vol_name)s: "
                     "%(response)s.") %
                   {"vol_name": volume_provider_id,
                    "response": response["message"]})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        return response["volumeIdList"][0]

    def _get_protection_domain_id_by_name(self, domain_name):
        url = "/types/Domain/instances/getByName::%(encoded_domain_name)s"

        if not domain_name:
            msg = _("Unable to query Protection Domain id with None name.")
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        encoded_domain_name = urllib.parse.quote(domain_name, "")
        r, domain_id = self.execute_vxflexos_get_request(
            url, encoded_domain_name=encoded_domain_name
        )
        if not domain_id:
            msg = (_("Prorection Domain with name %s wasn't found.")
                   % domain_name)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        if r.status_code != http_client.OK and "errorCode" in domain_id:
            msg = (_("Failed to get Protection Domain id with name "
                     "%(name)s: %(err_msg)s.") %
                   {"name": domain_name, "err_msg": domain_id["message"]})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        LOG.info("Protection Domain id: %s.", domain_id)
        return domain_id

    def _get_protection_domain_id(self, domain_name):
        response = self._get_protection_domain_properties(domain_name)
        if response is None:
            return None
        return response["id"]

    def _get_protection_domain_properties(self, domain_name):
        url = "/instances/ProtectionDomain::%(domain_id)s"

        cached_val = self.pdCache.get_value(domain_name)
        if cached_val is not None:
            return cached_val
        domain_id = self._get_protection_domain_id_by_name(domain_name)
        r, response = self.execute_vxflexos_get_request(
            url, domain_id=domain_id
        )
        if r.status_code != http_client.OK:
            msg = (_("Failed to get domain properties from id %(domain_id)s: "
                     "%(err_msg)s.") %
                   {"domain_id": domain_id, "err_msg": response})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        self.pdCache.update(domain_name, response)
        return response

    def _get_storage_pool_id_by_name(self, domain_name, pool_name):
        url = ("/types/Pool/instances/getByName::"
               "%(domain_id)s,%(encoded_pool_name)s")

        if not domain_name or not pool_name:
            msg = (_("Unable to query storage pool id for "
                     "Pool %(pool_name)s and Domain %(domain_name)s.") %
                   {"pool_name": pool_name, "domain_name": domain_name})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        domain_id = self._get_protection_domain_id(domain_name)
        encoded_pool_name = urllib.parse.quote(pool_name, "")
        r, pool_id = self.execute_vxflexos_get_request(
            url, domain_id=domain_id, encoded_pool_name=encoded_pool_name
        )
        if not pool_id:
            msg = (_("Pool with name %(pool_name)s wasn't found in "
                     "domain %(domain_id)s.") %
                   {"pool_name": pool_name, "domain_id": domain_id})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        if r.status_code != http_client.OK and "errorCode" in pool_id:
            msg = (_("Failed to get pool id from name %(pool_name)s: "
                     "%(err_msg)s.") %
                   {"pool_name": pool_name, "err_msg": pool_id["message"]})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        LOG.info("Pool id: %s.", pool_id)
        return pool_id

    def get_storage_pool_properties(self, domain_name, pool_name):
        url = "/instances/StoragePool::%(pool_id)s"

        fullname = "{}:{}".format(domain_name, pool_name)
        cached_val = self.spCache.get_value(fullname)
        if cached_val is not None:
            return cached_val
        pool_id = self._get_storage_pool_id_by_name(domain_name, pool_name)
        r, response = self.execute_vxflexos_get_request(url, pool_id=pool_id)
        if r.status_code != http_client.OK:
            msg = (_("Failed to get pool properties from id %(pool_id)s: "
                     "%(err_msg)s.") %
                   {"pool_id": pool_id, "err_msg": response})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        self.spCache.update(fullname, response)
        return response

    def get_storage_pool_id(self, domain_name, pool_name):
        response = self.get_storage_pool_properties(domain_name, pool_name)
        if response is None:
            return None
        return response["id"]

    def _get_verify_cert(self):
        verify_cert = False
        if self.verify_certificate:
            verify_cert = self.certificate_path
        return verify_cert

    def execute_vxflexos_get_request(self, url, **url_params):
        request = self.base_url + url % url_params
        r = requests.get(request,
                         auth=(self.rest_username, self.rest_token),
                         verify=self._get_verify_cert())
        r = self._check_response(r, request)
        response = r.json()
        return r, response

    def execute_vxflexos_post_request(self, url, params=None, **url_params):
        if not params:
            params = {}
        request = self.base_url + url % url_params
        r = requests.post(request,
                          data=json.dumps(params),
                          headers=self._get_headers(),
                          auth=(self.rest_username, self.rest_token),
                          verify=self._get_verify_cert())
        r = self._check_response(r, request, False, params)
        response = None
        try:
            response = r.json()
        except ValueError:
            response = None
        return r, response

    def _check_response(self,
                        response,
                        request,
                        is_get_request=True,
                        params=None):
        login_url = "/login"

        if (response.status_code == http_client.UNAUTHORIZED or
                response.status_code == http_client.FORBIDDEN):
            LOG.info("Token is invalid, going to re-login and get "
                     "a new one.")
            login_request = self.base_url + login_url
            verify_cert = self._get_verify_cert()
            r = requests.get(login_request,
                             auth=(self.rest_username, self.rest_password),
                             verify=verify_cert)
            token = r.json()
            self.rest_token = token
            # Repeat request with valid token.
            LOG.info("Going to perform request again %s with valid token.",
                     request)
            if is_get_request:
                response = requests.get(request,
                                        auth=(
                                            self.rest_username,
                                            self.rest_token
                                        ),
                                        verify=verify_cert)
            else:
                response = requests.post(request,
                                         data=json.dumps(params),
                                         headers=self._get_headers(),
                                         auth=(
                                             self.rest_username,
                                             self.rest_token
                                         ),
                                         verify=verify_cert)
        level = logging.DEBUG
        # for anything other than an OK from the REST API, log an error
        if response.status_code != http_client.OK:
            level = logging.ERROR
        LOG.log(level,
                "REST Request: %s with params %s",
                request,
                json.dumps(params))
        LOG.log(level,
                "REST Response: %s with data %s",
                response.status_code,
                response.text)
        return response

    @retry(exception.VolumeBackendAPIException)
    def extend_volume(self, vol_id, new_size):
        url = "/instances/Volume::%(vol_id)s/action/setVolumeSize"

        round_volume_capacity = (
            self.configuration.vxflexos_round_volume_capacity
        )
        if not round_volume_capacity and not new_size % 8 == 0:
            LOG.warning("VxFlex OS only supports volumes with a granularity "
                        "of 8 GBs. The new volume size is: %d.",
                        new_size)
        params = {"sizeInGB": six.text_type(new_size)}
        r, response = self.execute_vxflexos_post_request(url,
                                                         params,
                                                         vol_id=vol_id)
        if r.status_code != http_client.OK:
            response = r.json()
            msg = (_("Failed to extend volume %(vol_id)s: %(err)s.") %
                   {"vol_id": vol_id, "err": response["message"]})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def _unmap_volume_before_delete(self, vol_id):
        url = "/instances/Volume::%(vol_id)s/action/removeMappedSdc"

        volume_is_mapped = False
        try:
            volume = self.query_volume(vol_id)
            if volume.get("mappedSdcInfo") is not None:
                volume_is_mapped = True
        except exception.VolumeBackendAPIException:
            LOG.info("Volume %s is not found thus is not mapped to any SDC.",
                     vol_id)
        if volume_is_mapped:
            params = {"allSdcs": ""}
            LOG.info("Unmap volume from all sdcs before deletion.")
            r, unused = self.execute_vxflexos_post_request(url,
                                                           params,
                                                           vol_id=vol_id)

    @retry(exception.VolumeBackendAPIException)
    def remove_volume(self, vol_id):
        url = "/instances/Volume::%(vol_id)s/action/removeVolume"

        self._unmap_volume_before_delete(vol_id)
        params = {"removeMode": "ONLY_ME"}
        r, response = self.execute_vxflexos_post_request(url,
                                                         params,
                                                         vol_id=vol_id)
        if r.status_code != http_client.OK:
            error_code = response["errorCode"]
            if error_code == VOLUME_NOT_FOUND_ERROR:
                LOG.warning("Ignoring error in delete volume %s: "
                            "Volume not found.", vol_id)
            elif vol_id is None:
                LOG.warning("Volume does not have provider_id thus does not "
                            "map to a VxFlex OS volume. "
                            "Allowing deletion to proceed.")
            else:
                msg = (_("Failed to delete volume %(vol_id)s: %(err)s.") %
                       {"vol_id": vol_id, "err": response["message"]})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

    def is_volume_creation_safe(self, protection_domain, storage_pool):
        """Checks if volume creation is safe or not.

        Using volumes with zero padding disabled can lead to existing data
        being read off of a newly created volume.
        """

        # if we have been told to allow unsafe volumes
        if self.configuration.vxflexos_allow_non_padded_volumes:
            # Enabled regardless of type, so safe to proceed
            return True
        try:
            properties = self.get_storage_pool_properties(
                protection_domain, storage_pool
            )
            padded = properties["zeroPaddingEnabled"]
        except Exception:
            msg = (_("Unable to retrieve properties for pool %s.") %
                   storage_pool)
            raise exception.InvalidInput(reason=msg)
        # zero padded storage pools are safe
        if padded:
            return True
        # if we got here, it's unsafe
        return False

    def rename_volume(self, volume, name):
        url = "/instances/Volume::%(id)s/action/setVolumeName"

        new_name = flex_utils.id_to_base64(name)
        vol_id = volume["provider_id"]
        params = {"newName": new_name}
        r, response = self.execute_vxflexos_post_request(url,
                                                         params,
                                                         id=vol_id)
        if r.status_code != http_client.OK:
            error_code = response["errorCode"]
            if ((error_code == VOLUME_NOT_FOUND_ERROR or
                 error_code == OLD_VOLUME_NOT_FOUND_ERROR or
                 error_code == ILLEGAL_SYNTAX)):
                LOG.info("Ignore renaming action because the volume "
                         "%(vol_id)s is not a VxFlex OS volume.",
                         {"vol_id": vol_id})
            else:
                msg = (_("Failed to rename volume %(vol_id)s: %(err)s.") %
                       {"vol_id": vol_id, "err": response["message"]})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
        else:
            LOG.info("VxFlex OS volume %(vol_id)s was renamed to "
                     "%(new_name)s.", {"vol_id": vol_id, "new_name": new_name})
