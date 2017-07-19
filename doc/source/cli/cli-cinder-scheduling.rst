===============================
Manage Block Storage scheduling
===============================

As an administrative user, you have some control over which volume
back end your volumes reside on. You can specify affinity or
anti-affinity between two volumes. Affinity between volumes means
that they are stored on the same back end, whereas anti-affinity
means that they are stored on different back ends.

For information on how to set up multiple back ends for Cinder,
refer to :ref:`multi_backend`.

Example Usages
~~~~~~~~~~~~~~

#. Create a new volume on the same back end as Volume_A:

   .. code-block:: console

      $ openstack volume create --hint same_host=Volume_A-UUID \
        --size SIZE VOLUME_NAME

#. Create a new volume on a different back end than Volume_A:

   .. code-block:: console

      $ openstack volume create --hint different_host=Volume_A-UUID \
        --size SIZE VOLUME_NAME

#. Create a new volume on the same back end as Volume_A and Volume_B:

   .. code-block:: console

      $ openstack volume create --hint same_host=Volume_A-UUID \
        --hint same_host=Volume_B-UUID --size SIZE VOLUME_NAME

   Or:

   .. code-block:: console

      $ openstack volume create --hint same_host="[Volume_A-UUID, \
        Volume_B-UUID]" --size SIZE VOLUME_NAME

#. Create a new volume on a different back end than both Volume_A and
   Volume_B:

   .. code-block:: console

      $ openstack volume create --hint different_host=Volume_A-UUID \
        --hint different_host=Volume_B-UUID --size SIZE VOLUME_NAME

   Or:

   .. code-block:: console

      $ openstack volume create --hint different_host="[Volume_A-UUID, \
        Volume_B-UUID]" --size SIZE VOLUME_NAME
