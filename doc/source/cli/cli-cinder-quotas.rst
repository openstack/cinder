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

      $ PROJECT_ID=$(openstack project show -f value -c id PROJECT_NAME)

#. List the default quotas for a project:

   .. code-block:: console

      $ openstack quota show --default $PROJECT_ID
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
   quotas. You can use `$PROJECT_ID` or `$PROJECT_NAME` arguments to
   show Block Storage service quotas. If the `$PROJECT_ID` argument returns
   errors in locating resources, use `$PROJECT_NAME`.

#. View Block Storage service quotas for a project:

   .. code-block:: console

      $ openstack quota show --volume $PROJECT_ID
      +-----------------------+-------+
      | Resource              | Limit |
      +-----------------------+-------+
      | volumes               |    10 |
      | snapshots             |    10 |
      | gigabytes             |  1000 |
      | backups               |    10 |
      | volumes_lvmdriver-1   |    -1 |
      | gigabytes_lvmdriver-1 |    -1 |
      | snapshots_lvmdriver-1 |    -1 |
      | volumes___DEFAULT__   |    -1 |
      | gigabytes___DEFAULT__ |    -1 |
      | snapshots___DEFAULT__ |    -1 |
      | groups                |    10 |
      | backup-gigabytes      |  1000 |
      | per-volume-gigabytes  |    -1 |
      +-----------------------+-------+

#. Show the current usage of a per-project quota:

   .. code-block:: console

      $ openstack quota show --volume --usage $PROJECT_ID
      +-----------------------+-------+--------+----------+
      | Resource              | Limit | In Use | Reserved |
      +-----------------------+-------+--------+----------+
      | volumes               |    10 |      1 |        0 |
      | snapshots             |    10 |      0 |        0 |
      | gigabytes             |  1000 |      1 |        0 |
      | backups               |    10 |      0 |        0 |
      | volumes_lvmdriver-1   |    -1 |      1 |        0 |
      | gigabytes_lvmdriver-1 |    -1 |      1 |        0 |
      | snapshots_lvmdriver-1 |    -1 |      0 |        0 |
      | volumes___DEFAULT__   |    -1 |      0 |        0 |
      | gigabytes___DEFAULT__ |    -1 |      0 |        0 |
      | snapshots___DEFAULT__ |    -1 |      0 |        0 |
      | groups                |    10 |      0 |        0 |
      | backup-gigabytes      |  1000 |      0 |        0 |
      | per-volume-gigabytes  |    -1 |      0 |        0 |
      +-----------------------+-------+--------+----------+


Edit and update Block Storage service quotas
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Administrative users can edit and update Block Storage
service quotas.

#. To update the default quota values for the initial deployment,
   update the values of the :guilabel:`quota_*` config options in the
   ``/etc/cinder/cinder.conf`` file.
   For more information, see the :doc:`Block Storage service
   configuration </configuration/index>`.

   .. note::
      The values of the :guilabel:`quota_*` config options are only used at
      the initial database sync in the initial deployment. If you want to
      change a default value for a new project, see the following.

   To update a default value for a new project, set
   ``use_default_quota_class = True`` (which is the default setting) in the
   :guilabel:`DEFAULT` section of the ``/etc/cinder/cinder.conf`` file, and
   run the command as the following.

   .. code-block:: console

      $ openstack quota set --class default --QUOTA_NAME QUOTA_VALUE

   Replace ``QUOTA_NAME`` with the quota that is to be updated,
   ``QUOTA_VALUE`` with the required new value.

#. To update Block Storage service quotas for an existing project

   .. code-block:: console

      $ openstack quota set --QUOTA_NAME QUOTA_VALUE PROJECT_ID

   Replace ``QUOTA_NAME`` with the quota that is to be updated,
   ``QUOTA_VALUE`` with the required new value. Use the :command:`openstack quota show`
   command with ``PROJECT_ID``, which is the required project ID.

   For example:

   .. code-block:: console

      $ openstack quota set --volumes 15 $PROJECT_ID
      $ openstack quota show $PROJECT_ID
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

      $ openstack quota delete --volume $PROJECT_ID
