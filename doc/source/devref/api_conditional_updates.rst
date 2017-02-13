API Races - Conditional Updates
===============================

Background
----------

On Cinder API nodes we have to check that requested action can be performed by
checking request arguments and involved resources, and only if everything
matches required criteria we will proceed with the RPC call to any of the other
nodes.

Checking the conditions must be done in a non racy way to ensure that already
checked requirements don't change while we check remaining conditions.  This is
of utter importance, as Cinder uses resource status as a lock to prevent
concurrent operations on a resource.

An simple example of this would be extending a volume, where we first check the
status:

.. code:: python

   if volume['status'] != 'available':

Then update the status:

.. code:: python

       self.update(context, volume, {'status': 'extending'})

And finally make the RPC call:

.. code:: python

       self.volume_rpcapi.extend_volume(context, volume, new_size,
                                        reservations)

The problem is that this code would allow races, as other request could
have already changed the volume status between us getting the value and
updating the DB.

There are multiple ways to fix this, such as:

- Using a Distributed Locking Mechanism
- Using DB isolation level
- Using SQL SELECT ... FOR UPDATE
- USING compare and swap mechanism in SQL query

Our tests showed that the best alternative was compare and swap and we decided
to call this mechanism "Conditional Update" as it seemed more appropriate.

Conditional Update
------------------

Conditional Update is the mechanism we use in Cinder to prevent races when
updating the DB.  In essence it is the SQL equivalent of an ``UPDATE ... FROM
... WHERE;`` clause

It is implemented as an abstraction layer on top of SQLAlchemy ORM engine in
our DB api layer and exposed for consumption in Cinder's Persistent Versioned
Objects through the ``conditional_update`` method so it can be used from any
Versioned Object instance that has persistence (Volume, Snapshot, Backup...).

Method signature is:

.. code:: python

   def conditional_update(self, values, expected_values=None, filters=(),
                          save_all=False, session=None, reflect_changes=True):

:values:
  Dictionary of key-value pairs with changes that we want to make to the
  resource in the DB.

:expected_values:
  Dictionary with conditions that must be met for the update to be executed.

  Condition ``field.id == resource.id`` is implicit and there is no need to add
  it to the conditions.

  If no ``expected_values`` argument is provided update will only go through if
  no field in the DB has changed. Dirty fields from the Versioned Object are
  excluded as we don't know their original value.

:filters:
  Additional SQLAlchemy filters can be provided for more complex conditions.

:save_all:
  By default we will only be updating the DB with values provided in the
  ``values`` argument, but we can explicitly say that we also want to save
  object's current dirty fields.

:session:
  A SQLAlchemy session can be provided, although it is unlikely to be needed.

:reflect_changes:
  On a successful update we will also update Versioned Object instance to
  reflect these changes, but we can prevent this instance update passing False
  on this argument.

:Return Value:
  We'll return the number of changed rows.  So we'll get a 0 value if the
  conditional update has not been successful instead of an exception.

Basic Usage
-----------

- **Simple match**

  The most basic example is doing a simple match, for example for a ``volume``
  variable that contains a Versioned Object Volume class instance we may want
  to change the ``status`` to "deleting" and update the ``terminated_at`` field
  with current UTC time only if current ``status`` is "available" and the
  volume is not in a consistency group.

  .. code:: python

     values={'status': 'deleting',
             'terminated_at': timeutils.utcnow()}
     expected_values = {'status': 'available',
                        'consistencygroup_id': None}

     volume.conditional_update(values, expected_values)

- **Iterable match**

  Conditions can contain not only single values, but also iterables, and the
  conditional update mechanism will correctly handle the presence of None
  values in the range, unlike SQL ``IN`` clause that doesn't support ``NULL``
  values.

  .. code:: python

     values={'status': 'deleting',
             'terminated_at': timeutils.utcnow()}
     expected_values={
         'status': ('available', 'error', 'error_restoring' 'error_extending'),
         'migration_status': (None, 'deleting', 'error', 'success'),
         'consistencygroup_id': None
     }

     volume.conditional_update(values, expected_values)

- **Exclusion**

  In some cases we'll need to set conditions on what is *not* in the DB record
  instead of what is is, for that we will use the exclusion mechanism provided
  by the ``Not`` class in all persistent objects.  This class accepts single
  values as well as iterables.

  .. code:: python

     values={'status': 'deleting',
             'terminated_at': timeutils.utcnow()}
     expected_values={
         'attach_status': volume.Not('attached'),
         'status': ('available', 'error', 'error_restoring' 'error_extending'),
         'migration_status': (None, 'deleting', 'error', 'success'),
         'consistencygroup_id': None
     }

     volume.conditional_update(values, expected_values)

- **Filters**

  We can use complex filters in the conditions, but these must be SQLAlchemy
  queries/conditions and as the rest of the DB methods must be properly
  abstracted from the API.

  Therefore we will create the method in cinder/db/sqlalchemy/api.py:

  .. code:: python

     def volume_has_snapshots_filter():
         return sql.exists().where(
             and_(models.Volume.id == models.Snapshot.volume_id,
                  ~models.Snapshot.deleted))

  Then expose this filter through the cinder/db/api.py:

  .. code:: python

    def volume_has_snapshots_filter():
        return IMPL.volume_has_snapshots_filter()

  And finally used in the API (notice how we are negating the filter at the
  API):

  .. code:: python

     filters = [~db.volume_has_snapshots_filter()]
     values={'status': 'deleting',
             'terminated_at': timeutils.utcnow()}
     expected_values={
         'attach_status': volume.Not('attached'),
         'status': ('available', 'error', 'error_restoring' 'error_extending'),
         'migration_status': (None, 'deleting', 'error', 'success'),
         'consistencygroup_id': None
     }

     volume.conditional_update(values, expected_values, filters)

Returning Errors
----------------

The most important downside of using conditional updates to remove API races is
the inherent uncertainty of the cause of failure resulting in more generic
error messages.

When we use the `conditional_update` method we'll use returned value to
determine the success of the operation, as a value of 0 indicates that no rows
have been updated and the conditions were not met.  But we don't know which
one, or which ones, were the cause of the failure.

There are 2 approaches to this issue:

- On failure we go one by one checking the conditions and return the first one
  that fails.

- We return a generic error message indicating all conditions that must be met
  for the operation to succeed.

It was decided that we would go with the second approach, because even though
the first approach was closer to what we already had and would give a better
user experience, it had considerable implications such as:

- More code was needed to do individual checks making operations considerable
  longer and less readable.  This was greatly alleviated using helper methods
  to return the errors.

- Higher number of DB queries required to determine failure cause.

- Since there could be races because DB contents could be changed between the
  failed update and the follow up queries that checked the values for the
  specific error, a loop would be needed to make sure that either the
  conditional update succeeds or one of the condition checks fails.

- Having such a loop means that a small error in the code could lead to an
  endless loop in a production environment.  This coding error could be an
  incorrect conditional update filter that would always fail or a missing or
  incorrect condition that checked for the specific issue to return the error.

A simple example of a generic error can be found in `begin_detaching` code:

.. code:: python

   @wrap_check_policy
   def begin_detaching(self, context, volume):
       # If we are in the middle of a volume migration, we don't want the
       # user to see that the volume is 'detaching'. Having
       # 'migration_status' set will have the same effect internally.
       expected = {'status': 'in-use',
                   'attach_status': 'attached',
                   'migration_status': self.AVAILABLE_MIGRATION_STATUS}

       result = volume.conditional_update({'status': 'detaching'}, expected)

       if not (result or self._is_volume_migrating(volume)):
           msg = _("Unable to detach volume. Volume status must be 'in-use' "
                   "and attach_status must be 'attached' to detach.")
           LOG.error(msg)
           raise exception.InvalidVolume(reason=msg)

Building filters on the API
---------------------------

SQLAlchemy filters created as mentioned above can create very powerful and
complex conditions, but sometimes we may require a condition that, while more
complex than the basic match and not match on the resource fields, it's still
quite simple.  For those cases we can create filters directly on the API using
the ``model`` field provided in Versioned Objects.

This ``model`` field is a reference to the ORM model that allows us to
reference ORM fields.

We'll use as an example changing the ``status`` field of a backup to
"restoring" if the backup status is "available" and the volume where we are
going to restore the backup is also in "available" state.

Joining of tables is implicit when using a model different from the one used
for the Versioned Object instance.

- **As expected_values**

  Since this is a matching case we can use ``expected_values`` argument to make
  the condition:

  .. code:: python

     values = {'status': 'restoring'}
     expected_values={'status': 'available',
                      objects.Volume.model.id: volume.id,
                      objects.Volume.model.status: 'available'}

- **As filters**

  We can also use the ``filters`` argument to achieve the same results:

  .. code:: python

     filters = [objects.Volume.model.id == volume.id,
                objects.Volume.model.status == 'available']

- **Other filters**

  If we are not doing a match for the condition the only available option will
  be to use ``filters`` argument.  For example if we want to do a check on the
  volume size against the backup size:

  .. code:: python

     filters = [objects.Volume.model.id == volume.id,
                objects.Volume.model.size >= backup.model.size]

Using DB fields for assignment
------------------------------

- **Using non modified fields**

  Similar to the way we use the fields to specify conditions, we can also use
  them to set values in the DB.

  For example when we disable a service we want to keep existing ``updated_at``
  field value:

  .. code:: python

     values = {'disabled': True,
               'updated_at': service.model.updated_at}

- **Using modified field**

  In some cases we may need to use a DB field that we are also updating, for
  example when we are updating the ``status`` but we also want to keep the old
  value in the ``previous_status`` field.

  .. code:: python

     values = {'status': 'retyping',
               'previous_status': volume.model.status}

  Conditional update mechanism takes into account that MySQL does not follow
  SQL language specs and adjusts the query creation accordingly.

- **Together with filters**

  Using DB fields for assignment together with using them for values can give
  us advanced functionality like for example increasing a quota value based on
  current value and making sure we don't exceed our quota limits.

  .. code:: python

     values = {'in_use': quota.model.in_use + volume.size}
     filters = [quota.model.in_use <= max_usage - volume.size]

Conditional value setting
-------------------------

Under certain circumstances you may not know what value should be set in the DB
because it depends on another field or on another condition.  For those cases
we can use the ``Case`` class present in our persistent Versioned Objects which
implements the SQL CASE clause.

The idea is simple, using ``Case`` class we can say which values to set in a
field based on conditions and also set a default value if none of the
conditions are True.

Conditions must be SQLAlchemy conditions, so we'll need to use fields from the
 ``model`` attribute.

For example setting the status to "maintenance" during migration if current
status is "available" and leaving it as it was if it's not can be done using
the following:

.. code:: python

   values = {
       'status': volume.Case(
           [
               (volume.model.status == 'available', 'maintenance')
           ],
           else_=volume.model.status)
   }

reflect_changes considerations
------------------------------

As we've already mentioned ``conditional_update`` method will update Versioned
Object instance with provided values if the row in the DB has been updated, and
in most cases this is OK since we can set the values directly because we are
using simple values, but there are cases where we don't know what value we
should set in the instance, and is in those cases where the default
``reflect_changes`` value of True has performance implications.

There are 2 cases where Versioned Object ``conditional_update`` method doesn't
know the value it has to set on the Versioned Object instance, and they are
when we use a field for assignment and when we are using the ``Case`` class,
since in both cases the DB is the one deciding the value that will be set.

In those cases ``conditional_update`` will have to retrieve the value from the
DB using ``get_by_id`` method, and this has a performance impact and therefore
should be avoided when possible.

So the recommendation is to set ``reflect_changes`` to False when using
``Case`` class or using fields in the ``values`` argument if we don't care
about the stored value.

Limitations
-----------

We can only use functionality that works on **all** supported DBs, and that's
why we don't allow multi table updates and will raise ProgrammingError
exception even when the code is running against a DB engine that supports this
functionality.

This way we make sure that we don't inadvertently add a multi table update that
works on MySQL but will surely fail on PostgreSQL.

MySQL DB engine also has some limitations that we should be aware of when
creating our filters.

One that is very common is when we are trying to check if there is a row that
matches a specific criteria in the same table that we are updating.  For
example, when deleting a Consistency Group we want to check that it is not
being used as the source for a Consistency Group that is in the process of
being created.

The straightforward way of doing this is using the core exists expression and
use an alias to differentiate general query fields and the exists subquery.
Code would look like this:

.. code:: python

    def cg_creating_from_src(cg_id):
       model = aliased(models.ConsistencyGroup)
       return sql.exists().where(and_(
           ~model.deleted,
           model.status == 'creating',
           conditions.append(model.source_cgid == cg_id)))

While this will work in SQLite and PostgreSQL, it will not work on MySQL and an
error will be raised when the query is executed: "You can't specify target
table 'consistencygroups' for update in FROM clause".

To solve this we have 2 options:

- Create a specific query for MySQL engines using an update with a left self
  join, which is a feature only available in MySQL.
- Use a trick -using a select subquery- that will work on all DBs.

Considering that it's always better to have only 1 way of doing things and that
SQLAlchemy doesn't support MySQL's non standard behavior we should generate
these filters using the select subquery method like this:

.. code:: python

    def cg_creating_from_src(cg_id):
       subq = sql.select([models.ConsistencyGroup]).where(and_(
           ~model.deleted,
           model.status == 'creating')).alias('cg2')

       return sql.exists([subq]).where(subq.c.source_cgid == cgid)


Considerations for new ORM & Versioned Objects
----------------------------------------------

Conditional update mechanism works using generic methods for getting an object
from the DB as well as determining the model for a specific Versioned Object
instance for field binding.

These generic methods rely on some naming rules for Versioned Object classes,
ORM classes, and get methods, so when we are creating a new ORM class and
adding the matching Versioned Object and access methods we must be careful to
follow these rules or at least specify exceptions if we have a good reason not
to follow these conventions.

Rules:

- Versioned Object class name must be the same as the ORM class
- Get method name must be ORM class converted to snake format with postfix
  "_get".  For example, for ``Volume`` ORM class expected method is
  ``volume_get``, and for an imaginary ``MyORMClass`` it would be
  ``my_orm_class_get``.
- Get method must receive the ``context`` as the first argument and the ``id``
  as the second one, although it may accept more optional arguments.

We should avoid diverging from these rules whenever is possible, but there are
cases where this is not possible, for example ``BackupImport`` Versioned Object
that really uses ``Backup`` ORM class.  For cases such as this we have a way to
set exceptions both for the generic get method and the model for a Versioned
Object.

To add exceptions for the get method we have to add a new entry to
``GET_EXCEPTIONS`` dictionary mapping in
``cinder.db.sqlalchemy.api._get_get_method``.

And for determining the model for the Versioned Object we have to add a new
entry to ``VO_TO_MODEL_EXCEPTIONS`` dictionary mapping in
``cinder.db.sqlalchemy.api.get_model_for_versioned_object``.
