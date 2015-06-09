# Copyright 2011 OpenStack Foundation
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


def compare_links(actual, expected):
    """Compare xml atom links."""

    return compare_tree_to_dict(actual, expected, ('rel', 'href', 'type'))


def compare_media_types(actual, expected):
    """Compare xml media types."""

    return compare_tree_to_dict(actual, expected, ('base', 'type'))


def compare_tree_to_dict(actual, expected, keys):
    """Compare parts of lxml.etree objects to dicts."""

    for elem, data in zip(actual, expected):
        for key in keys:
            if elem.get(key) != data.get(key):
                return False
    return True
