===================================
Manage Block Storage service quotas
===================================

As an administrative user, you can update the OpenStack Block
Storage service quotas for a project. You can also update the quota
defaults for a new project.

**Block Storage quotas**

===================  =============================================
 Property name          Defines the number of
===================  =============================================
 gigabytes              Volume gigabytes allowed for each project.
 snapshots              Volume snapshots allowed for each project.
 volumes                Volumes allowed for each project.
===================  =============================================

View Block Storage quotas
~~~~~~~~~~~~~~~~~~~~~~~~~

Administrative users can view Block Storage service quotas.

#. Obtain the project ID:

   .. code-block:: console

      $ project_id=$(openstack project show -f value -c id PROJECT_NAME)

#. List the default quotas for a project:

   .. code-block:: console

      $ openstack quota show --default $OS_TENANT_ID
      +-----------------------+-------+
      | Field                 | Value |
      +-----------------------+-------+
      | backup-gigabytes      | 1000  |
      | backups               | 10    |
      | cores                 | 20    |
      | fixed-ips             | -1    |
      | floating-ips          | 50    |
      | gigabytes             | 1000  |
      | gigabytes_lvmdriver-1 | -1    |
      | health_monitors       | None  |
      | injected-file-size    | 10240 |
      | injected-files        | 5     |
      | injected-path-size    | 255   |
      | instances             | 10    |
      | key-pairs             | 100   |
      | l7_policies           | None  |
      | listeners             | None  |
      | load_balancers        | None  |
      | location              | None  |
      | name                  | None  |
      | networks              | 10    |
      | per-volume-gigabytes  | -1    |
      | pools                 | None  |
      | ports                 | 50    |
      | project               | None  |
      | project_id            | None  |
      | properties            | 128   |
      | ram                   | 51200 |
      | rbac_policies         | 10    |
      | routers               | 10    |
      | secgroup-rules        | 100   |
      | secgroups             | 10    |
      | server-group-members  | 10    |
      | server-groups         | 10    |
      | snapshots             | 10    |
      | snapshots_lvmdriver-1 | -1    |
      | subnet_pools          | -1    |
      | subnets               | 10    |
      | volumes               | 10    |
      | volumes_lvmdriver-1   | -1    |
      +-----------------------+-------+

.. note::

   Listing default quotas with the OpenStack command line client will
   provide all quotas for storage and network services. Previously, the
   :command:`cinder quota-defaults` command would list only storage
   quotas. You can use `PROJECT_ID` or `$OS_TENANT_NAME` arguments to
   show Block Storage service quotas. If the `PROJECT_ID` argument returns
   errors in locating resources, use `$OS_TENANT_NAME`.

#. View Block Storage service quotas for a project:

   .. code-block:: console

      $ openstack quota show $OS_TENANT_ID
      +-----------------------+-------+
      | Field                 | Value |
      +-----------------------+-------+
      | backup-gigabytes      | 1000  |
      | backups               | 10    |
      | cores                 | 20    |
      | fixed-ips             | -1    |
      | floating-ips          | 50    |
      | gigabytes             | 1000  |
      | gigabytes_lvmdriver-1 | -1    |
      | health_monitors       | None  |
      | injected-file-size    | 10240 |
      | injected-files        | 5     |
      | injected-path-size    | 255   |
      | instances             | 10    |
      | key-pairs             | 100   |
      | l7_policies           | None  |
      | listeners             | None  |
      | load_balancers        | None  |
      | location              | None  |
      | name                  | None  |
      | networks              | 10    |
      | per-volume-gigabytes  | -1    |
      | pools                 | None  |
      | ports                 | 50    |
      | project               | None  |
      | project_id            | None  |
      | properties            | 128   |
      | ram                   | 51200 |
      | rbac_policies         | 10    |
      | routers               | 10    |
      | secgroup-rules        | 100   |
      | secgroups             | 10    |
      | server-group-members  | 10    |
      | server-groups         | 10    |
      | snapshots             | 10    |
      | snapshots_lvmdriver-1 | -1    |
      | subnet_pools          | -1    |
      | subnets               | 10    |
      | volumes               | 10    |
      | volumes_lvmdriver-1   | -1    |
      +-----------------------+-------+


#. Show the current usage of a per-project quota:

   .. code-block:: console

      $ cinder quota-usage $project_id
      +-----------------------+--------+----------+-------+
      | Type                  | In_use | Reserved | Limit |
      +-----------------------+--------+----------+-------+
      | backup_gigabytes      | 0      | 0        | 1000  |
      | backups               | 0      | 0        | 10    |
      | gigabytes             | 0      | 0        | 1000  |
      | gigabytes_lvmdriver-1 | 0      | 0        | -1    |
      | per_volume_gigabytes  | 0      | 0        | -1    |
      | snapshots             | 0      | 0        | 10    |
      | snapshots_lvmdriver-1 | 0      | 0        | -1    |
      | volumes               | 0      | 0        | 10    |
      | volumes_lvmdriver-1   | 0      | 0        | -1    |
      +-----------------------+--------+----------+-------+


Edit and update Block Storage service quotas
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Administrative users can edit and update Block Storage
service quotas.

#. To update a default value for a new project,
   update the property in the :guilabel:`cinder.quota`
   section of the ``/etc/cinder/cinder.conf`` file.
   For more information, see the `Block Storage service
   <https://docs.openstack.org/ocata/config-reference/block-storage.html>`_
   in OpenStack Configuration Reference.

#. To update Block Storage service quotas for an existing project

   .. code-block:: console

      $ openstack quota set --QUOTA_NAME QUOTA_VALUE PROJECT_ID

   Replace ``QUOTA_NAME`` with the quota that is to be updated,
   ``QUOTA_VALUE`` with the required new value. Use the :command:`openstack quota show`
   command with ``PROJECT_ID``, which is the required project ID.

   For example:

   .. code-block:: console

      $ openstack quota set --volumes 15  $project_id
      $ openstack quota show $project_id
      +-----------------------+----------------------------------+
      | Field                 | Value                            |
      +-----------------------+----------------------------------+
      | backup-gigabytes      | 1000                             |
      | backups               | 10                               |
      | cores                 | 20                               |
      | fixed-ips             | -1                               |
      | floating-ips          | 29                               |
      | gigabytes             | 1000                             |
      | gigabytes_lvmdriver-1 | -1                               |
      | health_monitors       | None                             |
      | injected-file-size    | 10240                            |
      | injected-files        | 5                                |
      | injected-path-size    | 255                              |
      | instances             | 10                               |
      | key-pairs             | 100                              |
      | l7_policies           | None                             |
      | listeners             | None                             |
      | load_balancers        | None                             |
      | location              | None                             |
      | name                  | None                             |
      | networks              | 10                               |
      | per-volume-gigabytes  | -1                               |
      | pools                 | None                             |
      | ports                 | 50                               |
      | project               | e436339c7f9c476cb3120cf3b9667377 |
      | project_id            | None                             |
      | properties            | 128                              |
      | ram                   | 51200                            |
      | rbac_policies         | 10                               |
      | routers               | 10                               |
      | secgroup-rules        | 100                              |
      | secgroups             | 10                               |
      | server-group-members  | 10                               |
      | server-groups         | 10                               |
      | snapshots             | 10                               |
      | snapshots_lvmdriver-1 | -1                               |
      | subnet_pools          | -1                               |
      | subnets               | 10                               |
      | volumes               | 15                               |
      | volumes_lvmdriver-1   | -1                               |
      +-----------------------+----------------------------------+

#. To clear per-project quota limits:

   .. code-block:: console

      $ cinder quota-delete PROJECT_ID
