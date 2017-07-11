import pathlib
from collections import namedtuple

from sw_cli import settings
from sw_cli.commands import custom_script
from . import bash_completion
from . import debug
from . import devel
from . import global_commands
from . import help
from . import init
from . import jenkins


class CommandDeclaration:
    def __init__(self, name, source, kwargs=None):
        self.name = name
        self.source = source
        self.kwargs = kwargs or {}

commands = [
    CommandDeclaration('help', help.HelpCommand),
    CommandDeclaration('init', init.InitCommand),
    CommandDeclaration('install_bash_completion', bash_completion.InstallCompletion),
    CommandDeclaration('bash_completion', bash_completion.RunCompletion),
    CommandDeclaration('jenkins_init', jenkins.JenkinsInitCommand),
    CommandDeclaration('jenkins_build', jenkins.JenkinsBuildCommand),
    CommandDeclaration('jenkins_reconfig', jenkins.JenkinsReconfigCommand),
    CommandDeclaration('jenkins_info', jenkins.JenkinsInfoCommand),
    CommandDeclaration('variables', debug.DebugCommand),
    CommandDeclaration('build', devel.BuildCommand),
    CommandDeclaration('test', devel.TestCommand),
    CommandDeclaration('update_requirements', devel.UpdateRequirementsCommand),
    CommandDeclaration('push', devel.PushCommand),
    CommandDeclaration('deploy', devel.DeployCommand),
    CommandDeclaration('setup_dev_db', devel.SetupDevDbCommand),
    CommandDeclaration('setup_dev_elastic', devel.SetupDevElasticsearchCommand),
    CommandDeclaration('setup_pubsub_emulator', devel.SetupPubSubEmulatorCommand),
    CommandDeclaration('setup_dev_redis', devel.SetupDevRedisCommand),
    CommandDeclaration('setup_dev_cassandra', devel.SetupDevCassandraCommand),
    CommandDeclaration('setup', global_commands.SetupCommand),
    CommandDeclaration('install_global_secrets', global_commands.InstallGlobalSecretsCommand),
]


def get_all_commands():
    cmds = commands.copy()

    def cmd_exists(name):
        return any(cmd.name == name for cmd in cmds)

    scripts_dir = pathlib.Path(settings.DEFAULT_SWCLI_SCRIPTS_DIR)
    if scripts_dir.exists():
        scripts_dir = scripts_dir.resolve()
        for filepath in scripts_dir.glob("*"):
            if filepath.is_file() and not cmd_exists(filepath.name):
                cmds.append(CommandDeclaration(filepath.name, custom_script.CustomScriptCommand,
                                               kwargs={'script_name': filepath}))
    return cmds
