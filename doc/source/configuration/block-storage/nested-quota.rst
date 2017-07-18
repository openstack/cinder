=============
Nested quotas
=============

Nested quota is a change in how OpenStack services (such as Block Storage and
Compute) handle their quota resources by being hierarchy-aware. The main
reason for this change is to fully appreciate the hierarchical multi-tenancy
concept, which was introduced in keystone in the Kilo release.

Once you have a project hierarchy created in keystone, nested quotas let you
define how much of a project's quota you want to give to its subprojects. In
that way, hierarchical projects can have hierarchical quotas (also known as
nested quotas).

Projects and subprojects have similar behaviors, but they differ from each
other when it comes to default quota values. The default quota value for
resources in a subproject is 0, so that when a subproject is created it will
not consume all of its parent's quota.

In order to keep track of how much of each quota was allocated to a
subproject, a column ``allocated`` was added to the quotas table. This column
is updated after every delete and update quota operation.

This example shows you how to use nested quotas.

.. note::

   Assume that you have created a project hierarchy in keystone, such as
   follows:

   .. code-block:: console

      +-----------+
      |           |
      |     A     |
      |    / \    |
      |   B   C   |
      |  /        |
      | D         |
      +-----------+

Getting default quotas
~~~~~~~~~~~~~~~~~~~~~~

#. Get the quota for root projects.

   Use the :command:`openstack quota show` command and specify:

   - The ``PROJECT`` of the relevant project. In this case, the name of
     project A.

     .. code-block:: console

        $ openstack quota show PROJECT
        +----------------------+-------+
        | Field                | Value |
        +----------------------+-------+
        | ...                  | ...   |
        | backup_gigabytes     | 1000  |
        | backups              | 10    |
        | gigabytes            | 1000  |
        | per_volume_gigabytes | -1    |
        | snapshots            | 10    |
        | volumes              | 10    |
        +----------------------+-------+

     .. note::

        This command returns the default values for resources.
        This is because the quotas for this project were not explicitly set.

#. Get the quota for subprojects.

   In this case, use the same :command:`openstack quota show` command and
   specify:

   - The ``PROJECT`` of the relevant project. In this case the name of
     project B, which is a child of A.

     .. code-block:: console

        $ openstack quota show PROJECT
        +----------------------+-------+
        | Field                | Value |
        +----------------------+-------+
        | ...                  | ...   |
        | backup_gigabytes     | 0     |
        | backups              | 0     |
        | gigabytes            | 0     |
        | per_volume_gigabytes | 0     |
        | snapshots            | 0     |
        | volumes              | 0     |
        +----------------------+-------+

     .. note::

        In this case, 0 was the value returned as the quota for all the
        resources. This is because project B is a subproject of A, thus,
        the default quota value is 0, so that it will not consume all the
        quota of its parent project.

Setting the quotas for subprojects
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Now that the projects were created, assume that the admin of project B wants
to use it. First of all, you need to set the quota limit of the project,
because as a subproject it does not have quotas allocated by default.

In this example, when all of the parent project is allocated to its
subprojects the user will not be able to create more resources in the parent
project.

#. Update the quota of B.

   Use the :command:`openstack quota set` command and specify:

   - The ``PROJECT`` of the relevant project.
     In this case the name of project B.

   - The ``--volumes`` option, followed by the number to which you wish to
     increase the volumes quota.

     .. code-block:: console

        $ openstack quota set --volumes 10 PROJECT
        +----------------------+-------+
        |        Property      | Value |
        +----------------------+-------+
        | ...                  | ...   |
        | backup_gigabytes     | 0     |
        | backups              | 0     |
        | gigabytes            | 0     |
        | per_volume_gigabytes | 0     |
        | snapshots            | 0     |
        | volumes              | 10    |
        +----------------------+-------+

     .. note::

        The volumes resource quota is updated.

#. Try to create a volume in project A.

   Use the :command:`openstack volume create` command and specify:

   - The ``SIZE`` of the volume that will be created;

   - The ``NAME`` of the volume.

     .. code-block:: console

        $ openstack volume create --size SIZE NAME
        VolumeLimitExceeded: Maximum number of volumes allowed (10) exceeded for quota 'volumes'. (HTTP 413) (Request-ID: req-f6f7cc89-998e-4a82-803d-c73c8ee2016c)

     .. note::

        As the entirety of project A's volumes quota has been assigned to
        project B, it is treated as if all of the quota has been used. This
        is true even when project B has not created any volumes.

See `cinder nested quota spec
<https://specs.openstack.org/openstack/cinder-specs/specs/liberty/cinder-nested-quota-driver.html>`_
and `hierarchical multi-tenancy spec
<https://blueprints.launchpad.net/keystone/+spec/hierarchical-multitenancy>`_
for details.
