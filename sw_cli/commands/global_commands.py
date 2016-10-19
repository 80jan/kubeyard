from argparse import ArgumentParser
import contextlib
import pathlib

import yaml
from sw_cli import context_factories, kubernetes


def setup(args):
    GlobalCommand(args).setup()


class GlobalCommand:
    def __init__(self, args):
        self.context = context_factories.GlobalContextFactory().get()
        parser = self.get_parser()
        self.options = parser.parse_args(args)
        self.context['SWCLI_MODE'] = self.options.mode

    def setup(self):
        user_context_filepath = pathlib.Path(self.context['SWCLI_USER_CONTEXT_FILEPATH'])
        with contextlib.suppress(FileExistsError):
            user_context_filepath.parent.mkdir()
        with user_context_filepath.open('w') as context_file:
            yaml.dump({
                'SWCLI_MODE': self.context['SWCLI_MODE'],
            }, stream=context_file)
        kubernetes.setup_cluster_context(self.context)

    def get_parser(self):
        parser = ArgumentParser()
        parser.add_argument("--development", dest="mode", default='production', action='store_const',
                            const='development', help="Select project root directory.")
        return parser
