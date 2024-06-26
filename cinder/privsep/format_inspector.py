# Copyright 2024 Red Hat, Inc
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
Helpers for the image format_inspector.
"""


from cinder.image import format_inspector
import cinder.privsep


@cinder.privsep.sys_admin_pctxt.entrypoint
def get_format_if_safe(path, allow_qcow2_backing_file):
    """Returns a str format name if the format is safe, otherwise None"""
    return _get_format_if_safe(path, allow_qcow2_backing_file)


def _get_format_if_safe(path, allow_qcow2_backing_file):
    """Returns a str format name if the format is safe, otherwise None"""
    inspector = format_inspector.detect_file_format(path)
    format_name = str(inspector)
    safe = inspector.safety_check()
    if not safe and format_name == 'qcow2' and allow_qcow2_backing_file:
        safe = inspector.safety_check_allow_backing_file()
    if safe:
        return format_name
