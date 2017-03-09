#  Copyright (c) 2016 IBM Corporation
#  All Rights Reserved.
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
import os
import tempfile

from oslo_log import log as logging

LOG = logging.getLogger(__name__)


class CertificateCollector(object):

    def __init__(self, paths=None):
        self.paths_checked = [
            '/etc/ssl/certs', '/etc/ssl/certs/xiv', '/etc/pki', '/etc/pki/xiv']
        if paths:
            self.paths_checked.extend(paths)
        self.paths_checked = set(self.paths_checked)
        self.tmp_fd = None
        self.tmp_path = None

    def collect_certificate(self):
        self.tmp_fd, self.tmp_path = tempfile.mkstemp()
        for path in self.paths_checked:
            if os.path.exists(path) and os.path.isdir(path):
                dir_contents = os.listdir(path)
                for f in dir_contents:
                    full_path = os.path.join(path, f)
                    if (os.path.isfile(full_path) and
                            f.startswith('XIV') and
                            f.endswith('.pem')):
                        try:
                            cert_file = open(full_path, 'r')
                            os.write(self.tmp_fd, cert_file.read())
                            cert_file.close()
                        except Exception:
                            LOG.exception("Failed to process certificate")
        os.close(self.tmp_fd)
        fsize = os.path.getsize(self.tmp_path)
        if fsize > 0:
            return self.tmp_path
        else:
            return None

    def free_certificate(self):
        if self.tmp_path:
            try:
                os.remove(self.tmp_path)
            except Exception:
                pass
            self.tmp_path = None
