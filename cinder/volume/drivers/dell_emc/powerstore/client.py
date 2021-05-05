# Copyright (c) 2020 Dell Inc. or its subsidiaries.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""REST client for Dell EMC PowerStore Cinder Driver."""

import functools
import json

from oslo_log import log as logging
from oslo_utils import strutils
import requests

from cinder import exception
from cinder.i18n import _


LOG = logging.getLogger(__name__)
VOLUME_NOT_MAPPED_ERROR = "0xE0A08001000F"


class PowerStoreClient(object):
    def __init__(self, configuration):
        self.configuration = configuration
        self.rest_ip = None
        self.rest_username = None
        self.rest_password = None
        self.verify_certificate = None
        self.certificate_path = None
        self.base_url = None
        self.ok_codes = [
            requests.codes.ok,
            requests.codes.created,
            requests.codes.no_content,
            requests.codes.partial_content
        ]

    @property
    def _verify_cert(self):
        verify_cert = self.verify_certificate
        if self.verify_certificate and self.certificate_path:
            verify_cert = self.certificate_path
        return verify_cert

    def do_setup(self):
        self.rest_ip = self.configuration.safe_get("san_ip")
        self.rest_username = self.configuration.safe_get("san_login")
        self.rest_password = self.configuration.safe_get("san_password")
        self.base_url = "https://%s:/api/rest" % self.rest_ip
        self.verify_certificate = self.configuration.safe_get(
            "driver_ssl_cert_verify"
        )
        if self.verify_certificate:
            self.certificate_path = (
                self.configuration.safe_get("driver_ssl_cert_path")
            )

    def check_for_setup_error(self):
        if not all([self.rest_ip, self.rest_username, self.rest_password]):
            msg = _("REST server IP, username and password must be set.")
            raise exception.VolumeBackendAPIException(data=msg)

        # log warning if not using certificates
        if not self.verify_certificate:
            LOG.warning("Verify certificate is not set, using default of "
                        "False.")
        LOG.debug("Successfully initialized PowerStore REST client. "
                  "Server IP: %(ip)s, username: %(username)s. "
                  "Verify server's certificate: %(verify_cert)s.",
                  {
                      "ip": self.rest_ip,
                      "username": self.rest_username,
                      "verify_cert": self._verify_cert,
                  })

    def _send_request(self,
                      method,
                      url,
                      payload=None,
                      params=None,
                      log_response_data=True):
        if not payload:
            payload = {}
        if not params:
            params = {}
        request_params = {
            "auth": (self.rest_username, self.rest_password),
            "verify": self._verify_cert,
        }
        if method == "GET":
            request_params["params"] = params
        else:
            request_params["data"] = json.dumps(payload)
        request_url = self.base_url + url
        r = requests.request(method, request_url, **request_params)

        log_level = logging.DEBUG
        if r.status_code not in self.ok_codes:
            log_level = logging.ERROR
        LOG.log(log_level,
                "REST Request: %s %s with body %s",
                r.request.method,
                r.request.url,
                strutils.mask_password(r.request.body))
        if log_response_data or log_level == logging.ERROR:
            msg = "REST Response: %s with data %s" % (r.status_code, r.text)
        else:
            msg = "REST Response: %s" % r.status_code
        LOG.log(log_level, msg)

        try:
            response = r.json()
        except ValueError:
            response = None
        return r, response

    _send_get_request = functools.partialmethod(_send_request, "GET")
    _send_post_request = functools.partialmethod(_send_request, "POST")
    _send_patch_request = functools.partialmethod(_send_request, "PATCH")
    _send_delete_request = functools.partialmethod(_send_request, "DELETE")

    def get_chap_config(self):
        r, response = self._send_get_request(
            "/chap_config/0",
            params={
                "select": "mode"
            }
        )
        if r.status_code not in self.ok_codes:
            msg = _("Failed to query PowerStore CHAP configuration.")
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        return response

    def get_appliance_id_by_name(self, appliance_name):
        r, response = self._send_get_request(
            "/appliance",
            params={
                "name": "eq.%s" % appliance_name,
            }
        )
        if r.status_code not in self.ok_codes:
            msg = _("Failed to query PowerStore appliances.")
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        try:
            appliance_id = response[0].get("id")
            return appliance_id
        except IndexError:
            msg = _("PowerStore appliance %s is not found.") % appliance_name
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def get_appliance_metrics(self, appliance_id):
        r, response = self._send_post_request(
            "/metrics/generate",
            payload={
                "entity": "space_metrics_by_appliance",
                "entity_id": appliance_id,
            },
            log_response_data=False
        )
        if r.status_code not in self.ok_codes:
            msg = (_("Failed to query metrics for "
                     "PowerStore appliance with id %s.") % appliance_id)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        try:
            latest_metrics = response[-1]
            return latest_metrics
        except IndexError:
            msg = (_("Failed to query metrics for "
                     "PowerStore appliance with id %s.") % appliance_id)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def create_volume(self, appliance_id, name, size):
        r, response = self._send_post_request(
            "/volume",
            payload={
                "appliance_id": appliance_id,
                "name": name,
                "size": size,
            }
        )
        if r.status_code not in self.ok_codes:
            msg = _("Failed to create PowerStore volume %s.") % name
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        return response["id"]

    def delete_volume_or_snapshot(self, entity_id, entity="volume"):
        r, response = self._send_delete_request("/volume/%s" % entity_id)
        if r.status_code not in self.ok_codes:
            if r.status_code == requests.codes.not_found:
                LOG.warning("PowerStore %(entity)s with id %(entity_id)s is "
                            "not found. Ignoring error.",
                            {
                                "entity": entity,
                                "entity_id": entity_id,
                            })
            else:
                msg = (_("Failed to delete PowerStore %(entity)s with id "
                         "%(entity_id)s.")
                       % {"entity": entity,
                          "entity_id": entity_id, })
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

    def extend_volume(self, volume_id, size):
        r, response = self._send_patch_request(
            "/volume/%s" % volume_id,
            payload={
                "size": size,
            }
        )
        if r.status_code not in self.ok_codes:
            msg = (_("Failed to extend PowerStore volume with id %s.")
                   % volume_id)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def create_snapshot(self, volume_id, name):
        r, response = self._send_post_request(
            "/volume/%s/snapshot" % volume_id,
            payload={
                "name": name,
            }
        )
        if r.status_code not in self.ok_codes:
            msg = (_("Failed to create snapshot %(snapshot_name)s for "
                     "PowerStore volume with id %(volume_id)s.")
                   % {"snapshot_name": name,
                      "volume_id": volume_id, })
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        return response["id"]

    def clone_volume_or_snapshot(self,
                                 name,
                                 entity_id,
                                 entity="volume"):
        r, response = self._send_post_request(
            "/volume/%s/clone" % entity_id,
            payload={
                "name": name,
            }
        )
        if r.status_code not in self.ok_codes:
            msg = (_("Failed to create clone %(clone_name)s for "
                     "PowerStore %(entity)s with id %(entity_id)s.")
                   % {"clone_name": name,
                      "entity": entity,
                      "entity_id": entity_id, })
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        return response["id"]

    def get_all_hosts(self, protocol):
        r, response = self._send_get_request(
            "/host",
            params={
                "select": "id,name,host_initiators",
                "host_initiators->0->>port_type": "eq.%s" % protocol,
            }
        )
        if r.status_code not in self.ok_codes:
            msg = _("Failed to query PowerStore hosts.")
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        return response

    def create_host(self, name, ports):
        r, response = self._send_post_request(
            "/host",
            payload={
                "name": name,
                "os_type": "Linux",
                "initiators": ports
            }
        )
        if r.status_code not in self.ok_codes:
            msg = _("Failed to create PowerStore host %s.") % name
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        return response

    def modify_host_initiators(self, host_id, **kwargs):
        r, response = self._send_patch_request(
            "/host/%s" % host_id,
            payload={
                **kwargs,
            }
        )
        if r.status_code not in self.ok_codes:
            msg = (_("Failed to modify initiators of PowerStore host "
                     "with id %s.") % host_id)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def attach_volume_to_host(self, host_id, volume_id):
        r, response = self._send_post_request(
            "/volume/%s/attach" % volume_id,
            payload={
                "host_id": host_id,
            }
        )
        if r.status_code not in self.ok_codes:
            msg = (_("Failed to attach PowerStore volume %(volume_id)s "
                     "to host %(host_id)s.")
                   % {"volume_id": volume_id,
                      "host_id": host_id, })
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def get_volume_mapped_hosts(self, volume_id):
        r, response = self._send_get_request(
            "/host_volume_mapping",
            params={
                "volume_id": "eq.%s" % volume_id,
                "select": "host_id"
            }
        )
        if r.status_code not in self.ok_codes:
            msg = _("Failed to query PowerStore host volume mappings.")
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        mapped_hosts = [mapped_host["host_id"] for mapped_host in response]
        return mapped_hosts

    def get_volume_lun(self, host_id, volume_id):
        r, response = self._send_get_request(
            "/host_volume_mapping",
            params={
                "host_id": "eq.%s" % host_id,
                "volume_id": "eq.%s" % volume_id,
                "select": "logical_unit_number"
            }
        )
        if r.status_code not in self.ok_codes:
            msg = _("Failed to query PowerStore host volume mappings.")
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        try:
            logical_unit_number = response[0].get("logical_unit_number")
            return logical_unit_number
        except IndexError:
            msg = (_("PowerStore mapping of volume with id %(volume_id)s "
                     "to host %(host_id)s is not found.")
                   % {"volume_id": volume_id,
                      "host_id": host_id, })
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def get_fc_port(self, appliance_id):
        r, response = self._send_get_request(
            "/fc_port",
            params={
                "appliance_id": "eq.%s" % appliance_id,
                "is_link_up": "eq.True",
                "select": "wwn"

            }
        )
        if r.status_code not in self.ok_codes:
            msg = _("Failed to query PowerStore IP pool addresses.")
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        return response

    def get_ip_pool_address(self, appliance_id):
        r, response = self._send_get_request(
            "/ip_pool_address",
            params={
                "appliance_id": "eq.%s" % appliance_id,
                "purposes": "cs.{Storage_Iscsi_Target}",
                "select": "address,ip_port(target_iqn)"

            }
        )
        if r.status_code not in self.ok_codes:
            msg = _("Failed to query PowerStore IP pool addresses.")
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        return response

    def detach_volume_from_host(self, host_id, volume_id):
        r, response = self._send_post_request(
            "/volume/%s/detach" % volume_id,
            payload={
                "host_id": host_id,
            }
        )
        if r.status_code not in self.ok_codes:
            if r.status_code == requests.codes.not_found:
                LOG.warning("PowerStore volume with id %(volume_id)s is "
                            "not found. Ignoring error.",
                            {
                                "volume_id": volume_id,
                            })
            elif (
                    r.status_code == requests.codes.unprocessable and
                    any([
                        message["code"] == VOLUME_NOT_MAPPED_ERROR
                        for message in response["messages"]
                    ])
            ):
                LOG.warning("PowerStore volume with id %(volume_id)s is "
                            "not mapped to host with id %(host_id)s. "
                            "Ignoring error.",
                            {
                                "volume_id": volume_id,
                                "host_id": host_id,
                            })
            else:
                msg = (_("Failed to detach PowerStore volume %(volume_id)s "
                         "to host %(host_id)s.")
                       % {"volume_id": volume_id,
                          "host_id": host_id, })
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

    def restore_from_snapshot(self, volume_id, snapshot_id):
        r, response = self._send_post_request(
            "/volume/%s/restore" % volume_id,
            payload={
                "from_snap_id": snapshot_id,
                "create_backup_snap": False,
            }
        )
        if r.status_code not in self.ok_codes:
            msg = (_("Failed to restore PowerStore volume with id "
                     "%(volume_id)s from snapshot with id %(snapshot_id)s.")
                   % {"volume_id": volume_id,
                      "snapshot_id": snapshot_id, })
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
