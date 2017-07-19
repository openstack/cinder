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

Cinder System Architecture
==========================

The Cinder Block Storage Service is intended to be ran on one or more nodes.

Cinder uses a sql-based central database that is shared by all Cinder services in the system.  The amount and depth of the data fits into a sql database quite well.  For small deployments this seems like an optimal solution.  For larger deployments, and especially if security is a concern, cinder will be moving towards multiple data stores with some kind of aggregation system.

Components
----------

Below you will find a brief explanation of the different components.

::

                                                  /- ( LDAP )
                              [ Auth Manager ] ---
                                     |            \- ( DB )
                                     |
                                     |
                    cinderclient     |
                   /             \   |                   /- [ scheduler ] -- [ volume ] -- ( iSCSI )
 [ Web Dashboard ]-               -[ api ] -- < AMQP > --
                   \             /   |                   \- [ backup ]
                    novaclient       |
                                     |
                                     |
                                     |
                                  < REST >


* DB: sql database for data storage. Used by all components (LINKS NOT SHOWN).
* Web Dashboard: potential external component that talks to the api.
* api: component that receives http requests, converts commands and communicates with other components via the queue or http.
* Auth Manager: component responsible for users/projects/and roles.  Can backend to DB or LDAP.  This is not a separate binary, but rather a python class that is used by most components in the system.
* scheduler: decides which host gets each volume.
* volume: manages dynamically attachable block devices.
* backup: manages backups of block storage devices.
