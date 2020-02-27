# Copyright (c) 2018 Huawei Technologies Co., Ltd.
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

import requests


class FakeBaseSession(requests.Session):
    method_map = {}

    def _get_response(self, method, url):
        url_map = self.method_map.get(method, {})
        tmp = None
        data = {}
        for k in url_map:
            if re.search(k, url):
                if not tmp or len(tmp) < len(k):
                    data = url_map[k]
                    tmp = k

        resp_content = {'result': 0}
        resp_content.update(data)
        resp = requests.Response()
        resp.headers['X-Auth-Token'] = 'fake_token'
        resp.status_code = 0
        resp.encoding = 'utf-8'
        resp._content = json.dumps(resp_content).encode('utf-8')

        return resp

    def get(self, url, **kwargs):
        return self._get_response('get', url)

    def post(self, url, **kwargs):
        return self._get_response('post', url)
