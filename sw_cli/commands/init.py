import logging
import pathlib

import sw_cli.files_generator

from sw_cli import base_command
from sw_cli import context_factories
from sw_cli import settings

logger = logging.getLogger(__name__)


class InitCommand(base_command.BaseCommand):
    """
    Initialises empty repository. Adds basic configuration and placeholders for source code and tests.
    It can be run only in git repository. It also adds missing files in not empty repositories.
    Most commands requires repository to have files structure as provisioned by this command.
    By default it uses python application template.
    """

    def __init__(self, *, directory, init_type):
        self.directory = directory
        self.init_type = init_type

    def run(self):
        logger.info("Initialising repo...")
        init_type = self.init_type
        project_dst = pathlib.Path(self.directory)
        context = context_factories.EmptyRepoContextFactory(self.directory, init_type.prompted_context).get()
        sw_cli.files_generator.copy_template(init_type.template_directory, project_dst, context=context)


class PythonPackageInitType:
    template_directory = 'new_repository'
    prompted_context = [
        context_factories.PromptedContext(
            'KUBE_SERVICE_NAME', 'service name', settings.DEFAULT_KUBE_SERVICE_NAME_PATTERN),
        context_factories.PromptedContext(
            'KUBE_SERVICE_PORT', 'service port', settings.DEFAULT_KUBE_SERVICE_PORT),
        context_factories.PromptedContext(
            'DOCKER_REGISTRY_NAME', 'docker registry name', settings.DEFAULT_DOCKER_REGISTRY_NAME),
    ]


class EmberInitType:
    template_directory = 'new_ember_repository'
    prompted_context = PythonPackageInitType.prompted_context + [
        context_factories.PromptedContext(
            'KUBE_LIVE_RELOAD_PORT', 'live reload development port', settings.DEFAULT_KUBE_LIVE_RELOAD_PORT),
        context_factories.PromptedContext(
            'DOCKER_REGISTRY_NAME', 'docker registry name', settings.DEFAULT_DOCKER_REGISTRY_NAME),
    ]
