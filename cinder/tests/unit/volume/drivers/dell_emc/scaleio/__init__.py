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
import copy
import requests
import six

from cinder import test
from cinder.tests.unit.volume.drivers.dell_emc.scaleio import mocks
from cinder.volume import configuration as conf
from cinder.volume.drivers.dell_emc.scaleio import driver


class CustomResponseMode(object):
    """A context manager to define a custom set of per-request response modes.

    Example:

        with CustomResponseMode(self, **{
                    'some/api/path': RESPONSE_MODE.Valid,
                    'another/api/path': RESPONSE_MODE.BadStatus,
                    'last/api/path': MockResponse('some data',
                                                  status_code=403),
                }):
            self.assertRaises(SomeException, self.driver.api_call, data)
    """
    def __init__(self, test_instance, **kwargs):
        self.test_instance = test_instance
        self.custom_responses = kwargs
        self.current_responses = None

    def __enter__(self):
        self.current_responses = self.test_instance.HTTPS_MOCK_RESPONSES

        https_responses = copy.deepcopy(
            self.test_instance.HTTPS_MOCK_RESPONSES
        )
        current_mode = self.test_instance.current_https_response_mode

        for call, new_mode in self.custom_responses.items():
            if isinstance(new_mode, mocks.MockHTTPSResponse):
                https_responses[current_mode][call] = new_mode
            else:
                https_responses[current_mode][call] = \
                    self.test_instance.get_https_response(call, new_mode)

        self.test_instance.HTTPS_MOCK_RESPONSES = https_responses

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.test_instance.HTTPS_MOCK_RESPONSES = self.current_responses


class TestScaleIODriver(test.TestCase):
    """Base ``TestCase`` subclass for the ``ScaleIODriver``"""
    RESPONSE_MODE = type(str('ResponseMode'), (object, ), dict(
        Valid='0',
        Invalid='1',
        BadStatus='2',
        ValidVariant='3',
    ))
    __RESPONSE_MODE_NAMES = {
        '0': 'Valid',
        '1': 'Invalid',
        '2': 'BadStatus',
        '3': 'ValidVariant',
    }

    BAD_STATUS_RESPONSE = mocks.MockHTTPSResponse(
        {
            'errorCode': 500,
            'message': 'BadStatus Response Test',
        }, 500
    )

    OLD_VOLUME_NOT_FOUND_ERROR = 78
    VOLUME_NOT_FOUND_ERROR = 79

    HTTPS_MOCK_RESPONSES = {}
    __COMMON_HTTPS_MOCK_RESPONSES = {
        RESPONSE_MODE.Valid: {
            'login': 'login_token',
        },
        RESPONSE_MODE.BadStatus: {
            'login': mocks.MockHTTPSResponse(
                {
                    'errorCode': 403,
                    'message': 'Bad Login Response Test',
                }, 403
            ),
        },
    }
    __https_response_mode = RESPONSE_MODE.Valid
    log = None

    STORAGE_POOL_ID = six.text_type('1')
    STORAGE_POOL_NAME = 'SP1'

    PROT_DOMAIN_ID = six.text_type('1')
    PROT_DOMAIN_NAME = 'PD1'

    STORAGE_POOLS = ['{}:{}'.format(PROT_DOMAIN_NAME, STORAGE_POOL_NAME)]

    def setUp(self):
        """Setup a test case environment.

        Creates a ``ScaleIODriver`` instance
        Mocks the ``requests.get/post`` methods to return
                  ``MockHTTPSResponse``'s instead.
        """
        super(TestScaleIODriver, self).setUp()
        self.configuration = conf.Configuration(driver.scaleio_opts,
                                                conf.SHARED_CONF_GROUP)
        self._set_overrides()
        self.driver = mocks.ScaleIODriver(configuration=self.configuration)

        self.mock_object(requests, 'get', self.do_request)
        self.mock_object(requests, 'post', self.do_request)

    def _set_overrides(self):
        # Override the defaults to fake values
        self.override_config('san_ip', override='127.0.0.1',
                             group=conf.SHARED_CONF_GROUP)
        self.override_config('sio_rest_server_port', override='8888',
                             group=conf.SHARED_CONF_GROUP)
        self.override_config('san_login', override='test',
                             group=conf.SHARED_CONF_GROUP)
        self.override_config('san_password', override='pass',
                             group=conf.SHARED_CONF_GROUP)
        self.override_config('sio_storage_pool_id',
                             override=self.STORAGE_POOL_ID,
                             group=conf.SHARED_CONF_GROUP)
        self.override_config('sio_protection_domain_id',
                             override=self.PROT_DOMAIN_ID,
                             group=conf.SHARED_CONF_GROUP)
        self.override_config('sio_storage_pools',
                             override='PD1:SP1',
                             group=conf.SHARED_CONF_GROUP)
        self.override_config('max_over_subscription_ratio',
                             override=5.0, group=conf.SHARED_CONF_GROUP)
        self.override_config('sio_server_api_version',
                             override='2.0.0', group=conf.SHARED_CONF_GROUP)

    def do_request(self, url, *args, **kwargs):
        """Do a fake GET/POST API request.

        Splits `url` on '/api/' to get the what API call is, then returns
        the value of `self.HTTPS_MOCK_RESPONSES[<response_mode>][<api_call>]`
        converting to a `MockHTTPSResponse` if necessary.

        :raises test.TestingException: If the current mode/api_call does not
        exist.
        :returns MockHTTPSResponse:
        """
        return self.get_https_response(url.split('/api/')[1])

    def set_https_response_mode(self, mode=RESPONSE_MODE.Valid):
        """Set the HTTPS response mode.

        RESPONSE_MODE.Valid: Respond with valid data
        RESPONSE_MODE.Invalid: Respond with invalid data
        RESPONSE_MODE.BadStatus: Response with not-OK status code.
        """
        self.__https_response_mode = mode

    def get_https_response(self, api_path, mode=None):
        if mode is None:
            mode = self.__https_response_mode

        try:
            response = self.HTTPS_MOCK_RESPONSES[mode][api_path]
        except KeyError:
            try:
                response = self.__COMMON_HTTPS_MOCK_RESPONSES[mode][api_path]
            except KeyError:
                raise test.TestingException(
                    'Mock API Endpoint not implemented: [{}]{}'.format(
                        self.__RESPONSE_MODE_NAMES[mode], api_path
                    )
                )

        if not isinstance(response, mocks.MockHTTPSResponse):
            return mocks.MockHTTPSResponse(response, 200)
        return response

    @property
    def current_https_response_mode(self):
        return self.__https_response_mode

    def https_response_mode_name(self, mode):
        return self.__RESPONSE_MODE_NAMES[mode]

    def custom_response_mode(self, **kwargs):
        return CustomResponseMode(self, **kwargs)
