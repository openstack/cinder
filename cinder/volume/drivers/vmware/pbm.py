# Copyright (c) 2013 VMware, Inc.
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
Class for making VMware PBM SOAP calls.

This is used for storage policy based placement of volumes. Read more about
it here:
http://pubs.vmware.com/vsphere-55/index.jsp#com.vmware.vspsdk.apiref.doc/\
right-pane.html
"""

import suds
import suds.sax.element as element

from cinder.openstack.common import log as logging
from cinder.volume.drivers.vmware import vim as vim_module
from cinder.volume.drivers.vmware import vim_util

LOG = logging.getLogger(__name__)
SERVICE_INSTANCE = 'ServiceInstance'
SERVICE_TYPE = 'PbmServiceInstance'


class PBMClient(vim_module.Vim):
    """Sets up a client to interact with the vSphere PBM APIs.

    This client piggy backs on Vim object's authenticated cookie to invoke
    PBM API calls.

    Note that this class needs the PBM wsdl file in order to make SOAP API
    calls. This wsdl file is included in the VMware Storage Policy SDK.
    A user of this feature needs to install this SDK on the Cinder volume
    nodes and configure the path in the cinder.conf file.
    """

    def __init__(self, vimSession, pbm_wsdl, protocol='https',
                 host='localhost'):
        """Constructs a PBM client object.

        :param vimSession: an authenticated api.VMwareAPISession object
        :param pbm_wsdl: URL path to where pbmService.wsdl file is located.
        :param protocol: http or https
        :param host: Server IPAddress[:port] or Hostname[:port]
        """
        self._vimSession = vimSession
        self._url = vim_util.get_soap_url(protocol, host, 'pbm')
        # create the pbm client
        self._client = suds.client.Client(pbm_wsdl, location=self._url,
                                          cache=suds.cache.NoCache())
        PBMClient._copy_client_cookie(self._vimSession, self._client)
        # Get the PBM service content
        si_moref = vim_module.get_moref(SERVICE_INSTANCE, SERVICE_TYPE)
        self._sc = self._client.service.PbmRetrieveServiceContent(si_moref)

    @staticmethod
    def _copy_client_cookie(vimSession, pbmClient):
        """Copy the vim session cookie to pbm client soap header.

        :param vimSession: an vim session authenticated with VC/ESX
        :param pbmClient: a PBMClient object to set the session cookie
        """
        vcSessionCookie = PBMClient._get_vc_session_cookie(vimSession)
        vcc = element.Element('vcSessionCookie').setText(vcSessionCookie)
        pbmClient.set_options(soapheaders=vcc)

    @staticmethod
    def _get_vc_session_cookie(vimSession):
        """Look for vmware_soap_session cookie in vimSession."""
        cookies = vimSession.client.options.transport.cookiejar
        for c in cookies:
            if c.name.lower() == 'vmware_soap_session':
                return c.value

    @property
    def service_content(self):
        return self._sc

    @property
    def client(self):
        return self._client

    def set_cookie(self):
        """Set the authenticated vim session cookie in this pbm client."""
        PBMClient._copy_client_cookie(self._vimSession, self.client)
