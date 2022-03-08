===================
Database migrations
===================

.. note::

   This document details how to generate database migrations as part of a new
   feature or bugfix. For info on how to apply existing database migrations,
   refer to the documentation for the :program:`cinder-manage db sync`
   command in :doc:`/cli/cinder-manage`.
   For info on the general upgrade process for a cinder deployment, refer to
   :doc:`/admin/upgrades`.

Occasionally the databases used in cinder will require schema or data
migrations.


Schema migrations
-----------------

.. versionchanged:: 24.0.0 (Xena)

   The database migration engine was changed from ``sqlalchemy-migrate`` to
   ``alembic``.

The `alembic`__ database migration tool is used to manage schema migrations in
cinder. The migration files and related metadata can be found in
``cinder/db/migrations``. As discussed in :doc:`/admin/upgrades`, these can be
run by end users using the :program:`cinder-manage db sync` command.

.. __: https://alembic.sqlalchemy.org/en/latest/

.. note::

   There are also legacy migrations provided in the
   ``cinder/db/legacy_migrations`` directory . These are provided to facilitate
   upgrades from pre-Xena (24.0.0) deployments and will be removed in a future
   release. They should not be modified or extended.

The best reference for alembic is the `alembic documentation`__, but a small
example is provided here. You can create the migration either manually or
automatically. Manual generation might be necessary for some corner cases such
as renamed tables but auto-generation will typically handle your issues.
Examples of both are provided below. In both examples, we're going to
demonstrate how you could add a new model, ``Foo``, to the main database.

.. __: https://alembic.sqlalchemy.org/en/latest/

.. code-block:: diff

   diff --git cinder/db/sqlalchemy/models.py cinder/db/sqlalchemy/models.py
   index 7eab643e14..8f70bcdaca 100644
   --- cinder/db/sqlalchemy/models.py
   +++ cinder/db/sqlalchemy/models.py
   @@ -73,6 +73,16 @@ def MediumText():
            sqlalchemy.dialects.mysql.MEDIUMTEXT(), 'mysql')


   +class Foo(BASE, models.SoftDeleteMixin):
   +    """A test-only model."""
   +
   +    __tablename__ = 'foo'
   +
   +    id = sa.Column(sa.Integer, primary_key=True)
   +    uuid = sa.Column(sa.String(36), nullable=True)
   +    bar = sa.Column(sa.String(255))
   +
   +
    class Service(BASE, models.SoftDeleteMixin):
        """Represents a running service on a host."""

(you might not be able to apply the diff above cleanly - this is just a demo).

.. rubric:: Auto-generating migration scripts

In order for alembic to compare the migrations with the underlying models, it
require a database that it can inspect and compare the models against. As such,
we first need to create a working database. We'll bypass ``cinder-manage`` for
this and go straight to the :program:`alembic` CLI. The ``alembic.ini`` file
provided in the ``cinder/db`` directory is helpfully configured to use an
SQLite database by default (``cinder.db``). Create this database and apply the
current schema, as dictated by the current migration scripts:

.. code-block:: bash

   $ tox -e venv -- alembic -c cinder/db/alembic.ini \
       upgrade head

Once done, you should notice the new ``cinder.db`` file in the root of the
repo. Now, let's generate the new revision:

.. code-block:: bash

   $ tox -e venv -- alembic -c cinder/db/alembic.ini \
       revision -m "Add foo model" --autogenerate

This will create a new file in ``cinder/db/migrations/versions`` with
``add_foo_model`` in the name including (hopefully!) the necessary changes to
add the new ``Foo`` model. You **must** inspect this file once created, since
there's a chance you'll be missing imports or something else which will need to
be manually corrected. Once you've inspected this file and made any required
changes, you can apply the migration and make sure it works:

.. code-block:: bash

   $ tox -e venv -- alembic -c cinder/db/alembic.ini \
       upgrade head

.. rubric:: Manually generating migration scripts

For trickier migrations or things that alembic doesn't understand, you may need
to manually create a migration script. This is very similar to the
auto-generation step, with the exception being that you don't need to have a
database in place beforehand. As such, you can simply run:

.. code-block:: bash

   $ tox -e venv -- alembic -c cinder/db/alembic.ini \
       revision -m "Add foo model"

As before, this will create a new file in ``cinder/db/migrations/versions``
with ``add_foo_model`` in the name. You can simply modify this to make whatever
changes are necessary. Once done, you can apply the migration and make sure it
works:

.. code-block:: bash

   $ tox -e venv -- alembic -c cinder/db/alembic.ini \
       upgrade head


Data migrations
---------------

.. todo: Populate this.
