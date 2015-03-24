# Copyright 2011 Justin Santa Barbara
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

from lxml import etree
from oslo_log import log as logging

from cinder.api import common
from cinder.tests.integrated import integrated_helpers


LOG = logging.getLogger(__name__)


class XmlTests(integrated_helpers._IntegratedTestBase):
    """"Some basic XML sanity checks."""

    # FIXME(ja): does cinder need limits?
    # def test_namespace_limits(self):
    #     headers = {}
    #     headers['Accept'] = 'application/xml'

    #     response = self.api.api_request('/limits', headers=headers)
    #     data = response.read()
    #     LOG.debug("data: %s" % data)
    #     root = etree.XML(data)
    #     self.assertEqual(root.nsmap.get(None), xmlutil.XMLNS_COMMON_V10)

    def test_namespace_volumes(self):
        headers = {}
        headers['Accept'] = 'application/xml'

        response = self.api.api_request('/volumes', headers=headers,
                                        stream=True)
        data = response.raw
        LOG.warn("data: %s" % data)
        root = etree.parse(data).getroot()
        self.assertEqual(root.nsmap.get(None), common.XML_NS_V2)
