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

.. _release-notes:

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

Bugs
----

For bug fixes, release notes must include the bug number in Launchpad with a
link to it as a RST link like in the following example:

.. code-block:: yaml

   ---
   fixes:
     - |
       `Bug #1889758 <https://bugs.launchpad.net/cinder/+bug/1889758>`_: Fix
       revert to snapshot not working for non admin users when using the
       snapshot's name.

Drivers
-------

For release notes related to a specific driver -be it volume, backup, or
zone manager- the release note line must start with ``<driver-name> driver:``.
For example:

.. code-block:: yaml

   ---
   features:
     - |
       RBD driver: Add support for volume manage and unmanage operations.

When fixing a driver bug we must not only have the driver name prefix but also
the bug number and link:

.. code-block:: yaml

  ---
  fixes:
    - |
      Brocade driver `bug #1866860
      <https://bugs.launchpad.net/cinder/+bug/1889758>`_: Fix
      ``AttributeError`` when using ``REST_HTTP`` or ``REST_HTTPS`` as the
      ``fc_southbound_protocol`` option and an exception is raised by the
      client.

There are times when a bug affects multiple drivers.  In such a cases we must
list each of the driver as an independent item following above rules:

.. code-block:: yaml

  ---
  fixes:
    - |
      Unity driver `bug #1881108
      <https://bugs.launchpad.net/cinder/+bug/1881108>`_: Fix leaving leftover
      devices on the host when validation of the attached volume fails on some
      cloning cases and create volume from snapshot.
    - |
      Kaminario driver `bug #1881108
      <https://bugs.launchpad.net/cinder/+bug/1881108>`_: Fix leaving leftover
      devices on the host when validation of the attached volume fails on some
      cloning cases and create volume from snapshot.

Creating the note
-----------------

Cinder uses `reno <https://docs.openstack.org/reno/latest/>`_ to
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
