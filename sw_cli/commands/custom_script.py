import os

import sh

from sw_cli import base_command


class CustomScriptCommandException(Exception):
    pass


def run(script_name):
    print("Starting command %s" % script_name)
    cmd = CustomScriptCommand()
    cmd.run(script_name)
    print("Done.")


class CustomScriptCommand(base_command.BaseCommand):

    def __init__(self):
        super(CustomScriptCommand, self).__init__()

    def run(self, script_name):
        filepath = self.project_dir / self.context.get('SWCLI_SCRIPTS_DIR') / script_name
        if not filepath.exists():
            raise CustomScriptCommandException(
                "Could not execute %s command, script doesn't exist: %s" % (script_name, filepath))
        if not os.access(str(filepath), os.X_OK):
            raise PermissionError(
                "Could not execute %s command, script exists but is not executable: %s" % (script_name, filepath))
        env = os.environ.copy()
        env.update(self.context)
        script = sh.Command(str(filepath))
        for line in script(_env=env, _iter=True):
            print(line)
