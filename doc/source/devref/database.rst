..
      Copyright 2010-2011 United States Government as represented by the
      Administrator of the National Aeronautics and Space Administration.
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

The Database Layer
==================

The :mod:`cinder.db.api` Module
-------------------------------

.. automodule:: cinder.db.api
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:


The Sqlalchemy Driver
---------------------

The :mod:`cinder.db.sqlalchemy.api` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: cinder.db.sqlalchemy.api
    :noindex:

The :mod:`cinder.db.sqlalchemy.models` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: cinder.db.sqlalchemy.models
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`cinder.db.sqlalchemy.session` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: cinder.db.sqlalchemy.session
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:


Tests
-----

Tests are lacking for the db api layer and for the sqlalchemy driver.
Failures in the drivers would be detected in other test cases, though.
