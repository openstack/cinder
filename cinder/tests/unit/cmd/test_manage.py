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

from io import StringIO
from pathlib import Path
from unittest import mock

from cinder.cmd.manage import SapCommands
from cinder import coordination
from cinder.tests.unit import test


class SapCommandsTests(test.TestCase):
    def setUp(self):
        super(SapCommandsTests, self).setUp()
        mock_coordinator = mock.Mock()
        # random directory such that directory operations do not fail
        mock_coordinator._dir = "/tmp"
        coordination.COORDINATOR.coordinator = mock_coordinator

    def test_clean_old_lock_files(self):
        sap_commands = SapCommands()
        fnames = [
            "cinder-nfs-4291c6b3-dd2a-4e9b-ad76-7572a2ce0971",
            "cinder-4291c6b3-dd2a-4e9b-ad76-7572a2ce0971",
            "cinder-attachment_update-4291c6b3-dd2a-4e9b-ad76-7572a2ce0971-"
            "no-match.txt"
        ]
        mock_files = []
        for fname in fnames:
            mock_file1 = mock.MagicMock(spec=Path)
            mock_file1.is_file.return_value = True
            mock_file1.name = fname
            mock_files.append(mock_file1)
        with mock.patch('sys.stdout', new_callable=StringIO) as mock_stdout,\
                mock.patch("pathlib.Path.iterdir", return_value=mock_files):
            sap_commands.clean_old_lock_files(dry_run=False, verbose=True,
                                              batch_size=10000)
            print_output = mock_stdout.getvalue()
        self.assertIn("Found 3 lock files", print_output)
