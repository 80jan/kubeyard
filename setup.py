from pip.req import parse_requirements
from setuptools import find_packages
from setuptools import setup
import pathlib


def templates():
    for path in pathlib.Path('sw_cli/templates').glob('**/*'):
        if not path.is_dir():
            yield str(path.relative_to('sw_cli'))


setup(
    name='Sw-Cli',
    version='docker',
    packages=find_packages(exclude=['tests']),
    install_requires=[str(ir.req) for ir in parse_requirements('base_requirements.txt', session=False)],
    test_suite='tests',
    entry_points={
        'console_scripts': [
            'sw-cli = sw_cli.entrypoints.sw_cli:run',
        ],
    },
    package_dir={'sw_cli': 'sw_cli'},
    package_data={'sw_cli': list(templates())},
    include_package_data=True,
)
