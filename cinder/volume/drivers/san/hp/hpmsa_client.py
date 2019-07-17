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

import cinder.volume.drivers.stx.client as client


class HPMSAClient(client.STXClient):

    def __init__(self, host, login, password, protocol, ssl_verify):
        super(HPMSAClient, self).__init__(host, login, password,
                                          protocol, ssl_verify)
