from contextlib import contextmanager
import io
import logging
import os
import sys
import tempfile

import kubepy.appliers
from kubepy import appliers_options
import kubepy.base_commands
import pathlib
import sh
from cached_property import cached_property

from sw_cli import base_command
from sw_cli import kubernetes
from sw_cli import minikube
from sw_cli import settings
from sw_cli.commands import custom_script

logger = logging.getLogger(__name__)

MAX_JOB_RETRIES = 2


class BaseDevelCommand(base_command.InitialisedRepositoryCommand):
    docker_repository = 'docker.socialwifi.com'

    def __init__(self, *args):
        super().__init__(*args)
        if self.is_development:
            self.cluster = self._prepare_cluster(self.context)
            self.context.update(self.cluster.docker_env())
        self.docker_runner = DockerRunner(self.context)

    @staticmethod
    def _prepare_cluster(context):
        logger.info('Checking if cluster is running and configured...')
        cluster = minikube.ClusterFactory().get(context)
        cluster.ensure_started()
        logger.info('Cluster is ready')
        return cluster

    def run(self):
        super().run()
        custom_script_runner = custom_script.CustomScriptRunner(self.project_dir, self.context)
        custom_script_exists = custom_script_runner.exists(self.custom_script_name)
        if self.options.default or not custom_script_exists:
            self.run_default()
        else:
            custom_script_runner.run(self.custom_script_name, self.args)

    @cached_property
    def options(self):
        parser = self.get_parser()
        return parser.parse_known_args()[0]

    @classmethod
    def get_parser(cls, **kwargs):
        parser = super().get_parser(**kwargs)
        parser.add_argument(
            '--tag', dest='tag', action='store', default=None, help='Used image tag.')
        parser.add_argument(
            '--default', dest='default', action='store_true', default=False,
            help='Don\'t try to execute custom script. Useful when you need original behaviour in overridden method.')
        parser.add_argument(
            '--image-name', dest='image_name', action='store', default=None,
            help='Image name (without repository). Default is set in sw-cli.yml.')
        return parser

    def docker(self, *args, **kwargs):
        return self.docker_runner.run(*args, **kwargs)

    def docker_with_output(self, *args, **kwargs):
        return self.docker_runner.run_with_output(*args, **kwargs)

    @property
    def image(self):
        return '{}/{}:{}'.format(self.docker_repository, self.image_name, self.tag)

    @property
    def latest_image(self):
        return '{}/{}:latest'.format(self.docker_repository, self.image_name)

    @property
    def image_name(self):
        return self.options.image_name or self.context["DOCKER_IMAGE_NAME"]

    @property
    def tag(self):
        return self.options.tag or self.default_tag

    @property
    def default_tag(self):
        if self.is_development:
            return 'dev'
        else:
            return 'latest'

    @property
    def is_development(self):
        return self.context['SWCLI_MODE'] == 'development'

    def run_default(self):
        raise NotImplementedError

    @property
    def custom_script_name(self):
        raise NotImplementedError


class BuildCommand(BaseDevelCommand):
    """
    Builds docker image required to run tests and deployment. Can be overridden in <project_dir>/sripts/build.
    If sw-cli is set up in development mode it uses minikube as docker host.
    """
    custom_script_name = 'build'

    def run_default(self):
        image_context = self.options.image_context or "{0}/docker".format(self.project_dir)
        logger.info('Building image "{}"...'.format(self.image))
        self.docker_with_output('build', '-t', self.image, image_context)

    @classmethod
    def get_parser(cls, **kwargs):
        parser = super().get_parser(**kwargs)
        parser.add_argument(
            '--image-context', dest='image_context', action='store', default=None,
            help='Image context containing Dockerfile. Defaults to <project_dir>/docker')
        return parser


class UpdateRequirementsCommand(BaseDevelCommand):
    """
    Updates docker/requirements/python.txt file based on docker/source/base_requirements.txt.
    In container it creates virtualenv and runs
    `pip install -r docker/source/base_requirements.txt && pip freeze > docker/source/base_requirements.txt`
    Can be overridden in <project_dir>/sripts/update_requirements.
    If sw-cli is set up in development mode it uses minikube as docker host.
    """
    custom_script_name = 'update_requirements'

    @classmethod
    def get_parser(cls, **kwargs):
        parser = super().get_parser(**kwargs)
        parser.add_argument('--before3.6.0-5', dest='before', action='store_true',
                            default=False, help='Add this flag to use update for an older python application.')
        return parser

    def run_default(self):
        logger.info('Updating requirements for "{}"...'.format(self.image))
        if self.options.before is True:
            os.system(self.legacy_pip_freeze_command)
        else:
            with open("docker/requirements/python.txt", "w") as output_file:
                output_file.write(self.get_pip_freeze_output())
        logger.info('Requirements updated and saved to "docker/requirements/python.txt"')

    @property
    def legacy_pip_freeze_command(self):
        return ('(cat docker/source/base_requirements.txt | docker run --rm -i python:3.6.0'
                ' bash -c "'
                'pip install --upgrade setuptools==34.3.0 > /dev/stderr ; '
                'pip install -r /dev/stdin > /dev/stderr ; '
                'pip freeze")'
                ' > docker/requirements.txt')

    def get_pip_freeze_output(self):
        output = io.StringIO()
        input = sh.cat("docker/source/base_requirements.txt")
        self.docker('run', '--rm', '-i', self.image, 'freeze_requirements', _in=input, _out=output,
                    _err=sys.stdout.buffer)
        return output.getvalue()


class TestCommand(BaseDevelCommand):
    """
    Runs tests in docker image built by build command. Can be overridden in <project_dir>/sripts/test.
    If sw-cli is set up in development mode it uses minikube as docker host and mounts volumes configured in
    dev_mounted_paths in config/sw_cli.yml if they have mount-in-test set.

    Example:
    dev_mounted_paths:
    - name: dev-volume
      host-path: docker/source
      mount-in-tests:
        path: /package
        image-name: sw-project
    """
    custom_script_name = 'test'

    def __init__(self, *args):
        super().__init__(*args)
        self.context['HOST_VOLUMES'] = ' '.join(self.volumes)

    def run_default(self):
        self.docker_with_output('run', '--rm', '--net=none', *self.volumes, self.image, 'run_tests')

    @property
    def volumes(self):
        if self.is_development:
            mounted_project_dir = self.cluster.get_mounted_project_dir(self.project_dir)
            for volume in self.context.get('DEV_MOUNTED_PATHS', []):
                if 'mount-in-tests' in volume and volume['mount-in-tests']['image-name'] == self.image_name:
                    host_path = str(mounted_project_dir / volume['host-path'])
                    container_path = volume['mount-in-tests']['path']
                    mount_mode = self.get_mount_mode(volume['mount-in-tests'])
                    yield from ['-v', '{}:{}:{}'.format(host_path, container_path, mount_mode)]

    def get_mount_mode(self, configuration):
        mount_mode = configuration.get('mount-mode', 'ro')
        if mount_mode not in {'ro', 'rw'}:
            raise base_command.CommandException('Volume "mount-mode" should be one of: "ro", "rw".')
        return mount_mode


class PushCommand(BaseDevelCommand):
    """
    Runs `docker push` on docker image built by build command. It also tags image as latest adn push it as well.
    Can be overridden in <project_dir>/sripts/push.
    If sw-cli is set up in development mode it uses minikube as docker host.
    Normally you want to run it only in production.
    """
    custom_script_name = 'push'

    def run_default(self):
        self.docker_with_output('push', self.image)
        self.docker_with_output('tag', self.image, self.latest_image)
        self.docker_with_output('push', self.latest_image)


class DeployCommand(BaseDevelCommand):
    """
    Deploys application to kubernetes. If it got aws credentials and is not in development mode than it uploads static
    files to socialwifi-static s3 bucket in STATICS_DIRECTORY configured through context(config/sw_cli.yml).
    Image should implement collect_statics_tar command For this part to work.
    Next step is creating secret. Secret is named KUBE_SERVICE_NAME configured through context. its content is gathered
    either form repository in development mode or from global directory in production mode (see sw-cli help setup).
    key value pairs of this secrets are collected from files in this directory: keys are filenames and values are
    contents of these files. File secrets.yml is exception: it contains yaml encoded dictionary of additional key,
    value pairs. In genereal you should use secrets.yml for your short text secrets.
    Last step is deploying ./config/kubernetes/deploy/ using kubepy_deploy_all command
    (https://github.com/socialwifi/kubepy/). In development mode it also merges differences from
    config/development_overrides, and adds volumes to every pod configured in dev_mounted_paths in config/sw_cli.yml.
    These volumes should be mounted in selected pods using development_overrides.
    Example:
    dev_mounted_paths:
    - name: dev-volume
      host-path: docker/source

    Can be overridden in <project_dir>/sripts/deploy.
    """
    custom_script_name = 'deploy'

    @classmethod
    def get_parser(cls, **kwargs):
        parser = super().get_parser(**kwargs)
        parser.add_argument(
            '--build-url', dest='build_url', action='store', default=None,
            help='URL to a CI/CD (eg. Jenkins) build. It will be used as a pod annotation.')
        parser.add_argument(
            '--aws-credentials', dest='aws_credentials', action='store', default=None,
            help='AWS key and secret. Required to deploy static files. Format: AWS_KEY:AWS_SECRET.')
        parser.add_argument(
            '--gcs-service-key-file', dest='gcs_service_key_file', action='store', default=None,
            help='Service account key path for Google Cloud Storage. Required to deploy static files.')
        parser.add_argument(
            '--gcs-bucket-name', dest='gcs_bucket_name', action='store', default=None,
            help='Google Cloud Storage bucket name. Required to deploy static files.')
        return parser

    def run_default(self):
        if self.should_deploy_statics:
            self.run_statics_deploy()
        if self.definition_directories:
            if self.dev_requirements and self.is_development:
                self.run_dev_requirements_deploy()
            self.run_kubernetes_deploy()

    @property
    def should_deploy_statics(self):
        return not self.is_development and self.static_files_storage

    @cached_property
    def static_files_storage(self):
        return static_files_storage_factory(self.options, self.context, self.image)

    def run_statics_deploy(self):
        logger.info('Uploading static files...')
        self.static_files_storage.collect_and_upload()
        logger.info('Static files uploaded')

    def run_kubernetes_deploy(self):
        pod_annotations = {}
        if self.options.build_url is not None:
            pod_annotations['sw-cli/build-url'] = self.options.build_url
        options = appliers_options.Options(
            build_tag=self.tag, replace=self.is_development, host_volumes=self.host_volumes,
            max_job_retries=MAX_JOB_RETRIES, pod_annotations=pod_annotations,
        )
        kubernetes.install_secrets(self.context)
        logger.info('Applying Kubernetes definitions from YAML files...')
        kubepy.appliers.DirectoriesApplier(self.definition_directories, options).apply_all()
        logger.info('Kubernetes definitions applied')

    @property
    def definition_directories(self):
        kubernetes_dir = self.project_dir / settings.DEFAULT_KUBERNETES_DEPLOY_DIR
        overrides_dir = self.project_dir / settings.DEFAULT_KUBERNETES_DEV_DEPLOY_OVERRIDES_DIR
        definition_directories = []
        if kubernetes_dir.exists():
            definition_directories.append(kubernetes_dir)
        if self.is_development and overrides_dir.exists():
            definition_directories.append(overrides_dir)
        return definition_directories

    @property
    def host_volumes(self):
        if self.is_development:
            mounted_project_dir = self.cluster.get_mounted_project_dir(self.project_dir)
            return {
                volume['name']: mounted_project_dir / volume['host-path']
                for volume in self.context.get('DEV_MOUNTED_PATHS', [])
            }
        else:
            return {}

    def run_dev_requirements_deploy(self):
        logger.info('Checking development requirements...')
        from sw_cli.commands.dev_requirements import RequirementsDispatcher
        dispatcher = RequirementsDispatcher(self.context)
        dispatcher.dispatch_all(self.dev_requirements)
        logger.info('Development requirements are satisfied')

    @property
    def dev_requirements(self):
        return self.context.get('DEV_REQUIREMENTS')


def static_files_storage_factory(options, context, image):
    statics_directory = context.get('STATICS_DIRECTORY')
    collect_statics_command = context.get('COLLECT_STATICS_COMMAND', 'collect_statics_tar')
    docker_runner = DockerRunner(context)
    arguments = {
        'statics_directory': statics_directory,
        'collect_statics_command': collect_statics_command,
        'image': image,
        'docker_runner': docker_runner,
    }
    if statics_directory and options.gcs_service_key_file and options.gcs_bucket_name:
        return GCSFilesStorage(
            **arguments,
            service_key_file=options.gcs_service_key_file,
            bucket_name=options.gcs_bucket_name,
        )
    elif statics_directory and options.aws_credentials:
        return S3FilesStorage(
            **arguments,
            credentials=options.aws_credentials,
        )
    else:
        return None


class FilesStorage:
    def __init__(self, statics_directory, collect_statics_command, image, docker_runner):
        self.statics_directory = statics_directory
        self.collect_statics_command = collect_statics_command
        self.image = image
        self.docker_runner = docker_runner

    def collect_and_upload(self):
        statics_tar_process = self.get_statics_tar_process()
        self.upload_tarred_files(statics_tar_process)

    def get_statics_tar_process(self):
        return self.docker_runner.run(
            'run', '-i', '--rm', self.image, self.collect_statics_command, _err=sys.stdout.buffer, _piped=True)

    def upload_tarred_files(self, statics_tar_process):
        raise NotImplementedError


class S3FilesStorage(FilesStorage):
    def __init__(self, statics_directory, collect_statics_command, image, docker_runner, credentials):
        super().__init__(statics_directory, collect_statics_command, image, docker_runner)
        if ':' in credentials:
            self.access_key, self.secret_key = credentials.split(':', 2)
        else:
            raise base_command.CommandException('Aws credentials should be in form access_key:secret_key.')

    def upload_tarred_files(self, statics_tar_process):
        logger.info('Uploading to AWS S3...')
        upload_statics_run_command = [
            'run', '-i', '--rm', '-e', 'AWS_ACCESS_KEY={}'.format(self.access_key),
            '-e',  'AWS_SECRET_KEY={}'.format(self.secret_key), '-e', 'UPLOAD_BUCKET=socialwifi-static',
            '-e', 'UPLOAD_PATH={}/'.format(self.statics_directory),
            'docker.socialwifi.com/aws-utils', 'upload_tar'
        ]
        self.docker_runner.run_with_output(statics_tar_process, *upload_statics_run_command)


class GCSFilesStorage(FilesStorage):
    cloud_sdk_image = 'google/cloud-sdk:183.0.0'

    def __init__(self, statics_directory, collect_statics_command, image, docker_runner, service_key_file, bucket_name):
        super().__init__(statics_directory, collect_statics_command, image, docker_runner)
        self.service_key_file = service_key_file
        self.bucket_name = bucket_name

    def upload_tarred_files(self, statics_tar_process):
        logger.info('Uploading to GCS...')
        with self.docker_runner.temporary_volume() as volume_name:
            self._save_tar_to_volume(statics_tar_process, volume_name)
            self.docker_runner.run_with_output(
                'run', '-i', '--rm',
                '-v', '{}:/service-account.json:ro'.format(self.service_key_file),
                '-v', '{}:/upload/:ro'.format(volume_name),
                self.cloud_sdk_image,
                'gsutil',
                '-m',
                '-o', 'Credentials:gs_service_key_file=/service-account.json',
                'cp', '-r', '/upload/*', 'gs://{}/{}/'.format(self.bucket_name, self.statics_directory)
            )

    def _save_tar_to_volume(self, tar_process, volume_name):
        self.docker_runner.run_with_output(
            tar_process,
            'run', '-i', '--rm',
            '-v', '{}:/extracted/'.format(volume_name),
            'busybox:1.28.0',
            'tar', 'xf', '-', '-C', '/extracted/'
        )


class DockerRunner:
    def __init__(self, context):
        self.context = context

    def run(self, *args, **kwargs):
        return sh.docker(*args, _env=self.sh_env, **kwargs)

    def run_with_output(self, *args, **kwargs):
        return self.run(*args, _out=sys.stdout.buffer, _err=sys.stdout.buffer, **kwargs)

    @cached_property
    def sh_env(self):
        env = os.environ.copy()
        env.update(self.context.as_environment())
        return env

    @contextmanager
    def temporary_volume(self):
        volume_name = self.run('volume', 'create').strip()
        logger.debug('volume_name: {}'.format(volume_name))
        yield volume_name
        self.run('volume', 'remove', volume_name)
