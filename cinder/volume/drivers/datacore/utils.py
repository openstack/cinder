# Copyright (c) 2017 DataCore Software Corp. All Rights Reserved.
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

"""Utilities and helper functions."""

from oslo_utils import netutils
import six


def build_network_address(host, port):
    """Combines the specified host name or IP address with the specified port.

    :param host: Host name or IP address in presentation (string) format
    :param port: Port number
    :return: The host name or IP address and port combination;
             IPv6 addresses are enclosed in the square brackets
    """
    if netutils.is_valid_ipv6(host):
        return '[%s]:%s' % (host, port)
    else:
        return '%s:%s' % (host, port)


def get_first(predicate, source):
    """Searches for an item that matches the conditions.

    :param predicate: Defines the conditions of the item to search for
    :param source: Iterable collection of items
    :return: The first item that matches the conditions defined by the
             specified predicate, if found; otherwise StopIteration is raised
    """

    return six.next(item for item in source if predicate(item))


def get_first_or_default(predicate, source, default):
    """Searches for an item that matches the conditions.

    :param predicate: Defines the conditions of the item to search for
    :param source: Iterable collection of items
    :param default: Value that is returned if the iterator is exhausted
    :return: The first item that matches the conditions defined by the
             specified predicate, if found; otherwise the default value
    """

    try:
        return get_first(predicate, source)
    except StopIteration:
        return default


def get_distinct_by(key, source):
    """Finds distinct items for the key and returns the result in a list.

    :param key: Function computing a key value for each item
    :param source: Iterable collection of items
    :return: The list of distinct by the key value items
    """

    seen_keys = set()
    return [item for item in source
            if key(item) not in seen_keys and not seen_keys.add(key(item))]
