"""Public package entry point for the SSSEP batch processor.

Most users never import this package directly; they run the repository's
`main.py` GUI entrypoint from PyCharm. This package-level `main()` function
still supports a config-driven batch run for existing Python integrations.
"""

def main():
    """Run the batch processor using fallback folders from `config.py`."""
    from sssep_batch.batch import main as batch_main

    return batch_main()

__all__ = ["main"]
