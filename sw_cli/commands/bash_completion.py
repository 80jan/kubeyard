import logging
import pathlib
import os
import sys

import sw_cli.files_generator
from sw_cli import base_command


logger = logging.getLogger(__name__)


class InstallCompletion(base_command.BaseCommand):
    """
    Run this to enable bash completion. It writes /etc/bash_completion.d/sw-cli file. It will work automatically on
    your next bash use. You can enable it in your current sessions by running `. /etc/bash_completion.d/sw-cli`
    """
    def run(self):
        logger.info("Installing sw-cli...")
        sw_cli_dst = pathlib.Path('/etc/bash_completion.d/sw-cli')
        sw_cli.files_generator.copy_template('sw-cli-completion.sh', sw_cli_dst)
        sw_cli_dst.chmod(0o644)
        logger.info('Done')


class RunCompletion(base_command.BaseCommand):
    """
    Command run by script installed by `sw-cli install_bash_completion`. Shouldn't be called manually.
    It reads COMP_LINE and COMP_POINT environment variables and writes possible commands which starts with current word
    from its start to cursor position.
    """
    def run(self):
        line = os.environ.get('COMP_LINE', '')
        point = int(os.environ.get('COMP_POINT', '0'))
        prefix = line[:point].split(' ')[-1]
        script_names = get_script_names()
        filtered = [name for name in script_names if name.startswith(prefix)]
        sys.stdout.write(' '.join(filtered))


def get_script_names():
    from sw_cli import commands
    for command in commands.get_all_commands():
        yield command.name
