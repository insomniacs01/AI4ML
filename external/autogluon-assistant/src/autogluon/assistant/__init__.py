from importlib.metadata import version

__version__ = version("autogluon.assistant")


def run_agent(*args, **kwargs):
    from .coding_agent import run_agent as _run_agent

    return _run_agent(*args, **kwargs)
