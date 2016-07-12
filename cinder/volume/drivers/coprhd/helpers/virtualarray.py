# Copyright (c) 2016 EMC Corporation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from cinder.i18n import _
from cinder.volume.drivers.coprhd.helpers import commoncoprhdapi as common


class VirtualArray(common.CoprHDResource):

    # Commonly used URIs for the 'varrays' module
    URI_VIRTUALARRAY = '/vdc/varrays'
    URI_VIRTUALARRAY_BY_VDC_ID = '/vdc/varrays?vdc-id={0}'
    URI_VIRTUALARRAY_URI = '/vdc/varrays/{0}'

    def varray_query(self, name):
        """Returns the UID of the varray specified by the name."""
        if common.is_uri(name):
            return name

        uris = self.varray_list()

        for uri in uris:
            varray = self.varray_show(uri)
            if varray and varray['name'] == name:
                return varray['id']

        raise common.CoprHdError(common.CoprHdError.NOT_FOUND_ERR,
                                 (_("varray %s: not found") % name))

    def varray_list(self, vdcname=None):
        """Returns all the varrays in a vdc.

        :param vdcname: Name of the Virtual Data Center
        :returns: JSON payload of varray list
        """
        vdcrestapi = None
        if vdcname is not None:
            vdcrestapi = VirtualArray.URI_VIRTUALARRAY_BY_VDC_ID.format(
                vdcname)
        else:
            vdcrestapi = VirtualArray.URI_VIRTUALARRAY
        (s, h) = common.service_json_request(
            self.ipaddr, self.port, "GET",
            vdcrestapi, None)

        o = common.json_decode(s)

        returnlst = []
        for item in o['varray']:
            returnlst.append(item['id'])

        return returnlst

    def varray_show(self, label):
        """Makes REST API call to retrieve varray details based on name."""
        uri = self.varray_query(label)

        (s, h) = common.service_json_request(
            self.ipaddr, self.port, "GET",
            VirtualArray.URI_VIRTUALARRAY_URI.format(uri),
            None)

        o = common.json_decode(s)
        if 'inactive' in o and o['inactive'] is True:
            return None
        else:
            return o
