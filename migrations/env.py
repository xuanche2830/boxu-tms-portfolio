from alembic import context

connection = context.config.attributes.get('connection')
if connection is None:
    raise RuntimeError('请通过 python -m backend.database_cli upgrade 执行迁移')
context.configure(connection=connection, transactional_ddl=True)
with context.begin_transaction():
    context.run_migrations()
