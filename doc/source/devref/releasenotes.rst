..
      Copyright 2015 Intel Corporation
      All Rights Reserved.

      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

Release notes
=============

The release notes for a patch should be included in the patch.

If the following applies to the patch, a release note is required:

* Upgrades

  * The deployer needs to take an action when upgrading
  * A new config option is added that the deployer should consider changing
    from the default
  * A configuration option is deprecated or removed

* Features

  * A new feature or driver is implemented
  * Feature is deprecated or removed
  * Current behavior is changed

* Bugs

  * A security bug is fixed
  * A long-standing or important bug is fixed

* APIs

  * REST API changes

Cinder uses `reno <http://docs.openstack.org/developer/reno/usage.html>`_ to
generate release notes. Please read the docs for details. In summary, use

.. code-block:: bash

  $ tox -e venv -- reno new <bug-,bp-,whatever>

Then edit the sample file that was created and push it with your change.

To see the results:

.. code-block:: bash

  $ git commit  # Commit the change because reno scans git log.

  $ tox -e releasenotes

Then look at the generated release notes files in releasenotes/build/html in
your favorite browser.
