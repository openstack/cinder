# Copyright (c) 2024 Pure Storage, Inc.
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

from copy import deepcopy
import json
import pprint
import sys
from unittest import mock

import ddt
from oslo_utils import units

from cinder import context
from cinder import exception
from cinder.objects import fields
from cinder.objects import volume_type
from cinder.tests.unit.consistencygroup import fake_cgsnapshot
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_group
from cinder.tests.unit import fake_group_snapshot
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit import test
from cinder.volume import qos_specs
from cinder.volume import volume_types
from cinder.volume import volume_utils


def fake_retry(exceptions, interval=1, retries=3, backoff_rate=2):
    def _decorator(f):
        return f

    return _decorator


patch_retry = mock.patch('cinder.utils.retry', fake_retry)
patch_retry.start()
sys.modules['pypureclient'] = mock.Mock()
from cinder.volume.drivers import pure  # noqa

# Only mock utils.retry for cinder.volume.drivers.pure import
patch_retry.stop()

# This part is copied from the Pure 2.x REST API code


class Parameters(object):
    """A class for static parameter names.

    """
    continuation_token = 'continuation_token'
    filter = 'filter'
    limit = 'limit'
    offset = 'offset'
    sort = 'sort'
    x_request_id = 'x_request_id'


class Headers(object):
    """A class for static header names.

    """
    api_token = 'api-token'
    authorization = 'Authorization'
    x_auth_token = 'x-auth-token'
    x_request_id = 'X-Request-ID'
    x_ratelimit_sec = 'X-RateLimit-Limit-second'
    x_ratelimit_min = 'X-RateLimit-Limit-minute'
    x_ratelimit_remaining_sec = 'X-RateLimit-Remaining-second'
    x_ratelimit_remaining_min = 'X-RateLimit-Remaining-minute'


class ItemIterator(object):
    """An iterator for items of a collection returned by the server.

    """

    def __init__(self, client, api_endpoint, kwargs, continuation_token,
                 total_item_count, items, x_request_id,
                 more_items_remaining=None,
                 response_size_limit=1000):
        """Initialize an ItemIterator.

        Args:
            client (Client): A Pure1 Client that can call the API.
            api_endpoint (function): The function that corresponds to the
                internal API call.
            kwargs (dict): The kwargs of the initial call.
            continuation_token (str): The continuation token provided by the
                server. May be None.
            total_item_count (int): The total number of items available in the
                collection.
            items (list[object]): The items returned from the initial response.
            x_request_id (str): The X-Request-ID to use for all subsequent
                calls.
        """
        self._response_size_limit = response_size_limit
        self._client = client
        self._api_endpoint = api_endpoint
        self._kwargs = kwargs
        self._continuation_token = '\'{}\''.format(continuation_token)
        self._total_item_count = total_item_count
        self._more_items_remaining = more_items_remaining
        self._items = items
        self._x_request_id = x_request_id
        self._index = 0

    def __iter__(self):
        """Creates a new iterator.

        Returns:
            ItemIterator
        """
        return self

    def __next__(self):
        """Get the next item in the collection. If there are no items left to

        get from the last response, it calls the API again to get more items.

        Returns:
            object

        Raises:
            StopIteration: If there are no more items to return, or if there
                was an error calling the API.
        """
        # If we've reached the end of the desired limit, stop
        if Parameters.limit in self._kwargs and \
                self._kwargs.get(Parameters.limit) <= self._index:
            raise StopIteration
        # If we've reached the end of all possible items, stop
        if self._total_item_count is not None and self._total_item_count \
                <= self._index:
            raise StopIteration
        if self._response_size_limit is None:
            item_index = self._index
        else:
            item_index = self._index % self._response_size_limit
        # If we've reached the end of the current collection, get more data
        if item_index == len(self._items):
            if self._more_items_remaining is False:
                raise StopIteration
            self._refresh_data()
        # Return the next item in the current list if possible
        if item_index < len(self._items):
            to_return = self._items[item_index]
            self._index += 1
            return to_return
        # If no new data was given, just stop
        raise StopIteration

    def __len__(self):
        """Get the length of collection. Number of items returned is not

        guaranteed to be the length of collection at the start.

        Returns:
            int
        """
        return self._total_item_count or len(self._items)

    def _refresh_data(self):
        """Call the API to collect more items and updates the internal state.

        Raises:
            StopIteration: If there was an error calling the API.
        """
        # Use continuation token if provided
        if Parameters.continuation_token in self._kwargs:
            self._kwargs[Parameters.continuation_token] = \
                self._continuation_token
        else:  # Use offset otherwise (no continuation token with sorts)
            self._kwargs[Parameters.offset] = len(self._items)
        if self._x_request_id is not None:
            self._kwargs[Parameters.x_request_id] = self._x_request_id
        # Call the API again and update internal state
        response, is_error = self._client._call_api(self._api_endpoint,
                                                    self._kwargs)
        if is_error is True:
            raise StopIteration
        body, _, _ = response
        self._continuation_token = '\'{}\''.format(body.continuation_token)
        self._total_item_count = body.total_item_count
        self._items = body.items


class ResponseHeaders(object):
    """An object that includes headers from the server response.

    """

    def __init__(self, x_request_id, x_ratelimit_limit_second,
                 x_ratelimit_limit_minute, x_ratelimit_remaining_second,
                 x_ratelimit_remaining_minute):
        """Initialize a ResponseHeaders.

        Args:
            x_request_id (str): The X-Request-ID from the client or generated
                by the server.
            x_ratelimit_limit_second (int): The number of requests available
                per second.
            x_ratelimit_limit_minute (int): The number of requests available
                per minute.
            x_ratelimit_remaining_second (int): The number of requests
                remaining in that second.
            x_ratelimit_remaining_minute (int): The number of requests
                remaining in that minute.
        """

        self.x_request_id = x_request_id
        self.x_ratelimit_limit_second = x_ratelimit_limit_second
        self.x_ratelimit_limit_minute = x_ratelimit_limit_minute
        self.x_ratelimit_remaining_second = x_ratelimit_remaining_second
        self.x_ratelimit_remaining_minute = x_ratelimit_remaining_minute

    def to_dict(self):
        """Return a dictionary of the class attributes.

        Returns:
            dict
        """

        return self.__dict__

    def __repr__(self):
        """Return a pretty formatted string of the object.

        Returns:
            str
        """

        return pprint.pformat(self.to_dict())


def _create_response_headers(headers):
    response_headers = None
    if headers and headers.get(Headers.x_request_id, None):
        RH = ResponseHeaders(headers.get(Headers.x_request_id, None),
                             headers.get(Headers.x_ratelimit_sec, None),
                             headers.get(Headers.x_ratelimit_min, None),
                             headers.get(Headers.x_ratelimit_remaining_sec,
                                         None),
                             headers.get(Headers.x_ratelimit_remaining_min,
                                         None))
        response_headers = RH
    return response_headers


class Response(object):
    """An abstract response that is extended to a valid or error response.

    """

    def __init__(self, status_code, headers):
        """Initialize a Response.

        Args:
            status_code (int): The HTTP status code.
            headers (dict): Response headers from the server.
        """

        self.status_code = status_code
        self.headers = _create_response_headers(headers)


class ValidResponse(Response):
    """A response that indicates the request was successful and has the

    returned data.
    """

    def __init__(self, status_code, continuation_token, total_item_count,
                 items, headers, total=None, more_items_remaining=None):
        """Initialize a ValidResponse.

        Args:
            status_code (int): The HTTP status code.
            continuation_token (str): An opaque token to iterate over a
                collection of resources. May be None.
            total_item_count (int): The total number of items available in the
                collection.
            items (ItemIterator): An iterator over the items in the collection.
            headers (dict): Response headers from the server.
        """

        super(ValidResponse, self).__init__(status_code, headers)
        self.continuation_token = continuation_token
        self.total_item_count = total_item_count
        self.items = items
        if total is not None:
            self.total = total
        if more_items_remaining is not None:
            self.more_items_remaining = more_items_remaining

    def to_dict(self):
        """Return a dictionary of the class attributes. It will convert the

        items to a list of items by exhausting the iterator. If any items
        were previously iterated, they will be missed.

        Returns:
            dict
        """

        new_dict = dict(self.__dict__)
        if isinstance(self.items, ItemIterator):
            new_dict['items'] = [item.to_dict() for item in list(self.items)]

        new_dict['headers'] = (self.headers.to_dict
                               if self.headers is not None else None)

        if hasattr(self, 'total') and isinstance(self.total, list):
            new_dict['total'] = [item.to_dict() for item in self.total]
        return new_dict

    def __repr__(self):
        """Return a pretty formatted string of the object. Does not convert the

        items to a list of items by using the iterator.

        Returns:
            str
        """

        new_dict = dict(self.__dict__)
        if self.headers:
            new_dict['headers'] = self.headers.to_dict()
        return pprint.pformat(new_dict)


class ErrorResponse(Response):
    """A response that indicates there was an error with the request and has

    the list of errors.
    """

    def __init__(self, status_code, errors, headers):
        """Initialize an ErrorResponse.

        Args:
            status_code (int): The HTTP status code.
            errors (list[ApiError]): The list of errors encountered.
            headers (dict): Response headers from the
                server.
        """

        super(ErrorResponse, self).__init__(status_code,
                                            headers)
        self.errors = errors

    def to_dict(self):
        """Return a dictionary of the class attributes.

        Returns:
            dict
        """

        new_dict = dict(self.__dict__)
        new_dict['errors'] = [err.to_dict() for err in new_dict['errors']]
        new_dict['headers'] = (self.headers.to_dict
                               if self.headers is not None else None)
        return new_dict

    def __repr__(self):
        """Return a pretty formatted string of the object.

        Returns:
            str
        """

        return pprint.pformat(self.to_dict())


# Simple implementation of dot notation dictionary

class DotNotation(dict):

    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__

    def __init__(self, data):
        if isinstance(data, str):
            data = json.loads(data)

        for name, value in data.items():
            setattr(self, name, self._wrap(value))

    def __getattr__(self, attr):
        def _traverse(obj, attr):
            if self._is_indexable(obj):
                try:
                    return obj[int(attr)]
                except Exception:
                    return None
            elif isinstance(obj, dict):
                return obj.get(attr, None)
            else:
                return attr
        # if '.' in attr:
        #    return reduce(_traverse, attr.split('.'), self)
        return self.get(attr, None)

    def _wrap(self, value):
        if self._is_indexable(value):
            # (!) recursive (!)
            return type(value)([self._wrap(v) for v in value])
        elif isinstance(value, dict):
            return DotNotation(value)
        else:
            return value

    @staticmethod
    def _is_indexable(obj):
        return isinstance(obj, (tuple, list, set, frozenset))

    def __deepcopy__(self, memo=None):
        return DotNotation(deepcopy(dict(self), memo=memo))


DRIVER_PATH = "cinder.volume.drivers.pure"
BASE_DRIVER_OBJ = DRIVER_PATH + ".PureBaseVolumeDriver"
ISCSI_DRIVER_OBJ = DRIVER_PATH + ".PureISCSIDriver"
FC_DRIVER_OBJ = DRIVER_PATH + ".PureFCDriver"
NVME_DRIVER_OBJ = DRIVER_PATH + ".PureNVMEDriver"
ARRAY_OBJ = DRIVER_PATH + ".FlashArray"
UNMANAGED_SUFFIX = "-unmanaged"

GET_ARRAY_PRIMARY = {"version": "99.9.9",
                     "name": "pure_target1",
                     "id": "primary_array_id"}
VALID_GET_ARRAY_PRIMARY = ValidResponse(200, None, 1,
                                        [DotNotation(GET_ARRAY_PRIMARY)], {})
GET_ARRAY_SECONDARY = {"version": "99.9.9",
                       "name": "pure_target2",
                       "id": "secondary_array_id"}
VALID_GET_ARRAY_SECONDARY = ValidResponse(200, None, 1,
                                          [DotNotation(GET_ARRAY_SECONDARY)],
                                          {})

REPLICATION_TARGET_TOKEN = "12345678-abcd-1234-abcd-1234567890ab"
REPLICATION_PROTECTION_GROUP = "cinder-group"
REPLICATION_INTERVAL_IN_SEC = 3600
REPLICATION_RETENTION_SHORT_TERM = 14400
REPLICATION_RETENTION_LONG_TERM = 6
REPLICATION_RETENTION_LONG_TERM_PER_DAY = 3

PRIMARY_MANAGEMENT_IP = GET_ARRAY_PRIMARY["name"]
API_TOKEN = "12345678-abcd-1234-abcd-1234567890ab"
VOLUME_BACKEND_NAME = "Pure_iSCSI"
ISCSI_PORT_NAMES = ["ct0.eth2", "ct0.eth3", "ct1.eth2", "ct1.eth3"]
NVME_PORT_NAMES = ["ct0.eth8", "ct0.eth9", "ct1.eth8", "ct1.eth9"]
FC_PORT_NAMES = ["ct0.fc2", "ct0.fc3", "ct1.fc2", "ct1.fc3"]
# These two IP blocks should use the same prefix (see NVME_CIDR_FILTERED to
# make sure changes make sense). Our arrays now have 4 IPv4 + 4 IPv6 ports.
NVME_IPS = ["10.0.0." + str(i + 1) for i in range(len(NVME_PORT_NAMES))]
NVME_IPS += ["[2001:db8::" + str(i + 1) + "]"
             for i in range(len(NVME_PORT_NAMES))]
AC_NVME_IPS = ["10.0.0." + str(i + 1 + len(NVME_PORT_NAMES))
               for i in range(len(NVME_PORT_NAMES))]
AC_NVME_IPS += ["[2001:db8::1:" + str(i + 1) + "]"
                for i in range(len(NVME_PORT_NAMES))]
NVME_CIDR = "0.0.0.0/0"
NVME_CIDR_V6 = "::/0"
NVME_PORT = 4420
# Designed to filter out only one of the AC NVMe IPs, leaving the rest in
NVME_CIDR_FILTERED = "10.0.0.0/29"
# Include several IP / networks: 10.0.0.2, 10.0.0.3, 10.0.0.6, 10.0.0.7
NVME_CIDRS_FILTERED = ["10.0.0.2", "10.0.0.3", "2001:db8::1:2/127"]

# These two IP blocks should use the same prefix (see ISCSI_CIDR_FILTERED to
# make sure changes make sense). Our arrays now have 4 IPv4 + 4 IPv6 ports.
ISCSI_IPS = ["10.0.0." + str(i + 1) for i in range(len(ISCSI_PORT_NAMES))]
ISCSI_IPS += ["[2001:db8::1:" + str(i + 1) + "]"
              for i in range(len(ISCSI_PORT_NAMES))]
AC_ISCSI_IPS = ["10.0.0." + str(i + 1 + len(ISCSI_PORT_NAMES))
                for i in range(len(ISCSI_PORT_NAMES))]
AC_ISCSI_IPS += ["[2001:db8::1:" + str(i + 1) + "]"
                 for i in range(len(ISCSI_PORT_NAMES))]
ISCSI_CIDR = "0.0.0.0/0"
ISCSI_CIDR_V6 = "::/0"
# Designed to filter out only one of the AC ISCSI IPs, leaving the rest in
ISCSI_CIDR_FILTERED = '10.0.0.0/29'
# Include several IP / networks: 10.0.0.2, 10.0.0.3, 10.0.0.6, 10.0.0.7
ISCSI_CIDRS_FILTERED = ['10.0.0.2', '10.0.0.3', '2001:db8::1:2/127']
FC_WWNS = ["21000024ff59fe9" + str(i + 1) for i in range(len(FC_PORT_NAMES))]
AC_FC_WWNS = [
    "21000024ff59fab" + str(i + 1) for i in range(len(FC_PORT_NAMES))]
HOSTNAME = "computenode1"
PURE_HOST_NAME = pure.PureBaseVolumeDriver._generate_purity_host_name(HOSTNAME)
PURE_HOST = {
    "name": PURE_HOST_NAME,
    "host_group": None,
    "nqns": [],
    "iqns": [],
    "wwns": [],
}
INITIATOR_NQN = (
    "nqn.2014-08.org.nvmexpress:uuid:6953a373-c3f7-4ea8-ae77-105c393012ff"
)
INITIATOR_IQN = "iqn.1993-08.org.debian:01:222"
INITIATOR_WWN = "5001500150015081abc"
NVME_CONNECTOR = {"nqn": INITIATOR_NQN, "host": HOSTNAME}
ISCSI_CONNECTOR = {"initiator": INITIATOR_IQN, "name": HOSTNAME,
                   "host": DotNotation({"name": HOSTNAME})}
FC_CONNECTOR = {"wwpns": {INITIATOR_WWN}, "host": HOSTNAME}
TARGET_NQN = "nqn.2010-06.com.purestorage:flasharray.12345abc"
AC_TARGET_NQN = "nqn.2010-06.com.purestorage:flasharray.67890def"
TARGET_IQN = "iqn.2010-06.com.purestorage:flasharray.12345abc"
AC_TARGET_IQN = "iqn.2018-06.com.purestorage:flasharray.67890def"
TARGET_WWN = "21000024ff59fe94"
TARGET_PORT = "3260"
TARGET_ROCE_PORT = "4420"
INITIATOR_TARGET_MAP = {
    # _build_initiator_target_map() calls list(set()) on the list,
    # we must also call list(set()) to get the exact same order
    '5001500150015081abc': list(set(FC_WWNS)),
}
AC_INITIATOR_TARGET_MAP = {
    # _build_initiator_target_map() calls list(set()) on the list,
    # we must also call list(set()) to get the exact same order
    '5001500150015081abc': list(set(FC_WWNS + AC_FC_WWNS)),
}
DEVICE_MAPPING = {
    "fabric": {
        'initiator_port_wwn_list': {INITIATOR_WWN},
        'target_port_wwn_list': FC_WWNS,
    },
}
AC_DEVICE_MAPPING = {
    "fabric": {
        'initiator_port_wwn_list': {INITIATOR_WWN},
        'target_port_wwn_list': FC_WWNS + AC_FC_WWNS,
    },
}

# We now have IPv6 in addition to IPv4 on each interface
NVME_PORTS = [{"name": name,
               "nqn": TARGET_NQN,
               "iqn": None,
               "portal": ip + ":" + TARGET_ROCE_PORT,
               "wwn": None,
               } for name, ip in zip(NVME_PORT_NAMES * 2, NVME_IPS)]
AC_NVME_PORTS = [{"name": name,
                  "nqn": AC_TARGET_NQN,
                  "iqn": None,
                  "portal": ip + ":" + TARGET_ROCE_PORT,
                  "wwn": None,
                  } for name, ip in zip(NVME_PORT_NAMES * 2, AC_NVME_IPS)]
ISCSI_PORTS = [{"name": name,
                "iqn": TARGET_IQN,
                "portal": ip + ":" + TARGET_PORT,
                "nqn": None,
                "wwn": None,
                } for name, ip in zip(ISCSI_PORT_NAMES * 2, ISCSI_IPS)]
AC_ISCSI_PORTS = [{"name": name,
                   "iqn": AC_TARGET_IQN,
                   "portal": ip + ":" + TARGET_PORT,
                   "nqn": None,
                   "wwn": None,
                   } for name, ip in zip(ISCSI_PORT_NAMES * 2, AC_ISCSI_IPS)]
FC_PORTS = [{"name": name,
             "iqn": None,
             "nqn": None,
             "portal": None,
             "wwn": wwn,
             } for name, wwn in zip(FC_PORT_NAMES, FC_WWNS)]
AC_FC_PORTS = [{"name": name,
                "iqn": None,
                "nqn": None,
                "portal": None,
                "wwn": wwn,
                } for name, wwn in zip(FC_PORT_NAMES, AC_FC_WWNS)]
NON_ISCSI_PORT = {
    "name": "ct0.fc1",
    "iqn": None,
    "nqn": None,
    "portal": None,
    "wwn": "5001500150015081",
}
NVME_PORTS_WITH = NVME_PORTS + [NON_ISCSI_PORT]
PORTS_WITH = ISCSI_PORTS + [NON_ISCSI_PORT]
PORTS_WITHOUT = [NON_ISCSI_PORT]
TOTAL_CAPACITY = 50.0
USED_SPACE = 32.1
PROVISIONED_CAPACITY = 70.0
TOTAL_REDUCTION = 2.18
DEFAULT_OVER_SUBSCRIPTION = 20
SPACE_INFO = {"space": {"capacity": TOTAL_CAPACITY * units.Gi,
                        "total_used": USED_SPACE * units.Gi}}
SPACE_INFO_EMPTY = {
    "capacity": TOTAL_CAPACITY * units.Gi,
    "total": 0,
}

CTRL_INFO = {'mode': 'primary',
             'mode_since': 1910956431807,
             'model': 'dummy-model',
             'name': 'CT0',
             'status': 'ready',
             'type': 'array_controller',
             'version': '6.6.3'}

CTRL_OBJ = ValidResponse(200, None, 1, [DotNotation(CTRL_INFO)], {})

PERF_INFO = {
    'writes_per_sec': 318,
    'usec_per_write_op': 255,
    'output_per_sec': 234240,
    'read_bytes_per_sec': 234240,
    'reads_per_sec': 15,
    'input_per_sec': 2827943,
    'write_bytes_per_sec': 2827943,
    'time': '2015-12-17T21:50:55Z',
    'usec_per_read_op': 192,
    'queue_depth': 4,
}
PERF_INFO_RAW = [PERF_INFO]

ARRAYS_SPACE_INFO = {'capacity': 53687091200,
                     'id': 'd4eca33c-xxx-yyyy-zzz-8615590fzzz',
                     'name': 'dummy-array',
                     'parity': 1.0,
                     'space': {'data_reduction': 4.084554444259789,
                               'shared': 34617664613455,
                               'snapshots': 1239024085076,
                               'system': 0,
                               'thin_provisioning': 0.8557968609746274,
                               'total_physical': 34467112550.4,
                               'total_provisioned': 75161927680,
                               'total_reduction': 21.020004503715246,
                               'unique': 2564030093034,
                               'virtual': 110211386607104},
                     'time': 1713201705834}

ISCSI_CONNECTION_INFO = {
    "driver_volume_type": "iscsi",
    "data": {
        "target_discovered": False,
        "discard": True,
        "target_luns": [1, 1, 1, 1],
        "addressing_mode": "SAM2",
        "target_iqns": [TARGET_IQN, TARGET_IQN, TARGET_IQN, TARGET_IQN],
        "target_portals": [ISCSI_IPS[0] + ":" + TARGET_PORT,
                           ISCSI_IPS[1] + ":" + TARGET_PORT,
                           ISCSI_IPS[2] + ":" + TARGET_PORT,
                           ISCSI_IPS[3] + ":" + TARGET_PORT],
        "wwn": "3624a93709714b5cb91634c470002b2c8",
    },
}
ISCSI_CONNECTION_INFO_V6 = {
    "driver_volume_type": "iscsi",
    "data": {
        "target_discovered": False,
        "discard": True,
        "target_luns": [1, 1, 1, 1],
        "addressing_mode": "SAM2",
        "target_iqns": [TARGET_IQN, TARGET_IQN, TARGET_IQN, TARGET_IQN],
        "target_portals": [ISCSI_IPS[4] + ":" + TARGET_PORT,
                           ISCSI_IPS[5] + ":" + TARGET_PORT,
                           ISCSI_IPS[6] + ":" + TARGET_PORT,
                           ISCSI_IPS[7] + ":" + TARGET_PORT],
        "wwn": "3624a93709714b5cb91634c470002b2c8",
    },
}
ISCSI_CONNECTION_INFO_AC = {
    "driver_volume_type": "iscsi",
    "data": {
        "target_discovered": False,
        "discard": True,
        "addressing_mode": "SAM2",
        "target_luns": [1, 1, 1, 1, 5, 5, 5, 5],
        "target_iqns": [TARGET_IQN, TARGET_IQN,
                        TARGET_IQN, TARGET_IQN,
                        AC_TARGET_IQN, AC_TARGET_IQN,
                        AC_TARGET_IQN, AC_TARGET_IQN],
        "target_portals": [ISCSI_IPS[0] + ":" + TARGET_PORT,
                           ISCSI_IPS[1] + ":" + TARGET_PORT,
                           ISCSI_IPS[2] + ":" + TARGET_PORT,
                           ISCSI_IPS[3] + ":" + TARGET_PORT,
                           AC_ISCSI_IPS[0] + ":" + TARGET_PORT,
                           AC_ISCSI_IPS[1] + ":" + TARGET_PORT,
                           AC_ISCSI_IPS[2] + ":" + TARGET_PORT,
                           AC_ISCSI_IPS[3] + ":" + TARGET_PORT],
        "wwn": "3624a93709714b5cb91634c470002b2c8",
    },
}
ISCSI_CONNECTION_INFO_AC_FILTERED = {
    "driver_volume_type": "iscsi",
    "data": {
        "target_discovered": False,
        "discard": True,
        "addressing_mode": "SAM2",
        "target_luns": [1, 1, 1, 1, 5, 5, 5],
        # Final entry filtered by ISCSI_CIDR_FILTERED
        "target_iqns": [TARGET_IQN, TARGET_IQN,
                        TARGET_IQN, TARGET_IQN,
                        AC_TARGET_IQN, AC_TARGET_IQN,
                        AC_TARGET_IQN],
        # Final entry filtered by ISCSI_CIDR_FILTERED
        "target_portals": [ISCSI_IPS[0] + ":" + TARGET_PORT,
                           ISCSI_IPS[1] + ":" + TARGET_PORT,
                           ISCSI_IPS[2] + ":" + TARGET_PORT,
                           ISCSI_IPS[3] + ":" + TARGET_PORT,
                           AC_ISCSI_IPS[0] + ":" + TARGET_PORT,
                           AC_ISCSI_IPS[1] + ":" + TARGET_PORT,
                           AC_ISCSI_IPS[2] + ":" + TARGET_PORT],
        "wwn": "3624a93709714b5cb91634c470002b2c8",
    },
}
ISCSI_CONNECTION_INFO_AC_FILTERED_LIST = {
    "driver_volume_type": "iscsi",
    "data": {
        "target_discovered": False,
        "discard": True,
        "addressing_mode": "SAM2",
        "target_luns": [1, 1, 5, 5],
        # Final entry filtered by ISCSI_CIDR_FILTERED
        "target_iqns": [TARGET_IQN, TARGET_IQN,
                        AC_TARGET_IQN, AC_TARGET_IQN],
        # Final entry filtered by ISCSI_CIDR_FILTERED
        "target_portals": [ISCSI_IPS[1] + ":" + TARGET_PORT,
                           ISCSI_IPS[2] + ":" + TARGET_PORT,
                           AC_ISCSI_IPS[5] + ":" + TARGET_PORT,   # IPv6
                           AC_ISCSI_IPS[6] + ":" + TARGET_PORT],  # IPv6
        "wwn": "3624a93709714b5cb91634c470002b2c8",
    },
}

NVME_CONNECTION_INFO = {
    "driver_volume_type": "nvmeof",
    "data": {
        "target_nqn": TARGET_NQN,
        "discard": True,
        "portals": [(NVME_IPS[0], NVME_PORT, "rdma"),
                    (NVME_IPS[1], NVME_PORT, "rdma"),
                    (NVME_IPS[2], NVME_PORT, "rdma"),
                    (NVME_IPS[3], NVME_PORT, "rdma")],
        "volume_nguid": "0009714b5cb916324a9374c470002b2c8",
    },
}
NVME_CONNECTION_INFO_V6 = {
    "driver_volume_type": "nvmeof",
    "data": {
        "target_nqn": TARGET_NQN,
        "discard": True,
        "portals": [(NVME_IPS[4].strip("[]"), NVME_PORT, "rdma"),
                    (NVME_IPS[5].strip("[]"), NVME_PORT, "rdma"),
                    (NVME_IPS[6].strip("[]"), NVME_PORT, "rdma"),
                    (NVME_IPS[7].strip("[]"), NVME_PORT, "rdma")],
        "volume_nguid": "0009714b5cb916324a9374c470002b2c8",
    },
}
NVME_CONNECTION_INFO_AC = {
    "driver_volume_type": "nvmeof",
    "data": {
        "target_nqn": TARGET_NQN,
        "discard": True,
        "portals": [
            (NVME_IPS[0], NVME_PORT, "rdma"),
            (NVME_IPS[1], NVME_PORT, "rdma"),
            (NVME_IPS[2], NVME_PORT, "rdma"),
            (NVME_IPS[3], NVME_PORT, "rdma"),
            (AC_NVME_IPS[0], NVME_PORT, "rdma"),
            (AC_NVME_IPS[1], NVME_PORT, "rdma"),
            (AC_NVME_IPS[2], NVME_PORT, "rdma"),
            (AC_NVME_IPS[3], NVME_PORT, "rdma")],
        "volume_nguid": "0009714b5cb916324a9374c470002b2c8",
    },
}
NVME_CONNECTION_INFO_AC_FILTERED = {
    "driver_volume_type": "nvmeof",
    "data": {
        "target_nqn": TARGET_NQN,
        "discard": True,
        # Final entry filtered by NVME_CIDR_FILTERED
        "portals": [
            (NVME_IPS[0], NVME_PORT, "rdma"),
            (NVME_IPS[1], NVME_PORT, "rdma"),
            (NVME_IPS[2], NVME_PORT, "rdma"),
            (NVME_IPS[3], NVME_PORT, "rdma"),
            (AC_NVME_IPS[0], NVME_PORT, "rdma"),
            (AC_NVME_IPS[1], NVME_PORT, "rdma"),
            (AC_NVME_IPS[2], NVME_PORT, "rdma")],
        "volume_nguid": "0009714b5cb916324a9374c470002b2c8",
    },
}
NVME_CONNECTION_INFO_AC_FILTERED_LIST = {
    "driver_volume_type": "nvmeof",
    "data": {
        "target_nqn": TARGET_NQN,
        "discard": True,
        # Final entry filtered by NVME_CIDR_FILTERED
        "portals": [
            (NVME_IPS[1], NVME_PORT, "rdma"),
            (NVME_IPS[2], NVME_PORT, "rdma"),
            (AC_NVME_IPS[5].strip("[]"), NVME_PORT, "rdma"),  # IPv6
            (AC_NVME_IPS[6].strip("[]"), NVME_PORT, "rdma"),  # IPv6
        ],
        "volume_nguid": "0009714b5cb916324a9374c470002b2c8",
    },
}
FC_CONNECTION_INFO = {
    "driver_volume_type": "fibre_channel",
    "data": {
        "target_wwn": FC_WWNS,
        "target_wwns": FC_WWNS,
        "target_lun": 1,
        "target_luns": [1, 1, 1, 1],
        "target_discovered": True,
        "addressing_mode": "SAM2",
        "initiator_target_map": INITIATOR_TARGET_MAP,
        "discard": True,
        "wwn": "3624a93709714b5cb91634c470002b2c8",
    },
}
FC_CONNECTION_INFO_AC = {
    "driver_volume_type": "fibre_channel",
    "data": {
        "target_wwn": FC_WWNS + AC_FC_WWNS,
        "target_wwns": FC_WWNS + AC_FC_WWNS,
        "target_lun": 1,
        "target_luns": [1, 1, 1, 1, 5, 5, 5, 5],
        "target_discovered": True,
        "addressing_mode": "SAM2",
        "initiator_target_map": AC_INITIATOR_TARGET_MAP,
        "discard": True,
        "wwn": "3624a93709714b5cb91634c470002b2c8",
    },
}
PURE_SNAPSHOT = {
    "created": "2015-05-27T17:34:33Z",
    "name": "vol1.snap1",
    "serial": "8343DFDE2DAFBE40000115E4",
    "size": 3221225472,
    "source": "vol1"
}
PURE_PGROUP = {
    "hgroups": None,
    "hosts": None,
    "name": "pg1",
    "source": "pure01",
    "targets": None,
    "volumes": ["v1"]
}

PGROUP_ON_TARGET_NOT_ALLOWED = {
    "name": "array1:replicated_pgroup",
    "hgroups": None,
    "source": "array1",
    "hosts": None,
    "volumes": ["array1:replicated_volume"],
    "time_remaining": None,
    "targets": [{"name": "array2",
                 "allowed": False}]}
PGROUP_ON_TARGET_ALLOWED = {
    "name": "array1:replicated_pgroup",
    "hgroups": None,
    "source": "array1",
    "hosts": None,
    "volumes": ["array1:replicated_volume"],
    "time_remaining": None,
    "allowed": True,
    "targets": [{"name": "array2",
                 "allowed": True}]}
REPLICATED_PGSNAPS = [
    {
        "name": "array1:cinder-repl-pg.3",
        "created": "2014-12-04T22:59:38Z",
        "started": "2014-12-04T22:59:38Z",
        "completed": "2014-12-04T22:59:39Z",
        "source": "array1:cinder-repl-pg",
        "logical_data_transferred": 0,
        "progress": 1.0,
        "data_transferred": 318
    },
    {
        "name": "array1:cinder-repl-pg.2",
        "created": "2014-12-04T21:59:38Z",
        "started": "2014-12-04T21:59:38Z",
        "completed": "2014-12-04T21:59:39Z",
        "source": "array1:cinder-repl-pg",
        "logical_data_transferred": 0,
        "progress": 1.0,
        "data_transferred": 318
    },
    {
        "name": "array1:cinder-repl-pg.1",
        "created": "2014-12-04T20:59:38Z",
        "started": "2014-12-04T20:59:38Z",
        "completed": "2014-12-04T20:59:39Z",
        "source": "array1:cinder-repl-pg",
        "logical_data_transferred": 0,
        "progress": 1.0,
        "data_transferred": 318
    }]
REPLICATED_VOLUME_OBJS = [
    fake_volume.fake_volume_obj(
        None, id=fake.VOLUME_ID,
        provider_id=("volume-%s-cinder" % fake.VOLUME_ID)
    ),
    fake_volume.fake_volume_obj(
        None, id=fake.VOLUME2_ID,
        provider_id=("volume-%s-cinder" % fake.VOLUME2_ID)
    ),
    fake_volume.fake_volume_obj(
        None, id=fake.VOLUME3_ID,
        provider_id=("volume-%s-cinder" % fake.VOLUME3_ID)
    ),
]
REPLICATED_VOLUME_SNAPS = [
    {
        "source": "array1:volume-%s-cinder" % fake.VOLUME_ID,
        "serial": "BBA481C01639104E0001D5F7",
        "created": "2014-12-04T22:59:38Z",
        "name": "array1:cinder-repl-pg.2.volume-%s-cinder" % fake.VOLUME_ID,
        "size": 1048576
    },
    {
        "source": "array1:volume-%s-cinder" % fake.VOLUME2_ID,
        "serial": "BBA481C01639104E0001D5F8",
        "created": "2014-12-04T22:59:38Z",
        "name": "array1:cinder-repl-pg.2.volume-%s-cinder" % fake.VOLUME2_ID,
        "size": 1048576
    },
    {
        "source": "array1:volume-%s-cinder" % fake.VOLUME3_ID,
        "serial": "BBA481C01639104E0001D5F9",
        "created": "2014-12-04T22:59:38Z",
        "name": "array1:cinder-repl-pg.2.volume-%s-cinder" % fake.VOLUME3_ID,
        "size": 1048576
    }
]

array_1 = {'status': 'online',
           'id': '47966b2d-a1ed-4144-8cae-6332794562b8',
           'name': 'fs83-14',
           'mediator_status': 'online'}
array_2 = {'status': 'online',
           'id': '8ed17cf4-4650-4634-ab3d-f2ca165cd021',
           'name': 'fs83-15',
           'mediator_status': 'online'}
pod_1 = dict(arrays = [array_1, array_2],
             source = None,
             name= 'cinder-pod')
dotted_dict = DotNotation(pod_1)
CINDER_POD = ValidResponse(200, None, 1, [dotted_dict], {})
VALID_ISCSI_PORTS = ValidResponse(200, None, 1,
                                  [DotNotation(ISCSI_PORTS[0]),
                                   DotNotation(ISCSI_PORTS[1]),
                                   DotNotation(ISCSI_PORTS[2]),
                                   DotNotation(ISCSI_PORTS[3])], {})
VALID_AC_ISCSI_PORTS = ValidResponse(200, None, 1,
                                     [DotNotation(AC_ISCSI_PORTS[0]),
                                      DotNotation(AC_ISCSI_PORTS[1]),
                                      DotNotation(AC_ISCSI_PORTS[2]),
                                      DotNotation(AC_ISCSI_PORTS[3])], {})
VALID_AC_ISCSI_PORTS_IPV6 = ValidResponse(200, None, 1,
                                          [DotNotation(AC_ISCSI_PORTS[4]),
                                           DotNotation(AC_ISCSI_PORTS[5]),
                                           DotNotation(AC_ISCSI_PORTS[6]),
                                           DotNotation(AC_ISCSI_PORTS[7])], {})
VALID_ISCSI_PORTS_IPV6 = ValidResponse(200, None, 1,
                                       [DotNotation(ISCSI_PORTS[4]),
                                        DotNotation(ISCSI_PORTS[5]),
                                        DotNotation(ISCSI_PORTS[6]),
                                        DotNotation(ISCSI_PORTS[7])], {})
VALID_FC_PORTS = ValidResponse(200, None, 1,
                               [DotNotation(FC_PORTS[0]),
                                DotNotation(FC_PORTS[1]),
                                DotNotation(FC_PORTS[2]),
                                DotNotation(FC_PORTS[3])], {})

VALID_AC_FC_PORTS = ValidResponse(200, None, 1,
                                  [DotNotation(AC_FC_PORTS[0]),
                                   DotNotation(AC_FC_PORTS[1]),
                                   DotNotation(AC_FC_PORTS[2]),
                                   DotNotation(AC_FC_PORTS[3])], {})

MANAGEABLE_PURE_VOLS = [
    {
        'name': 'myVol1',
        'id': fake.VOLUME_ID,
        'serial': '8E9C7E588B16C1EA00048CCA',
        'size': 3221225472,
        'provisioned': 3221225472,
        'space': {'total_provisioned': 3221225472},
        'created': '2016-08-05T17:26:34Z',
        'source': None,
        'connection_count': 0
    },
    {
        'name': 'myVol2',
        'id': fake.VOLUME2_ID,
        'serial': '8E9C7E588B16C1EA00048CCB',
        'size': 3221225472,
        'provisioned': 3221225472,
        'space': {'total_provisioned': 3221225472},
        'created': '2016-08-05T17:26:34Z',
        'source': None,
        'connection_count': 0
    },
    {
        'name': 'myVol3',
        'id': fake.VOLUME3_ID,
        'serial': '8E9C7E588B16C1EA00048CCD',
        'size': 3221225472,
        'provisioned': 3221225472,
        'space': {'total_provisioned': 3221225472},
        'created': '2016-08-05T17:26:34Z',
        'source': None,
        'connection_count': 0
    }
]
MANAGEABLE_PURE_VOL_REFS = [
    {
        'reference': {'name': 'myVol1'},
        'size': 3,
        'safe_to_manage': True,
        'reason_not_safe': '',
        'cinder_id': None,
        'extra_info': None,
    },
    {
        'reference': {'name': 'myVol2'},
        'size': 3,
        'safe_to_manage': True,
        'reason_not_safe': '',
        'cinder_id': None,
        'extra_info': None,
    },
    {
        'reference': {'name': 'myVol3'},
        'size': 3,
        'safe_to_manage': True,
        'reason_not_safe': '',
        'cinder_id': None,
        'extra_info': None,
    }
]

MPV_REFS = ValidResponse(200, None, 3,
                         [DotNotation(MANAGEABLE_PURE_VOL_REFS[0]),
                          DotNotation(MANAGEABLE_PURE_VOL_REFS[1]),
                          DotNotation(MANAGEABLE_PURE_VOL_REFS[2])], {})
MPV = ValidResponse(200, None, 3,
                    [DotNotation(MANAGEABLE_PURE_VOLS[0]),
                     DotNotation(MANAGEABLE_PURE_VOLS[1]),
                     DotNotation(MANAGEABLE_PURE_VOLS[2])], {})


CONNECTION_DATA = {'host': {'name': 'utest'},
                   'host_group': {},
                   'lun': 1,
                   'nsid': 9753,
                   'protocol_endpoint': {},
                   'volume': {'id': '78a9e55b-d9ef-37ce-0dbd-14de74ae35d4',
                              'name': 'xVol1'}}
CONN = ValidResponse(200, None, 1, [DotNotation(CONNECTION_DATA)], {})
vol_dict = {'id': '1e5177e7-95e5-4a0f-b170-e45f4b469f6a',
            'name': 'volume-1e5177e7-95e5-4a0f-b170-e45f4b469f6a-cinder'}
NCONNECTION_DATA = {'host': {'name': PURE_HOST_NAME},
                    'host_group': {},
                    'lun': 1,
                    'nsid': 9753,
                    'protocol_endpoint': {},
                    'volume': vol_dict}
NCONN = ValidResponse(200, None, 1,
                      [DotNotation(NCONNECTION_DATA)], {})

AC_CONNECTION_DATA = [{'host': {'name': 'utest5'},
                       'host_group': {},
                       'lun': 5,
                       'nsid': 9755,
                       'protocol_endpoint': {},
                       'volume': {'id': '78a9e55b-d9ef-37ce-0dbd-14de74ae35d5',
                                  'name': 'xVol5'}}]
AC_CONN = ValidResponse(200, None, 1,
                        [DotNotation(AC_CONNECTION_DATA[0])], {})

MANAGEABLE_PURE_SNAPS = [
    {
        'name': 'volume-fd33de6e-56f6-452d-a7b6-451c11089a9f-cinder.snap1',
        'serial': '8E9C7E588B16C1EA00048CCA',
        'size': 3221225472,
        'provisioned': 3221225472,
        'created': '2016-08-05T17:26:34Z',
        'source': {'name':
                   'volume-fd33de6e-56f6-452d-a7b6-451c11089a9f-cinder'},
    },
    {
        'name': 'volume-fd33de6e-56f6-452d-a7b6-451c11089a9f-cinder.snap2',
        'serial': '8E9C7E588B16C1EA00048CCB',
        'size': 4221225472,
        'provisioned': 4221225472,
        'created': '2016-08-05T17:26:34Z',
        'source': {'name':
                   'volume-fd33de6e-56f6-452d-a7b6-451c11089a9f-cinder'},
    },
    {
        'name': 'volume-fd33de6e-56f6-452d-a7b6-451c11089a9f-cinder.snap3',
        'serial': '8E9C7E588B16C1EA00048CCD',
        'size': 5221225472,
        'provisioned': 5221225472,
        'created': '2016-08-05T17:26:34Z',
        'source': {'name':
                   'volume-fd33de6e-56f6-452d-a7b6-451c11089a9f-cinder'},
    }
]
MANAGEABLE_PURE_SNAP_REFS = [
    {
        'reference': {'name': MANAGEABLE_PURE_SNAPS[0]['name']},
        'size': 3,
        'safe_to_manage': True,
        'reason_not_safe': None,
        'cinder_id': None,
        'extra_info': None,
        'source_reference': {'name':
                             MANAGEABLE_PURE_SNAPS[0]['source']['name']},
    },
    {
        'reference': {'name': MANAGEABLE_PURE_SNAPS[1]['name']},
        'size': 4,
        'safe_to_manage': True,
        'reason_not_safe': None,
        'cinder_id': None,
        'extra_info': None,
        'source_reference': {'name':
                             MANAGEABLE_PURE_SNAPS[1]['source']['name']},
    },
    {
        'reference': {'name': MANAGEABLE_PURE_SNAPS[2]['name']},
        'size': 5,
        'safe_to_manage': True,
        'reason_not_safe': None,
        'cinder_id': None,
        'extra_info': None,
        'source_reference': {'name':
                             MANAGEABLE_PURE_SNAPS[2]['source']['name']},
    }
]
MAX_SNAP_LENGTH = 96
MPS = ValidResponse(200, None, 3,
                    [DotNotation(MANAGEABLE_PURE_SNAPS[0]),
                     DotNotation(MANAGEABLE_PURE_SNAPS[1]),
                     DotNotation(MANAGEABLE_PURE_SNAPS[2])], {})
MPS_REFS = ValidResponse(200, None, 3,
                         [DotNotation(MANAGEABLE_PURE_SNAP_REFS[0]),
                          DotNotation(MANAGEABLE_PURE_SNAP_REFS[1]),
                          DotNotation(MANAGEABLE_PURE_SNAP_REFS[2])], {})

# unit for maxBWS is MB
QOS_IOPS_BWS = {"maxIOPS": "100", "maxBWS": "1"}
QOS_IOPS_BWS_2 = {"maxIOPS": "1000", "maxBWS": "10"}
QOS_INVALID = {"maxIOPS": "100", "maxBWS": str(512 * 1024 + 1)}
QOS_ZEROS = {"maxIOPS": "0", "maxBWS": "0"}
QOS_IOPS = {"maxIOPS": "100"}
QOS_BWS = {"maxBWS": "1"}

ARRAY_RESPONSE = {
    'status_code': 200
}


class PureDriverTestCase(test.TestCase):
    def setUp(self):
        super(PureDriverTestCase, self).setUp()
        self.mock_config = mock.Mock()
        self.mock_config.san_ip = PRIMARY_MANAGEMENT_IP
        self.mock_config.pure_api_token = API_TOKEN
        self.mock_config.volume_backend_name = VOLUME_BACKEND_NAME
        self.mock_config.safe_get.return_value = None
        self.mock_config.pure_eradicate_on_delete = False
        self.mock_config.driver_ssl_cert_verify = False
        self.mock_config.driver_ssl_cert_path = None
        self.mock_config.pure_iscsi_cidr = ISCSI_CIDR
        self.mock_config.pure_iscsi_cidr_list = None
        self.mock_config.pure_nvme_cidr = NVME_CIDR
        self.mock_config.pure_nvme_cidr_list = None
        self.mock_config.pure_nvme_transport = "roce"
        self.array = mock.Mock()
        self.array.get_arrays.return_value = VALID_GET_ARRAY_PRIMARY
        self.array.get.return_value = GET_ARRAY_PRIMARY
        self.array.array_name = GET_ARRAY_PRIMARY["name"]
        self.array.array_id = GET_ARRAY_PRIMARY["id"]
        self.async_array2 = mock.Mock()
        self.async_array2.get_arrays.return_value = VALID_GET_ARRAY_SECONDARY
        self.async_array2.array_name = GET_ARRAY_SECONDARY["name"]
        self.async_array2.array_id = GET_ARRAY_SECONDARY["id"]
        self.async_array2.get.return_value = GET_ARRAY_SECONDARY
        self.async_array2.replication_type = 'async'
        self.flasharray = pure.flasharray
        # self.purestorage_module = pure.flasharray
        # self.purestorage_module.PureHTTPError = FakePureStorageHTTPError

    def fake_get_array(self, *args, **kwargs):
        if 'action' in kwargs and kwargs['action'] == 'monitor':
            return ValidResponse(200, None, 1, [DotNotation(PERF_INFO_RAW)],
                                 {})

        if 'space' in kwargs and kwargs['space'] is True:
            return ValidResponse(200, None, 1, [DotNotation(SPACE_INFO)], {})
        return ValidResponse(200, None, 1, [DotNotation(GET_ARRAY_PRIMARY)],
                             {})

    def assert_error_propagates(self, mocks, func, *args, **kwargs):
        """Assert that errors from mocks propagate to func.

        Fail if exceptions raised by mocks are not seen when calling
        func(*args, **kwargs). Ensure that we are really seeing exceptions
        from the mocks by failing if just running func(*args, **kargs) raises
        an exception itself.
        """
        func(*args, **kwargs)
        for mock_func in mocks:
            original_side_effect = mock_func.side_effect
            mock_func.side_effect = [pure.PureDriverException(
                reason='reason')]
            self.assertRaises(pure.PureDriverException,
                              func, *args, **kwargs)
            mock_func.side_effect = original_side_effect

    @mock.patch('distro.name')
    def test_for_user_agent(self, mock_distro):
        mock_distro.return_value = 'MyFavouriteDistro'
        driver = pure.PureBaseVolumeDriver(configuration=self.mock_config)
        expected_agent = "OpenStack Cinder %s/%s (MyFavouriteDistro)" % (
            driver.__class__.__name__,
            driver.VERSION
        )
        self.assertEqual(expected_agent, driver._user_agent)


class PureBaseSharedDriverTestCase(PureDriverTestCase):
    def setUp(self):
        super(PureBaseSharedDriverTestCase, self).setUp()
        self.driver = pure.PureBaseVolumeDriver(configuration=self.mock_config)
        self.driver._array = self.array
        self.mock_object(self.driver, '_get_current_array',
                         return_value=self.array)
        self.driver._replication_pod_name = 'cinder-pod'
        self.driver._replication_pg_name = 'cinder-group'

    def new_fake_vol(self, set_provider_id=True, fake_context=None,
                     spec=None, type_extra_specs=None, type_qos_specs_id=None,
                     type_qos_specs=None):
        if fake_context is None:
            fake_context = mock.MagicMock()
        if type_extra_specs is None:
            type_extra_specs = {}
        if spec is None:
            spec = {}

        voltype = fake_volume.fake_volume_type_obj(fake_context)
        voltype.extra_specs = type_extra_specs
        voltype.qos_specs_id = type_qos_specs_id
        voltype.qos_specs = type_qos_specs

        vol = fake_volume.fake_volume_obj(fake_context, **spec)

        repl_type = self.driver._get_replication_type_from_vol_type(voltype)
        vol_name = vol.name + '-cinder'
        if repl_type == 'sync':
            vol_name = 'cinder-pod::' + vol_name

        if set_provider_id:
            vol.provider_id = vol_name

        vol.volume_type = voltype
        vol.volume_type_id = voltype.id
        vol.volume_attachment = None

        return vol, vol_name

    def new_fake_snap(self, vol=None, group_snap=None):
        if vol:
            vol_name = vol.name + "-cinder"
        else:
            vol, vol_name = self.new_fake_vol()
        snap = fake_snapshot.fake_snapshot_obj(mock.MagicMock())
        snap.volume_id = vol.id
        snap.volume = vol

        if group_snap is not None:
            snap.group_snapshot_id = group_snap.id
            snap.group_snapshot = group_snap

        snap_name = "%s.%s" % (vol_name, snap.name)
        return snap, snap_name

    def new_fake_group(self):
        group = fake_group.fake_group_obj(mock.MagicMock())
        group_name = "consisgroup-%s-cinder" % group.id
        return group, group_name

    def new_fake_group_snap(self, group=None):
        if group:
            group_name = "consisgroup-%s-cinder" % group.id
        else:
            group, group_name = self.new_fake_group()
        group_snap = fake_group_snapshot.fake_group_snapshot_obj(
            mock.MagicMock())

        group_snap_name = "%s.cgsnapshot-%s-cinder" % (group_name,
                                                       group_snap.id)

        group_snap.group = group
        group_snap.group_id = group.id

        return group_snap, group_snap_name


class PureBaseVolumeDriverGetCurrentArrayTestCase(PureDriverTestCase):
    def setUp(self):
        super(PureBaseVolumeDriverGetCurrentArrayTestCase, self).setUp()
        self.driver = pure.PureBaseVolumeDriver(configuration=self.mock_config)
        self.driver._array = self.array
        self.driver._replication_pod_name = 'cinder-pod'
        self.driver._replication_pg_name = 'cinder-group'
#        self.purestorage_module.Client.side_effect = None

    def test_get_current_array(self):
        self.driver._is_active_cluster_enabled = True
        self.array.array_id = '47966b2d-a1ed-4144-8cae-6332794562b8'
        self.array.get_pods.return_value = CINDER_POD
        self.driver._active_cluster_target_arrays = [self.array]
        self.driver._get_current_array()
        self.array.get_pods.assert_called_with(names=['cinder-pod'])


@ddt.ddt(testNameFormat=ddt.TestNameFormat.INDEX_ONLY)
class PureBaseVolumeDriverTestCase(PureBaseSharedDriverTestCase):
    def _setup_mocks_for_replication(self):
        # Mock config values
        self.mock_config.pure_replica_interval_default = (
            REPLICATION_INTERVAL_IN_SEC)
        self.mock_config.pure_replica_retention_short_term_default = (
            REPLICATION_RETENTION_SHORT_TERM)
        self.mock_config.pure_replica_retention_long_term_default = (
            REPLICATION_RETENTION_LONG_TERM)
        self.mock_config.pure_replica_retention_long_term_default = (
            REPLICATION_RETENTION_LONG_TERM_PER_DAY)

        self.mock_config.pure_replication_pg_name = 'cinder-group'
        self.mock_config.pure_replication_pod_name = 'cinder-pod'
        self.mock_config.safe_get.return_value = [
            {"backend_id": self.driver._array.array_id,
             "managed_backend_name": None,
             "san_ip": "1.2.3.4",
             "api_token": "abc123"}]

    @mock.patch(BASE_DRIVER_OBJ + '._get_flasharray')
    @mock.patch(BASE_DRIVER_OBJ + '._generate_replication_retention')
    @mock.patch(BASE_DRIVER_OBJ + '._setup_replicated_pgroups')
    def test_parse_replication_configs_single_async_target(
            self,
            mock_setup_repl_pgroups,
            mock_generate_replication_retention,
            mock_getarray):
        retention = mock.MagicMock()
        mock_generate_replication_retention.return_value = retention
        mock_setup_repl_pgroups.return_value = None

        # Test single array configured
        self.mock_config.safe_get.return_value = [
            {"backend_id": self.driver._array.id,
             "managed_backend_name": None,
             "san_ip": "1.2.3.4",
             "api_token": "abc123"}]
        mock_getarray().get_arrays.return_value = VALID_GET_ARRAY_PRIMARY
        self.driver.parse_replication_configs()
        self.assertEqual(1, len(self.driver._replication_target_arrays))
        self.assertEqual(mock_getarray(),
                         self.driver._replication_target_arrays[0])
        only_target_array = self.driver._replication_target_arrays[0]
        self.assertEqual(self.driver._array.id,
                         only_target_array.backend_id)

    @mock.patch(BASE_DRIVER_OBJ + '._get_flasharray')
    @mock.patch(BASE_DRIVER_OBJ + '._generate_replication_retention')
    @mock.patch(BASE_DRIVER_OBJ + '._setup_replicated_pgroups')
    def test_parse_replication_configs_multiple_async_target(
            self,
            mock_setup_repl_pgroups,
            mock_generate_replication_retention,
            mock_getarray):

        retention = mock.MagicMock()
        mock_generate_replication_retention.return_value = retention
        mock_setup_repl_pgroups.return_value = None

        # Test multiple arrays configured
        self.mock_config.safe_get.return_value = [
            {"backend_id": GET_ARRAY_PRIMARY["id"],
             "managed_backend_name": None,
             "san_ip": "1.2.3.4",
             "api_token": "abc123"},
            {"backend_id": GET_ARRAY_SECONDARY["id"],
             "managed_backend_name": None,
             "san_ip": "1.2.3.5",
             "api_token": "abc124"}]
        mock_getarray.side_effect = [self.array, self.async_array2]
        self.driver.parse_replication_configs()
        self.assertEqual(2, len(self.driver._replication_target_arrays))
        self.assertEqual(self.array, self.driver._replication_target_arrays[0])
        first_target_array = self.driver._replication_target_arrays[0]
        self.assertEqual(GET_ARRAY_PRIMARY["id"],
                         first_target_array.backend_id)
        self.assertEqual(
            self.async_array2, self.driver._replication_target_arrays[1])
        second_target_array = self.driver._replication_target_arrays[1]
        self.assertEqual(GET_ARRAY_SECONDARY["id"],
                         second_target_array.backend_id)

    @mock.patch(BASE_DRIVER_OBJ + '._get_flasharray')
    @mock.patch(BASE_DRIVER_OBJ + '._generate_replication_retention')
    @mock.patch(BASE_DRIVER_OBJ + '._setup_replicated_pgroups')
    def test_parse_replication_configs_single_sync_target_non_uniform(
            self,
            mock_setup_repl_pgroups,
            mock_generate_replication_retention,
            mock_getarray):
        retention = mock.MagicMock()
        mock_generate_replication_retention.return_value = retention
        mock_setup_repl_pgroups.return_value = None

        # Test single array configured
        self.mock_config.safe_get.return_value = [
            {
                "backend_id": "foo",
                "managed_backend_name": None,
                "san_ip": "1.2.3.4",
                "api_token": "abc123",
                "type": "sync",
            }
        ]
        mock_getarray().get_arrays.return_value = VALID_GET_ARRAY_PRIMARY
        self.driver._storage_protocol = 'iSCSI'
        self.driver.parse_replication_configs()
        self.assertEqual(1, len(self.driver._replication_target_arrays))
        self.assertEqual(mock_getarray(),
                         self.driver._replication_target_arrays[0])
        only_target_array = self.driver._replication_target_arrays[0]
        self.assertEqual("foo", only_target_array.backend_id)
        self.assertEqual([mock_getarray()],
                         self.driver._active_cluster_target_arrays)
        self.assertEqual(
            0, len(self.driver._uniform_active_cluster_target_arrays))

    @mock.patch(BASE_DRIVER_OBJ + '._get_flasharray')
    @mock.patch(BASE_DRIVER_OBJ + '._generate_replication_retention')
    @mock.patch(BASE_DRIVER_OBJ + '._setup_replicated_pgroups')
    def test_parse_replication_configs_single_sync_target_uniform(
            self,
            mock_setup_repl_pgroups,
            mock_generate_replication_retention,
            mock_getarray):
        retention = mock.MagicMock()
        mock_generate_replication_retention.return_value = retention
        mock_setup_repl_pgroups.return_value = None

        # Test single array configured
        self.mock_config.safe_get.return_value = [
            {
                "backend_id": "foo",
                "managed_backend_name": None,
                "san_ip": "1.2.3.4",
                "api_token": "abc123",
                "type": "sync",
                "uniform": True,
            }
        ]

        mock_getarray().get_arrays.return_value = VALID_GET_ARRAY_PRIMARY
        self.driver._storage_protocol = 'iSCSI'
        self.driver.parse_replication_configs()
        self.assertEqual(1, len(self.driver._replication_target_arrays))
        self.assertEqual(mock_getarray(),
                         self.driver._replication_target_arrays[0])
        only_target_array = self.driver._replication_target_arrays[0]
        self.assertEqual("foo", only_target_array.backend_id)
        self.assertEqual([mock_getarray()],
                         self.driver._active_cluster_target_arrays)
        self.assertEqual(
            1, len(self.driver._uniform_active_cluster_target_arrays))
        self.assertEqual(
            mock_getarray(),
            self.driver._uniform_active_cluster_target_arrays[0])

    @mock.patch(BASE_DRIVER_OBJ + '._generate_replication_retention')
    @mock.patch(BASE_DRIVER_OBJ + '._setup_replicated_pgroups')
    def test_do_setup_replicated(self,
                                 mock_setup_repl_pgroups,
                                 mock_generate_replication_retention):
        retention = mock.MagicMock()
        mock_generate_replication_retention.return_value = retention
        self._setup_mocks_for_replication()
        self.mock_config.safe_get.return_value = [
            {
                "backend_id": "foo",
                "managed_backend_name": None,
                "san_ip": "1.2.3.4",
                "api_token": "abc123",
                "type": "async",
            }
        ]
        self.driver._get_flasharray = mock.MagicMock()
        self.driver._get_flasharray().\
            get_arrays.return_value = VALID_GET_ARRAY_PRIMARY
        self.driver._replication_target_arrays = [self.async_array2]
        self.driver._storage_protocol = 'iSCSI'
        self.driver.do_setup(None)
        calls = [
            mock.call(self.array,
                      [self.async_array2, self.driver._get_flasharray()],
                      'cinder-group',
                      3600, retention)
        ]
        mock_setup_repl_pgroups.assert_has_calls(calls)

    @mock.patch(BASE_DRIVER_OBJ + '._setup_replicated_pods')
    @mock.patch(BASE_DRIVER_OBJ + '._generate_replication_retention')
    @mock.patch(BASE_DRIVER_OBJ + '._setup_replicated_pgroups')
    def test_do_setup_replicated_sync_rep(self,
                                          mock_setup_repl_pgroups,
                                          mock_generate_replication_retention,
                                          mock_setup_pods):
        retention = mock.MagicMock()
        mock_generate_replication_retention.return_value = retention
        self._setup_mocks_for_replication()

        self.mock_config.safe_get.return_value = [
            {
                "backend_id": "foo",
                "managed_backend_name": None,
                "san_ip": "1.2.3.4",
                "api_token": "abc123",
                "type": "sync",
            }
        ]
        mock_sync_target = mock.MagicMock()
        mock_sync_target.get_arrays.return_value = VALID_GET_ARRAY_SECONDARY
        self.driver._get_flasharray = mock.MagicMock()
        self.driver._get_flasharray().\
            get_arrays.return_value = VALID_GET_ARRAY_PRIMARY
        self.driver._active_cluster_target_arrays = [mock_sync_target]
        self.driver.configuration.pure_nvme_transport = "roce"
        self.driver._storage_protocol = 'iSCSI'
        self.driver.do_setup(None)
        mock_setup_pods.assert_has_calls([
            mock.call(self.array,
                      [mock_sync_target, self.driver._get_flasharray()],
                      'cinder-pod')
        ])

    def test_update_provider_info_update_all(self):
        test_vols = [
            self.new_fake_vol(spec={'id': fake.VOLUME_ID},
                              set_provider_id=False),
            self.new_fake_vol(spec={'id': fake.VOLUME2_ID},
                              set_provider_id=False),
            self.new_fake_vol(spec={'id': fake.VOLUME3_ID},
                              set_provider_id=False),
        ]

        vols = []
        vol_names = []
        for v in test_vols:
            vols.append(v[0])
            vol_names.append(v[1])

        model_updates, _ = self.driver.update_provider_info(vols, None)
        self.assertEqual(len(test_vols), len(model_updates))
        for update, vol_name in zip(model_updates, vol_names):
            self.assertEqual(vol_name, update['provider_id'])

    def test_update_provider_info_update_some(self):
        test_vols = [
            self.new_fake_vol(spec={'id': fake.VOLUME_ID},
                              set_provider_id=True),
            self.new_fake_vol(spec={'id': fake.VOLUME2_ID},
                              set_provider_id=True),
            self.new_fake_vol(spec={'id': fake.VOLUME3_ID},
                              set_provider_id=False),
        ]

        vols = []
        vol_names = []
        for v in test_vols:
            vols.append(v[0])
            vol_names.append(v[1])

        model_updates, _ = self.driver.update_provider_info(vols, None)
        self.assertEqual(1, len(model_updates))
        self.assertEqual(vol_names[2], model_updates[0]['provider_id'])

    def test_update_provider_info_no_updates(self):
        test_vols = [
            self.new_fake_vol(spec={'id': fake.VOLUME_ID},
                              set_provider_id=True),
            self.new_fake_vol(spec={'id': fake.VOLUME2_ID},
                              set_provider_id=True),
            self.new_fake_vol(spec={'id': fake.VOLUME3_ID},
                              set_provider_id=True),
        ]

        vols = []
        for v in test_vols:
            vols.append(v[0])

        model_updates, _ = self.driver.update_provider_info(vols, None)
        self.assertEqual(0, len(model_updates))

    def test_generate_purity_host_name(self):
        result = self.driver._generate_purity_host_name(
            "really-long-string-thats-a-bit-too-long")
        self.assertTrue(result.startswith("really-long-string-that-"))
        self.assertTrue(result.endswith("-cinder"))
        self.assertEqual(63, len(result))
        self.assertTrue(bool(pure.GENERATED_NAME.match(result)))
        result = self.driver._generate_purity_host_name("!@#$%^-invalid&*")
        self.assertTrue(result.startswith("invalid---"))
        self.assertTrue(result.endswith("-cinder"))
        self.assertEqual(49, len(result))
        self.assertIsNotNone(pure.GENERATED_NAME.match(result))

    @mock.patch(DRIVER_PATH + ".flasharray.VolumePost")
    def test_revert_to_snapshot(self, mock_fa):
        vol, vol_name = self.new_fake_vol(set_provider_id=True)
        snap, snap_name = self.new_fake_snap(vol)
        mock_data = self.flasharray.VolumePost(source=self.flasharray.
                                               Reference(name=vol_name))
        context = mock.MagicMock()
        self.driver.revert_to_snapshot(context, vol, snap)

        self.array.post_volumes.assert_called_with(names=[snap_name],
                                                   overwrite=True,
                                                   volume=mock_data)
        self.assert_error_propagates([self.array.post_volumes],
                                     self.driver.revert_to_snapshot,
                                     context, vol, snap)

    @mock.patch(DRIVER_PATH + ".flasharray.VolumePost")
    def test_revert_to_snapshot_group(self, mock_fa):
        vol, vol_name = self.new_fake_vol(set_provider_id=True)
        group, group_name = self.new_fake_group()
        group_snap, group_snap_name = self.new_fake_group_snap(group)
        snap, snap_name = self.new_fake_snap(vol, group_snap)
        mock_data = self.flasharray.VolumePost(source=self.flasharray.
                                               Reference(name=vol_name))
        context = mock.MagicMock()
        self.driver.revert_to_snapshot(context, vol, snap)

        self.array.post_volumes.assert_called_with(names=[snap_name],
                                                   volume=mock_data,
                                                   overwrite=True)

        self.assert_error_propagates([self.array.post_volumes],
                                     self.driver.revert_to_snapshot,
                                     context, vol, snap)

    @mock.patch(DRIVER_PATH + ".flasharray.VolumePost")
    @mock.patch(BASE_DRIVER_OBJ + "._add_to_group_if_needed")
    @mock.patch(BASE_DRIVER_OBJ + "._get_replication_type_from_vol_type")
    def test_create_volume(self, mock_get_repl_type, mock_add_to_group,
                           mock_fa):
        mock_get_repl_type.return_value = None
        vol_obj = fake_volume.fake_volume_obj(mock.MagicMock(), size=2)
        mock_data = self.array.flasharray.VolumePost(provisioned=2147483648)
        mock_fa.return_value = mock_data
        self.driver.create_volume(vol_obj)
        vol_name = vol_obj["name"] + "-cinder"
        self.array.post_volumes.assert_called_with(names=[vol_name],
                                                   with_default_protection=
                                                   False, volume=mock_data)
        mock_add_to_group.assert_called_once_with(vol_obj, vol_name)
        self.assert_error_propagates([mock_fa],
                                     self.driver.create_volume, vol_obj)

    @mock.patch(DRIVER_PATH + ".flasharray.VolumePost")
    @mock.patch(BASE_DRIVER_OBJ + "._add_to_group_if_needed")
    @mock.patch(BASE_DRIVER_OBJ + "._get_replication_type_from_vol_type")
    @mock.patch.object(volume_types, 'get_volume_type')
    def test_create_volume_from_snapshot(self, mock_get_volume_type,
                                         mock_get_replicated_type,
                                         mock_add_to_group, mock_fa):
        srcvol, _ = self.new_fake_vol()
        snap = fake_snapshot.fake_snapshot_obj(mock.MagicMock(), volume=srcvol)
        snap_name = snap["volume_name"] + "-cinder." + snap["name"]
        mock_get_replicated_type.return_value = None
        vol, vol_name = self.new_fake_vol(set_provider_id=False)
        mock_data = self.array.flasharray.VolumePost(names=[snap_name],
                                                     source=pure.flasharray.
                                                     Reference(name=vol_name),
                                                     name=vol_name)
        mock_fa.return_value = mock_data

        mock_get_volume_type.return_value = vol.volume_type
        # Branch where extend unneeded
        self.driver.create_volume_from_snapshot(vol, snap)
        self.array.post_volumes.assert_called_with(names=[vol_name],
                                                   with_default_protection=
                                                   False,
                                                   volume=mock_data)
        self.assertFalse(self.array.extend_volume.called)
        mock_add_to_group.assert_called_once_with(vol, vol_name)
        self.assert_error_propagates(
            [mock_fa],
            self.driver.create_volume_from_snapshot, vol, snap)
        self.assertFalse(self.array.extend_volume.called)

    @mock.patch(BASE_DRIVER_OBJ + "._extend_if_needed")
    @mock.patch(DRIVER_PATH + ".flasharray.VolumePost")
    @mock.patch(BASE_DRIVER_OBJ + "._add_to_group_if_needed")
    @mock.patch(BASE_DRIVER_OBJ + "._get_replication_type_from_vol_type")
    @mock.patch.object(volume_types, 'get_volume_type')
    def test_create_volume_from_snapshot_with_extend(self,
                                                     mock_get_volume_type,
                                                     mock_get_replicated_type,
                                                     mock_add_to_group,
                                                     mock_fa, mock_extend):
        srcvol, srcvol_name = self.new_fake_vol(spec={"size": 1})
        snap = fake_snapshot.fake_snapshot_obj(mock.MagicMock(), volume=srcvol)
        snap_name = snap["volume_name"] + "-cinder." + snap["name"]
        mock_get_replicated_type.return_value = None

        vol, vol_name = self.new_fake_vol(set_provider_id=False,
                                          spec={"size": 2})
        mock_data = self.array.flasharray.VolumePost(names=[snap_name],
                                                     source=pure.flasharray.
                                                     Reference(name=vol_name),
                                                     name=vol_name)
        mock_fa.return_value = mock_data
        mock_get_volume_type.return_value = vol.volume_type

        self.driver.create_volume_from_snapshot(vol, snap)
        mock_extend.assert_called_with(self.array,
                                       vol_name,
                                       snap["volume_size"],
                                       vol["size"])
        mock_add_to_group.assert_called_once_with(vol, vol_name)

    @mock.patch(DRIVER_PATH + ".flasharray.VolumePost")
    @mock.patch.object(volume_types, 'get_volume_type')
    def test_create_volume_from_snapshot_sync(self, mock_get_volume_type,
                                              mock_fa):
        repl_extra_specs = {
            'replication_type': '<in> async',
            'replication_enabled': '<is> true',
        }
        srcvol, _ = self.new_fake_vol(type_extra_specs=repl_extra_specs)
        snap, snap_name = self.new_fake_snap(vol=srcvol)

        vol, vol_name = self.new_fake_vol(set_provider_id=False,
                                          type_extra_specs=repl_extra_specs)
        mock_data = self.array.flasharray.VolumePost(names=[snap_name],
                                                     source=pure.flasharray.
                                                     Reference(name=vol_name),
                                                     name=vol_name)
        mock_fa.return_value = mock_data
        mock_get_volume_type.return_value = vol.volume_type
        self.driver.create_volume_from_snapshot(vol, snap)
        self.array.post_volumes.assert_called_with(names=[vol_name],
                                                   with_default_protection=
                                                   False,
                                                   volume=mock_data)

    @mock.patch(DRIVER_PATH + ".flasharray.VolumePost")
    @mock.patch(BASE_DRIVER_OBJ + "._add_to_group_if_needed")
    @mock.patch(BASE_DRIVER_OBJ + "._extend_if_needed", autospec=True)
    @mock.patch(BASE_DRIVER_OBJ + "._get_pgroup_snap_name_from_snapshot")
    @mock.patch(BASE_DRIVER_OBJ + "._get_replication_type_from_vol_type")
    @mock.patch.object(volume_types, 'get_volume_type')
    def test_create_volume_from_cgsnapshot(self, mock_get_volume_type,
                                           mock_get_replicated_type,
                                           mock_get_snap_name,
                                           mock_extend_if_needed,
                                           mock_add_to_group,
                                           mock_fa):
        cgroup = fake_group.fake_group_obj(mock.MagicMock())
        cgsnap = fake_group_snapshot.fake_group_snapshot_obj(mock.MagicMock(),
                                                             group=cgroup)
        vol, vol_name = self.new_fake_vol(spec={"group": cgroup})
        mock_get_volume_type.return_value = vol.volume_type
        snap = fake_cgsnapshot.fake_cgsnapshot_obj(mock.MagicMock(),
                                                   volume=vol)
        snap.cgsnapshot_id = cgsnap.id
        snap.cgsnapshot = cgsnap
        snap.volume_size = 1
        snap_name = "consisgroup-%s-cinder.%s.%s-cinder" % (
            cgroup.id,
            snap.id,
            vol.name
        )
        mock_get_snap_name.return_value = snap_name
        mock_get_replicated_type.return_value = False
        mock_data = self.array.flasharray.VolumePost(names=[vol_name],
                                                     source=pure.flasharray.
                                                     Reference(name=vol_name),
                                                     name=vol_name)
        mock_fa.return_value = mock_data

        self.driver.create_volume_from_snapshot(vol, snap, True)

        self.array.post_volumes.assert_called_with(names=[vol_name],
                                                   with_default_protection=
                                                   False,
                                                   volume=mock_data)
        self.assertTrue(mock_extend_if_needed.called)
        mock_add_to_group.assert_called_with(vol, vol_name)

    # Tests cloning a volume that is not replicated type
    @mock.patch(DRIVER_PATH + ".flasharray.VolumePost")
    @mock.patch(BASE_DRIVER_OBJ + "._add_to_group_if_needed")
    @mock.patch(BASE_DRIVER_OBJ + "._get_replication_type_from_vol_type")
    def test_create_cloned_volume(self, mock_get_replication_type,
                                  mock_add_to_group,
                                  mock_fa):
        vol, vol_name = self.new_fake_vol(set_provider_id=False)
        src_vol, src_name = self.new_fake_vol()
        mock_data = self.array.flasharray.VolumePost(names=[vol_name],
                                                     source=
                                                     pure.flasharray.
                                                     reference(name=src_name))
        mock_fa.return_value = mock_data
        mock_get_replication_type.return_value = None
        # Branch where extend unneeded
        self.driver.create_cloned_volume(vol, src_vol)
        self.array.post_volumes.assert_called_with(names=[vol_name],
                                                   volume=mock_data)
        self.assertFalse(self.array.extend_volume.called)
        mock_add_to_group.assert_called_once_with(vol,
                                                  vol_name)
        self.assert_error_propagates(
            [self.array.post_volumes],
            self.driver.create_cloned_volume, vol, src_vol)
        self.assertFalse(self.array.extend_volume.called)

    @mock.patch(DRIVER_PATH + ".flasharray.VolumePost")
    def test_create_cloned_volume_sync_rep(self, mock_fa):
        repl_extra_specs = {
            'replication_type': '<in> sync',
            'replication_enabled': '<is> true',
        }
        src_vol, src_name = self.new_fake_vol(
            type_extra_specs=repl_extra_specs)
        vol, vol_name = self.new_fake_vol(set_provider_id=False,
                                          type_extra_specs=repl_extra_specs)
        mock_data = self.array.flasharray.VolumePost(names=[vol_name],
                                                     source=pure.flasharray.
                                                     reference(name=src_name))
        mock_fa.return_value = mock_data
        # Branch where extend unneeded
        self.driver.create_cloned_volume(vol, src_vol)
        self.array.post_volumes.assert_called_with(names=[vol_name],
                                                   volume=mock_data)
        self.assertFalse(self.array.extend_volume.called)

    @mock.patch(BASE_DRIVER_OBJ + "._extend_if_needed")
    @mock.patch(DRIVER_PATH + ".flasharray.VolumePost")
    @mock.patch(BASE_DRIVER_OBJ + "._add_to_group_if_needed")
    @mock.patch(BASE_DRIVER_OBJ + "._get_replication_type_from_vol_type")
    def test_create_cloned_volume_and_extend(self, mock_get_replication_type,
                                             mock_add_to_group,
                                             mock_fa, mock_extend):
        vol, vol_name = self.new_fake_vol(set_provider_id=False,
                                          spec={"size": 2})
        src_vol, src_name = self.new_fake_vol()
        mock_get_replication_type.return_value = None
        mock_data = self.array.flasharray.VolumePost(names=[vol_name],
                                                     source=
                                                     pure.flasharray.
                                                     Reference(name=src_name),
                                                     name=vol_name)
        mock_fa.return_value = mock_data
        self.driver.create_cloned_volume(vol, src_vol)
        mock_extend.assert_called_with(self.array, vol_name,
                                       src_vol["size"], vol["size"])
        mock_add_to_group.assert_called_once_with(vol,
                                                  vol_name)

    # Tests cloning a volume that is part of a consistency group
    @mock.patch(BASE_DRIVER_OBJ + "._add_to_group_if_needed")
    @mock.patch(BASE_DRIVER_OBJ + "._get_replication_type_from_vol_type")
    def test_create_cloned_volume_with_cgroup(self, mock_get_replication_type,
                                              mock_add_to_group):
        vol, vol_name = self.new_fake_vol(set_provider_id=False)
        group = fake_group.fake_group_obj(mock.MagicMock())
        src_vol, _ = self.new_fake_vol(spec={"group_id": group.id})
        mock_get_replication_type.return_value = None

        self.driver.create_cloned_volume(vol, src_vol)

        mock_add_to_group.assert_called_with(vol, vol_name)

    def test_delete_volume_already_deleted(self):
        vol, _ = self.new_fake_vol()
        self.array.get_connections.return_value = CONN
        self.driver.delete_volume(vol)
        self.assertFalse(self.array.delete_volumes.called)

        # Testing case where array.destroy_volume returns an exception
        # because volume has already been deleted
        self.array.get_connections.side_effect = None
        self.array.get_connections.return_value = ValidResponse(200, None, 1,
                                                                [], {})
        self.driver.delete_volume(vol)
        self.array.delete_connections.assert_called_with(host_names=['utest'],
                                                         volume_names=
                                                         [vol["provider_id"]])
        self.assertTrue(self.array.patch_volumes.called)
        self.assertFalse(self.array.delete_volumes.called)

    def test_delete_volume(self):
        vol, vol_name = self.new_fake_vol()
        self.array.get_connections.return_value = CONN
        self.driver.delete_volume(vol)
        self.array.get_connections.assert_called()
        self.array.patch_volumes.assert_called()
        self.assertFalse(self.array.eradicate_volume.called)

    @mock.patch(DRIVER_PATH + ".LOG")
    @mock.patch(DRIVER_PATH + ".flasharray.VolumePatch")
    def test_delete_volume_error(self, mock_vol_patch, mock_logger):
        vol, vol_name = self.new_fake_vol()
        self.array.get_connections.return_value = ValidResponse(200, None, 1,
                                                                [], {})

        err_rsp = ErrorResponse(400, [DotNotation({'message':
                                      'does not exist'})], {})
        self.array.patch_volumes.return_value = err_rsp
        self.driver.delete_volume(vol)
        mock_logger.warning.\
            assert_called_with('Volume deletion failed with message: %s',
                               'does not exist')

    @mock.patch(DRIVER_PATH + ".flasharray.VolumePatch")
    def test_delete_volume_eradicate_now(self, mock_vol_patch):
        vol, vol_name = self.new_fake_vol()
        self.array.get_connections.return_value = ValidResponse(200, None, 1,
                                                                [], {})
        self.mock_config.pure_eradicate_on_delete = True
        mock_data = self.array.flasharray.VolumePatch(names=[vol_name],
                                                      volume=vol)
        mock_vol_patch.return_data = mock_data
        self.driver.delete_volume(vol)
        expected = [mock.call.flasharray.VolumePatch(names=[vol_name],
                                                     volume=vol),
                    mock.call.get_connections(volume_names = [vol_name]),
                    mock.call.patch_volumes(names=[vol_name],
                                            volume=mock_vol_patch()),
                    mock.call.delete_volumes(names=[vol_name])]
        self.array.assert_has_calls(expected)

    @mock.patch(DRIVER_PATH + ".flasharray.VolumePatch")
    def test_delete_connected_volume(self, mock_vol_patch):
        vol, vol_name = self.new_fake_vol()
        self.array.get_connections.return_value = CONN
        mock_data = self.array.flasharray.VolumePatch(names=[vol_name],
                                                      volume=vol)
        mock_vol_patch.return_data = mock_data
        self.driver.delete_volume(vol)
        expected = [mock.call.flasharray.VolumePatch(names=[vol_name],
                                                     volume=vol),
                    mock.call.get_connections(volume_names = [vol_name]),
                    mock.call.delete_connections(host_names=['utest'],
                                                 volume_names = [vol_name]),
                    mock.call.get_connections(host_names=['utest']),
                    mock.call.patch_volumes(names=[vol_name],
                                            volume=mock_vol_patch())
                    ]
        self.array.assert_has_calls(expected)

    @mock.patch(DRIVER_PATH + ".flasharray.VolumePatch")
    def test_delete_not_connected_pod_volume(self, mock_vol_patch):
        type_spec = {
            'replication_type': '<in> sync',
            'replication_enabled': '<is> true',
        }
        vol, vol_name = self.new_fake_vol(type_extra_specs=type_spec)
        self.array.get_connections.return_value = ValidResponse(200, None, 1,
                                                                [], {})
        mock_data = self.array.flasharray.VolumePatch(names=[vol_name],
                                                      volume=vol)
        mock_vol_patch.return_data = mock_data
        # Set the array to be in a sync-rep enabled version

        self.driver.delete_volume(vol)

        expected = [mock.call.flasharray.VolumePatch(names=[vol_name],
                                                     volume=vol),
                    mock.call.get_connections(volume_names = [vol_name]),
                    mock.call.patch_volumes(names=[vol_name],
                                            volume=mock_vol_patch())
                    ]
        self.array.assert_has_calls(expected)

    @mock.patch(DRIVER_PATH + ".flasharray.VolumePatch")
    def test_delete_connected_pod_volume(self, mock_vol_patch):
        type_spec = {
            'replication_type': '<in> sync',
            'replication_enabled': '<is> true',
        }
        vol, vol_name = self.new_fake_vol(type_extra_specs=type_spec)
        self.array.get_connections.return_value = CONN
        mock_data = self.array.flasharray.VolumePatch(names=[vol_name],
                                                      volume=vol)
        mock_vol_patch.return_data = mock_data

        # Set the array to be in a sync-rep enabled version

        self.driver.delete_volume(vol)
        expected = [mock.call.flasharray.VolumePatch(names=[vol_name],
                                                     volume=vol),
                    mock.call.get_connections(volume_names = [vol_name]),
                    mock.call.delete_connections(host_names = ['utest'],
                                                 volume_names = [vol_name]),
                    mock.call.get_connections(host_names = ['utest']),
                    mock.call.patch_volumes(names=[vol_name],
                                            volume=mock_vol_patch())
                    ]
        self.array.assert_has_calls(expected)

    @mock.patch(DRIVER_PATH + ".flasharray.VolumeSnapshotPost")
    def test_create_snapshot(self, mock_snap):
        vol, vol_name = self.new_fake_vol()
        snap = fake_snapshot.fake_snapshot_obj(mock.MagicMock(), volume=vol)
        suffix_name = snap['name'].split(".")
        mock_data = self.array.flasharray.VolumeSnapshotPost(suffix=
                                                             suffix_name)
        mock_snap.return_value = mock_data
        self.driver.create_snapshot(snap)
        self.array.post_volume_snapshots.assert_called_with(
            source_names=[vol_name],
            volume_snapshot=mock_data
        )
        self.assert_error_propagates([self.array.post_volume_snapshots],
                                     self.driver.create_snapshot, snap)

    @mock.patch(DRIVER_PATH + ".LOG")
    @mock.patch(DRIVER_PATH + ".flasharray.VolumeSnapshotPatch")
    def test_delete_snapshot_error(self, mock_snap_patch, mock_logger):
        vol, _ = self.new_fake_vol()
        snap = fake_snapshot.fake_snapshot_obj(mock.MagicMock(), volume=vol)
        err_rsp = ErrorResponse(400, [DotNotation({'message':
                                      'does not exist'})], {})
        self.array.patch_volume_snapshots.return_value = err_rsp
        self.driver.delete_snapshot(snap)
        mock_logger.warning.\
            assert_called_with('Unable to delete snapshot, '
                               'assuming already deleted. '
                               'Error: %s', 'does not exist')

    @mock.patch(DRIVER_PATH + ".flasharray.VolumeSnapshotPatch")
    def test_delete_snapshot(self, mock_snap_patch):
        vol, _ = self.new_fake_vol()
        snap = fake_snapshot.fake_snapshot_obj(mock.MagicMock(), volume=vol)
        snap_name = snap["volume_name"] + "-cinder." + snap["name"]
        mock_data = self.array.flasharray.VolumeSnapshotPatch(destroyed=True)
        mock_snap_patch.return_value = mock_data
        self.driver.delete_snapshot(snap)
        expected = [mock.call.flasharray.VolumeSnapshotPatch(destroyed=True),
                    mock.call.patch_volume_snapshots(names=[snap_name],
                    volume_snapshot=mock_data)]
        self.array.assert_has_calls(expected)
        self.assertFalse(self.array.delete_volume_snapshots.called)

    @mock.patch(DRIVER_PATH + ".flasharray.VolumeSnapshotPatch")
    def test_delete_snapshot_eradicate_now(self, mock_snap_patch):
        vol, _ = self.new_fake_vol()
        snap = fake_snapshot.fake_snapshot_obj(mock.MagicMock(), volume=vol)
        snap_name = snap["volume_name"] + "-cinder." + snap["name"]
        self.mock_config.pure_eradicate_on_delete = True
        mock_data = self.array.flasharray.VolumeSnapshotPatch(destroyed=True)
        mock_snap_patch.return_value = mock_data
        self.driver.delete_snapshot(snap)
        self.array.delete_volume_snapshots.asssert_called_with(names=
                                                               [snap_name])
        self.assertTrue(self.array.delete_volume_snapshots.called)

    @mock.patch(BASE_DRIVER_OBJ + "._get_host", autospec=True)
    def test_terminate_connection(self, mock_host):
        vol, vol_name = self.new_fake_vol()
        pure_hosts = ValidResponse(200, None, 1,
                                   [DotNotation({"name": "some-host"})], {})
        mock_host.return_value = pure_hosts.items
        self.array.get_connections.return_value = CONN
        # Branch with manually created host
        self.driver.terminate_connection(vol, ISCSI_CONNECTOR)
        self.array.delete_connections.\
            assert_called_with(host_names=["some-host"],
                               volume_names=[vol_name])
        self.assertTrue(self.array.get_connections.called)
        self.assertTrue(self.array.delete_connections.called)
        self.assertFalse(self.array.delete_hosts.called)
        # Branch with host added to host group
        self.array.reset_mock()
        self.array.get_connections.\
            return_value = ValidResponse(200, None, 1, [], {})
        pure_hosts = ValidResponse(200, None, 1,
                                   [DotNotation(PURE_HOST.copy())], {})
        mock_host.return_value = pure_hosts.items
        mock_host.return_value[0].update(hgroup="some-group")
        self.array.delete_hosts.\
            return_value = ValidResponse(200, None, 1, [], {})
        self.driver.terminate_connection(vol, ISCSI_CONNECTOR)
        self.array.delete_connections.\
            assert_called_with(host_names=[PURE_HOST_NAME],
                               volume_names=[vol_name])
        self.assertTrue(self.array.get_connections.called)
        self.assertTrue(self.array.delete_hosts.called)
        # Branch with host still having connected volumes
        self.array.reset_mock()
        pure_hosts = ValidResponse(200, None, 1,
                                   [DotNotation(PURE_HOST.copy())], {})
        self.array.get_host_connections.return_value = [
            {"lun": 2, "name": PURE_HOST_NAME, "vol": "some-vol"}]
        mock_host.return_value = pure_hosts.items
        self.driver.terminate_connection(vol, ISCSI_CONNECTOR)
        self.array.delete_connections.\
            assert_called_with(host_names=[PURE_HOST_NAME],
                               volume_names=[vol_name])
        self.assertTrue(self.array.get_connections.called)
        self.assertFalse(self.array.delete_host.called)
        # Branch where host gets deleted
        self.array.reset_mock()
        self.array.get_host_connections.\
            return_value = ValidResponse(200, None, 1, [], {})
        self.driver.terminate_connection(vol, ISCSI_CONNECTOR)
        self.array.delete_connections.\
            assert_called_with(host_names=[PURE_HOST_NAME],
                               volume_names=[vol_name])
        self.assertTrue(self.array.get_connections.called)
        self.array.delete_hosts.assert_called_with(names=[PURE_HOST_NAME])
        # Branch where connection is missing and the host is still deleted
        self.array.reset_mock()
        err_rsp = ErrorResponse(400, [DotNotation({'message':
                                      'does not exist'})], {})
        self.array.get_host_connections.return_value = err_rsp
        self.driver.terminate_connection(vol, ISCSI_CONNECTOR)
        self.array.delete_connections.\
            assert_called_with(host_names=[PURE_HOST_NAME],
                               volume_names=[vol_name])
        self.assertTrue(self.array.get_connections.called)
        self.array.delete_hosts.assert_called_with(names=[PURE_HOST_NAME])
        # Branch where an unexpected exception occurs
        self.array.reset_mock()
        err_rsp = ErrorResponse(500, [DotNotation({'message':
                                      'Some other error'})], {})
        self.array.get_host_connections.return_value = err_rsp
        self.driver.terminate_connection(vol, ISCSI_CONNECTOR)
        self.array.delete_connections.\
            assert_called_with(host_names=[PURE_HOST_NAME],
                               volume_names=[vol_name])
        self.assertTrue(self.array.get_connections.called)
        self.array.delete_hosts.assert_called_with(names=[PURE_HOST_NAME])

    @mock.patch(BASE_DRIVER_OBJ + "._disconnect_host")
    @mock.patch(BASE_DRIVER_OBJ + "._get_host", autospec=True)
    def test_terminate_connection_uniform_ac_remove_remote_hosts(
            self, mock_host, mock_disconnect):
        repl_extra_specs = {
            'replication_type': '<in> sync',
            'replication_enabled': '<is> true',
        }
        vol, vol_name = self.new_fake_vol(type_extra_specs=repl_extra_specs)
        self.driver._is_active_cluster_enabled = True
        mock_secondary = mock.MagicMock()
        self.driver._uniform_active_cluster_target_arrays = [mock_secondary]
        pure_hosts = ValidResponse(200, None, 2,
                                   [DotNotation({"name":
                                                 "secondary-fa1:some-host1"}),
                                    DotNotation({"name": "some-host1"})], {})
        mock_host.return_value = pure_hosts.items
        self.driver.terminate_connection(vol, ISCSI_CONNECTOR)
        mock_disconnect.assert_has_calls([
            mock.call(mock_secondary, "secondary-fa1:some-host1", vol_name),
            mock.call(mock_secondary, "some-host1", vol_name)
        ])

    @mock.patch(BASE_DRIVER_OBJ + "._disconnect_host")
    @mock.patch(BASE_DRIVER_OBJ + "._get_host", autospec=True)
    def test_terminate_connection_uniform_ac_no_remote_hosts(
            self, mock_host, mock_disconnect):
        repl_extra_specs = {
            'replication_type': '<in> sync',
            'replication_enabled': '<is> true',
        }
        vol, vol_name = self.new_fake_vol(type_extra_specs=repl_extra_specs)
        self.driver._is_active_cluster_enabled = True
        mock_secondary = mock.MagicMock()
        self.driver._uniform_active_cluster_target_arrays = [mock_secondary]
        pure_hosts = ValidResponse(200, None, 2,
                                   [DotNotation({"name": "some-host2"})], {})
        mock_host.return_value = pure_hosts.items

        self.driver.terminate_connection(vol, ISCSI_CONNECTOR)
        mock_disconnect.assert_has_calls([
            mock.call(self.array, "some-host2", vol_name),
        ])

    def _test_terminate_connection_with_error(self, mock_host, error_text):
        vol, vol_name = self.new_fake_vol()
        mock_host.return_value = [DotNotation(PURE_HOST.copy())]
        self.array.reset_mock()
        self.array.get_host_connections.return_value = []
        err_rsp = ErrorResponse(400, [DotNotation({'message':
                                      f"{error_text}"})], {})
        self.array.delete_hosts.return_value = err_rsp
        pure_hosts = ValidResponse(200, None, 1, [], {})
        self.array.get_connections.return_value = pure_hosts
        self.driver.terminate_connection(vol, DotNotation(ISCSI_CONNECTOR))
        self.array.get_connections.\
            assert_called_with(host_names=[PURE_HOST_NAME])
        self.array.delete_hosts.\
            assert_called_once_with(names=[PURE_HOST_NAME])

    @mock.patch(BASE_DRIVER_OBJ + "._get_host", autospec=True)
    def test_terminate_connection_host_deleted(self, mock_host):
        self._test_terminate_connection_with_error(mock_host, 'does not exist')

    @mock.patch(BASE_DRIVER_OBJ + "._get_host", autospec=True)
    def test_terminate_connection_host_got_new_connections(self, mock_host):
        self._test_terminate_connection_with_error(
            mock_host,
            'Host cannot be deleted due to existing connections.'
        )

    def test_terminate_connection_no_connector_with_host(self):
        vol, vol_name = self.new_fake_vol()
        # Show the volume having a connection
        connections = [
            {"host": "h1", "name": vol_name},
            {"host": "h2", "name": vol_name},
        ]
        self.array.get_connections.\
            return_value = ValidResponse(200, None, 1,
                                         [DotNotation(connections[0])], {})

        self.driver.terminate_connection(vol, None)
        self.array.delete_connections.\
            assert_called_with(host_names=[connections[0]["host"]],
                               volume_names=[vol_name])

    def test_terminate_connection_no_connector_no_host(self):
        vol, _ = self.new_fake_vol()

        # Show the volume not having a connection
        self.array.get_connections.return_value = []
        self.array.get_connections.\
            return_value = ValidResponse(200, None, 1, [], {})
        self.driver.terminate_connection(vol, None)
        self.array.delete_connections.assert_not_called()

    @mock.patch(DRIVER_PATH + ".flasharray.VolumePatch")
    def test_extend_volume(self, mock_fa):
        vol, vol_name = self.new_fake_vol(spec={"size": 1})
        mock_data = self.flasharray.VolumePatch(provisioned=3 * units.Gi)
        self.driver.extend_volume(vol, 3)
        self.array.patch_volumes.\
            assert_called_with(names=[vol_name], volume=mock_data)
        self.assert_error_propagates([self.array.patch_volumes],
                                     self.driver.extend_volume, vol, 3)

    @ddt.data(
        dict(
            repl_types=[None],
            id=fake.GROUP_ID,
            expected_name=("consisgroup-%s-cinder" % fake.GROUP_ID)
        ),
        dict(
            repl_types=['async'],
            id=fake.GROUP_ID,
            expected_name=("consisgroup-%s-cinder" % fake.GROUP_ID)
        ),
        dict(
            repl_types=[None, 'async'],
            id=fake.GROUP_ID,
            expected_name=("consisgroup-%s-cinder" % fake.GROUP_ID)
        ),
        dict(
            repl_types=['sync'],
            id=fake.GROUP_ID,
            expected_name=("cinder-pod::consisgroup-%s-cinder" % fake.GROUP_ID)
        ),
        dict(
            repl_types=[None, 'sync'],
            id=fake.GROUP_ID,
            expected_name=("cinder-pod::consisgroup-%s-cinder" % fake.GROUP_ID)
        ),
        dict(
            repl_types=['trisync'],
            id=fake.GROUP_ID,
            expected_name=("cinder-pod::consisgroup-%s-cinder" % fake.GROUP_ID)
        ),
        dict(
            repl_types=[None, 'trisync'],
            id=fake.GROUP_ID,
            expected_name=("cinder-pod::consisgroup-%s-cinder" % fake.GROUP_ID)
        ),
        dict(
            repl_types=['sync', 'async'],
            id=fake.GROUP_ID,
            expected_name=("cinder-pod::consisgroup-%s-cinder" % fake.GROUP_ID)
        ),
        dict(
            repl_types=[None, 'sync', 'async'],
            id=fake.GROUP_ID,
            expected_name=("cinder-pod::consisgroup-%s-cinder" % fake.GROUP_ID)
        ),
        dict(
            repl_types=['trisync', 'sync', 'async'],
            id=fake.GROUP_ID,
            expected_name=("cinder-pod::consisgroup-%s-cinder" % fake.GROUP_ID)
        ),
        dict(
            repl_types=[None, 'trisync', 'sync', 'async'],
            id=fake.GROUP_ID,
            expected_name=("cinder-pod::consisgroup-%s-cinder" % fake.GROUP_ID)
        ),
    )
    @ddt.unpack
    def test_get_pgroup_name(self, repl_types, id, expected_name):
        pgroup = fake_group.fake_group_obj(mock.MagicMock(), id=id)
        vol_types = []
        for repl_type in repl_types:
            vol_type = fake_volume.fake_volume_type_obj(None)
            if repl_type is not None:
                repl_extra_specs = {
                    'replication_type': '<in> %s' % repl_type,
                    'replication_enabled': '<is> true',
                }
                vol_type.extra_specs = repl_extra_specs
            vol_types.append(vol_type)
        pgroup.volume_types = volume_type.VolumeTypeList(objects=vol_types)
        actual_name = self.driver._get_pgroup_name(pgroup)
        self.assertEqual(expected_name, actual_name)

    def test_get_pgroup_snap_suffix(self):
        cgsnap = {
            'id': "4a2f7e3a-312a-40c5-96a8-536b8a0fe074"
        }
        expected_suffix = "cgsnapshot-%s-cinder" % cgsnap['id']
        actual_suffix = self.driver._get_pgroup_snap_suffix(cgsnap)
        self.assertEqual(expected_suffix, actual_suffix)

    @mock.patch(BASE_DRIVER_OBJ + "._get_pgroup_name")
    def test_get_pgroup_snap_name(self, mock_get_pgroup_name):
        cg = fake_group.fake_group_obj(mock.MagicMock())
        cgsnap = fake_group_snapshot.fake_group_snapshot_obj(mock.MagicMock())
        cgsnap.group_id = cg.id
        cgsnap.group = cg
        group_name = "consisgroup-%s-cinder" % cg.id
        mock_get_pgroup_name.return_value = group_name
        expected_name = ("%(group_name)s.cgsnapshot-%(snap)s-cinder" % {
            "group_name": group_name, "snap": cgsnap.id})

        actual_name = self.driver._get_pgroup_snap_name(cgsnap)

        self.assertEqual(expected_name, actual_name)

    def test_get_pgroup_snap_name_from_snapshot(self):
        vol, _ = self.new_fake_vol()
        cg = fake_group.fake_group_obj(mock.MagicMock())
        cgsnap = fake_group_snapshot.fake_group_snapshot_obj(mock.MagicMock())
        cgsnap.group_id = cg.id
        cgsnap.group = cg

        pgsnap_name_base = (
            'consisgroup-%s-cinder.cgsnapshot-%s-cinder.%s-cinder')
        pgsnap_name = pgsnap_name_base % (cg.id, cgsnap.id, vol.name)

        snap, _ = self.new_fake_snap(vol=vol, group_snap=cgsnap)

        actual_name = self.driver._get_pgroup_snap_name_from_snapshot(
            snap
        )
        self.assertEqual(pgsnap_name, actual_name)

    @mock.patch(BASE_DRIVER_OBJ + "._group_potential_repl_types")
    def test_create_consistencygroup(self, mock_get_repl_types):
        cgroup = fake_group.fake_group_obj(mock.MagicMock())
        mock_get_repl_types.return_value = set()

        model_update = self.driver.create_consistencygroup(None, cgroup)

        expected_name = "consisgroup-" + cgroup.id + "-cinder"
        self.driver._get_current_array.assert_called()
        self.array.post_protection_groups.assert_called_with(names=
                                                             [expected_name])
        self.assertEqual({'status': 'available'}, model_update)

        self.assert_error_propagates(
            [self.array.post_protection_groups],
            self.driver.create_consistencygroup, None, cgroup)

    @mock.patch(BASE_DRIVER_OBJ + "._group_potential_repl_types")
    def test_create_consistencygroup_in_pod(self, mock_get_repl_types):
        cgroup = fake_group.fake_group_obj(mock.MagicMock())
        mock_get_repl_types.return_value = ['sync', 'async']

        model_update = self.driver.create_consistencygroup(None, cgroup)

        expected_name = "cinder-pod::consisgroup-" + cgroup.id + "-cinder"
        self.array.post_protection_groups.assert_called_with(names=
                                                             [expected_name])
        self.assertEqual({'status': 'available'}, model_update)

    @mock.patch('cinder.volume.group_types.get_group_type_specs')
    @mock.patch(BASE_DRIVER_OBJ + ".create_volume_from_snapshot")
    @mock.patch(BASE_DRIVER_OBJ + ".create_consistencygroup")
    def test_create_consistencygroup_from_cgsnapshot(self, mock_create_cg,
                                                     mock_create_vol,
                                                     mock_gp_specs):
        ctxt = context.get_admin_context()
        mock_gp_specs.return_value = '<is> True'
        mock_group = fake_group.fake_group_obj(
            None, group_type_id=fake.GROUP_TYPE_ID)
        mock_cgsnapshot = mock.Mock()
        mock_snapshots = [mock.Mock() for i in range(5)]
        mock_volumes = [mock.Mock() for i in range(5)]
        self.driver.create_consistencygroup_from_src(
            ctxt,
            mock_group,
            mock_volumes,
            cgsnapshot=mock_cgsnapshot,
            snapshots=mock_snapshots,
            source_cg=None,
            source_vols=None
        )
        mock_create_cg.assert_called_with(ctxt, mock_group, None)
        expected_calls = [mock.call(vol, snap, cgsnapshot=True)
                          for vol, snap in zip(mock_volumes, mock_snapshots)]
        mock_create_vol.assert_has_calls(expected_calls,
                                         any_order=True)

        self.assert_error_propagates(
            [mock_create_vol, mock_create_cg],
            self.driver.create_consistencygroup_from_src,
            ctxt,
            mock_group,
            mock_volumes,
            cgsnapshot=mock_cgsnapshot,
            snapshots=mock_snapshots,
            source_cg=None,
            source_vols=None
        )

    @mock.patch('cinder.volume.group_types.get_group_type_specs')
    @mock.patch(BASE_DRIVER_OBJ + ".create_consistencygroup")
    def test_create_consistencygroup_from_cg(self, mock_create_cg,
                                             mock_gp_specs):
        num_volumes = 5
        ctxt = context.get_admin_context()
        mock_gp_specs.return_value = '<is> True'
        mock_group = fake_group.fake_group_obj(
            None, group_type_id=fake.GROUP_TYPE_ID)
        mock_source_cg = mock.MagicMock()
        mock_volumes = [mock.MagicMock() for i in range(num_volumes)]
        mock_source_vols = [mock.MagicMock() for i in range(num_volumes)]
        self.driver.create_consistencygroup_from_src(
            ctxt,
            mock_group,
            mock_volumes,
            source_cg=mock_source_cg,
            source_vols=mock_source_vols
        )
        mock_create_cg.assert_called_with(ctxt, mock_group, None)
        self.assertTrue(self.array.post_protection_group_snapshots.called)
        self.assertTrue(self.array.patch_protection_group_snapshots.called)

    @mock.patch('cinder.volume.group_types.get_group_type_specs')
    @mock.patch(DRIVER_PATH + ".LOG")
    @mock.patch(DRIVER_PATH + ".flasharray.ProtectionGroup")
    @mock.patch(BASE_DRIVER_OBJ + ".delete_volume", autospec=True)
    def test_delete_consistencygroup(self, mock_delete_volume, mock_pg,
                                     mock_logger, mock_gp_specs):
        ctxt = context.get_admin_context()
        mock_gp_specs.return_value = '<is> True'
        mock_cgroup = fake_group.fake_group_obj(ctxt)
        mock_volume = fake_volume.fake_volume_obj(ctxt)
        self.array.patch_protection_groups.\
            return_value = ValidResponse(200, None, 1,
                                         ['pgroup_name'], {})
        mock_data = self.array.flasharray.ProtectionGroup(destroyed=True)
        mock_pg.return_value = mock_data
        model_update, volumes = self.driver.delete_consistencygroup(
            ctxt, mock_cgroup, [mock_volume])

        expected_name = "consisgroup-%s-cinder" % mock_cgroup.id
        self.array.patch_protection_groups.\
            assert_called_with(names=[expected_name],
                               protection_group=mock_data)
        self.assertFalse(self.array.delete_protection_groups.called)
        self.assertIsNone(volumes)
        self.assertIsNone(model_update)
        mock_delete_volume.assert_called_with(self.driver, mock_volume)
        err_rsp = ErrorResponse(400, [DotNotation({'message':
                                      'does not exist'})], {})

        self.array.patch_protection_groups.return_value = err_rsp
        self.driver.delete_consistencygroup(ctxt,
                                            mock_cgroup,
                                            [mock_volume])
        mock_logger.warning.\
            assert_called_with('Unable to delete Protection Group: %s',
                               None)
        self.assert_error_propagates(
            [self.array.patch_protection_groups],
            self.driver.delete_consistencygroup,
            ctxt,
            mock_cgroup,
            [mock_volume]
        )

    def test_update_consistencygroup(self):
        group, group_name = self.new_fake_group()
        add_vols = [
            self.new_fake_vol(spec={"id": fake.VOLUME_ID}),
            self.new_fake_vol(spec={"id": fake.VOLUME2_ID}),
            self.new_fake_vol(spec={"id": fake.VOLUME3_ID}),
        ]
        add_vol_objs = []
        expected_addvollist = []
        for vol in add_vols:
            add_vol_objs.append(vol[0])
            expected_addvollist.append(vol[1])

        remove_vols = [
            self.new_fake_vol(spec={"id": fake.VOLUME4_ID}),
            self.new_fake_vol(spec={"id": fake.VOLUME5_ID}),
        ]
        rem_vol_objs = []
        expected_remvollist = []
        for vol in remove_vols:
            rem_vol_objs.append(vol[0])
            expected_remvollist.append(vol[1])

        self.driver.update_consistencygroup(mock.Mock(), group,
                                            add_vol_objs, rem_vol_objs)
        self.array.post_protection_groups_volumes.assert_called_with(
            group_names=[group_name],
            member_names=expected_addvollist
        )
        self.array.delete_protection_groups_volumes.assert_called_with(
            group_names=[group_name],
            member_names=expected_remvollist
        )

    def test_update_consistencygroup_no_add_vols(self):
        group, group_name = self.new_fake_group()
        remove_vols = [
            self.new_fake_vol(spec={"id": fake.VOLUME4_ID}),
            self.new_fake_vol(spec={"id": fake.VOLUME5_ID}),
        ]
        rem_vol_objs = []
        expected_remvollist = []
        for vol in remove_vols:
            rem_vol_objs.append(vol[0])
            expected_remvollist.append(vol[1])
        self.driver.update_consistencygroup(mock.Mock(), group,
                                            None, rem_vol_objs)
        self.array.delete_protection_groups_volumes.assert_called_with(
            group_names=[group_name],
            member_names=expected_remvollist
        )

    def test_update_consistencygroup_no_remove_vols(self):
        group, group_name = self.new_fake_group()
        add_vols = [
            self.new_fake_vol(spec={"id": fake.VOLUME_ID}),
            self.new_fake_vol(spec={"id": fake.VOLUME2_ID}),
            self.new_fake_vol(spec={"id": fake.VOLUME3_ID}),
        ]
        add_vol_objs = []
        expected_addvollist = []
        for vol in add_vols:
            add_vol_objs.append(vol[0])
            expected_addvollist.append(vol[1])
        self.driver.update_consistencygroup(mock.Mock(), group,
                                            add_vol_objs, None)
        self.array.post_protection_groups_volumes.assert_called_with(
            group_names=[group_name],
            member_names=expected_addvollist
        )

    def test_update_consistencygroup_no_vols(self):
        group, group_name = self.new_fake_group()
        self.driver.update_consistencygroup(mock.Mock(), group,
                                            None, None)
        self.array.post_protection_groups_volumes.assert_called_with(
            group_names=[group_name],
            member_names=[]
        )
        self.array.delete_protection_groups_volumes.assert_called_with(
            group_names=[group_name],
            member_names=[]
        )

    @mock.patch(DRIVER_PATH + ".flasharray.ProtectionGroupSnapshotPost")
    def test_create_cgsnapshot(self, mock_pgsnap):
        ctxt = context.get_admin_context()
        mock_group = fake_group.fake_group_obj(ctxt)
        mock_cgsnap = fake_group_snapshot.fake_group_snapshot_obj(
            ctxt, group_id=mock_group.id)
        mock_snap = fake_snapshot.fake_snapshot_obj(ctxt)
        suffix_name = mock_snap['name'].split(".")
        mock_data = self.array.flasharray.\
            ProtectionGroupSnapshotPost(suffix=suffix_name)
        mock_pgsnap.return_value = mock_data

        # Avoid having the group snapshot object load from the db
        with mock.patch('cinder.objects.Group.get_by_id') as mock_get_group:
            mock_get_group.return_value = mock_group

            model_update, snapshots = self.driver.create_cgsnapshot(
                ctxt, mock_cgsnap, [mock_snap])

        expected_pgroup_name = self.driver._get_pgroup_name(mock_group)
        self.array.post_protection_group_snapshots\
            .assert_called_with(source_names=[expected_pgroup_name],
                                protection_group_snapshot=mock_data)
        self.assertIsNone(model_update)
        self.assertIsNone(snapshots)

        self.assert_error_propagates(
            [self.array.post_protection_group_snapshots],
            self.driver.create_cgsnapshot, ctxt, mock_cgsnap, [])

    @ddt.data("does not exist", "has been destroyed")
    @mock.patch(DRIVER_PATH + ".LOG")
    @mock.patch(DRIVER_PATH + ".flasharray.ProtectionGroupSnapshotPatch")
    @mock.patch(BASE_DRIVER_OBJ + "._get_pgroup_snap_name",
                spec=pure.PureBaseVolumeDriver._get_pgroup_snap_name)
    def test_delete_cgsnapshot(self, error_text, mock_get_snap_name,
                               mock_pgsnap_patch, mock_logger):
        snap_name = "consisgroup-4a2f7e3a-312a-40c5-96a8-536b8a0f" \
                    "e074-cinder.4a2f7e3a-312a-40c5-96a8-536b8a0fe075"
        mock_get_snap_name.return_value = snap_name
        mock_cgsnap = mock.Mock()
        mock_cgsnap.status = 'deleted'
        ctxt = context.get_admin_context()
        mock_snap = mock.Mock()
        mock_data = self.array.flasharray.\
            ProtectionGroupSnapshotPatch(destroyed=True)
        mock_pgsnap_patch.return_value = mock_data

        model_update, snapshots = self.driver.delete_cgsnapshot(ctxt,
                                                                mock_cgsnap,
                                                                [mock_snap])

        self.array.patch_protection_group_snapshots.\
            assert_called_with(names=[snap_name],
                               protection_group_snapshot=mock_data)
        self.assertFalse(self.array.delete_protection_group_snapshots.called)
        self.assertIsNone(model_update)
        self.assertIsNone(snapshots)

        err_rsp = ErrorResponse(400, [DotNotation({'message':
                                      f"{error_text}"})], {})
        self.array.patch_protection_group_snapshots.return_value = err_rsp

        self.driver.delete_cgsnapshot(ctxt, mock_cgsnap, [mock_snap])
        self.assertFalse(self.array.delete_protection_group_snapshots.called)
        mock_logger.warning.assert_called_with('Unable to delete '
                                               'Protection Group '
                                               'Snapshot: %s',
                                               f"{error_text}")

        self.assert_error_propagates(
            [self.array.patch_protection_group_snapshots],
            self.driver.delete_cgsnapshot,
            ctxt,
            mock_cgsnap,
            [mock_snap]
        )

    @mock.patch(DRIVER_PATH + ".flasharray.ProtectionGroupSnapshotPatch")
    @mock.patch(BASE_DRIVER_OBJ + "._get_pgroup_snap_name",
                spec=pure.PureBaseVolumeDriver._get_pgroup_snap_name)
    def test_delete_cgsnapshot_eradicate_now(self, mock_get_snap_name,
                                             mock_pgsnap_patch):
        snap_name = "consisgroup-4a2f7e3a-312a-40c5-96a8-536b8a0f" \
                    "e074-cinder.4a2f7e3a-312a-40c5-96a8-536b8a0fe075"
        mock_get_snap_name.return_value = snap_name
        self.mock_config.pure_eradicate_on_delete = True
        mock_data = self.array.flasharray.ProtectionGroupSnapshotPatch(
            destroyed=True)
        mock_pgsnap_patch.return_value = mock_data
        model_update, snapshots = self.driver.delete_cgsnapshot(mock.Mock(),
                                                                mock.Mock(),
                                                                [mock.Mock()])

        self.array.patch_protection_group_snapshots.\
            assert_called_with(names=[snap_name],
                               protection_group_snapshot=mock_data)
        self.array.delete_protection_group_snapshots.\
            assert_called_with(names=[snap_name])

    @mock.patch(BASE_DRIVER_OBJ + "._rename_volume_object")
    def test_manage_existing(self, mock_rename):
        ref_name = 'vol1'
        volume_ref = {'name': ref_name}
        self.array.get_volumes.return_value = MPV
        self.array.get_connections.return_value = []
        vol, vol_name = self.new_fake_vol(set_provider_id=False)
        self.driver.manage_existing(vol, volume_ref)
        mock_rename.assert_called_with(ref_name, vol_name,
                                       raise_not_exist=True)

    @mock.patch(BASE_DRIVER_OBJ + '._validate_manage_existing_ref')
    @mock.patch(BASE_DRIVER_OBJ + "._rename_volume_object")
    def test_manage_existing_error_propagates(self, mock_rename,
                                              mock_validate):
        self.array.get_volumes.return_value = MPV
        self.array.get_connections.return_value = []
        vol, _ = self.new_fake_vol(set_provider_id=False)
        self.assert_error_propagates(
            [mock_rename, mock_validate],
            self.driver.manage_existing,
            vol, {'name': 'vol1'}
        )

    def test_manage_existing_bad_ref(self):
        vol, _ = self.new_fake_vol(set_provider_id=False)
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing,
                          vol, {'bad_key': 'bad_value'})

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing,
                          vol, {'name': ''})

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing,
                          vol, {'name': None})

    def test_manage_existing_sync_repl_type(self):
        ref_name = 'vol1'
        volume_ref = {'name': ref_name}
        type_spec = {
            'replication_type': '<in> sync',
            'replication_enabled': '<is> true',
        }
        self.array.get_connections.return_value = []
        vol, vol_name = self.new_fake_vol(set_provider_id=False,
                                          type_extra_specs=type_spec)

        self.assertRaises(exception.ManageExistingVolumeTypeMismatch,
                          self.driver.manage_existing,
                          vol, volume_ref)

    def test_manage_existing_vol_in_pod(self):
        ref_name = 'somepod::vol1'
        volume_ref = {'name': ref_name}
        self.array.get_connections.return_value = []
        vol, vol_name = self.new_fake_vol(set_provider_id=False)

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing,
                          vol, volume_ref)

    @mock.patch(BASE_DRIVER_OBJ + "._rename_volume_object")
    def test_manage_existing_with_connected_hosts(self, mock_rename):
        ref_name = 'vol1'
        vol, _ = self.new_fake_vol(set_provider_id=False)
        cvol = deepcopy(MANAGEABLE_PURE_VOLS)
        cvol[0]['connection_count'] = 1
        self.array.get_volumes.\
            return_value = ValidResponse(200, None, 1,
                                         [DotNotation(cvol[0])], {})
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing,
                          vol, {'name': ref_name})
        self.assertFalse(mock_rename.called)

    def test_manage_existing_get_size(self):
        ref_name = 'vol1'
        volume_ref = {'name': ref_name}
        expected_size = 3
        self.array.get_volumes.return_value = MPV
        vol, _ = self.new_fake_vol(set_provider_id=False)

        size = self.driver.manage_existing_get_size(vol, volume_ref)

        self.assertEqual(expected_size, size)
        self.array.get_volumes.assert_called_with(names=[ref_name])

    @mock.patch(BASE_DRIVER_OBJ + '._validate_manage_existing_ref')
    def test_manage_existing_get_size_error_propagates(self, mock_validate):
        self.array.get_volumes.return_value = mock.MagicMock()
        vol, _ = self.new_fake_vol(set_provider_id=False)
        self.assert_error_propagates([mock_validate],
                                     self.driver.manage_existing_get_size,
                                     vol, {'name': 'vol1'})

    def test_manage_existing_get_size_bad_ref(self):
        vol, _ = self.new_fake_vol(set_provider_id=False)
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size,
                          vol, {'bad_key': 'bad_value'})

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size,
                          vol, {'name': ''})

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size,
                          vol, {'name': None})

    @mock.patch(BASE_DRIVER_OBJ + "._rename_volume_object")
    def test_unmanage(self, mock_rename):
        vol, vol_name = self.new_fake_vol()
        unmanaged_vol_name = vol_name + UNMANAGED_SUFFIX

        self.driver.unmanage(vol)

        mock_rename.assert_called_with(vol_name,
                                       unmanaged_vol_name)

    @mock.patch(BASE_DRIVER_OBJ + "._rename_volume_object")
    def test_unmanage_error_propagates(self, mock_rename):
        vol, _ = self.new_fake_vol()
        self.assert_error_propagates([mock_rename],
                                     self.driver.unmanage,
                                     vol)

    @mock.patch(BASE_DRIVER_OBJ + "._rename_volume_object")
    def test_unmanage_with_deleted_volume(self, mock_rename):
        vol, vol_name = self.new_fake_vol()
        unmanaged_vol_name = vol_name + UNMANAGED_SUFFIX
        self.driver.unmanage(vol)
        mock_rename.assert_called_with(vol_name, unmanaged_vol_name)

    @mock.patch(DRIVER_PATH + ".LOG")
    @mock.patch(DRIVER_PATH + ".flasharray.VolumePatch")
    def test_unmanage_with_deleted_volume_error(self, mock_vol_patch,
                                                mock_logger):
        vol, vol_name = self.new_fake_vol()
        err_rsp = ErrorResponse(400, [DotNotation({'message':
                                      'does not exist'})], {})
        self.array.patch_volumes.return_value = err_rsp
        self.driver.unmanage(vol)
        mock_logger.warning.\
            assert_called_with('Unable to rename %(old_name)s, '
                               'error message: %(error)s',
                               {'old_name': f"{vol_name}",
                                'error': 'does not exist'})

    @mock.patch(BASE_DRIVER_OBJ + "._rename_volume_object")
    def test_manage_existing_snapshot(self, mock_rename):
        ref_name = PURE_SNAPSHOT['name']
        snap_ref = {'name': ref_name}
        snap, snap_name = self.new_fake_snap()
        vol_rsp = ValidResponse(200, None, 1,
                                [DotNotation(PURE_SNAPSHOT)], {})
        self.array.get_volumes.return_value = vol_rsp
        self.array.get_volume_snapshots.return_value = MPV
        self.driver.manage_existing_snapshot(snap, snap_ref)
        mock_rename.assert_called_once_with(ref_name, snap_name,
                                            raise_not_exist=True,
                                            snapshot=True)
        self.array.get_volumes.\
            assert_called_with(names=[PURE_SNAPSHOT['source']])

    @mock.patch(BASE_DRIVER_OBJ + "._rename_volume_object")
    def test_manage_existing_snapshot_multiple_snaps_on_volume(self,
                                                               mock_rename):
        ref_name = PURE_SNAPSHOT['name']
        snap_ref = {'name': ref_name}
        pure_snaps = [PURE_SNAPSHOT]
        snap, snap_name = self.new_fake_snap()
        for i in range(5):
            pure_snap = PURE_SNAPSHOT.copy()
            pure_snap['name'] += str(i)
            pure_snaps.append(DotNotation(pure_snap))
        vol_rsp = ValidResponse(200, None, 1,
                                pure_snaps, {})
        self.array.get_volumes.return_value = vol_rsp
        self.array.get_volume_snapshots.return_value = MPS
        self.driver.manage_existing_snapshot(snap, snap_ref)
        mock_rename.assert_called_once_with(ref_name, snap_name,
                                            raise_not_exist=True,
                                            snapshot=True)

    @mock.patch(BASE_DRIVER_OBJ + '._validate_manage_existing_ref')
    def test_manage_existing_snapshot_error_propagates(self, mock_validate):
        self.array.get_volumes.return_value = [PURE_SNAPSHOT]
        snap, _ = self.new_fake_snap()
        self.assert_error_propagates(
            [mock_validate],
            self.driver.manage_existing_snapshot,
            snap, {'name': PURE_SNAPSHOT['name']}
        )

    def test_manage_existing_snapshot_bad_ref(self):
        snap, _ = self.new_fake_snap()
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot,
                          snap, {'bad_key': 'bad_value'})

    def test_manage_existing_snapshot_empty_ref(self):
        snap, _ = self.new_fake_snap()
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot,
                          snap, {'name': ''})

    def test_manage_existing_snapshot_none_ref(self):
        snap, _ = self.new_fake_snap()
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot,
                          snap, {'name': None})

    def test_manage_existing_snapshot_volume_ref_not_exist(self):
        snap, _ = self.new_fake_snap()
        err_rsp = ErrorResponse(400, [DotNotation({'message':
                                      'does not exist'})], {})
        self.array.get_volumes.return_value = err_rsp
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot,
                          snap, {'name': 'non-existing-volume.snap1'})

    def test_manage_existing_snapshot_ref_not_exist(self):
        ref_name = PURE_SNAPSHOT['name'] + '-fake'
        snap_ref = {'name': ref_name}
        snap, _ = self.new_fake_snap()
        err_rsp = ErrorResponse(400, [DotNotation({'message':
                                      'does not exist'})], {})
        self.array.get_volumes.return_value = err_rsp
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot,
                          snap, snap_ref)

    def test_manage_existing_snapshot_get_size(self):
        ref_name = PURE_SNAPSHOT['name']
        snap_ref = {'name': ref_name}
        self.array.get_volumes.return_value = MPV
        self.array.get_volume_snapshots.return_value = MPS
        snap, _ = self.new_fake_snap()
        size = self.driver.manage_existing_snapshot_get_size(snap,
                                                             snap_ref)
        expected_size = 3.0
        self.assertEqual(expected_size, size)
        self.array.get_volumes.\
            assert_called_with(names=[PURE_SNAPSHOT['source']])

    @mock.patch(BASE_DRIVER_OBJ + '._validate_manage_existing_ref')
    def test_manage_existing_snapshot_get_size_error_propagates(self,
                                                                mock_valid):
        self.array.get_volumes.return_value = MPS
        snap, _ = self.new_fake_snap()
        self.assert_error_propagates(
            [mock_valid],
            self.driver.manage_existing_snapshot_get_size,
            snap, {'names': PURE_SNAPSHOT['name']}
        )

    def test_manage_existing_snapshot_get_size_bad_ref(self):
        snap, _ = self.new_fake_snap()
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot_get_size,
                          snap, {'bad_key': 'bad_value'})

    def test_manage_existing_snapshot_get_size_empty_ref(self):
        snap, _ = self.new_fake_snap()
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot_get_size,
                          snap, {'name': ''})

    def test_manage_existing_snapshot_get_size_none_ref(self):
        snap, _ = self.new_fake_snap()
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot_get_size,
                          snap, {'name': None})

    def test_manage_existing_snapshot_get_size_volume_ref_not_exist(self):
        snap, _ = self.new_fake_snap()
        err_rsp = ErrorResponse(400, [DotNotation({'message':
                                      'does not exist'})], {})
        self.array.get_volumes.return_value = err_rsp
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot_get_size,
                          snap, {'name': 'non-existing-volume.snap1'})

    @ddt.data(
        # 96 chars, will exceed allowable length
        'volume-1e5177e7-95e5-4a0f-b170-e45f4b469f6a-cinder.'
        'snapshot-253b2878-ec60-4793-ad19-e65496ec7aab',
        # short_name that will require no adjustment
        'volume-1e5177e7-cinder.snapshot-e65496ec7aab')
    @mock.patch(DRIVER_PATH + ".flasharray.VolumePatch")
    @mock.patch(BASE_DRIVER_OBJ + "._get_snap_name")
    def test_unmanage_snapshot(self, fake_name, mock_get_snap_name,
                               mock_vol_patch):
        snap, snap_name = self.new_fake_snap()
        mock_get_snap_name.return_value = fake_name
        mock_data = self.array.flasharray.VolumePatch(names='snap_name')
        mock_vol_patch.return_value = mock_data
        self.driver.unmanage_snapshot(snap)
        self.array.patch_volume_snapshots.\
            assert_called_with(names=[fake_name], volume_snapshot=mock_data)

    @mock.patch(BASE_DRIVER_OBJ + "._rename_volume_object")
    def test_unmanage_snapshot_error_propagates(self, mock_rename):
        snap, _ = self.new_fake_snap()
        self.assert_error_propagates([mock_rename],
                                     self.driver.unmanage_snapshot,
                                     snap)

    @mock.patch(DRIVER_PATH + ".LOG")
    def test_unmanage_snapshot_with_deleted_snapshot(self, mock_logger):
        snap, snap_name = self.new_fake_snap()
        self.driver.unmanage_snapshot(snap)
        err_rsp = ErrorResponse(400, [DotNotation({'message':
                                      'does not exist'})], {})
        self.array.patch_volume_snapshots.return_value = err_rsp
        self.driver.unmanage_snapshot(snap)
        mock_logger.warning.\
            assert_called_with('Unable to rename %(old_name)s, '
                               'error message: %(error)s',
                               {'old_name': f"{snap_name}",
                                'error': 'does not exist'})

    def _test_get_manageable_things(self,
                                    pure_objs=MPV,
                                    expected_refs=MPV_REFS.items,
                                    pure_hosts = CONN,
                                    cinder_objs=list(),
                                    is_snapshot=False):
        self.array.get_connections.return_value = pure_hosts
        self.array.get_volume_snapshots.return_value = pure_objs
        self.array.get_volumes.return_value = pure_objs
        marker = mock.Mock()
        limit = mock.Mock()
        offset = mock.Mock()
        sort_keys = mock.Mock()
        sort_dirs = mock.Mock()

        with mock.patch('cinder.volume.volume_utils.'
                        'paginate_entries_list') as mpage:
            if is_snapshot:
                test_func = self.driver.get_manageable_snapshots
            else:
                test_func = self.driver.get_manageable_volumes
            test_func(cinder_objs, marker, limit, offset, sort_keys, sort_dirs)
            mpage.assert_called_once_with(
                expected_refs,
                marker,
                limit,
                offset,
                sort_keys,
                sort_dirs
            )

    def test_get_manageable_volumes(self,):
        """Default success case.

        Given a list of pure volumes from the REST API, give back a list
        of volume references.
        """
        self._test_get_manageable_things()

    def test_get_manageable_volumes_connected_vol(self):
        """Make sure volumes connected to hosts are flagged as unsafe."""
        connected_vol = deepcopy(MPV.items)
        connected_vol[0]['name'] = 'xVol1'
        nexpected_refs = deepcopy(MPV_REFS.items)
        nexpected_refs[0]['reference'] = {'name': 'xVol1'}
        nexpected_refs[0]['safe_to_manage'] = False
        nexpected_refs[0]['reason_not_safe'] = 'Volume connected to host utest'
        del nexpected_refs[-2:]
        local_pure_objs = ValidResponse(200, None, 1,
                                        [DotNotation(connected_vol[0])], {})
        self._test_get_manageable_things(pure_objs=local_pure_objs,
                                         expected_refs=nexpected_refs)
        nexpected_refs[0]['safe_to_manage'] = True

    def test_get_manageable_volumes_already_managed(self):
        """Make sure volumes already owned by cinder are flagged as unsafe."""
        cinder_vol, cinder_vol_name = self.new_fake_vol()
        cinders_vols = [cinder_vol]

        # Have one of our vol names match up with the existing cinder volume
        purity_vols = deepcopy(MPV.items)
        purity_vols[0]['name'] = cinder_vol_name
        managed_expected_refs = deepcopy(MPV_REFS.items)
        managed_expected_refs[0]['reference'] = {'name': cinder_vol_name}
        managed_expected_refs[0]['safe_to_manage'] = False
        managed_expected_refs[0]['reason_not_safe'] = 'Volume already managed'
        managed_expected_refs[0]['cinder_id'] = cinder_vol.id
        local_pure_objs = ValidResponse(200, None, 3,
                                        [DotNotation(purity_vols[0]),
                                         DotNotation(purity_vols[1]),
                                         DotNotation(purity_vols[2])], {})
        self._test_get_manageable_things(pure_objs=local_pure_objs,
                                         expected_refs=managed_expected_refs,
                                         cinder_objs=cinders_vols)
        managed_expected_refs[0]['safe_to_manage'] = True

    def test_get_manageable_volumes_no_pure_volumes(self):
        """Expect no refs to be found if no volumes are on Purity."""
        self._test_get_manageable_things(pure_objs=ValidResponse(200, None,
                                                                 0, [], {}),
                                         expected_refs=[])

    def test_get_manageable_volumes_no_hosts(self):
        """Success case with no hosts on Purity."""
        self._test_get_manageable_things(pure_hosts=ValidResponse(200, None,
                                                                  0, [], {}))

    def test_get_manageable_snapshots(self):
        """Default success case.

        Given a list of pure snapshots from the REST API, give back a list
        of snapshot references.
        """
        self._test_get_manageable_things(
            pure_objs=MPS,
            expected_refs=MPS_REFS.items,
            pure_hosts=ValidResponse(200, None, 1,
                                     [DotNotation(CONNECTION_DATA)], {}),
            is_snapshot=True
        )

    def test_get_manageable_snapshots_already_managed(self):
        """Make sure snaps already owned by cinder are flagged as unsafe."""
        cinder_vol, _ = self.new_fake_vol()
        cinder_snap = fake_snapshot.fake_snapshot_obj(mock.MagicMock())
        cinder_snap.volume = cinder_vol
        cinder_snaps = [cinder_snap]
        purity_snaps = MPS.items.copy()
        purity_snaps[0]['name'] = 'volume-%s-cinder.snapshot-%s' % (
            cinder_vol.id, cinder_snap.id
        )

        expected_refs = MPS_REFS.items.copy()
        expected_refs[0]['reference'] = {'name': purity_snaps[0]['name']}
        expected_refs[0]['safe_to_manage'] = False
        expected_refs[0]['reason_not_safe'] = 'Snapshot already managed.'
        expected_refs[0]['cinder_id'] = cinder_snap.id

        self._test_get_manageable_things(
            pure_objs=ValidResponse(200, None, 3,
                                    [DotNotation(purity_snaps[0]),
                                     DotNotation(purity_snaps[1]),
                                     DotNotation(purity_snaps[2])], {}),
            expected_refs=expected_refs,
            cinder_objs=cinder_snaps,
            is_snapshot=True
        )

    def test_get_manageable_snapshots_no_pure_snapshots(self):
        """Expect no refs to be found if no snapshots are on Purity."""
        self._test_get_manageable_things(pure_objs=ValidResponse(200, None,
                                                                 0, [], {}),
                                         pure_hosts=ValidResponse(200, None,
                                                                  0, [], {}),
                                         expected_refs=[],
                                         is_snapshot=True)

    @ddt.data(
        # No replication change, non-replicated
        dict(
            current_spec={
                'replication_enabled': '<is> false',
            },
            new_spec={
                'replication_type': '<in> async',
                'replication_enabled': '<is> false',
            },
            expected_model_update=None,
            expected_did_retype=True,
            expected_add_to_group=False,
            expected_remove_from_pgroup=False,
        ),
        # No replication change, async to async
        dict(
            current_spec={
                'replication_type': '<in> async',
                'replication_enabled': '<is> true',
                'other_spec': 'blah'
            },
            new_spec={
                'replication_type': '<in> async',
                'replication_enabled': '<is> true',
                'other_spec': 'something new'
            },
            expected_model_update=None,
            expected_did_retype=True,
            expected_add_to_group=False,
            expected_remove_from_pgroup=False,
        ),
        # No replication change, sync to sync
        dict(
            current_spec={
                'replication_type': '<in> sync',
                'replication_enabled': '<is> true',
                'other_spec': 'blah'
            },
            new_spec={
                'replication_type': '<in> sync',
                'replication_enabled': '<is> true',
                'other_spec': 'something new'
            },
            expected_model_update=None,
            expected_did_retype=True,
            expected_add_to_group=False,
            expected_remove_from_pgroup=False,
        ),
        # Turn on async rep
        dict(
            current_spec={
                'replication_enabled': '<is> false',
            },
            new_spec={
                'replication_type': '<in> async',
                'replication_enabled': '<is> true',
            },
            expected_model_update={
                "replication_status": fields.ReplicationStatus.ENABLED
            },
            expected_did_retype=True,
            expected_add_to_group=True,
            expected_remove_from_pgroup=False,
        ),
        # Turn off async rep
        dict(
            current_spec={
                'replication_type': '<in> async',
                'replication_enabled': '<is> true',
            },
            new_spec={
                'replication_type': '<in> async',
                'replication_enabled': '<is> false',
            },

            expected_model_update={
                "replication_status": fields.ReplicationStatus.DISABLED
            },
            expected_did_retype=True,
            expected_add_to_group=False,
            expected_remove_from_pgroup=True,
        ),
        # Turn on sync rep
        dict(
            current_spec={
                'replication_enabled': '<is> false',
            },
            new_spec={
                'replication_type': '<in> sync',
                'replication_enabled': '<is> true',
            },
            expected_model_update=None,
            # cannot retype via fast path to/from sync rep
            expected_did_retype=False,
            expected_add_to_group=False,
            expected_remove_from_pgroup=False,
        ),
        # Turn on trisync rep
        dict(
            current_spec={
                'replication_enabled': '<is> false',
            },
            new_spec={
                'replication_type': '<in> trisync',
                'replication_enabled': '<is> true',
            },
            expected_model_update=None,
            # cannot retype via fast path to/from sync rep
            expected_did_retype=False,
            expected_add_to_group=False,
            expected_remove_from_pgroup=False,
        ),
        # Turn off sync rep
        dict(
            current_spec={
                'replication_type': '<in> sync',
                'replication_enabled': '<is> true',
            },
            new_spec={
                'replication_type': '<in> sync',
                'replication_enabled': '<is> false',
            },
            expected_model_update=None,
            # cannot retype via fast path to/from sync rep
            expected_did_retype=False,
            expected_add_to_group=False,
            expected_remove_from_pgroup=False,
        ),
        # Turn off trisync rep
        dict(
            current_spec={
                'replication_type': '<in> trisync',
                'replication_enabled': '<is> true',
            },
            new_spec={
                'replication_type': '<in> trisync',
                'replication_enabled': '<is> false',
            },
            expected_model_update=None,
            # cannot retype via fast path to/from sync rep
            expected_did_retype=False,
            expected_add_to_group=False,
            expected_remove_from_pgroup=False,
        ),
        # Change from async to sync rep
        dict(
            current_spec={
                'replication_type': '<in> async',
                'replication_enabled': '<is> true',
            },
            new_spec={
                'replication_type': '<in> sync',
                'replication_enabled': '<is> true',
            },
            expected_model_update=None,
            # cannot retype via fast path to/from sync rep
            expected_did_retype=False,
            expected_add_to_group=False,
            expected_remove_from_pgroup=False,
        ),
        # Change from async to trisync rep
        dict(
            current_spec={
                'replication_type': '<in> async',
                'replication_enabled': '<is> true',
            },
            new_spec={
                'replication_type': '<in> trisync',
                'replication_enabled': '<is> true',
            },
            expected_model_update=None,
            # cannot retype via fast path to/from sync rep
            expected_did_retype=False,
            expected_add_to_group=False,
            expected_remove_from_pgroup=False,
        ),
        # Change from sync to async rep
        dict(
            current_spec={
                'replication_type': '<in> sync',
                'replication_enabled': '<is> true',
            },
            new_spec={
                'replication_type': '<in> async',
                'replication_enabled': '<is> true',
            },
            expected_model_update=None,
            # cannot retype via fast path to/from sync rep
            expected_did_retype=False,
            expected_add_to_group=False,
            expected_remove_from_pgroup=False,
        ),
        # Change from trisync to async rep
        dict(
            current_spec={
                'replication_type': '<in> trisync',
                'replication_enabled': '<is> true',
            },
            new_spec={
                'replication_type': '<in> async',
                'replication_enabled': '<is> true',
            },
            expected_model_update=None,
            # cannot retype via fast path to/from trisync rep
            expected_did_retype=False,
            expected_add_to_group=False,
            expected_remove_from_pgroup=False,
        ),
        # Change from trisync to sync rep
        dict(
            current_spec={
                'replication_type': '<in> trisync',
                'replication_enabled': '<is> true',
            },
            new_spec={
                'replication_type': '<in> sync',
                'replication_enabled': '<is> true',
            },
            expected_model_update=None,
            expected_did_retype=True,
            expected_add_to_group=False,
            expected_remove_from_pgroup=True,
        ),
        # Change from sync to trisync rep
        dict(
            current_spec={
                'replication_type': '<in> sync',
                'replication_enabled': '<is> true',
            },
            new_spec={
                'replication_type': '<in> trisync',
                'replication_enabled': '<is> true',
            },
            expected_model_update=None,
            expected_did_retype=True,
            expected_add_to_group=True,
            expected_remove_from_pgroup=False,
        ),
    )
    @ddt.unpack
    def test_retype_replication(self,
                                current_spec,
                                new_spec,
                                expected_model_update,
                                expected_did_retype,
                                expected_add_to_group,
                                expected_remove_from_pgroup):
        ctxt = context.get_admin_context()
        vol, vol_name = self.new_fake_vol(type_extra_specs=current_spec)
        new_type = fake_volume.fake_volume_type_obj(ctxt)
        new_type.extra_specs = new_spec
        get_voltype = "cinder.objects.volume_type.VolumeType.get_by_name_or_id"
        with mock.patch(get_voltype) as mock_get_vol_type:
            mock_get_vol_type.return_value = new_type
            did_retype, model_update = self.driver.retype(
                ctxt,
                vol,
                {"id": new_type.id, "extra_specs": new_spec},
                None,  # ignored by driver
                None,  # ignored by driver
            )

        self.assertEqual(expected_did_retype, did_retype)
        self.assertEqual(expected_model_update, model_update)
        if expected_add_to_group:
            if "trisync" not in new_type.extra_specs["replication_type"]:
                self.array.post_protection_groups_volumes.\
                    assert_called_once_with(group_names =
                                            [self.driver._replication_pg_name],
                                            member_names = [vol_name])
        if expected_remove_from_pgroup:
            if "trisync" not in current_spec["replication_type"]:
                self.array.delete_protection_groups_volumes.\
                    assert_called_once_with(group_names =
                                            [self.driver._replication_pg_name],
                                            member_names = [vol_name])

    @ddt.data(
        dict(
            specs={
                'replication_type': '<in> async',
                'replication_enabled': '<is> true',
            },
            expected_repl_type='async'
        ),
        dict(
            specs={
                'replication_type': '<in> sync',
                'replication_enabled': '<is> true',
            },
            expected_repl_type='sync'
        ),
        dict(
            specs={
                'replication_type': '<in> trisync',
                'replication_enabled': '<is> true',
            },
            expected_repl_type='trisync'
        ),
        dict(
            specs={
                'replication_type': '<in> async',
                'replication_enabled': '<is> false',
            },
            expected_repl_type=None
        ),
        dict(
            specs={
                'replication_type': '<in> sync',
                'replication_enabled': '<is> false',
            },
            expected_repl_type=None
        ),
        dict(
            specs={
                'not_replication_stuff': 'foo',
                'replication_enabled': '<is> true',
            },
            expected_repl_type='async'
        ),
        dict(
            specs=None,
            expected_repl_type=None
        ),
        dict(
            specs={
                'replication_type': '<in> super-turbo-repl-mode',
                'replication_enabled': '<is> true',
            },
            expected_repl_type=None
        )
    )
    @ddt.unpack
    def test_get_replication_type_from_vol_type(self, specs,
                                                expected_repl_type):
        voltype = fake_volume.fake_volume_type_obj(mock.MagicMock())
        voltype.extra_specs = specs
        actual_type = self.driver._get_replication_type_from_vol_type(voltype)
        self.assertEqual(expected_repl_type, actual_type)

    @mock.patch(DRIVER_PATH + ".LOG")
    def test_does_pgroup_exist_not_exists(self, mock_logger):
        err_rsp = ErrorResponse(400, [DotNotation({'message':
                                      'does not exist'})], {})
        self.array.get_protection_groups.return_value = err_rsp
        exists = self.driver._does_pgroup_exist(self.array, "some_pgroup")
        self.assertFalse(exists)

    def test_does_pgroup_exist_exists(self):
        valid_rsp = ValidResponse(200, None, 1,
                                  [DotNotation(PGROUP_ON_TARGET_NOT_ALLOWED)],
                                  {})
        self.array.get_protection_groups.return_value = valid_rsp
        exists = self.driver._does_pgroup_exist(self.array, "some_pgroup")
        self.assertTrue(exists)

    def test_does_pgroup_exist_error_propagates(self):
        err_rsp = ErrorResponse(400, [DotNotation({'message':
                                      'does not exist'})], {})
        self.array.get_protection_groups.return_value = err_rsp
        self.assert_error_propagates([self.array.get_protection_groups],
                                     self.driver._does_pgroup_exist,
                                     self.array,
                                     "some_pgroup")

    @mock.patch(BASE_DRIVER_OBJ + "._does_pgroup_exist")
    def test_wait_until_target_group_setting_propagates_ready(self,
                                                              mock_exists):
        mock_exists.return_value = True
        self.driver._wait_until_target_group_setting_propagates(
            self.array,
            "some_pgroup"
        )

    @mock.patch(BASE_DRIVER_OBJ + "._does_pgroup_exist")
    def test_wait_until_target_group_setting_propagates_not_ready(self,
                                                                  mock_exists):
        mock_exists.return_value = False
        self.assertRaises(
            pure.PureDriverException,
            self.driver._wait_until_target_group_setting_propagates,
            self.array,
            "some_pgroup"
        )

    def test_wait_until_source_array_allowed_ready(self):
        pgtgt = ValidResponse(200, None, 1,
                              [DotNotation(PGROUP_ON_TARGET_ALLOWED)],
                              {})
        self.array.get_protection_groups_targets.return_value = \
            pgtgt
        self.driver._wait_until_source_array_allowed(
            self.array,
            "array1:replicated_pgroup",)

    def test_wait_until_source_array_allowed_not_ready(self):
        pgtgt = ValidResponse(200, None, 1,
                              [DotNotation(PGROUP_ON_TARGET_NOT_ALLOWED)],
                              {})
        self.array.get_protection_groups_targets.return_value = \
            pgtgt
        self.assertRaises(
            pure.PureDriverException,
            self.driver._wait_until_source_array_allowed,
            self.array,
            "some_pgroup",
        )

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_create_volume_replicated_async(self, mock_get_volume_type):
        repl_extra_specs = {
            'replication_type': '<in> async',
            'replication_enabled': '<is> true',
        }
        vol, vol_name = self.new_fake_vol(spec={"size": 2},
                                          type_extra_specs=repl_extra_specs)
        mock_get_volume_type.return_value = vol.volume_type

        self.driver.create_volume(vol)

        self.array.post_volumes.assert_called()
        self.array.post_protection_groups_volumes.assert_called_with(
            group_names=[REPLICATION_PROTECTION_GROUP],
            member_names=[vol["name"] + "-cinder"])

    @mock.patch(DRIVER_PATH + ".flasharray.VolumePost")
    @mock.patch.object(volume_types, 'get_volume_type')
    def test_create_volume_replicated_sync(self, mock_get_volume_type,
                                           mock_fa):
        repl_extra_specs = {
            'replication_type': '<in> sync',
            'replication_enabled': '<is> true',
        }
        vol, vol_name = self.new_fake_vol(spec={"size": 2},
                                          type_extra_specs=repl_extra_specs)

        mock_get_volume_type.return_value = vol.volume_type
        mock_data = self.array.flasharray.VolumePost(provisioned=2147483648)
        mock_fa.return_value = mock_data
        self.driver.create_volume(vol)

        self.array.post_volumes.assert_called_with(names=[vol_name],
                                                   with_default_protection=
                                                   False,
                                                   volume=mock_data)

    def test_find_async_failover_target_no_repl_targets(self):
        self.driver._replication_target_arrays = []
        self.assertRaises(pure.PureDriverException,
                          self.driver._find_async_failover_target)

    @mock.patch(BASE_DRIVER_OBJ + '._get_latest_replicated_pg_snap')
    def test_find_async_failover_target(self, mock_get_snap):
        mock_backend_1 = mock.Mock()
        mock_backend_1.replication_type = 'async'
        mock_backend_2 = mock.Mock()
        mock_backend_2.replication_type = 'async'
        self.driver._replication_target_arrays = [mock_backend_1,
                                                  mock_backend_2]
        mock_get_snap.return_value = REPLICATED_PGSNAPS[0]

        array, pg_snap = self.driver._find_async_failover_target()
        self.assertEqual(mock_backend_1, array)
        self.assertEqual(REPLICATED_PGSNAPS[0], pg_snap)

    @mock.patch(BASE_DRIVER_OBJ + '._get_latest_replicated_pg_snap')
    def test_find_async_failover_target_missing_pgsnap(
            self, mock_get_snap):
        mock_backend_1 = mock.Mock()
        mock_backend_1.replication_type = 'async'
        mock_backend_2 = mock.Mock()
        mock_backend_2.replication_type = 'async'
        self.driver._replication_target_arrays = [mock_backend_1,
                                                  mock_backend_2]
        mock_get_snap.side_effect = [None, REPLICATED_PGSNAPS[0]]

        array, pg_snap = self.driver._find_async_failover_target()
        self.assertEqual(mock_backend_2, array)
        self.assertEqual(REPLICATED_PGSNAPS[0], pg_snap)

    @mock.patch(BASE_DRIVER_OBJ + '._get_latest_replicated_pg_snap')
    def test_find_async_failover_target_no_pgsnap(
            self, mock_get_snap):
        mock_backend = mock.Mock()
        mock_backend.replication_type = 'async'
        self.driver._replication_target_arrays = [mock_backend]
        mock_get_snap.return_value = None

        self.assertRaises(pure.PureDriverException,
                          self.driver._find_async_failover_target)

    @mock.patch(BASE_DRIVER_OBJ + '._get_latest_replicated_pg_snap')
    def test_find_async_failover_target_error_propagates_no_secondary(
            self, mock_get_snap):
        mock_backend = mock.Mock()
        mock_backend.replication_type = 'async'
        self.driver._replication_target_arrays = [mock_backend]
        self.assert_error_propagates(
            [mock_get_snap],
            self.driver._find_async_failover_target
        )

    def test_find_sync_failover_target_success(self):
        secondary = mock.MagicMock()
        self.driver._active_cluster_target_arrays = [secondary]
        secondary.get_pods.return_value = CINDER_POD
        secondary.array_id = CINDER_POD.items[0]['arrays'][1]['id']

        actual_secondary = self.driver._find_sync_failover_target()
        self.assertEqual(secondary, actual_secondary)

    def test_find_sync_failover_target_no_ac_arrays(self):
        self.driver._active_cluster_target_arrays = []
        actual_secondary = self.driver._find_sync_failover_target()
        self.assertIsNone(actual_secondary)

    def test_find_sync_failover_target_fail_to_get_pod(self):
        secondary = mock.MagicMock()
        self.driver._active_cluster_target_arrays = [secondary]
        secondary.array_id = CINDER_POD.items[0]['arrays'][1]['id']

        actual_secondary = self.driver._find_sync_failover_target()
        self.assertIsNone(actual_secondary)

    def test_find_sync_failover_target_pod_status_error(self):
        secondary = mock.MagicMock()
        self.driver._active_cluster_target_arrays = [secondary]
        modified_array = deepcopy(array_2)
        modified_array['status'] = 'error'
        POD_WITH_ERR = dict(arrays = [array_1, modified_array],
                            source = None,
                            name= 'cinder-pod')
        secondary.get_pod.\
            return_value = ValidResponse(200, None, 1,
                                         [DotNotation(POD_WITH_ERR)], {})
        secondary.array_id = POD_WITH_ERR['arrays'][1]['id']

        actual_secondary = self.driver._find_sync_failover_target()
        self.assertIsNone(actual_secondary)

    def test_enable_async_replication_if_needed_success(self):
        repl_extra_specs = {
            'replication_type': '<in> async',
            'replication_enabled': '<is> true',
        }
        vol, vol_name = self.new_fake_vol(type_extra_specs=repl_extra_specs)
        self.driver._enable_async_replication_if_needed(self.array, vol)

        self.array.post_protection_groups_volumes.assert_called_with(
            group_names=[self.driver._replication_pg_name],
            member_names=[vol_name]
        )

    def test_enable_async_replication_if_needed_not_repl_type(self):
        vol_type = fake_volume.fake_volume_type_obj(mock.MagicMock())
        vol_obj = fake_volume.fake_volume_obj(mock.MagicMock())
        with mock.patch('cinder.objects.VolumeType.get_by_id') as mock_type:
            mock_type.return_value = vol_type
            self.driver._enable_async_replication_if_needed(self.array,
                                                            vol_obj)
        self.assertFalse(self.array.set_pgroup.called)

    def test_enable_async_replication_if_needed_sync_skip(self):
        repl_extra_specs = {
            'replication_type': '<in> sync',
            'replication_enabled': '<is> true',
        }
        vol, vol_name = self.new_fake_vol(type_extra_specs=repl_extra_specs)
        self.driver._enable_async_replication_if_needed(self.array, vol)
        self.array.post_protection_groups_volumes.assert_not_called()

    def test_enable_async_replication_if_needed_error_propagates(self):
        repl_extra_specs = {
            'replication_type': '<in> async',
            'replication_enabled': '<is> true',
        }
        vol, _ = self.new_fake_vol(type_extra_specs=repl_extra_specs)
        self.driver._enable_async_replication_if_needed(self.array, vol)
        self.assert_error_propagates(
            [self.array.post_protection_groups_volumes],
            self.driver._enable_async_replication,
            self.array, vol
        )

    @mock.patch(DRIVER_PATH + ".flasharray.VolumePost")
    @mock.patch(BASE_DRIVER_OBJ + '._get_flasharray')
    @mock.patch(BASE_DRIVER_OBJ + '._find_async_failover_target')
    def test_failover_async(self,
                            mock_find_failover_target,
                            mock_get_array,
                            mock_vol):
        secondary_device_id = 'foo'
        self.async_array2.backend_id = secondary_device_id
        self.driver._replication_target_arrays = [self.async_array2]
        pgout = ValidResponse(200, None, 1,
                              [DotNotation(REPLICATED_PGSNAPS[0]),
                               DotNotation(REPLICATED_PGSNAPS[1]),
                               DotNotation(REPLICATED_PGSNAPS[2])], {})
        volout = ValidResponse(200, None, 1,
                               [DotNotation(REPLICATED_VOLUME_SNAPS[0]),
                                DotNotation(REPLICATED_VOLUME_SNAPS[1]),
                                DotNotation(REPLICATED_VOLUME_SNAPS[2])], {})
        self.async_array2.get_volume_snapshots.return_value = volout
        array2 = mock.Mock()
        array2.backend_id = secondary_device_id
        array2.array_name = GET_ARRAY_SECONDARY['name']
        array2.array_id = GET_ARRAY_SECONDARY['id']
        mock_get_array.return_value = array2
        target_array = self.async_array2
        target_array.copy_volume = mock.Mock()

        mock_find_failover_target.return_value = (
            target_array,
            pgout.items[0],
        )

        array2.get_volume.return_value = volout.items
        context = mock.MagicMock()
        new_active_id, volume_updates, __ = self.driver.failover(
            context,
            REPLICATED_VOLUME_OBJS,
            None,
            []
        )

        self.assertEqual(secondary_device_id, new_active_id)
        expected_updates = [
            {
                'updates': {
                    'replication_status': fields.ReplicationStatus.FAILED_OVER
                },
                'volume_id': '1e5177e7-95e5-4a0f-b170-e45f4b469f6a'
            },
            {
                'updates': {
                    'replication_status': fields.ReplicationStatus.FAILED_OVER
                },
                'volume_id': '43a09914-e495-475f-b862-0bda3c8918e4'
            },
            {
                'updates': {
                    'replication_status': fields.ReplicationStatus.FAILED_OVER
                },
                'volume_id': '1b1cf149-219c-44ac-aee3-13121a7f86a7'
            }
        ]
        self.assertEqual(expected_updates, volume_updates)

        calls = []
        for snap in REPLICATED_VOLUME_SNAPS:
            vol_name = snap['name'].split('.')[-1]
            calls.append(mock.call(
                with_default_protection=False,
                names=[vol_name],
                volume=mock_vol(),
                overwrite=True
            ))
        target_array.post_volumes.assert_has_calls(calls, any_order=True)

    @mock.patch(BASE_DRIVER_OBJ + '._find_sync_failover_target')
    def test_failover_sync(self, mock_find_failover_target):
        secondary_device_id = 'foo'
        mock_secondary = mock.MagicMock()
        mock_secondary.backend_id = secondary_device_id
        mock_secondary.replication_type = 'sync'
        self.driver._replication_target_arrays = [mock_secondary]
        mock_find_failover_target.return_value = mock_secondary
        rpod = 'cinder-pod::volume-1e5177e7-95e5-4a0f-b170-e45f4b469f6a-cinder'
        repvol = deepcopy(REPLICATED_VOLUME_SNAPS[1])
        repvol['name'] = rpod
        volout = ValidResponse(200, None, 1,
                               [DotNotation(REPLICATED_VOLUME_SNAPS[0]),
                                DotNotation(repvol),
                                DotNotation(REPLICATED_VOLUME_SNAPS[2])], {})
        context = mock.MagicMock()

        sync_repl_extra_specs = {
            'replication_type': '<in> sync',
            'replication_enabled': '<is> true',
        }
        sync_replicated_vol, sync_replicated_vol_name = self.new_fake_vol(
            type_extra_specs=sync_repl_extra_specs,
            spec={'id': fake.VOLUME_ID}
        )
        async_repl_extra_specs = {
            'replication_type': '<in> async',
            'replication_enabled': '<is> true',
        }
        async_replicated_vol, _ = self.new_fake_vol(
            type_extra_specs=async_repl_extra_specs,
            spec={'id': fake.VOLUME2_ID}
        )
        not_replicated_vol, _ = self.new_fake_vol(
            spec={'id': fake.VOLUME3_ID}
        )
        not_replicated_vol2, _ = self.new_fake_vol(
            spec={'id': fake.VOLUME4_ID}
        )

        mock_secondary.get_connections.return_value = [
            {"name": sync_replicated_vol_name}
        ]

        mock_secondary.get_volumes.return_value = volout
        new_active_id, volume_updates, __ = self.driver.failover(
            context,
            [
                not_replicated_vol,
                async_replicated_vol,
                sync_replicated_vol,
                not_replicated_vol2
            ],
            None,
            []
        )

        self.assertEqual(secondary_device_id, new_active_id)

        # only expect the sync rep'd vol to make it through the failover
        expected_updates = [
            {
                'updates': {
                    'status': fields.VolumeStatus.ERROR
                },
                'volume_id': not_replicated_vol.id
            },
            {
                'updates': {
                    'status': fields.VolumeStatus.ERROR
                },
                'volume_id': async_replicated_vol.id
            },
            {
                'updates': {
                    'replication_status': fields.ReplicationStatus.FAILED_OVER
                },
                'volume_id': sync_replicated_vol.id
            },
            {
                'updates': {
                    'status': fields.VolumeStatus.ERROR
                },
                'volume_id': not_replicated_vol2.id
            },
        ]
        self.assertEqual(expected_updates, volume_updates)

    @mock.patch(BASE_DRIVER_OBJ + '._get_flasharray')
    @mock.patch(BASE_DRIVER_OBJ + '._find_async_failover_target')
    def test_async_failover_error_propagates(self, mock_find_failover_target,
                                             mock_get_array):
        pgout = ValidResponse(200, None, 1,
                              [DotNotation(REPLICATED_PGSNAPS[0]),
                               DotNotation(REPLICATED_PGSNAPS[1]),
                               DotNotation(REPLICATED_PGSNAPS[2])], {})
        volout = ValidResponse(200, None, 1,
                               [DotNotation(REPLICATED_VOLUME_SNAPS[0]),
                                DotNotation(REPLICATED_VOLUME_SNAPS[1]),
                                DotNotation(REPLICATED_VOLUME_SNAPS[2])], {})
        mock_find_failover_target.return_value = (
            self.async_array2,
            pgout.items[0]
        )
        self.async_array2.get_volume_snapshots.return_value = volout
        array2 = mock.Mock()
        array2.array_name = GET_ARRAY_SECONDARY['name']
        array2.array_id = GET_ARRAY_SECONDARY['id']
        mock_get_array.return_value = array2

        array2.get_volume.return_value = volout.items
        self.assert_error_propagates(
            [mock_find_failover_target,
             self.async_array2.get_volume_snapshots],
            self.driver.failover,
            mock.Mock(), REPLICATED_VOLUME_OBJS, None
        )

    def test_disable_replication_success(self):
        vol, vol_name = self.new_fake_vol()
        self.driver._disable_async_replication(vol)
        self.array.delete_protection_groups_volumes.assert_called_with(
            group_names=[self.driver._replication_pg_name],
            member_names=[vol_name]
        )

    def test_disable_replication_error_propagates(self):
        vol, _ = self.new_fake_vol()
        self.assert_error_propagates(
            [self.array.delete_protection_groups_volumes],
            self.driver._disable_async_replication,
            vol
        )

    @mock.patch(DRIVER_PATH + ".LOG")
    def test_disable_replication_already_disabled(self, mock_logger):
        vol, vol_name = self.new_fake_vol()
        err_rsp = ErrorResponse(400, [DotNotation({'message':
                                      'could not be found'})], {})
        self.array.delete_protection_groups_volumes.return_value = err_rsp
        self.driver._disable_async_replication(vol)
        self.array.delete_protection_groups_volumes.assert_called_with(
            group_names=[self.driver._replication_pg_name],
            member_names=[vol_name]
        )
        mock_logger.warning.\
            assert_called_with('Disable replication on volume failed:'
                               ' already disabled: %s', 'could not be found')

    def test_get_flasharray_verify_https(self):
        san_ip = '1.2.3.4'
        api_token = 'abcdef'
        cert_path = '/my/ssl/certs'
        self.flasharray.Client.return_value = mock.MagicMock()
        self.flasharray.Client().get_arrays.return_value = \
            self.fake_get_array()
        self.driver._get_flasharray(san_ip,
                                    api_token,
                                    verify_ssl=True,
                                    ssl_cert_path=cert_path)
        self.flasharray.Client.assert_called_with(
            target=san_ip,
            api_token=api_token,
            verify_ssl=True,
            ssl_cert=cert_path,
            user_agent=self.driver._user_agent,
        )

    def test_get_wwn(self):
        vol = {'created': '2019-01-28T14:16:54Z',
               'name': 'volume-fdc9892f-5af0-47c8-9d4a-5167ac29dc98-cinder',
               'serial': '9714B5CB91634C470002B2C8',
               'size': 3221225472,
               'source': 'volume-a366b1ba-ec27-4ca3-9051-c301b75bc778-cinder'}
        self.array.get_volumes.return_value = ValidResponse(200, None, 1,
                                                            [DotNotation
                                                             (vol)], {})
        returned_wwn = self.driver._get_wwn(vol['name'])
        expected_wwn = '3624a93709714b5cb91634c470002b2c8'
        self.assertEqual(expected_wwn, returned_wwn)

    @mock.patch.object(qos_specs, "get_qos_specs")
    def test_get_qos_settings_from_specs_id(self, mock_get_qos_specs):
        ctxt = context.get_admin_context()
        qos = qos_specs.create(ctxt, "qos-iops-bws", QOS_IOPS_BWS)
        mock_get_qos_specs.return_value = qos

        voltype = fake_volume.fake_volume_type_obj(mock.MagicMock())
        voltype.qos_specs_id = qos.id
        voltype.extra_specs = QOS_IOPS_BWS_2  # test override extra_specs

        specs = self.driver._get_qos_settings(voltype)
        self.assertEqual(specs["maxIOPS"],
                         int(QOS_IOPS_BWS["maxIOPS"]))
        self.assertEqual(specs["maxBWS"],
                         int(QOS_IOPS_BWS["maxBWS"]) * 1024 * 1024)

    def test_get_qos_settings_from_extra_specs(self):
        voltype = fake_volume.fake_volume_type_obj(mock.MagicMock())
        voltype.extra_specs = QOS_IOPS_BWS

        specs = self.driver._get_qos_settings(voltype)
        self.assertEqual(specs["maxIOPS"],
                         int(QOS_IOPS_BWS["maxIOPS"]))
        self.assertEqual(specs["maxBWS"],
                         int(QOS_IOPS_BWS["maxBWS"]) * 1024 * 1024)

    def test_get_qos_settings_set_zeros(self):
        voltype = fake_volume.fake_volume_type_obj(mock.MagicMock())
        voltype.extra_specs = QOS_ZEROS
        specs = self.driver._get_qos_settings(voltype)
        self.assertEqual(specs["maxIOPS"], 0)
        self.assertEqual(specs["maxBWS"], 0)

    def test_get_qos_settings_set_one(self):
        voltype = fake_volume.fake_volume_type_obj(mock.MagicMock())
        voltype.extra_specs = QOS_IOPS
        specs = self.driver._get_qos_settings(voltype)
        self.assertEqual(specs["maxIOPS"], int(QOS_IOPS["maxIOPS"]))
        self.assertEqual(specs["maxBWS"], 0)

        voltype.extra_specs = QOS_BWS
        specs = self.driver._get_qos_settings(voltype)
        self.assertEqual(specs["maxIOPS"], 0)
        self.assertEqual(specs["maxBWS"],
                         int(QOS_BWS["maxBWS"]) * 1024 * 1024)

    def test_get_qos_settings_invalid(self):
        voltype = fake_volume.fake_volume_type_obj(mock.MagicMock())
        voltype.extra_specs = QOS_INVALID
        self.assertRaises(exception.InvalidQoSSpecs,
                          self.driver._get_qos_settings,
                          voltype)

    @mock.patch(BASE_DRIVER_OBJ + ".create_with_qos")
    @mock.patch(BASE_DRIVER_OBJ + "._add_to_group_if_needed")
    @mock.patch(BASE_DRIVER_OBJ + "._get_replication_type_from_vol_type")
    @mock.patch.object(qos_specs, "get_qos_specs")
    @mock.patch.object(volume_types, 'get_volume_type')
    def test_create_volume_with_qos(self, mock_get_volume_type,
                                    mock_get_qos_specs,
                                    mock_get_repl_type,
                                    mock_add_to_group,
                                    mock_create_qos):
        ctxt = context.get_admin_context()
        qos = qos_specs.create(ctxt, "qos-iops-bws", dict(QOS_IOPS_BWS))
        vol, vol_name = self.new_fake_vol(spec={"size": 1},
                                          type_qos_specs_id=qos.id)

        mock_get_volume_type.return_value = vol.volume_type
        mock_get_qos_specs.return_value = qos
        mock_get_repl_type.return_value = None

        self.driver.create_volume(vol)
        self.driver.create_with_qos.assert_called_with(self.array, vol_name,
                                                       vol["size"] * 1024
                                                       * 1024 * 1024,
                                                       {'maxIOPS': 100,
                                                        'maxBWS': 1048576})
        mock_add_to_group.assert_called_once_with(vol,
                                                  vol_name)
        self.assert_error_propagates([mock_create_qos],
                                     self.driver.create_volume, vol)

    @mock.patch(BASE_DRIVER_OBJ + ".set_qos")
    @mock.patch(DRIVER_PATH + ".flasharray.VolumePost")
    @mock.patch(BASE_DRIVER_OBJ + "._add_to_group_if_needed")
    @mock.patch(BASE_DRIVER_OBJ + "._get_replication_type_from_vol_type")
    @mock.patch.object(qos_specs, "get_qos_specs")
    @mock.patch.object(volume_types, 'get_volume_type')
    def test_create_volume_from_snapshot_with_qos(self, mock_get_volume_type,
                                                  mock_get_qos_specs,
                                                  mock_get_repl_type,
                                                  mock_add_to_group,
                                                  mock_fa, mock_qos):
        ctxt = context.get_admin_context()
        srcvol, _ = self.new_fake_vol()
        snap = fake_snapshot.fake_snapshot_obj(mock.MagicMock(), volume=srcvol)
        qos = qos_specs.create(ctxt, "qos-iops-bws", QOS_IOPS_BWS)
        vol, vol_name = self.new_fake_vol(set_provider_id=False,
                                          type_qos_specs_id=qos.id)
        mock_data = self.array.flasharray.VolumePost(names=[vol_name],
                                                     source=pure.
                                                     flasharray.
                                                     Reference(name=vol_name),
                                                     name=vol_name,
                                                     qos={'maxIOPS': 100,
                                                     'maxBWS': 1048576})
        mock_fa.return_value = mock_data

        mock_get_volume_type.return_value = vol.volume_type
        mock_get_qos_specs.return_value = qos
        mock_get_repl_type.return_value = None

        self.driver.create_volume_from_snapshot(vol, snap)
        self.array.post_volumes.assert_called_with(names=[vol_name],
                                                   with_default_protection=
                                                   False,
                                                   volume=mock_data)
        self.driver.set_qos.assert_called_with(self.array, vol_name,
                                               {'maxIOPS': 100,
                                                'maxBWS': 1048576})
        self.assertFalse(self.array.extend_volume.called)
        mock_add_to_group.assert_called_once_with(vol, vol_name)
        self.assert_error_propagates(
            [self.array.post_volumes],
            self.driver.create_volume_from_snapshot, vol, snap)
        self.assertFalse(self.array.extend_volume.called)

    @mock.patch(BASE_DRIVER_OBJ + ".set_qos")
    @mock.patch.object(qos_specs, "get_qos_specs")
    @mock.patch.object(volume_types, 'get_volume_type')
    def test_manage_existing_with_qos(self, mock_get_volume_type,
                                      mock_get_qos_specs,
                                      mock_qos):
        ctxt = context.get_admin_context()
        ref_name = 'vol1'
        volume_ref = {'name': ref_name}
        qos = qos_specs.create(ctxt, "qos-iops-bws", QOS_IOPS_BWS)
        vol, vol_name = self.new_fake_vol(set_provider_id=False,
                                          type_qos_specs_id=qos.id)

        mock_get_volume_type.return_value = vol.volume_type
        mock_get_qos_specs.return_value = qos
        self.array.get_connections.return_value = []
        self.array.get_volumes.return_value = MPV

        self.driver.manage_existing(vol, volume_ref)
        mock_qos.assert_called_with(self.array, vol_name,
                                    {'maxIOPS': 100,
                                     'maxBWS': 1048576})

    @mock.patch(DRIVER_PATH + ".flasharray.VolumePatch")
    def test_retype_qos(self, mock_fa):
        ctxt = context.get_admin_context()
        vol, vol_name = self.new_fake_vol()
        qos = qos_specs.create(ctxt, "qos-iops-bws", QOS_IOPS_BWS)
        new_type = fake_volume.fake_volume_type_obj(ctxt)
        new_type.qos_specs_id = qos.id
        mock_data = self.array.flasharray.\
            VolumePatch(qos=self.flasharray.
                        Qos(iops_limit=int(QOS_IOPS_BWS["maxIOPS"]),
                            bandwidth_limit=int(QOS_IOPS_BWS["maxBWS"])
                            * 1024 * 1024))
        mock_fa.return_value = mock_data
        get_voltype = "cinder.objects.volume_type.VolumeType.get_by_name_or_id"
        with mock.patch(get_voltype) as mock_get_vol_type:
            mock_get_vol_type.return_value = new_type
            did_retype, model_update = self.driver.retype(
                ctxt,
                vol,
                new_type,
                None,  # ignored by driver
                None,  # ignored by driver
            )

        self.array.patch_volumes.assert_called_with(
            names=[vol_name],
            volume=mock_data)
        self.assertTrue(did_retype)
        self.assertIsNone(model_update)

    @mock.patch(DRIVER_PATH + ".flasharray.VolumePatch")
    def test_retype_qos_reset_iops(self, mock_fa):
        ctxt = context.get_admin_context()
        vol, vol_name = self.new_fake_vol()
        new_type = fake_volume.fake_volume_type_obj(ctxt)
        mock_data = self.array.flasharray.\
            VolumePatch(qos=self.flasharray.Qos(iops_limit='',
                                                bandwidth_limit=''))
        mock_fa.return_value = mock_data
        get_voltype = "cinder.objects.volume_type.VolumeType.get_by_name_or_id"
        with mock.patch(get_voltype) as mock_get_vol_type:
            mock_get_vol_type.return_value = new_type
            did_retype, model_update = self.driver.retype(
                ctxt,
                vol,
                new_type,
                None,  # ignored by driver
                None,  # ignored by driver
            )
        self.array.patch_volumes.assert_called_with(
            names=[vol_name],
            volume=mock_data)
        self.assertTrue(did_retype)
        self.assertIsNone(model_update)


class PureISCSIDriverTestCase(PureBaseSharedDriverTestCase):

    def setUp(self):
        super(PureISCSIDriverTestCase, self).setUp()
        self.mock_config.use_chap_auth = False
        self.driver = pure.PureISCSIDriver(configuration=self.mock_config)
        self.driver._array = self.array
        self.mock_object(self.driver, '_get_current_array',
                         return_value=self.array)
        self.driver._storage_protocol = 'iSCSI'
        self.mock_utils = mock.Mock()
        self.driver.driver_utils = self.mock_utils
        self.set_pure_hosts = ValidResponse(200, None, 1,
                                            [DotNotation(PURE_HOST.copy())],
                                            {})

    def test_get_host(self):
        good_host = PURE_HOST.copy()
        good_host.update(iqns=INITIATOR_IQN)
        pure_bad_host = ValidResponse(200, None, 1,
                                      [], {})
        pure_good_host = ValidResponse(200, None, 1,
                                       [DotNotation(good_host)], {})
        self.array.get_hosts.return_value = pure_bad_host
        real_result = self.driver._get_host(self.array, ISCSI_CONNECTOR)
        self.assertEqual([], real_result)
        self.array.get_hosts.return_value = pure_good_host
        real_result = self.driver._get_host(self.array, ISCSI_CONNECTOR)
        self.assertEqual([good_host], real_result)
        self.assert_error_propagates([self.array.get_hosts],
                                     self.driver._get_host,
                                     self.array,
                                     ISCSI_CONNECTOR)

    @mock.patch(ISCSI_DRIVER_OBJ + "._get_wwn")
    @mock.patch(ISCSI_DRIVER_OBJ + "._connect")
    @mock.patch(ISCSI_DRIVER_OBJ + "._get_target_iscsi_ports")
    def test_initialize_connection(self, mock_get_iscsi_ports,
                                   mock_connection, mock_get_wwn):
        vol, vol_name = self.new_fake_vol()
        mock_get_iscsi_ports.return_value = VALID_ISCSI_PORTS.items
        mock_get_wwn.return_value = '3624a93709714b5cb91634c470002b2c8'
        mock_connection.return_value = CONN.items
        result = deepcopy(ISCSI_CONNECTION_INFO)

        real_result = self.driver.initialize_connection(vol,
                                                        ISCSI_CONNECTOR)
        self.assertDictEqual(result, real_result)
        mock_get_iscsi_ports.assert_called_with(self.array)
        mock_connection.assert_called_with(self.array, vol_name,
                                           ISCSI_CONNECTOR, None, None)
        self.assert_error_propagates([mock_get_iscsi_ports, mock_connection],
                                     self.driver.initialize_connection,
                                     vol, ISCSI_CONNECTOR)

    @mock.patch(ISCSI_DRIVER_OBJ + "._get_wwn")
    @mock.patch(ISCSI_DRIVER_OBJ + "._connect")
    @mock.patch(ISCSI_DRIVER_OBJ + "._get_target_iscsi_ports")
    def test_initialize_connection_ipv6(self, mock_get_iscsi_ports,
                                        mock_connection, mock_get_wwn):
        vol, vol_name = self.new_fake_vol()
        mock_get_iscsi_ports.return_value = VALID_ISCSI_PORTS_IPV6.items
        mock_get_wwn.return_value = '3624a93709714b5cb91634c470002b2c8'
        mock_connection.return_value = CONN.items

        self.mock_config.pure_iscsi_cidr = ISCSI_CIDR_V6
        result = deepcopy(ISCSI_CONNECTION_INFO_V6)

        real_result = self.driver.initialize_connection(vol,
                                                        ISCSI_CONNECTOR)
        self.assertDictEqual(result, real_result)
        mock_get_iscsi_ports.assert_called_with(self.array)
        mock_connection.assert_called_with(self.array, vol_name,
                                           ISCSI_CONNECTOR, None, None)
        self.assert_error_propagates([mock_get_iscsi_ports, mock_connection],
                                     self.driver.initialize_connection,
                                     vol, ISCSI_CONNECTOR)

    @mock.patch(ISCSI_DRIVER_OBJ + "._get_wwn")
    @mock.patch(ISCSI_DRIVER_OBJ + "._connect")
    @mock.patch(ISCSI_DRIVER_OBJ + "._get_target_iscsi_ports")
    def test_initialize_connection_uniform_ac(self, mock_get_iscsi_ports,
                                              mock_connection, mock_get_wwn):
        repl_extra_specs = {
            'replication_type': '<in> sync',
            'replication_enabled': '<is> true',
        }
        vol, vol_name = self.new_fake_vol(type_extra_specs=repl_extra_specs)
        mock_get_wwn.return_value = '3624a93709714b5cb91634c470002b2c8'
        result = deepcopy(ISCSI_CONNECTION_INFO_AC)

        self.driver._is_active_cluster_enabled = True
        mock_secondary = mock.MagicMock()
        mock_connection.side_effect = lambda *args, **kwargs: \
            CONN.items if args and args[0] == self.array else AC_CONN.items
        mock_get_iscsi_ports.side_effect = lambda *args, **kwargs: \
            VALID_ISCSI_PORTS.items if args and args[0] == self.array \
            else VALID_AC_ISCSI_PORTS.items
        self.driver._uniform_active_cluster_target_arrays = [mock_secondary]

        real_result = self.driver.initialize_connection(vol,
                                                        ISCSI_CONNECTOR)
        self.assertDictEqual(result, real_result)
        mock_get_iscsi_ports.assert_has_calls([
            mock.call(self.array),
            mock.call(mock_secondary),
        ])
        mock_connection.assert_has_calls([
            mock.call(self.array, vol_name, ISCSI_CONNECTOR, None, None),
            mock.call(mock_secondary, vol_name, ISCSI_CONNECTOR, None, None),
        ])

    @mock.patch(ISCSI_DRIVER_OBJ + "._get_wwn")
    @mock.patch(ISCSI_DRIVER_OBJ + "._connect")
    @mock.patch(ISCSI_DRIVER_OBJ + "._get_target_iscsi_ports")
    def test_initialize_connection_uniform_ac_cidr(self,
                                                   mock_get_iscsi_ports,
                                                   mock_connection,
                                                   mock_get_wwn):
        repl_extra_specs = {
            'replication_type': '<in> sync',
            'replication_enabled': '<is> true',
        }
        vol, vol_name = self.new_fake_vol(type_extra_specs=repl_extra_specs)
        mock_get_wwn.return_value = '3624a93709714b5cb91634c470002b2c8'
        result = deepcopy(ISCSI_CONNECTION_INFO_AC_FILTERED)

        self.driver._is_active_cluster_enabled = True
        # Set up some CIDRs to block: this will block only one of the
        # ActiveCluster addresses from above, so we should check that we only
        # get four+three results back
        self.driver.configuration.pure_iscsi_cidr = ISCSI_CIDR_FILTERED
        mock_secondary = mock.MagicMock()
        mock_connection.side_effect = lambda *args, **kwargs: \
            CONN.items if args and args[0] == self.array else AC_CONN.items
        mock_get_iscsi_ports.side_effect = lambda *args, **kwargs: \
            VALID_ISCSI_PORTS.items if args and args[0] == self.array \
            else VALID_AC_ISCSI_PORTS.items
        self.driver._uniform_active_cluster_target_arrays = [mock_secondary]

        real_result = self.driver.initialize_connection(vol,
                                                        ISCSI_CONNECTOR)
        self.assertDictEqual(result, real_result)
        mock_get_iscsi_ports.assert_has_calls([
            mock.call(self.array),
            mock.call(mock_secondary),
        ])
        mock_connection.assert_has_calls([
            mock.call(self.array, vol_name, ISCSI_CONNECTOR, None, None),
            mock.call(mock_secondary, vol_name, ISCSI_CONNECTOR, None, None),
        ])

    @mock.patch(ISCSI_DRIVER_OBJ + "._get_wwn")
    @mock.patch(ISCSI_DRIVER_OBJ + "._connect")
    @mock.patch(ISCSI_DRIVER_OBJ + "._get_target_iscsi_ports")
    def test_initialize_connection_uniform_ac_cidrs(self,
                                                    mock_get_iscsi_ports,
                                                    mock_connection,
                                                    mock_get_wwn):
        repl_extra_specs = {
            'replication_type': '<in> sync',
            'replication_enabled': '<is> true',
        }
        vol, vol_name = self.new_fake_vol(type_extra_specs=repl_extra_specs)
        mock_get_wwn.return_value = '3624a93709714b5cb91634c470002b2c8'
        result = deepcopy(ISCSI_CONNECTION_INFO_AC_FILTERED_LIST)

        self.driver._is_active_cluster_enabled = True
        # Set up some CIDRs to block: this will allow only 2 addresses from
        # each host of the ActiveCluster, so we should check that we only
        # get two+two results back
        self.driver.configuration.pure_iscsi_cidr_list = ISCSI_CIDRS_FILTERED
        mock_secondary = mock.MagicMock()
        mock_connection.side_effect = lambda *args, **kwargs: \
            CONN.items if args and args[0] == self.array else AC_CONN.items
        mock_get_iscsi_ports.side_effect = lambda *args, **kwargs: \
            VALID_ISCSI_PORTS.items if args and args[0] == self.array \
            else VALID_AC_ISCSI_PORTS_IPV6.items
        self.driver._uniform_active_cluster_target_arrays = [mock_secondary]

        real_result = self.driver.initialize_connection(vol,
                                                        ISCSI_CONNECTOR)
        self.assertDictEqual(result, real_result)
        mock_get_iscsi_ports.assert_has_calls([
            mock.call(self.array),
            mock.call(mock_secondary),
        ])
        mock_connection.assert_has_calls([
            mock.call(self.array, vol_name, ISCSI_CONNECTOR, None, None),
            mock.call(mock_secondary, vol_name, ISCSI_CONNECTOR, None, None),
        ])

    @mock.patch(ISCSI_DRIVER_OBJ + "._get_wwn")
    @mock.patch(ISCSI_DRIVER_OBJ + "._get_chap_credentials")
    @mock.patch(ISCSI_DRIVER_OBJ + "._connect")
    @mock.patch(ISCSI_DRIVER_OBJ + "._get_target_iscsi_ports")
    def test_initialize_connection_with_auth(self, mock_get_iscsi_ports,
                                             mock_connection,
                                             mock_get_chap_creds,
                                             mock_get_wwn):
        vol, vol_name = self.new_fake_vol()
        self.maxDiff = None
        auth_type = "CHAP"
        chap_username = ISCSI_CONNECTOR["host"]
        chap_password = "password"
        mock_get_iscsi_ports.return_value = VALID_ISCSI_PORTS.items

        mock_get_wwn.return_value = '3624a93709714b5cb91634c470002b2c8'
        mock_connection.return_value = CONN.items
        result = deepcopy(ISCSI_CONNECTION_INFO)
        result["data"]["auth_method"] = auth_type
        result["data"]["auth_username"] = chap_username
        result["data"]["auth_password"] = chap_password

        self.mock_config.use_chap_auth = True
        mock_get_chap_creds.return_value = (chap_username, chap_password)

        # Branch where no credentials were generated
        real_result = self.driver.initialize_connection(vol,
                                                        ISCSI_CONNECTOR)
        mock_connection.assert_called_with(self.array,
                                           vol_name,
                                           ISCSI_CONNECTOR,
                                           chap_username,
                                           chap_password)
        self.assertDictEqual(result, real_result)

        self.assert_error_propagates([mock_get_iscsi_ports, mock_connection],
                                     self.driver.initialize_connection,
                                     vol, ISCSI_CONNECTOR)

    @mock.patch(ISCSI_DRIVER_OBJ + "._get_wwn")
    @mock.patch(ISCSI_DRIVER_OBJ + "._connect")
    @mock.patch(ISCSI_DRIVER_OBJ + "._get_target_iscsi_ports")
    def test_initialize_connection_multipath(self,
                                             mock_get_iscsi_ports,
                                             mock_connection, mock_get_wwn):
        vol, vol_name = self.new_fake_vol()
        mock_get_iscsi_ports.return_value = VALID_ISCSI_PORTS.items
        mock_get_wwn.return_value = '3624a93709714b5cb91634c470002b2c8'
        mock_connection.return_value = CONN.items
        multipath_connector = deepcopy(ISCSI_CONNECTOR)
        multipath_connector["multipath"] = True
        result = deepcopy(ISCSI_CONNECTION_INFO)

        real_result = self.driver.initialize_connection(vol,
                                                        multipath_connector)
        self.assertDictEqual(result, real_result)
        mock_get_iscsi_ports.assert_called_with(self.array)
        mock_connection.assert_called_with(self.array, vol_name,
                                           multipath_connector, None, None)

        multipath_connector["multipath"] = False
        self.driver.initialize_connection(vol, multipath_connector)

    def test_get_target_iscsi_ports(self):
        self.array.get_controllers.return_value = CTRL_OBJ
        self.array.get_ports.return_value = VALID_ISCSI_PORTS
        ret = self.driver._get_target_iscsi_ports(self.array)
        self.assertEqual(ISCSI_PORTS[0:4], ret)

    def test_get_target_iscsi_ports_with_iscsi_and_fc(self):
        self.array.get_controllers.return_value = CTRL_OBJ
        PORTS_DATA = [DotNotation(i) for i in PORTS_WITH]
        ifc_ports = ValidResponse(200, None, 1, PORTS_DATA, {})
        self.array.get_ports.return_value = ifc_ports
        ret = self.driver._get_target_iscsi_ports(self.array)
        self.assertEqual(ISCSI_PORTS, ret)

    def test_get_target_iscsi_ports_with_no_ports(self):
        # Should raise an exception if there are no ports
        self.array.get_controllers.return_value = CTRL_OBJ
        no_ports = ValidResponse(200, None, 1, [], {})
        self.array.get_ports.return_value = no_ports
        self.assertRaises(pure.PureDriverException,
                          self.driver._get_target_iscsi_ports,
                          self.array)

    def test_get_target_iscsi_ports_with_only_fc_ports(self):
        # Should raise an exception of there are no iscsi ports
        self.array.get_controllers.return_value = CTRL_OBJ
        PORTS_NOISCSI = [DotNotation(i) for i in PORTS_WITHOUT]
        self.array.get_ports.\
            return_value = ValidResponse(200, None, 1, PORTS_NOISCSI, {})
        self.assertRaises(pure.PureDriverException,
                          self.driver._get_target_iscsi_ports,
                          self.array)

    @mock.patch(DRIVER_PATH + ".flasharray.HostPatch")
    @mock.patch(DRIVER_PATH + ".flasharray.HostPost")
    @mock.patch(ISCSI_DRIVER_OBJ + "._get_host", autospec=True)
    @mock.patch(ISCSI_DRIVER_OBJ + "._generate_purity_host_name", spec=True)
    def test_connect(self, mock_generate, mock_host,
                     mock_post_host, mock_patch_host):
        vol, vol_name = self.new_fake_vol()

        # Branch where host already exists
        pure_hosts = ValidResponse(200, None, 1,
                                   [DotNotation(PURE_HOST.copy())], {})
        mock_host.return_value = pure_hosts.items
        self.array.post_connections.return_value = CONN
        real_result = self.driver._connect(self.array, vol_name,
                                           ISCSI_CONNECTOR, None, None)
        self.assertEqual([CONNECTION_DATA], real_result)
        mock_host.assert_called_with(self.driver, self.array,
                                     ISCSI_CONNECTOR, remote=False)
        self.assertFalse(mock_generate.called)
        self.assertFalse(self.array.post_hosts.called)
        self.array.post_connections.\
            assert_called_with(host_names=[PURE_HOST_NAME],
                               volume_names=[vol_name])

        # Branch where new host is created
        empty_hosts = ValidResponse(200, None, 1,
                                    [], {})
        mock_host.return_value = empty_hosts.items
        mock_generate.return_value = PURE_HOST_NAME
        real_result = self.driver._connect(self.array, vol_name,
                                           ISCSI_CONNECTOR, None, None)
        mock_host.assert_called_with(self.driver, self.array,
                                     ISCSI_CONNECTOR, remote=False)
        mock_generate.assert_called_with({'name': HOSTNAME})
        self.array.post_hosts.assert_called_with(names=[PURE_HOST_NAME],
                                                 host=mock_post_host())
        self.assertFalse(self.array.patch_hosts.called)
        self.assertEqual([CONNECTION_DATA], real_result)

        mock_generate.reset_mock()
        self.array.reset_mock()
        self.assert_error_propagates(
            [mock_host, mock_generate, self.array.post_connections,
             self.array.post_hosts], self.driver._connect, self.array,
            vol_name, ISCSI_CONNECTOR, None, None)

        self.mock_config.use_chap_auth = True
        chap_user = ISCSI_CONNECTOR["host"]
        chap_password = "sOmEseCr3t"

        # Branch where chap is used and credentials already exist
        real_result = self.driver._connect(self.array, vol_name,
                                           ISCSI_CONNECTOR,
                                           chap_user, chap_password)
        self.assertEqual([CONNECTION_DATA], real_result)
        self.array.patch_hosts.assert_called_with(names=[PURE_HOST_NAME],
                                                  host=mock_patch_host())

        self.array.reset_mock()
        self.mock_config.use_chap_auth = False
        self.mock_config.safe_get.return_value = 'oracle-vm-server'

        # Branch where personality is set
        self.driver._connect(self.array, vol_name, ISCSI_CONNECTOR,
                             None, None)
        self.assertEqual([CONNECTION_DATA], real_result)
        self.array.patch_hosts.\
            assert_called_with(names=[PURE_HOST_NAME],
                               host=mock_patch_host(
                                   personality='oracle-vm-server'))

    @mock.patch(DRIVER_PATH + ".LOG")
    @mock.patch(ISCSI_DRIVER_OBJ + "._get_host", autospec=True)
    def test_connect_already_connected(self, mock_host, mock_logger):
        vol, vol_name = self.new_fake_vol()
        mock_host.return_value = self.set_pure_hosts.items
        self.array.get_connections.return_value = NCONN
        err_rsp = ErrorResponse(400, [DotNotation({'message':
                                'already exists'})], {})
        self.array.post_connections.return_value = err_rsp
        self.array.get_volumes.return_value = MPV
        actual = self.driver._connect(self.array, vol_name, ISCSI_CONNECTOR,
                                      None, None)
        mock_logger.debug.\
            assert_called_with('Volume connection already exists for Purity '
                               'host with message: %s',
                               'already exists')
        self.assertEqual(NCONN.items, actual)
        self.assertTrue(self.array.post_connections.called)
        self.assertTrue(bool(self.array.get_connections))

    @mock.patch(ISCSI_DRIVER_OBJ + "._get_host", autospec=True)
    def test_connect_already_connected_list_hosts_empty(self, mock_host):
        vol, vol_name = self.new_fake_vol()
        mock_host.return_value = self.set_pure_hosts.items
        self.array.get_connections.return_value = CONN
        err_rsp = ErrorResponse(400, [DotNotation({'message':
                                'unknown'})], {})
        self.array.post_connections.return_value = err_rsp
        self.assertRaises(pure.PureDriverException, self.driver._connect,
                          self.array, vol_name, ISCSI_CONNECTOR, None, None)
        self.assertTrue(self.array.post_connections.called)
        self.assertTrue(bool(self.array.get_connections))

    @mock.patch(ISCSI_DRIVER_OBJ + "._get_host", autospec=True)
    def test_connect_already_connected_list_hosts_exception(self, mock_host):
        vol, vol_name = self.new_fake_vol()
        hosts = deepcopy(PURE_HOST)
        hosts['name'] = 'utest'
        pure_hosts = ValidResponse(200, None, 1,
                                   [DotNotation(hosts)], {})
        mock_host.return_value = pure_hosts.items
        self.array.get_connections.return_value = CONN
        err_con = ErrorResponse(400, [DotNotation({'message':
                                'Unknown Error'})], {})
        self.array.post_connections.return_value = err_con
        self.array.get_volumes.return_value = MPV
        self.assertRaises(pure.PureDriverException,
                          self.driver._connect, self.array, vol_name,
                          ISCSI_CONNECTOR, None, None)
        self.assertTrue(self.array.post_connections.called)
        self.assertTrue(bool(self.array.get_connections))

    @mock.patch(ISCSI_DRIVER_OBJ + "._generate_purity_host_name", spec=True)
    @mock.patch(ISCSI_DRIVER_OBJ + "._get_chap_secret_from_init_data")
    @mock.patch(ISCSI_DRIVER_OBJ + "._get_host", autospec=True)
    def test_connect_host_deleted(self, mock_host,
                                  mock_get_secret, mock_hname):
        vol, vol_name = self.new_fake_vol()
        empty_hosts = ValidResponse(200, None, 1,
                                    [], {})
        mock_host.return_value = empty_hosts.items
        mock_hname.return_value = PURE_HOST_NAME
        self.mock_config.use_chap_auth = True
        mock_get_secret.return_value = 'abcdef'
        err_rsp = ErrorResponse(400, [DotNotation({'message':
                                'Host does not exist'})], {})
        self.array.patch_hosts.return_value = err_rsp

        # Because we mocked out retry make sure we are raising the right
        # exception to allow for retries to happen.
        self.assertRaises(pure.PureRetryableException,
                          self.driver._connect,
                          self.array, vol_name, ISCSI_CONNECTOR, None, None)

    @mock.patch(ISCSI_DRIVER_OBJ + "._generate_purity_host_name", spec=True)
    @mock.patch(ISCSI_DRIVER_OBJ + "._get_host", autospec=True)
    def test_connect_iqn_already_in_use(self, mock_host, mock_hname):
        vol, vol_name = self.new_fake_vol()
        empty_hosts = ValidResponse(200, None, 1,
                                    [], {})
        mock_host.return_value = empty_hosts.items
        mock_hname.return_value = PURE_HOST_NAME
        err_iqn = ErrorResponse(400, [DotNotation({'message':
                                'already in use'})], {})
        self.array.post_hosts.return_value = err_iqn

        # Because we mocked out retry make sure we are raising the right
        # exception to allow for retries to happen.
        self.assertRaises(pure.PureRetryableException,
                          self.driver._connect,
                          self.array, vol_name, ISCSI_CONNECTOR, None, None)

    @mock.patch(ISCSI_DRIVER_OBJ + "._generate_purity_host_name", spec=True)
    @mock.patch(ISCSI_DRIVER_OBJ + "._get_host", autospec=True)
    def test_connect_create_host_already_exists(self, mock_host, mock_hname):
        vol, vol_name = self.new_fake_vol()
        mock_host.return_value = []
        mock_hname.return_value = PURE_HOST_NAME
        err_iqn = ErrorResponse(400, [DotNotation({'message':
                                'already exists'})], {})
        self.array.post_hosts.return_value = err_iqn

        # Because we mocked out retry make sure we are raising the right
        # exception to allow for retries to happen.
        self.assertRaises(pure.PureRetryableException,
                          self.driver._connect,
                          self.array, vol_name, ISCSI_CONNECTOR, None, None)

    @mock.patch(ISCSI_DRIVER_OBJ + "._generate_chap_secret")
    def test_get_chap_credentials_create_new(self, mock_generate_secret):
        self.mock_utils.get_driver_initiator_data.return_value = []
        host = 'host1'
        expected_password = 'foo123'
        mock_generate_secret.return_value = expected_password
        self.mock_utils.insert_driver_initiator_data.return_value = True
        username, password = self.driver._get_chap_credentials(host,
                                                               INITIATOR_IQN)
        self.assertEqual(host, username)
        self.assertEqual(expected_password, password)
        self.mock_utils.insert_driver_initiator_data.assert_called_once_with(
            INITIATOR_IQN, pure.CHAP_SECRET_KEY, expected_password
        )

    @mock.patch(ISCSI_DRIVER_OBJ + "._generate_chap_secret")
    def test_get_chap_credentials_create_new_fail_to_set(self,
                                                         mock_generate_secret):
        host = 'host1'
        expected_password = 'foo123'
        mock_generate_secret.return_value = 'badpassw0rd'
        self.mock_utils.insert_driver_initiator_data.return_value = False
        self.mock_utils.get_driver_initiator_data.side_effect = [
            [],
            [{'key': pure.CHAP_SECRET_KEY, 'value': expected_password}],
            pure.PureDriverException(reason='this should never be hit'),
        ]

        username, password = self.driver._get_chap_credentials(host,
                                                               INITIATOR_IQN)
        self.assertEqual(host, username)
        self.assertEqual(expected_password, password)


class PureFCDriverTestCase(PureBaseSharedDriverTestCase):

    def setUp(self):
        super(PureFCDriverTestCase, self).setUp()
        self.driver = pure.PureFCDriver(configuration=self.mock_config)
        self.driver._storage_protocol = "FC"
        self.driver._array = self.array
        self.mock_object(self.driver, '_get_current_array',
                         return_value=self.array)
        self.driver._lookup_service = mock.Mock()

    pure_hosts = ValidResponse(200, None, 1,
                               [DotNotation(PURE_HOST.copy())], {})

    def test_get_host(self):
        good_host = PURE_HOST.copy()
        good_host.update(wwn=["another-wrong-wwn", INITIATOR_WWN])
        pure_bad_host = ValidResponse(200, None, 1,
                                      [], {})
        pure_good_host = ValidResponse(200, None, 1,
                                       [DotNotation(good_host)], {})
        self.array.get_hosts.return_value = pure_bad_host
        actual_result = self.driver._get_host(self.array, FC_CONNECTOR)
        self.assertEqual([], actual_result)
        self.array.get_hosts.return_value = pure_good_host
        actual_result = self.driver._get_host(self.array, FC_CONNECTOR)
        self.assertEqual([good_host], actual_result)
        self.assert_error_propagates([self.array.get_hosts],
                                     self.driver._get_host,
                                     self.array,
                                     FC_CONNECTOR)

    def test_get_host_uppercase_wwpn(self):
        expected_host = PURE_HOST.copy()
        expected_host['wwn'] = [INITIATOR_WWN]
        pure_hosts = ValidResponse(200, None, 1,
                                   [DotNotation(expected_host)], {})
        self.array.get_hosts.return_value = pure_hosts
        connector = FC_CONNECTOR.copy()
        connector['wwpns'] = [wwpn.upper() for wwpn in FC_CONNECTOR['wwpns']]

        actual_result = self.driver._get_host(self.array, connector)
        self.assertEqual([expected_host], actual_result)

    @mock.patch(FC_DRIVER_OBJ + "._get_valid_ports")
    @mock.patch(FC_DRIVER_OBJ + "._get_wwn")
    @mock.patch(FC_DRIVER_OBJ + "._connect")
    def test_initialize_connection(self, mock_connection,
                                   mock_get_wwn, mock_ports):
        vol, vol_name = self.new_fake_vol()
        lookup_service = self.driver._lookup_service
        (lookup_service.get_device_mapping_from_network.
         return_value) = DEVICE_MAPPING
        mock_get_wwn.return_value = '3624a93709714b5cb91634c470002b2c8'
        self.array.get_connections.return_value = CONN.items
        mock_connection.return_value = CONN.items
        mock_ports.return_value = VALID_FC_PORTS.items
        actual_result = self.driver.initialize_connection(vol, FC_CONNECTOR)
        self.assertDictEqual(FC_CONNECTION_INFO, actual_result)

    @mock.patch(FC_DRIVER_OBJ + "._get_valid_ports")
    @mock.patch(FC_DRIVER_OBJ + "._get_wwn")
    @mock.patch(FC_DRIVER_OBJ + "._connect")
    def test_initialize_connection_uniform_ac(self, mock_connection,
                                              mock_get_wwn, mock_ports):
        repl_extra_specs = {
            'replication_type': '<in> sync',
            'replication_enabled': '<is> true',
        }
        vol, vol_name = self.new_fake_vol(type_extra_specs=repl_extra_specs)
        lookup_service = self.driver._lookup_service
        (lookup_service.get_device_mapping_from_network.
         return_value) = AC_DEVICE_MAPPING
        mock_get_wwn.return_value = '3624a93709714b5cb91634c470002b2c8'
        self.array.get_connections.return_value = CONN.items
        self.driver._is_active_cluster_enabled = True
        mock_secondary = mock.MagicMock()
        self.driver._uniform_active_cluster_target_arrays = [mock_secondary]
        mock_secondary.get_connections.return_value = AC_CONN.items
        mock_connection.side_effect = lambda *args, **kwargs: \
            CONN.items if args and args[0] == self.array else AC_CONN.items
        mock_ports.side_effect = lambda *args, **kwargs: \
            VALID_FC_PORTS.items if args and args[0] == self.array \
            else VALID_AC_FC_PORTS.items
        actual_result = self.driver.initialize_connection(vol, FC_CONNECTOR)
        self.assertDictEqual(FC_CONNECTION_INFO_AC, actual_result)

    @mock.patch(DRIVER_PATH + ".flasharray.HostPatch")
    @mock.patch(DRIVER_PATH + ".flasharray.HostPost")
    @mock.patch(FC_DRIVER_OBJ + "._get_host", autospec=True)
    @mock.patch(FC_DRIVER_OBJ + "._generate_purity_host_name", spec=True)
    def test_connect(self, mock_generate,
                     mock_host, mock_post_host,
                     mock_patch_host):
        vol, vol_name = self.new_fake_vol()

        # Branch where host already exists
        pure_hosts = ValidResponse(200, None, 1,
                                   [DotNotation(PURE_HOST.copy())], {})
        mock_host.return_value = pure_hosts.items
        self.array.get_connections.return_value = CONN
        self.array.post_connections.return_value = CONN
        real_result = self.driver._connect(self.array, vol_name, FC_CONNECTOR)
        self.assertEqual([CONNECTION_DATA], real_result)
        mock_host.assert_called_with(self.driver, self.array, FC_CONNECTOR,
                                     remote=False)
        self.assertFalse(mock_generate.called)
        self.assertFalse(self.array.create_host.called)
        self.array.post_connections.\
            assert_called_with(host_names=[PURE_HOST_NAME],
                               volume_names=[vol_name])

        # Branch where new host is created
        empty_hosts = ValidResponse(200, None, 1,
                                    [], {})
        mock_host.return_value = empty_hosts.items
        mock_generate.return_value = PURE_HOST_NAME
        real_result = self.driver._connect(self.array, vol_name, FC_CONNECTOR)
        mock_host.assert_called_with(self.driver, self.array, FC_CONNECTOR,
                                     remote=False)
        mock_generate.assert_called_with(HOSTNAME)
        self.array.post_hosts.assert_called_with(names=[PURE_HOST_NAME],
                                                 host=mock_post_host())
        self.assertEqual([CONNECTION_DATA], real_result)

        mock_generate.reset_mock()
        self.array.reset_mock()
        self.assert_error_propagates(
            [mock_host, mock_generate, self.array.post_connections,
             self.array.post_hosts],
            self.driver._connect, self.array, vol_name, FC_CONNECTOR)

        self.mock_config.safe_get.return_value = 'oracle-vm-server'

        # Branch where personality is set
        self.driver._connect(self.array, vol_name, FC_CONNECTOR)
        self.assertEqual([CONNECTION_DATA], real_result)
        self.array.patch_hosts.\
            assert_called_with(names=[PURE_HOST_NAME],
                               host=mock_patch_host(personality=
                                                    'oracle-vm-server'))

    @mock.patch(DRIVER_PATH + ".LOG")
    @mock.patch(FC_DRIVER_OBJ + "._get_host", autospec=True)
    def test_connect_already_connected(self, mock_host, mock_logger):
        vol, vol_name = self.new_fake_vol()
        hosts = deepcopy(PURE_HOST)
        hosts['name'] = 'utest'
        pure_hosts = ValidResponse(200, None, 1,
                                   [DotNotation(hosts)], {})
        mock_host.return_value = pure_hosts.items
        vdict = {'id': '1e5177e7-95e5-4a0f-b170-e45f4b469f6a',
                 'name': 'volume-1e5177e7-95e5-4a0f-b170-e45f4b469f6a-cinder'}
        NCONNECTION_DATA = {'host': {'name': 'utest'},
                            'host_group': {},
                            'lun': 1,
                            'nsid': None,
                            'protocol_endpoint': {},
                            'volume': vdict}
        NCONN = ValidResponse(200, None, 1,
                              [DotNotation(NCONNECTION_DATA)], {})
        self.array.get_connections.return_value = NCONN
        pure_vol_copy = deepcopy(MANAGEABLE_PURE_VOLS)
        MPV = ValidResponse(200, None, 3,
                            [DotNotation(pure_vol_copy[0]),
                             DotNotation(pure_vol_copy[1]),
                             DotNotation(pure_vol_copy[2])], {})
        self.array.get_volumes.return_value = MPV
        err_rsp = ErrorResponse(400, [DotNotation({'message':
                                'already exists'})], {})
        self.array.post_connections.return_value = err_rsp
        actual = self.driver._connect(self.array, vol_name, FC_CONNECTOR)
        mock_logger.debug.\
            assert_called_with('Volume connection already exists for Purity '
                               'host with message: %s',
                               'already exists')
        self.assertEqual(NCONN.items, actual)
        self.assertTrue(self.array.post_connections.called)
        self.assertTrue(bool(self.array.get_connections))

    @mock.patch(FC_DRIVER_OBJ + "._get_host", autospec=True)
    def test_connect_already_connected_list_hosts_empty(self, mock_host):
        vol, vol_name = self.new_fake_vol()
        pure_hosts = ValidResponse(200, None, 1,
                                   [DotNotation(PURE_HOST)], {})
        mock_host.return_value = pure_hosts.items
        self.array.get_volumes.return_value = MPV
        err_rsp = ErrorResponse(400, [DotNotation({'message':
                                'unknown'})], {})
        self.array.get_connections.return_value = CONN
        self.array.post_connections.return_value = err_rsp
        self.assertRaises(pure.PureDriverException, self.driver._connect,
                          self.array, vol_name, FC_CONNECTOR)
        self.assertTrue(self.array.post_connections.called)
        self.assertTrue(bool(self.array.get_connections))

    @mock.patch(FC_DRIVER_OBJ + "._get_host", autospec=True)
    def test_connect_already_connected_list_hosts_exception(self, mock_host):
        vol, vol_name = self.new_fake_vol()
        hosts = deepcopy(PURE_HOST)
        hosts['name'] = 'utest'
        pure_hosts = ValidResponse(200, None, 1,
                                   [DotNotation(hosts)], {})
        mock_host.return_value = pure_hosts.items
        err_rsp = ErrorResponse(400, [DotNotation({'message':
                                'Unknown Error'})], {})
        self.array.get_connections.return_value = CONN
        self.array.post_connections.return_value = err_rsp
        self.assertRaises(pure.PureDriverException,
                          self.driver._connect, self.array, vol_name,
                          FC_CONNECTOR)
        self.assertTrue(self.array.post_connections.called)
        self.assertTrue(bool(self.array.get_connections))

    @mock.patch(FC_DRIVER_OBJ + "._get_host", autospec=True)
    def test_connect_wwn_already_in_use(self, mock_host):
        vol, vol_name = self.new_fake_vol()
        mock_host.return_value = []

        err_rsp = ErrorResponse(400, [DotNotation({'message':
                                'already in use'})], {})
        self.array.post_hosts.return_value = err_rsp

        # Because we mocked out retry make sure we are raising the right
        # exception to allow for retries to happen.
        self.assertRaises(pure.PureRetryableException,
                          self.driver._connect,
                          self.array, vol_name, FC_CONNECTOR)

    @mock.patch(FC_DRIVER_OBJ + "._disconnect")
    def test_terminate_connection_uniform_ac(self, mock_disconnect):
        repl_extra_specs = {
            'replication_type': '<in> sync',
            'replication_enabled': '<is> true',
        }
        vol, vol_name = self.new_fake_vol(type_extra_specs=repl_extra_specs)
        fcls = self.driver._lookup_service
        fcls.get_device_mapping_from_network.return_value = AC_DEVICE_MAPPING
        self.driver._is_active_cluster_enabled = True
        mock_secondary = mock.MagicMock()
        self.driver._uniform_active_cluster_target_arrays = [mock_secondary]
        self.array.get_ports.return_value = FC_PORTS
        mock_secondary.list_ports.return_value = AC_FC_PORTS
        mock_disconnect.return_value = False

        self.driver.terminate_connection(vol, FC_CONNECTOR)
        mock_disconnect.assert_has_calls([
            mock.call(mock_secondary, vol, FC_CONNECTOR,
                      is_multiattach=False, remove_remote_hosts=True),
            mock.call(self.array, vol, FC_CONNECTOR,
                      is_multiattach=False, remove_remote_hosts=False)
        ])


@ddt.ddt
class PureVolumeUpdateStatsTestCase(PureBaseSharedDriverTestCase):
    def setUp(self):
        super(PureVolumeUpdateStatsTestCase, self).setUp()
        self.array.get_arrays.side_effect = self.fake_get_array

    @ddt.data(dict(reduction=10,
                   config_ratio=5,
                   expected_ratio=5,
                   auto=False),
              dict(reduction=10,
                   config_ratio=5,
                   expected_ratio=10,
                   auto=True),
              dict(reduction=1000,
                   config_ratio=5,
                   expected_ratio=5,
                   auto=True))
    @ddt.unpack
    def test_get_thin_provisioning(self,
                                   reduction,
                                   config_ratio,
                                   expected_ratio,
                                   auto):
        self.mock_object(volume_utils, 'get_max_over_subscription_ratio',
                         return_value=expected_ratio)
        self.mock_config.pure_automatic_max_oversubscription_ratio = auto
        self.mock_config.max_over_subscription_ratio = config_ratio
        actual_ratio = self.driver._get_thin_provisioning(reduction)
        self.assertEqual(expected_ratio, actual_ratio)

    @ddt.data(
        dict(
            connections=[
                {'status': 'connected', 'type': 'sync-replication'},
            ],
            expected='sync'),
        dict(
            connections=[
                {'status': 'connected', 'type': 'async-replication'}
            ],
            expected='async'),
        dict(
            connections=[
                {'status': 'connected', 'type': 'async-replication'},
                {'status': 'connected', 'type': 'sync-replication'},
                {'status': 'connected', 'type': 'async-replication'}
            ],
            expected='trisync'),
        dict(
            connections=[
                {'status': 'connected', 'type': 'async-replication'},
                {'status': 'connected', 'type': 'async-replication'}
            ],
            expected='async'),
        dict(
            connections=[
                {'status': 'connected', 'type': 'sync-replication'},
                {'status': 'connected', 'type': 'sync-replication'}
            ],
            expected='sync'),
        dict(
            connections=[
                {'status': 'connected', 'type': 'sync-replication'},
                {'status': 'connected', 'type': 'async-replication'}
            ],
            expected='trisync'),
        dict(
            connections=[
                {'status': 'connecting', 'type': 'sync-replication'}
            ],
            expected=None))
    @ddt.unpack
    def test_get_replication_capability(self, connections, expected):
        clist = [DotNotation(connections[i]) for i in range(len(connections))]
        con_obj = ValidResponse(200, None, 1, clist, {})
        self.array.get_array_connections.return_value = con_obj
        connection_status = self.driver._get_replication_capability()
        self.assertEqual(expected, connection_status)

    @mock.patch(BASE_DRIVER_OBJ + '._get_replication_capability')
    @mock.patch(BASE_DRIVER_OBJ + '.get_goodness_function')
    @mock.patch(BASE_DRIVER_OBJ + '.get_filter_function')
    @mock.patch(BASE_DRIVER_OBJ + '._get_thin_provisioning')
    def test_get_volume_stats(self, mock_get_thin_provisioning,
                              mock_get_filter, mock_get_goodness,
                              mock_get_replication_capability):
        filter_function = 'capabilities.total_volumes < 10'
        goodness_function = '90'
        reserved_percentage = 12
        SPACE_OBJ = ValidResponse(200, None, 1,
                                  [DotNotation(ARRAYS_SPACE_INFO)], {})
        PERF_OBJ = ValidResponse(200, None, 1, [DotNotation(PERF_INFO)], {})
        self.array.get_arrays_space.return_value = SPACE_OBJ
        self.array.get_arrays_performance.return_value = PERF_OBJ
        self.array.current_array.version.return_value = "6.2.0"
        pure_hosts = ValidResponse(200, None, 1,
                                   [DotNotation(PURE_HOST)], {})
        self.array.get_hosts.return_value = pure_hosts
        self.array.get_volumes.return_value = MPV
        self.array.get_volume_snapshots.return_value = MPS
        pg = ValidResponse(200, None, 1,
                           [DotNotation(PURE_PGROUP)],
                           {})
        self.array.get_protection_groups.return_value = \
            pg
        self.mock_config.reserved_percentage = reserved_percentage
        mock_get_filter.return_value = filter_function
        mock_get_goodness.return_value = goodness_function
        mock_get_replication_capability.return_value = 'sync'
        mock_get_thin_provisioning.return_value = TOTAL_REDUCTION

        expected_result = {
            'volume_backend_name': VOLUME_BACKEND_NAME,
            'vendor_name': 'Pure Storage',
            'driver_version': self.driver.VERSION,
            'storage_protocol': None,
            'consistencygroup_support': True,
            'consistent_group_snapshot_enabled': True,
            'consistent_group_replication_enabled': True,
            'thin_provisioning_support': True,
            'multiattach': True,
            'QoS_support': True,
            'total_capacity_gb': TOTAL_CAPACITY,
            'free_capacity_gb': TOTAL_CAPACITY - USED_SPACE,
            'reserved_percentage': reserved_percentage,
            'provisioned_capacity': PROVISIONED_CAPACITY,
            'max_over_subscription_ratio': TOTAL_REDUCTION,
            'filter_function': filter_function,
            'goodness_function': goodness_function,
            'total_volumes': 3,
            'total_snapshots': 3,
            'total_hosts': 1,
            'total_pgroups': 1,
            'writes_per_sec': PERF_INFO['writes_per_sec'],
            'reads_per_sec': PERF_INFO['reads_per_sec'],
            'input_per_sec': PERF_INFO['input_per_sec'],
            'output_per_sec': PERF_INFO['output_per_sec'],
            'usec_per_read_op': PERF_INFO['usec_per_read_op'],
            'usec_per_write_op': PERF_INFO['usec_per_write_op'],
            'queue_depth': PERF_INFO['queue_depth'],
            'replication_capability': 'sync',
            'replication_enabled': False,
            'replication_type': [],
            'replication_count': 0,
            'replication_targets': [],
        }
        real_result = self.driver.get_volume_stats(refresh=True)
        self.assertDictEqual(expected_result, real_result)

        # Make sure when refresh=False we are using cached values and not
        # sending additional requests to the array.
        self.array.reset_mock()
        real_result = self.driver.get_volume_stats(refresh=False)
        self.assertDictEqual(expected_result, real_result)
        self.assertFalse(self.array.get_arrays.called)
        self.assertFalse(self.array.get_volumes.called)
        self.assertFalse(self.array.get_hosts.called)
        self.assertFalse(self.array.get_protection_groups.called)


class PureVolumeGroupsTestCase(PureBaseSharedDriverTestCase):
    def setUp(self):
        super(PureVolumeGroupsTestCase, self).setUp()
        self.array.get_arrays.side_effect = self.fake_get_array
        self.ctxt = context.get_admin_context()
        self.driver.db = mock.Mock()
        self.driver.db.group_get = mock.Mock()

    @mock.patch(BASE_DRIVER_OBJ + '._add_volume_to_consistency_group')
    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type')
    def test_add_to_group_if_needed(self, mock_is_cg, mock_add_to_cg):
        mock_is_cg.return_value = False
        volume, vol_name = self.new_fake_vol()
        group, _ = self.new_fake_group()
        volume.group = group
        volume.group_id = group.id

        self.driver._add_to_group_if_needed(volume, vol_name)

        mock_is_cg.assert_called_once_with(group)
        mock_add_to_cg.assert_not_called()

    @mock.patch(BASE_DRIVER_OBJ + '._add_volume_to_consistency_group')
    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type')
    def test_add_to_group_if_needed_with_cg(self, mock_is_cg, mock_add_to_cg):
        mock_is_cg.return_value = True
        volume, vol_name = self.new_fake_vol()
        group, _ = self.new_fake_group()
        volume.group = group
        volume.group_id = group.id

        self.driver._add_to_group_if_needed(volume, vol_name)

        mock_is_cg.assert_called_once_with(group)
        mock_add_to_cg.assert_called_once_with(
            group,
            vol_name
        )

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type')
    def test_create_group(self, mock_is_cg):
        mock_is_cg.return_value = False
        group = fake_group.fake_group_type_obj(None)
        self.assertRaises(
            NotImplementedError,
            self.driver.create_group,
            self.ctxt, group
        )
        mock_is_cg.assert_called_once_with(group)

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type')
    def test_delete_group(self, mock_is_cg):
        mock_is_cg.return_value = False
        group = mock.MagicMock()
        volumes = [fake_volume.fake_volume_obj(None)]
        self.assertRaises(
            NotImplementedError,
            self.driver.delete_group,
            self.ctxt, group, volumes
        )
        mock_is_cg.assert_called_once_with(group)

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type')
    def test_update_group(self, mock_is_cg):
        mock_is_cg.return_value = False
        group = mock.MagicMock()
        self.assertRaises(
            NotImplementedError,
            self.driver.update_group,
            self.ctxt, group
        )
        mock_is_cg.assert_called_once_with(group)

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type')
    def test_create_group_from_src(self, mock_is_cg):
        mock_is_cg.return_value = False
        group = mock.MagicMock()
        volumes = [fake_volume.fake_volume_obj(None)]
        self.assertRaises(
            NotImplementedError,
            self.driver.create_group_from_src,
            self.ctxt, group, volumes
        )
        mock_is_cg.assert_called_once_with(group)

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type')
    def test_create_group_snapshot(self, mock_is_cg):
        mock_is_cg.return_value = False
        group_snapshot = mock.MagicMock()
        snapshots = [fake_snapshot.fake_snapshot_obj(None)]
        self.assertRaises(
            NotImplementedError,
            self.driver.create_group_snapshot,
            self.ctxt, group_snapshot, snapshots
        )
        mock_is_cg.assert_called_once_with(group_snapshot)

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type')
    def test_delete_group_snapshot(self, mock_is_cg):
        mock_is_cg.return_value = False
        group_snapshot = mock.MagicMock()
        snapshots = [fake_snapshot.fake_snapshot_obj(None)]
        self.assertRaises(
            NotImplementedError,
            self.driver.create_group_snapshot,
            self.ctxt, group_snapshot, snapshots
        )
        mock_is_cg.assert_called_once_with(group_snapshot)

    @mock.patch(BASE_DRIVER_OBJ + '.create_consistencygroup')
    @mock.patch('cinder.volume.group_types.get_group_type_specs')
    def test_create_group_with_cg(self, mock_get_specs, mock_create_cg):
        self.driver._is_replication_enabled = True
        mock_get_specs.return_value = '<is> True'
        group = mock.MagicMock()
        self.driver.create_group(self.ctxt, group)
        mock_create_cg.assert_called_once_with(self.ctxt, group, None)
        self.driver._is_replication_enabled = False

    @mock.patch(BASE_DRIVER_OBJ + '.delete_consistencygroup')
    @mock.patch('cinder.volume.group_types.get_group_type_specs')
    def test_delete_group_with_cg(self, mock_get_specs, mock_delete_cg):
        mock_get_specs.return_value = '<is> True'
        group = mock.MagicMock()
        volumes = [fake_volume.fake_volume_obj(None)]
        self.driver.delete_group(self.ctxt, group, volumes)
        mock_delete_cg.assert_called_once_with(self.ctxt,
                                               group,
                                               volumes)

    @mock.patch(BASE_DRIVER_OBJ + '.update_consistencygroup')
    @mock.patch('cinder.volume.group_types.get_group_type_specs')
    def test_update_group_with_cg(self, mock_get_specs, mock_update_cg):
        mock_get_specs.return_value = '<is> True'
        group = mock.MagicMock()
        addvollist = [mock.Mock()]
        remvollist = [mock.Mock()]
        self.driver.update_group(
            self.ctxt,
            group,
            addvollist,
            remvollist
        )
        mock_update_cg.assert_called_once_with(
            self.ctxt,
            group,
            addvollist,
            remvollist
        )

    @mock.patch(BASE_DRIVER_OBJ + '.create_consistencygroup_from_src')
    @mock.patch('cinder.volume.group_types.get_group_type_specs')
    def test_create_group_from_src_with_cg(self, mock_get_specs, mock_create):
        mock_get_specs.return_value = '<is> True'
        group = mock.MagicMock()
        volumes = [mock.Mock()]
        group_snapshot = mock.Mock()
        snapshots = [mock.Mock()]
        source_group = mock.MagicMock()
        source_vols = [mock.Mock()]
        group_type = True

        self.driver.create_group_from_src(
            self.ctxt,
            group,
            volumes,
            group_snapshot,
            snapshots,
            source_group,
            source_vols
        )
        mock_create.assert_called_once_with(
            self.ctxt,
            group,
            volumes,
            group_snapshot,
            snapshots,
            source_group,
            source_vols,
            group_type
        )

    @mock.patch(BASE_DRIVER_OBJ + '.create_cgsnapshot')
    @mock.patch('cinder.volume.group_types.get_group_type_specs')
    def test_create_group_snapshot_with_cg(self, mock_get_specs,
                                           mock_create_cgsnap):
        mock_get_specs.return_value = '<is> True'
        group_snapshot = mock.MagicMock()
        snapshots = [mock.Mock()]

        self.driver.create_group_snapshot(
            self.ctxt,
            group_snapshot,
            snapshots
        )
        mock_create_cgsnap.assert_called_once_with(
            self.ctxt,
            group_snapshot,
            snapshots
        )

    @mock.patch(BASE_DRIVER_OBJ + '.delete_cgsnapshot')
    @mock.patch('cinder.volume.group_types.get_group_type_specs')
    def test_delete_group_snapshot_with_cg(self, mock_get_specs,
                                           mock_delete_cg):
        mock_get_specs.return_value = '<is> True'
        group_snapshot = mock.MagicMock()
        snapshots = [mock.Mock()]

        self.driver.delete_group_snapshot(
            self.ctxt,
            group_snapshot,
            snapshots
        )
        mock_delete_cg.assert_called_once_with(
            self.ctxt,
            group_snapshot,
            snapshots
        )


class PureNVMEDriverTestCase(PureBaseSharedDriverTestCase):
    def setUp(self):
        super(PureNVMEDriverTestCase, self).setUp()
        self.driver = pure.PureNVMEDriver(configuration=self.mock_config)
        self.driver._array = self.array
        self.mock_object(self.driver, '_get_current_array',
                         return_value=self.array)
        self.driver._storage_protocol = 'NVMe-RoCE'
        self.mock_utils = mock.Mock()
        self.driver.transport_type = "rdma"
        self.driver.driver_utils = self.mock_utils
        self.set_pure_hosts = ValidResponse(200, None, 1,
                                            [DotNotation(PURE_HOST.copy())],
                                            {})

    def test_get_host(self):
        good_host = deepcopy(PURE_HOST)
        good_host.update(nqns=[INITIATOR_NQN])
        bad_host = ValidResponse(200, None, 1, [], {})
        self.array.get_hosts.return_value = bad_host
        real_result = self.driver._get_host(self.array, NVME_CONNECTOR)
        self.assertEqual([], real_result)
        hostg = ValidResponse(200, None, 1, [DotNotation(good_host)], {})
        self.array.get_hosts.return_value = hostg
        real_result = self.driver._get_host(self.array, NVME_CONNECTOR)
        self.assertEqual([good_host], real_result)
        self.assert_error_propagates(
            [self.array.get_hosts],
            self.driver._get_host,
            self.array,
            NVME_CONNECTOR,
        )

    def test_get_nguid(self):
        vol = {'created': '2019-01-28T14:16:54Z',
               'name': 'volume-fdc9892f-5af0-47c8-9d4a-5167ac29dc98-cinder',
               'serial': '9714B5CB91634C470002B2C8',
               'size': 3221225472,
               'source': 'volume-a366b1ba-ec27-4ca3-9051-c301b75bc778-cinder'}
        volumes_nguid = ValidResponse(200, None, 1, [DotNotation(vol)], {})
        self.array.get_volumes.return_value = volumes_nguid
        returned_nguid = self.driver._get_nguid(vol['name'])
        expected_nguid = '009714b5cb91634c24a937470002b2c8'
        self.assertEqual(expected_nguid, returned_nguid)

    @mock.patch(NVME_DRIVER_OBJ + "._get_nguid")
    @mock.patch(NVME_DRIVER_OBJ + "._get_wwn")
    @mock.patch(NVME_DRIVER_OBJ + "._connect")
    @mock.patch(NVME_DRIVER_OBJ + "._get_target_nvme_ports")
    def test_initialize_connection(
        self, mock_get_nvme_ports, mock_connection, mock_get_wwn,
        mock_get_nguid
    ):
        vol, vol_name = self.new_fake_vol()
        nvme_ports = ValidResponse(200, None, 4, [DotNotation(NVME_PORTS[x])
                                                  for x in range(8)], {})
        mock_get_nvme_ports.return_value = nvme_ports.items
        mock_get_wwn.return_value = "3624a93709714b5cb91634c470002b2c8"
        mock_get_nguid.return_value = "0009714b5cb916324a9374c470002b2c8"
        mock_connection.return_value = CONN.items
        result = deepcopy(NVME_CONNECTION_INFO)
        real_result = self.driver.initialize_connection(vol, NVME_CONNECTOR)
        self.maxDiff = None
        self.assertDictEqual(result, real_result)
        mock_get_nvme_ports.assert_called_with(self.array)
        mock_connection.assert_called_with(
            self.array, vol_name, NVME_CONNECTOR
        )
        self.assert_error_propagates(
            [mock_get_nvme_ports, mock_connection],
            self.driver.initialize_connection,
            vol,
            NVME_CONNECTOR,
        )

    @mock.patch(NVME_DRIVER_OBJ + "._get_nguid")
    @mock.patch(NVME_DRIVER_OBJ + "._get_wwn")
    @mock.patch(NVME_DRIVER_OBJ + "._connect")
    @mock.patch(NVME_DRIVER_OBJ + "._get_target_nvme_ports")
    def test_initialize_connection_ipv6(
        self, mock_get_nvme_ports, mock_connection, mock_get_wwn,
        mock_get_nguid
    ):
        vol, vol_name = self.new_fake_vol()
        nvme_ports = ValidResponse(200, None, 4,
                                   [DotNotation(NVME_PORTS[x])
                                    for x in range(8)], {})
        mock_get_nvme_ports.return_value = nvme_ports.items
        mock_get_wwn.return_value = "3624a93709714b5cb91634c470002b2c8"
        mock_get_nguid.return_value = "0009714b5cb916324a9374c470002b2c8"
        mock_connection.return_value = CONN.items
        self.mock_config.pure_nvme_cidr = NVME_CIDR_V6
        result = deepcopy(NVME_CONNECTION_INFO_V6)
        real_result = self.driver.initialize_connection(vol, NVME_CONNECTOR)
        self.maxDiff = None
        self.assertDictEqual(result, real_result)
        mock_get_nvme_ports.assert_called_with(self.array)
        mock_connection.assert_called_with(
            self.array, vol_name, NVME_CONNECTOR
        )
        self.assert_error_propagates(
            [mock_get_nvme_ports, mock_connection],
            self.driver.initialize_connection,
            vol,
            NVME_CONNECTOR,
        )

    @mock.patch(NVME_DRIVER_OBJ + "._get_nguid")
    @mock.patch(NVME_DRIVER_OBJ + "._get_wwn")
    @mock.patch(NVME_DRIVER_OBJ + "._connect")
    @mock.patch(NVME_DRIVER_OBJ + "._get_target_nvme_ports")
    def test_initialize_connection_uniform_ac(
        self, mock_get_nvme_ports, mock_connection, mock_get_wwn,
        mock_get_nguid
    ):
        repl_extra_specs = {
            "replication_type": "<in> sync",
            "replication_enabled": "<is> true",
        }
        vol, vol_name = self.new_fake_vol(type_extra_specs=repl_extra_specs)
        nvme_p = ValidResponse(200, None, 8,
                               [DotNotation(NVME_PORTS[x])
                                for x in range(8)], {})
        ac_nvme_p = ValidResponse(200, None, 8,
                                  [DotNotation(AC_NVME_PORTS[x])
                                   for x in range(8)], {})
        mock_get_nvme_ports.side_effect = [nvme_p.items, ac_nvme_p.items]
        mock_get_wwn.return_value = "3624a93709714b5cb91634c470002b2c8"
        mock_get_nguid.return_value = "0009714b5cb916324a9374c470002b2c8"
        mock_connection.side_effect = lambda *args, **kwargs: \
            CONN.items if args and args[0] == self.array else AC_CONN.items
        result = deepcopy(NVME_CONNECTION_INFO_AC)
        self.driver._is_active_cluster_enabled = True
        mock_secondary = mock.MagicMock()
        self.driver._uniform_active_cluster_target_arrays = [mock_secondary]
        real_result = self.driver.initialize_connection(vol, NVME_CONNECTOR)
        self.assertDictEqual(result, real_result)
        mock_get_nvme_ports.assert_has_calls(
            [
                mock.call(self.array),
                mock.call(mock_secondary),
            ]
        )
        mock_connection.assert_has_calls(
            [
                mock.call(self.array, vol_name, NVME_CONNECTOR),
                mock.call(
                    mock_secondary, vol_name, NVME_CONNECTOR),
            ]
        )

    @mock.patch(NVME_DRIVER_OBJ + "._get_nguid")
    @mock.patch(NVME_DRIVER_OBJ + "._get_wwn")
    @mock.patch(NVME_DRIVER_OBJ + "._connect")
    @mock.patch(NVME_DRIVER_OBJ + "._get_target_nvme_ports")
    def test_initialize_connection_uniform_ac_cidr(
        self, mock_get_nvme_ports, mock_connection, mock_get_wwn,
        mock_get_nguid
    ):
        repl_extra_specs = {
            "replication_type": "<in> sync",
            "replication_enabled": "<is> true",
        }
        nvme_p = ValidResponse(200, None, 8, [DotNotation(NVME_PORTS[x])
                                              for x in range(8)], {})
        ac_nvme_p = ValidResponse(200, None, 8, [DotNotation(AC_NVME_PORTS[x])
                                                 for x in range(8)], {})
        vol, vol_name = self.new_fake_vol(type_extra_specs=repl_extra_specs)
        mock_get_nvme_ports.side_effect = [nvme_p.items, ac_nvme_p.items]
        mock_get_wwn.return_value = "3624a93709714b5cb91634c470002b2c8"
        mock_get_nguid.return_value = "0009714b5cb916324a9374c470002b2c8"
        mock_connection.side_effect = lambda *args, **kwargs: \
            CONN.items if args and args[0] == self.array else AC_CONN.items
        result = deepcopy(NVME_CONNECTION_INFO_AC_FILTERED)
        self.driver._is_active_cluster_enabled = True
        # Set up some CIDRs to block: this will block only one of the
        # get four+three results back
        self.driver.configuration.pure_nvme_cidr = NVME_CIDR_FILTERED
        mock_secondary = mock.MagicMock()
        self.driver._uniform_active_cluster_target_arrays = [mock_secondary]

        real_result = self.driver.initialize_connection(vol, NVME_CONNECTOR)
        self.assertDictEqual(result, real_result)
        mock_get_nvme_ports.assert_has_calls(
            [
                mock.call(self.array),
                mock.call(mock_secondary),
            ]
        )
        mock_connection.assert_has_calls(
            [
                mock.call(self.array, vol_name, NVME_CONNECTOR),
                mock.call(mock_secondary, vol_name, NVME_CONNECTOR),
            ]
        )

    @mock.patch(NVME_DRIVER_OBJ + "._get_nguid")
    @mock.patch(NVME_DRIVER_OBJ + "._get_wwn")
    @mock.patch(NVME_DRIVER_OBJ + "._connect")
    @mock.patch(NVME_DRIVER_OBJ + "._get_target_nvme_ports")
    def test_initialize_connection_uniform_ac_cidrs(
        self, mock_get_nvme_ports, mock_connection, mock_get_wwn,
        mock_get_nguid
    ):
        repl_extra_specs = {
            "replication_type": "<in> sync",
            "replication_enabled": "<is> true",
        }
        vol, vol_name = self.new_fake_vol(type_extra_specs=repl_extra_specs)
        nvme_p = ValidResponse(200, None, 8,
                               [DotNotation(NVME_PORTS[x])
                                for x in range(8)], {})
        ac_nvme_p = ValidResponse(200, None, 8,
                                  [DotNotation(AC_NVME_PORTS[x])
                                   for x in range(8)], {})
        mock_get_nvme_ports.side_effect = [nvme_p.items, ac_nvme_p.items]
        mock_get_wwn.return_value = "3624a93709714b5cb91634c470002b2c8"
        mock_get_nguid.return_value = "0009714b5cb916324a9374c470002b2c8"
        mock_connection.side_effect = lambda *args, **kwargs: \
            CONN.items if args and args[0] == self.array else AC_CONN.items
        result = deepcopy(NVME_CONNECTION_INFO_AC_FILTERED_LIST)
        self.driver._is_active_cluster_enabled = True
        # Set up some CIDRs to block: this will allow only 2 addresses from
        # each host of the ActiveCluster, so we should check that we only
        # get two+two results back
        self.driver.configuration.pure_nvme = NVME_CIDR
        self.driver.configuration.pure_nvme_cidr_list = NVME_CIDRS_FILTERED
        mock_secondary = mock.MagicMock()
        self.driver._uniform_active_cluster_target_arrays = [mock_secondary]

        real_result = self.driver.initialize_connection(vol, NVME_CONNECTOR)
        self.assertDictEqual(result, real_result)
        mock_get_nvme_ports.assert_has_calls(
            [
                mock.call(self.array),
                mock.call(mock_secondary),
            ]
        )
        mock_connection.assert_has_calls(
            [
                mock.call(self.array, vol_name, NVME_CONNECTOR),
                mock.call(mock_secondary, vol_name, NVME_CONNECTOR),
            ]
        )

    @mock.patch(NVME_DRIVER_OBJ + "._get_nguid")
    @mock.patch(NVME_DRIVER_OBJ + "._get_wwn")
    @mock.patch(NVME_DRIVER_OBJ + "._connect")
    @mock.patch(NVME_DRIVER_OBJ + "._get_target_nvme_ports")
    def test_initialize_connection_multipath(
        self, mock_get_nvme_ports, mock_connection, mock_get_wwn,
        mock_get_nguid
    ):
        self.driver.configuration.pure_nvme_transport = "roce"
        vol, vol_name = self.new_fake_vol()
        nvme_ports = ValidResponse(200, None, 4, [DotNotation(NVME_PORTS[x])
                                                  for x in range(8)], {})
        mock_get_nvme_ports.return_value = nvme_ports.items
        mock_get_wwn.return_value = "3624a93709714b5cb91634c470002b2c8"
        mock_get_nguid.return_value = "0009714b5cb916324a9374c470002b2c8"
        mock_connection.return_value = CONN.items
        multipath_connector = deepcopy(NVME_CONNECTOR)
        multipath_connector["multipath"] = True
        result = deepcopy(NVME_CONNECTION_INFO)

        real_result = self.driver.initialize_connection(
            vol, multipath_connector
        )
        self.assertDictEqual(result, real_result)
        mock_get_nvme_ports.assert_called_with(self.array)
        mock_connection.assert_called_with(
            self.array, vol_name, multipath_connector
        )
        multipath_connector["multipath"] = False
        self.driver.initialize_connection(vol, multipath_connector)

    def test_get_target_nvme_ports(self):
        ports = [{'name': 'CT0.ETH4',
                  'wwn': None,
                  'iqn': None,
                  'nqn': TARGET_NQN},
                 {'name': 'CT0.ETH5',
                  'wwn': None,
                  'iqn': TARGET_IQN,
                  'nqn': None},
                 {'name': 'CT0.ETH20',
                  'wwn': None,
                  'iqn': None,
                  'nqn': TARGET_NQN},
                 {'name': 'CT0.FC4',
                  'wwn': TARGET_WWN,
                  'iqn': None,
                  'nqn': TARGET_NQN}]
        interfaces = [
            {'name': 'ct0.eth4', 'services': ['nvme-tcp']},
            {'name': 'ct0.eth5', 'services': ['iscsi']},
            {'name': 'ct0.eth20', 'services': ['nvme-roce']},
            {'name': 'ct0.fc4', 'services': ['nvme-fc']}
        ]
        # Test for the nvme-tcp port
        self.driver.configuration.pure_nvme_transport = "tcp"
        self.array.get_controllers.return_value = CTRL_OBJ
        nvme_interfaces = ValidResponse(200, None, 4,
                                        [DotNotation(interfaces[x])
                                         for x in range(4)], {})
        self.array.get_network_interfaces.return_value = nvme_interfaces
        nvme_ports = ValidResponse(200, None, 4,
                                   [DotNotation(ports[x])
                                    for x in range(4)], {})
        self.array.get_ports.return_value = nvme_ports
        ret = self.driver._get_target_nvme_ports(self.array)
        self.assertEqual([ports[0]], [ret[0]])

        # Test for failure if no NVMe ports
        self.array.get_network_interfaces.return_value = nvme_interfaces
        non_nvme_ports = ValidResponse(200, None, 1,
                                       [DotNotation(ports[1])], {})
        self.array.get_ports.return_value = non_nvme_ports
        self.assertRaises(
            pure.PureDriverException,
            self.driver._get_target_nvme_ports,
            self.array,
        )
        # Test for the nvme-roce port
        self.driver.configuration.pure_nvme_transport = "roce"
        nvme_roce_interface = ValidResponse(200, None, 1,
                                            [DotNotation(interfaces[2])], {})
        self.array.get_network_interfaces.return_value = nvme_roce_interface
        nvme_roce_ports = ValidResponse(200, None, 1,
                                        [DotNotation(ports[2])], {})
        self.array.get_ports.return_value = nvme_roce_ports
        ret = self.driver._get_target_nvme_ports(self.array)
        self.assertEqual([ports[2]], ret)
        # Test for empty dict if only nvme-fc port
        self.driver.configuration.pure_nvme_transport = "roce"
        nvme_fc_interface = ValidResponse(200, None, 1,
                                          [DotNotation(interfaces[3])], {})
        self.array.get_network_interfaces.return_value = nvme_fc_interface
        nvme_fc_ports = ValidResponse(200, None, 1,
                                      [DotNotation(ports[3])], {})
        self.array.get_ports.return_value = nvme_fc_ports
        ret = self.driver._get_target_nvme_ports(self.array)
        self.assertEqual([], ret)

    def test_get_target_nvme_ports_with_no_ports(self):
        # Should raise an exception if there are no ports
        self.array.get_controllers.return_value = CTRL_OBJ
        nvme_no_ports = ValidResponse(200, None, 1, [], {})
        self.array.get_ports.return_value = nvme_no_ports
        self.assertRaises(
            pure.PureDriverException,
            self.driver._get_target_nvme_ports,
            self.array,
        )

    def test_get_target_nvme_ports_with_only_fc_ports(self):
        # Should raise an exception of there are no nvme ports
        self.array.get_controllers.return_value = CTRL_OBJ
        nvme_noports = ValidResponse(200, None, 1, [PORTS_WITHOUT], {})
        self.array.get_ports.return_value = nvme_noports
        self.assertRaises(
            pure.PureDriverException,
            self.driver._get_target_nvme_ports,
            self.array,
        )

    @mock.patch(DRIVER_PATH + ".flasharray.HostPatch")
    @mock.patch(DRIVER_PATH + ".flasharray.HostPost")
    @mock.patch(NVME_DRIVER_OBJ + "._get_host", autospec=True)
    @mock.patch(NVME_DRIVER_OBJ + "._generate_purity_host_name", spec=True)
    def test_connect(self, mock_generate, mock_host,
                     mock_post_host, mock_patch_host):
        vol, vol_name = self.new_fake_vol()

        # Branch where host already exists
        pure_hosts = ValidResponse(200, None, 1,
                                   [DotNotation(PURE_HOST.copy())], {})
        mock_host.return_value = pure_hosts.items
        self.array.post_connections.return_value = CONN
        real_result = self.driver._connect(
            self.array, vol_name, NVME_CONNECTOR
        )
        self.assertEqual([CONNECTION_DATA], real_result)
        mock_host.assert_called_with(
            self.driver, self.array, NVME_CONNECTOR, remote=False
        )
        self.assertFalse(mock_generate.called)
        self.assertFalse(self.array.create_host.called)
        self.array.post_connections.\
            assert_called_with(host_names=[PURE_HOST_NAME],
                               volume_names=[vol_name])

        # Branch where new host is created
        empty_hosts = ValidResponse(200, None, 1,
                                    [], {})
        mock_host.return_value = empty_hosts.items
        mock_generate.return_value = PURE_HOST_NAME
        real_result = self.driver._connect(
            self.array, vol_name, NVME_CONNECTOR
        )
        mock_host.assert_called_with(
            self.driver, self.array, NVME_CONNECTOR, remote=False
        )
        mock_generate.assert_called_with(HOSTNAME)
        self.array.post_hosts.assert_called_with(
            names=[PURE_HOST_NAME], host=mock_post_host()
        )
        self.assertFalse(self.array.set_host.called)
        self.assertEqual([CONNECTION_DATA], real_result)

        mock_generate.reset_mock()
        self.array.reset_mock()
        self.assert_error_propagates(
            [
                mock_host,
                mock_generate,
                self.array.post_connections,
                self.array.post_hosts,
            ],
            self.driver._connect,
            self.array,
            vol_name,
            NVME_CONNECTOR,
        )

        self.mock_config.safe_get.return_value = "oracle-vm-server"

        # Branch where personality is set
        self.driver._connect(self.array, vol_name, NVME_CONNECTOR)
        self.assertEqual([CONNECTION_DATA], real_result)
        self.array.patch_hosts.assert_called_with(
            names=[PURE_HOST_NAME], host=mock_patch_host()
        )

    @mock.patch(DRIVER_PATH + ".LOG")
    @mock.patch(NVME_DRIVER_OBJ + "._get_host", autospec=True)
    def test_connect_already_connected(self, mock_host, mock_logger):
        vol, vol_name = self.new_fake_vol()
        mock_host.return_value = self.set_pure_hosts.items
        self.array.get_connections.return_value = NCONN
        err_rsp = ErrorResponse(400, [DotNotation({'message':
                                'already exists'})], {})
        self.array.post_connections.return_value = err_rsp
        self.array.get_volumes.return_value = MPV
        actual = self.driver._connect(self.array, vol_name, NVME_CONNECTOR)
        mock_logger.debug.\
            assert_called_with('Volume connection already exists for Purity '
                               'host with message: %s',
                               'already exists')
        self.assertEqual(NCONN.items, actual)
        self.assertTrue(self.array.post_connections.called)
        self.assertTrue(bool(self.array.get_connections))

    @mock.patch(NVME_DRIVER_OBJ + "._get_host", autospec=True)
    def test_connect_already_connected_list_hosts_empty(self, mock_host):
        vol, vol_name = self.new_fake_vol()
        mock_host.return_value = self.set_pure_hosts.items
        self.array.get_connections.return_value = CONN
        err_rsp = ErrorResponse(400, [DotNotation({'message':
                                'unknown'})], {})
        self.array.post_connections.return_value = err_rsp
        self.assertRaises(
            pure.PureDriverException,
            self.driver._connect,
            self.array,
            vol_name,
            NVME_CONNECTOR,
        )
        self.assertTrue(self.array.post_connections.called)
        self.assertTrue(bool(self.array.get_connections))

    @mock.patch(NVME_DRIVER_OBJ + "._get_host", autospec=True)
    def test_connect_already_connected_list_hosts_exception(self, mock_host):
        vol, vol_name = self.new_fake_vol()
        hosts = deepcopy(PURE_HOST)
        hosts['name'] = 'utest'
        pure_hosts = ValidResponse(200, None, 1,
                                   [DotNotation(hosts)], {})
        mock_host.return_value = pure_hosts.items
        err_rsp = ErrorResponse(400, [DotNotation({'message':
                                'Unknown Error'})], {})
        self.array.get_connections.return_value = CONN
        self.array.post_connections.return_value = err_rsp
        self.assertRaises(
            pure.PureDriverException,
            self.driver._connect,
            self.array,
            vol_name,
            NVME_CONNECTOR,
        )
        self.assertTrue(self.array.post_connections.called)
        self.assertTrue(bool(self.array.get_connections))

    @mock.patch(NVME_DRIVER_OBJ + "._generate_purity_host_name", spec=True)
    @mock.patch(NVME_DRIVER_OBJ + "._get_host", autospec=True)
    def test_connect_nqn_already_in_use(self, mock_host, mock_hname):
        vol, vol_name = self.new_fake_vol()
        empty_hosts = ValidResponse(200, None, 1,
                                    [], {})
        mock_host.return_value = empty_hosts.items

        mock_hname.return_value = PURE_HOST_NAME
        err_iqn = ErrorResponse(400, [DotNotation({'message':
                                'already in use'})], {})
        self.array.post_hosts.return_value = err_iqn

        # Because we mocked out retry make sure we are raising the right
        # exception to allow for retries to happen.
        self.assertRaises(
            pure.PureRetryableException,
            self.driver._connect,
            self.array,
            vol_name,
            NVME_CONNECTOR,
        )

    @mock.patch(NVME_DRIVER_OBJ + "._generate_purity_host_name", spec=True)
    @mock.patch(NVME_DRIVER_OBJ + "._get_host", autospec=True)
    def test_connect_create_host_already_exists(self, mock_host, mock_hname):
        vol, vol_name = self.new_fake_vol()
        mock_host.return_value = []

        mock_hname.return_value = PURE_HOST_NAME
        err_iqn = ErrorResponse(400, [DotNotation({'message':
                                'already exists'})], {})
        self.array.post_hosts.return_value = err_iqn

        # Because we mocked out retry make sure we are raising the right
        # exception to allow for retries to happen.
        self.assertRaises(
            pure.PureRetryableException,
            self.driver._connect,
            self.array,
            vol_name,
            NVME_CONNECTOR,
        )
