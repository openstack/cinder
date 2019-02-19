#    (c) Copyright 2019 Brocade, a Broadcom Company
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
#

"""
Brocade Zone Connector Factory is responsible to dynamically create the
connection object based on the configuration
"""

from oslo_log import log as logging
from oslo_utils import importutils

from cinder.zonemanager.drivers.brocade import fc_zone_constants

LOG = logging.getLogger(__name__)


class BrcdFCZoneFactory(object):

    def __init__(self):
        self.sb_conn_map = {}

    def get_connector(self, fabric, sb_connector):
        """Returns Device Connector.

        Factory method to create and return
        correct SB connector object based on the protocol
        """

        fabric_ip = fabric.safe_get('fc_fabric_address')
        client = self.sb_conn_map.get(fabric_ip)

        if not client:

            fabric_user = fabric.safe_get('fc_fabric_user')
            fabric_pwd = fabric.safe_get('fc_fabric_password')
            fabric_port = fabric.safe_get('fc_fabric_port')
            fc_vfid = fabric.safe_get('fc_virtual_fabric_id')
            fabric_ssh_cert_path = fabric.safe_get('fc_fabric_ssh_cert_path')

            LOG.debug("Client not found. Creating connection client for"
                      " %(ip)s with %(connector)s protocol "
                      "for the user %(user)s at port %(port)s.",
                      {'ip': fabric_ip,
                       'connector': sb_connector,
                       'user': fabric_user,
                       'port': fabric_port,
                       'vf_id': fc_vfid})

            if sb_connector.lower() in (fc_zone_constants.REST_HTTP,
                                        fc_zone_constants.REST_HTTPS):
                client = importutils.import_object(
                    "cinder.zonemanager.drivers.brocade."
                    "brcd_rest_fc_zone_client.BrcdRestFCZoneClient",
                    ipaddress=fabric_ip,
                    username=fabric_user,
                    password=fabric_pwd,
                    port=fabric_port,
                    vfid=fc_vfid,
                    protocol=sb_connector
                )
            elif sb_connector.lower() in (fc_zone_constants.HTTP,
                                          fc_zone_constants.HTTPS):
                client = importutils.import_object(
                    "cinder.zonemanager.drivers.brocade."
                    "brcd_http_fc_zone_client.BrcdHTTPFCZoneClient",
                    ipaddress=fabric_ip,
                    username=fabric_user,
                    password=fabric_pwd,
                    port=fabric_port,
                    vfid=fc_vfid,
                    protocol=sb_connector
                )
            else:
                client = importutils.import_object(
                    "cinder.zonemanager.drivers.brocade."
                    "brcd_fc_zone_client_cli.BrcdFCZoneClientCLI",
                    ipaddress=fabric_ip,
                    username=fabric_user,
                    password=fabric_pwd,
                    key=fabric_ssh_cert_path,
                    port=fabric_port
                )
            self.sb_conn_map.update({fabric_ip: client})
        return client
