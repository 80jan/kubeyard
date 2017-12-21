import logging
import pathlib

import sh

from sw_cli import dependencies
from sw_cli import kubernetes

logger = logging.getLogger(__name__)
definitions_directory = pathlib.Path(__file__).parent.parent / 'definitions' / 'dev_requirements'


class Requirement:
    valid_arguments = ()

    def __init__(self, context: dict):
        self.context = context

    def __call__(self, arguments: dict):
        if all(key in self.valid_arguments for key in arguments.keys()):
            self.run(arguments)
        else:
            logger.warning(
                'Requirement configuration is not valid: {}\n'
                'Available options are: {}'.format(arguments, self.valid_arguments))

    def run(self, arguments: dict):
        raise NotImplementedError


class Postgres(Requirement):
    valid_arguments = ('name')

    def run(self, arguments: dict):
        database_name = arguments.get('name') or self.context['KUBE_SERVICE_NAME']
        dependency = PostgresDependency()
        dependency.ensure_running()
        dependency.ensure_database_present(database_name)


class PostgresDependency(dependencies.KubernetesDependency):
    name = 'dev-postgres'
    definition = definitions_directory / 'postgres.yaml'
    started_log = 'PostgreSQL init process complete; ready for start up.'

    def ensure_database_present(self, database_name):
        logger.debug('Ensuring that database "{}" exists...'.format(database_name))
        try:
            self.run_command('createdb', database_name, '-U', 'postgres')
        except sh.ErrorReturnCode as e:
            if b'already exists' not in e.stderr:
                raise e
            else:
                logger.debug('Database "{}" exists'.format(database_name))
        else:
            logger.debug('Database "{}" created'.format(database_name))


class Elasticsearch(Requirement):
    valid_arguments = ()

    def run(self, arguments: dict):
        self.ensure_elastic_running()

    def ensure_elastic_running(self):
        ElasticsearchDependency().ensure_running()


class ElasticsearchDependency(dependencies.KubernetesDependency):
    name = 'dev-elasticsearch'
    definition = definitions_directory / 'elasticsearch.yaml'
    started_log = '] started'


class PubSubEmulator(Requirement):
    valid_arguments = ('topic', 'subscription')

    def run(self, arguments: dict):
        topic_name = arguments.get('topic') or self.context['KUBE_SERVICE_NAME']
        dependency = PubSubDependency()
        dependency.ensure_running()
        dependency.ensure_topic_present(topic_name)
        try:
            subscription_name = arguments['subscription']
        except KeyError:
            logger.debug("Subscription not specified, it won't be created")
        else:
            dependency.ensure_subscription_present(topic_name, subscription_name)


class PubSubDependency(dependencies.KubernetesDependency):
    name = 'dev-pubsub'
    definition = definitions_directory / 'pubsub-emulator.yaml'
    started_log = '[pubsub] INFO: Server started, listening on'

    def ensure_topic_present(self, topic_name):
        logger.debug('Ensuring that topic "{}" exists...'.format(topic_name))
        try:
            self.run_command('pubsub_add_topic', topic_name)
        except sh.ErrorReturnCode as e:
            if b'Topic already exists' not in e.stderr:
                raise
            else:
                logger.debug('Topic "{}" exists'.format(topic_name))
        else:
            logger.debug('Topic "{}" created'.format(topic_name))

    def ensure_subscription_present(self, topic_name, subscription_name):
        logger.debug('Ensuring that subscription "{}" exists...'.format(subscription_name))
        try:
            self.run_command('pubsub_add_subscription', topic_name, subscription_name)
        except sh.ErrorReturnCode as e:
            if b'Subscription already exists' not in e.stderr:
                raise
            else:
                logger.debug('Subscription "{}" exists'.format(subscription_name))
        else:
            logger.debug('Subscription "{}" created'.format(subscription_name))


class Redis(Requirement):
    valid_arguments = ('name', )

    def run(self, arguments: dict):
        dependency = RedisDependency()
        dependency.ensure_running()
        secret_key = arguments.get('name') or self.context['KUBE_SERVICE_NAME']
        self.reset_global_secrets(redis_host=dependency.name, secret_key=secret_key)

    def reset_global_secrets(self, redis_host, secret_key):
        manipulator = kubernetes.get_global_secrets_manipulator(self.context, 'redis-urls')
        redis_urls = manipulator.get_literal_secrets_mapping()
        if secret_key not in redis_urls:
            count = len(redis_urls)
            manipulator.set_literal_secret(secret_key, 'redis://{}:6379/{}'.format(redis_host, count))
            kubernetes.install_global_secrets(self.context)


class RedisDependency(dependencies.KubernetesDependency):
    name = 'dev-redis'
    definition = definitions_directory / 'redis.yaml'
    started_log = 'The server is now ready to accept connections'


class Cassandra(Requirement):
    valid_arguments = ('keyspace')

    def run(self, arguments: dict):
        keyspace_name = arguments.get('keyspace') or self.context['KUBE_SERVICE_NAME']
        dependency = CassandraDependency()
        dependency.ensure_running()
        dependency.ensure_database_present(keyspace_name)


class CassandraDependency(dependencies.KubernetesDependency):
    name = 'dev-cassandra'
    definition = definitions_directory / 'cassandra.yaml'
    started_log = "Created default superuser role 'cassandra'"

    def ensure_database_present(self, keyspace_name):
        keyspace_name = self.clean_keyspace_name(keyspace_name)
        logger.debug('Ensuring that keyspace "{}" exists...'.format(keyspace_name))
        query = ("create keyspace %s with replication = {'class': 'SimpleStrategy', "
                 "'replication_factor': 1}" % keyspace_name)
        try:
            self.run_command('cqlsh', '-e', query)
        except sh.ErrorReturnCode as e:
            if b'already exists' not in e.stderr:
                raise e
            else:
                logger.debug('Keyspace "{}" exists'.format(keyspace_name))
        else:
            logger.debug('Keyspace "{}" created'.format(keyspace_name))

    def clean_keyspace_name(self, original):
        cleaned = original.replace('-', '_')
        if cleaned != original:
            logger.warning("Keyspace name can't contain dashes (-), so it's been changed to: %s" % cleaned)
        return cleaned


class RequirementsDispatcher:
    commands = {
        'postgres': Postgres,
        'redis': Redis,
        'elastic': Elasticsearch,
        'pubsub': PubSubEmulator,
        'cassandra': Cassandra,
    }

    def __init__(self, context: dict):
        self.context = context

    def dispatch_all(self, requirements: dict):
        for requirement in requirements:
            if 'kind' in requirement:
                self.dispatch(requirement)
            else:
                logger.warning("Skipping requirement without specified kind. Requirement: {}".format(requirement))

    def dispatch(self, requirement: dict):
        arguments = requirement.copy()
        kind = arguments.pop('kind')
        logger.info('Checking requirement of kind "{}"...'.format(kind))
        try:
            command = self.commands[kind](self.context)
        except KeyError:
            logger.warning('Kind "{}" is not supported!'.format(kind))
        else:
            command(arguments)
            logger.info('Requirement of kind "{}" satisfied'.format(kind))
