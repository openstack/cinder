..
      Copyright (C) 2018 Lenovo, Inc.

      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

============================
Cinder Driver Support Matrix
============================

The following support matrix reflects the drivers that are currently
available or are available in
`Cinder's driver tree <https://github.com/openstack/cinder/tree/master/cinder/volume/drivers>`_
at the time of release.

.. note::

  This matrix replaces the old wiki based version of the Cinder Support
  Matrix as there was no way to ensure the wiki version was properly
  maintained.  The old matrix will be left for reference but
  this matrix should be treated as the correct state of Cinder.

Required Driver Functions
~~~~~~~~~~~~~~~~~~~~~~~~~

There are a number of functions that are required to be accepted as
a Cinder driver.  Rather than list all the required functionality in the
matrix we include the list of required functions here for reference.

* Create Volume
* Delete Volume
* Attach Volume
* Detach Volume
* Extend Volume
* Create Snapshot
* Delete Snapshot
* Create Volume from Snapshot
* Create Volume from Volume (clone)
* Create Image from Volume
* Volume Migration (host assisted)

.. note::

  Since the above functions are required their support is assumed and the
  matrix only includes support for optional functionality.

.. support_matrix:: support-matrix.ini

