from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("autogluon.assistant")
except PackageNotFoundError:
    __version__ = version("autogluon-assistant")


def run_agent(*args, **kwargs):
    from .coding_agent import run_agent as _run_agent

    return _run_agent(*args, **kwargs)
